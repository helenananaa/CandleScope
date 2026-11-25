"""SymbolHistoryPlanner: one per symbol, owning when, where from and by whom its history source data is fetched.

ADR-DATA-001 §2. Demands from charts, studies and streams are converted to
source slots (89m -> 1m, 90s -> 1s), merged per source interval, cut into
pieces by urgency and recency, and executed by an injected executor, at most
``max_running`` at a time. The planner does not fetch, write, derive or read
bars itself: the executor runs a piece through the existing fetch and native
write path, and ``on_committed`` lets derivation and publication continue as
they do today. A piece that fails is handed back to the existing path
(``on_handed_back``), which then behaves as without the planner.

Runs on the event loop; none of its methods block.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .demands import Demand, DemandOwner
from .pieces import MAX_PIECE_BARS, Piece, PieceResult, cut_pieces
from .slots import SlotMap

logger = logging.getLogger("data_manager.symbol_history")

MAX_RUNNING_PIECES = 2
HAND_BACK_SECONDS = 300.0

SourceFor = Callable[[str], tuple[str, int]]
ClosedUntil = Callable[[str], int]
Executor = Callable[[Piece, Callable[[], bool]], Awaitable[PieceResult]]


class SubmittingExecutor(Protocol):
    """An executor that submits a piece synchronously and waits for it later.

    ``submit`` returns a handle (a coordinator request id) at once, so a
    caller registering demand can hand it to the API before the piece runs.
    """

    def submit(self, piece: Piece) -> Any: ...

    async def wait(self, handle: Any, piece: Piece, still_wanted: Callable[[], bool]) -> PieceResult: ...


@dataclass(frozen=True, slots=True)
class _SubmitFailed:
    error: str


@dataclass(frozen=True, slots=True)
class SymbolKey:
    exchange: str
    market_type: str
    symbol: str
    identity: tuple[str, ...] = ()


class SymbolHistoryPlanner:
    """Demand, slots and pieces of one symbol."""

    def __init__(
        self,
        key: SymbolKey,
        *,
        executor: Executor | SubmittingExecutor,
        source_for: SourceFor,
        closed_until: ClosedUntil,
        on_committed: Callable[[Piece, PieceResult], None] | None = None,
        on_handed_back: Callable[[Piece, list[tuple[int, int]], str | None], None] | None = None,
        max_running: int = MAX_RUNNING_PIECES,
        max_piece_bars: int = MAX_PIECE_BARS,
        hand_back_seconds: float = HAND_BACK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        ``source_for(target_interval)`` gives the source interval and its width
        (IntervalResolver's history base). ``closed_until(source_interval)`` is
        the exclusive end of closed source slots: the forming source bar and
        the target's open bucket belong to the live stream and the aggregator
        (§7.1). ``executor(piece, still_wanted)`` runs one piece; it checks
        ``still_wanted()`` between pages and stops when it turns false (§6).
        """
        self.key = key
        self._executor = executor
        self._source_for = source_for
        self._closed_until = closed_until
        self._on_committed = on_committed
        self._on_handed_back = on_handed_back
        self._max_running = max(1, int(max_running))
        self._max_piece_bars = max(1, int(max_piece_bars))
        self._hand_back_seconds = max(0.0, float(hand_back_seconds))
        self._clock = clock
        self._slots: dict[str, SlotMap] = {}
        self._demands: dict[tuple[DemandOwner, str, Any], tuple[Demand, str]] = {}
        self._running: dict[str, tuple[Piece, asyncio.Task]] = {}
        self._handles: dict[str, Any] = {}
        self._hand_backs: list[tuple[float, str, int, int]] = []
        self._pump_handle: asyncio.Handle | None = None
        self._closed = False
        self.metrics = {
            "registered": 0, "unchanged": 0, "released": 0, "served": 0,
            "pieces_started": 0, "pieces_committed": 0, "pieces_failed": 0, "pieces_cancelled": 0,
            "bars_started": 0, "bars_handed_back": 0,
        }

    # Demand ---------------------------------------------------------------

    def register(self, demand: Demand) -> bool:
        """Add or replace one owner's demand; return whether the wanted slots changed.

        Registering the same demand again, as polls do, changes nothing and
        plans nothing (§3.3). A range beyond the closed source slots waits
        until they close and the demand is registered again.
        """
        if self._closed:
            return False
        source, width = self._source_for(demand.target_interval)
        slots = self._slot_map(source, width)
        previous = self._demands.get(demand.key)
        if previous is not None and previous[1] != source:
            self._slots[previous[1]].unwant(demand.key)
        self._demands[demand.key] = (demand, source)
        end = min(demand.end_ms, self._closed_until(source))
        changed = slots.want(demand.key, demand.owner, demand.start_ms, end, demand.urgency)
        changed = changed or (previous is not None and previous[1] != source)
        self.metrics["registered" if changed else "unchanged"] += 1
        if changed:
            self._schedule_pump()
        return changed

    def release(self, owner: DemandOwner) -> int:
        """Drop every demand of one owner (a chart closed, a symbol or interval switched)."""
        keys = [key for key, (demand, _) in self._demands.items() if demand.owner == owner]
        for key in keys:
            _, source = self._demands.pop(key)
            self._slots[source].unwant(key)
        if keys:
            self.metrics["released"] += len(keys)
            self._schedule_pump()
        return len(keys)

    def demands_over(self, piece: Piece) -> list[Demand]:
        """Current demands whose source slots this piece serves (to name its target windows)."""
        return [demand for demand, source in self._demands.values()
                if source == piece.source_interval and demand.start_ms < piece.end_ms
                and piece.start_ms < demand.end_ms]

    def settled(self, piece: Piece) -> list[tuple[Demand, tuple[int, int], bool]]:
        """Demands over this piece with nothing left to plan: ``(demand, (start, end), complete)``.

        A demand settles once each of its closed source slots ``[start, end)``
        is present or handed back and none is in flight. ``complete`` means
        every slot is present, so deriving its targets needs no fetch (§2 step 6).
        """
        slots = self._slots.get(piece.source_interval)
        if slots is None:
            return []
        settled = []
        for demand in self.demands_over(piece):
            start, end = slots.align(demand.start_ms,
                                     min(demand.end_ms, self._closed_until(piece.source_interval)))
            if start >= end:
                continue
            absent = slots.present.minus(start, end)
            if any(slots.in_flight.overlaps(a, b) or not slots.handed_back.covers(a, b) for a, b in absent):
                continue
            settled.append((demand, (start, end), not absent))
        return settled

    def demand_keys(self) -> list[Any]:
        return list(self._demands)

    def drop(self, demand: Demand) -> bool:
        """Forget one served demand; its owner registers again if it still lacks data."""
        entry = self._demands.get(demand.key)
        if entry is None or entry[0] != demand:
            return False  # replaced by a newer range of the same owner, which stays
        del self._demands[demand.key]
        self._slots[entry[1]].unwant(demand.key)
        self.metrics["served"] += 1
        return True

    def release_owner_id(self, owner_id: str) -> int:
        """Release every owner with this id, whatever its scope (a revoked request owner)."""
        owners = {demand.owner for demand, _ in self._demands.values() if demand.owner.owner_id == owner_id}
        return sum(self.release(owner) for owner in owners)

    def advance_scope(self, scope: str, generation: int) -> int:
        """A newer generation of a demand scope replaces the older generations' demands."""
        owners = {demand.owner for demand, _ in self._demands.values()
                  if demand.owner.scope == scope and demand.owner.generation is not None
                  and demand.owner.generation < generation}
        return sum(self.release(owner) for owner in owners)

    # Stored rows -----------------------------------------------------------

    def mark_present(self, source_interval: str, ranges: list[tuple[int, int]]) -> None:
        """Source ranges another writer (or the first storage read) proved present."""
        slots = self._slots.get(source_interval)
        if slots is None:
            return
        for start, end in ranges:
            slots.present.add(*slots.align(start, end))
        self._schedule_pump()

    def mark_missing(self, source_interval: str, ranges: list[tuple[int, int]]) -> None:
        """A revision deleted stored source rows; value corrections do not refetch (§7.4)."""
        slots = self._slots.get(source_interval)
        if slots is None:
            return
        for start, end in ranges:
            start, end = slots.align(start, end)
            slots.present.remove(start, end)
            slots.handed_back.remove(start, end)
        self._schedule_pump()

    # Execution -------------------------------------------------------------

    def _slot_map(self, source: str, width: int) -> SlotMap:
        slots = self._slots.get(source)
        if slots is None:
            slots = self._slots[source] = SlotMap(source, width)
        elif slots.width_ms != width:
            raise ValueError(f"source {source} width changed from {slots.width_ms} to {width}")
        return slots

    def _schedule_pump(self) -> None:
        if self._closed or self._pump_handle is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._pump_handle = loop.call_soon(self._pump)

    def next_pieces(self) -> list[Piece]:
        """Pieces the planner would start next, most urgent first (not started)."""
        pieces = []
        for slots in self._slots.values():
            pieces.extend(cut_pieces(slots.interval, slots.width_ms, slots.missing(),
                                     max_bars=self._max_piece_bars))
        pieces.sort(key=lambda piece: (piece.urgency, -piece.end_ms))
        return pieces

    def pump_now(self) -> None:
        """Start what can start now, synchronously (a caller about to read handles)."""
        if self._pump_handle is not None:
            self._pump_handle.cancel()
        self._pump()

    def handles_over(self, source_interval: str, start_ms: int, end_ms: int) -> list[Any]:
        """Handles of running pieces that overlap a source range, oldest first."""
        return [self._handles[piece.piece_id] for piece, _ in self._running.values()
                if piece.piece_id in self._handles and piece.source_interval == source_interval
                and piece.start_ms < end_ms and start_ms < piece.end_ms]

    def register_now(self, demand: Demand) -> list[Any]:
        """Register, start what can start, and return the handles serving this demand."""
        self.register(demand)
        self.pump_now()
        source, width = self._source_for(demand.target_interval)
        slots = self._slots[source]
        start, end = slots.align(demand.start_ms, min(demand.end_ms, self._closed_until(source)))
        return self.handles_over(source, start, end)

    def _pump(self) -> None:
        self._pump_handle = None
        if self._closed:
            return
        self._expire_hand_backs()
        capacity = self._max_running - len(self._running)
        if capacity <= 0:
            return
        submit = getattr(self._executor, "submit", None)
        for piece in self.next_pieces()[:capacity]:
            slots = self._slots[piece.source_interval]
            slots.in_flight.add(piece.start_ms, piece.end_ms)
            self.metrics["pieces_started"] += 1
            self.metrics["bars_started"] += piece.bars
            handle = None
            if callable(submit):
                try:
                    handle = submit(piece)
                except Exception as error:  # noqa: BLE001 - a refused submission hands the range back
                    logger.warning("history piece %s %s [%s, %s) was not submitted: %r", self.key.symbol,
                                   piece.source_interval, piece.start_ms, piece.end_ms, error)
                    handle = _SubmitFailed(repr(error)[:300])
                else:
                    self._handles[piece.piece_id] = handle
            task = asyncio.get_running_loop().create_task(
                self._run(piece, handle), name=f"symbol-history:{self.key.symbol}:{piece.source_interval}:{piece.piece_id}")
            self._running[piece.piece_id] = (piece, task)

    def _still_wanted(self, piece: Piece) -> bool:
        if self._closed:
            return False
        return bool(self._slots[piece.source_interval].owners_over(piece.start_ms, piece.end_ms))

    async def _run(self, piece: Piece, handle: Any = None) -> None:
        slots = self._slots[piece.source_interval]
        still_wanted = lambda: self._still_wanted(piece)  # noqa: E731
        try:
            try:
                if isinstance(handle, _SubmitFailed):
                    result = PieceResult("failed", error=handle.error)
                elif callable(getattr(self._executor, "submit", None)):
                    result = await self._executor.wait(handle, piece, still_wanted)
                else:
                    result = await self._executor(piece, still_wanted)
            except asyncio.CancelledError:
                result = PieceResult("cancelled")
                if self._closed:
                    raise
            except Exception as error:  # noqa: BLE001 - a piece failure hands the range back
                logger.warning("history piece %s %s [%s, %s) failed: %r", self.key.symbol,
                               piece.source_interval, piece.start_ms, piece.end_ms, error)
                result = PieceResult("failed", error=repr(error)[:300])
        finally:
            slots.in_flight.remove(piece.start_ms, piece.end_ms)
            self._running.pop(piece.piece_id, None)
            self._handles.pop(piece.piece_id, None)
        for start, end in result.written:
            start, end = max(start, piece.start_ms), min(end, piece.end_ms)
            if start < end:
                slots.present.add(*slots.align(start, end))
        if result.status == "committed":
            # The whole range is resolved: present, or proven absent at the source.
            slots.present.add(piece.start_ms, piece.end_ms)
            self.metrics["pieces_committed"] += 1
            self._notify(self._on_committed, piece, result)
        elif result.status == "failed":
            remaining = slots.present.minus(piece.start_ms, piece.end_ms)
            until = self._clock() + self._hand_back_seconds
            for start, end in remaining:
                slots.handed_back.add(start, end)
                self._hand_backs.append((until, piece.source_interval, start, end))
                self.metrics["bars_handed_back"] += (end - start) // piece.width_ms
            self.metrics["pieces_failed"] += 1
            self._notify(self._on_handed_back, piece, remaining, result.error)
        else:
            self.metrics["pieces_cancelled"] += 1
        self._schedule_pump()

    def _expire_hand_backs(self) -> None:
        now = self._clock()
        keep = []
        for entry in self._hand_backs:
            until, source, start, end = entry
            if until <= now:
                self._slots[source].handed_back.remove(start, end)
            else:
                keep.append(entry)
        self._hand_backs = keep

    def _notify(self, callback, *args) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:  # noqa: BLE001 - a listener must not stop the planner
            logger.exception("symbol history listener failed for %s", self.key.symbol)

    # Lifecycle -------------------------------------------------------------

    @property
    def idle(self) -> bool:
        """No demand, nothing running, and no range handed back to the existing path."""
        if self._demands or self._running:
            return False
        now = self._clock()
        return not any(until > now for until, *_ in self._hand_backs)

    async def drain(self) -> None:
        """Wait until nothing is running or about to start (tests and shutdown)."""
        while True:
            await asyncio.sleep(0)
            if self._pump_handle is None and not self._running:
                return
            tasks = [task for _, task in self._running.values()]
            if tasks:
                await asyncio.wait(tasks)

    async def close(self) -> None:
        """Stop starting pieces and cancel the running ones."""
        self._closed = True
        if self._pump_handle is not None:
            self._pump_handle.cancel()
            self._pump_handle = None
        tasks = [task for _, task in self._running.values()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def snapshot(self) -> dict[str, Any]:
        return {
            "symbol": self.key.symbol, "exchange": self.key.exchange, "market_type": self.key.market_type,
            "demands": len(self._demands),
            "running": [{"piece_id": piece.piece_id, "source": piece.source_interval, "start_ms": piece.start_ms,
                         "end_ms": piece.end_ms, "urgency": piece.urgency} for piece, _ in self._running.values()],
            "sources": {name: {"wanted": slots.wanted_count, "present_ms": slots.present.total,
                               "in_flight_ms": slots.in_flight.total, "handed_back_ms": slots.handed_back.total,
                               "missing_bars": sum((segment.end_ms - segment.start_ms) // slots.width_ms
                                                   for segment in slots.missing())}
                        for name, slots in sorted(self._slots.items())},
            **self.metrics,
        }


class PlannerRegistry:
    """At most one planner per symbol."""

    def __init__(self, factory: Callable[[SymbolKey], SymbolHistoryPlanner]) -> None:
        self._factory = factory
        self._planners: dict[SymbolKey, SymbolHistoryPlanner] = {}

    def get(self, key: SymbolKey) -> SymbolHistoryPlanner:
        planner = self._planners.get(key)
        if planner is None:
            planner = self._planners[key] = self._factory(key)
        return planner

    def existing(self, key: SymbolKey) -> SymbolHistoryPlanner | None:
        return self._planners.get(key)

    def keys(self) -> list[SymbolKey]:
        return list(self._planners)

    def prune(self) -> int:
        """Forget planners with no demand and nothing running."""
        idle = [key for key, planner in self._planners.items() if planner.idle]
        for key in idle:
            del self._planners[key]
        return len(idle)

    async def close(self) -> None:
        planners = list(self._planners.values())
        self._planners.clear()
        await asyncio.gather(*(planner.close() for planner in planners), return_exceptions=True)

    def snapshot(self) -> list[dict[str, Any]]:
        return [planner.snapshot() for planner in self._planners.values()]
