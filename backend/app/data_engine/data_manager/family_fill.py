"""Per-symbol cold source fill: steps 2-3 of docs/architecture/COLD_FAMILY_FILL_zh.md.

Off unless ENABLED. When a qualified mixed repair (a composed or bounded
history batch of one Binance USD-M symbol) arrives, the scheduler holds that
family's mixed chunks while one fill:

1. plans pending chunks alone, as their own runs would (target range and
   selected source grids: ``BackfillEngine.plan_mixed_sources``), the
   newest chunk of every chart first;
2. plans their sources jointly over what is stored (``backfill.family_plan``),
   so a finer cell one chart needs is planned for every chart whose coarse
   span it would refine;
3. acquires what chunks would otherwise race for, as a few ordinary native
   repairs of at most PIECE_ROWS rows, newest first and PIECE_CONCURRENCY at
   a time:

   - every hour of the months holding planned 1h-or-wider cells, when every
     chart that plans such cells can use 1h (a month of 1h is one archive
     object, and 1h then supersedes 4h and 1d there);
   - finer windows of at least DENSE_CELLS cells (the dense minutes of short
     charts), and finer windows within a day of a chunk boundary as whole
     UTC days (two chunks would otherwise import the same day).

   Shorter finer windows (a wide target's edge minutes) stay with the chunk
   that needs them: it fetches them in one run with its other sources.

The newest chunks are released as soon as no unfinished piece can write
into their range, while older ones are still being planned. A piece's reach
is widened to the archive object that may hold it: a UTC month where a
month fits in one object, else a UTC day. Released chunks plan and run
exactly as today, against what is now stored, so every fence, outcome and
ledger entry stays with the chunks and pieces. A failed plan, a failed piece
or a stall releases what is held; the chunks then acquire for themselves.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache

from app.core.executors import run_preparation
from app.data_engine.backfill.family_plan import ChartDemand, plan_family_sources, read_stored_series
from app.data_engine.backfill.source_router import MAX_USDM_ARCHIVE_OBJECT_ROWS
from app.data_engine.memory_budget import MemoryBudgetExceeded
from app.data_engine.history.cover_plan import FixedHistorySource
from app.data_engine.interval_policy import parse_interval_spec
from app.data_engine.interval_resolution import IntervalPurpose, IntervalResolver
from app.data_engine.series_identity import identity_from_metadata
from app.data_engine.storage.revisions import StaleAcquisition

from .backfill_contracts import RepairRequest
from .models import SeriesKey

logger = logging.getLogger("data_manager.FamilyFill")

ENABLED = False
# Charts of one workspace submit their history within a few milliseconds.
DEBOUNCE_SECONDS = 0.05
# No piece finished for this long: release everything still held.
STALL_SECONDS = 60.0
# Pieces in flight at once. All of a cold four-chart load's pieces at once
# put hundreds of chunks into memory admission together, whose per-waiter
# safety check then occupied the event loop for minutes.
PIECE_CONCURRENCY = 4
# Rows per piece: each piece is one native repair with fixed costs (ledger,
# detection, routing), so a few large ones beat one per window.
PIECE_ROWS = 4_000
# A finer-than-1h window this long is acquired by the fill (see above).
DENSE_CELLS = 360
MAX_STORED_ROWS = 200_000
# Plan-only attempts per chunk while earlier pieces write or hold memory.
PLAN_ATTEMPTS = 3
PLAN_RETRY_SECONDS = 0.2
PIECE_MARKER = "family_fill_piece"
FILL_REASONS = frozenset({"initial_history", "active_history_hydration", "visible_load_more",
                          "visible_range_gap", "visible_seed_gap"})
HOUR, DAY = 3_600_000, 86_400_000
_UTC = timezone.utc
_resolver = IntervalResolver()


def _reasons(request):
    return {part.strip() for part in str(request.reason or "").split("+") if part.strip()}


@lru_cache(maxsize=1024)
def _contract(exchange, market_type, interval):
    # The scheduler asks for every held chunk on every pass: resolve once.
    declaration = _resolver.history_composition_routes(exchange=exchange, market_type=market_type,
                                                       interval=interval)
    return None if declaration is None else declaration[0].contract_id


def family_of(request):
    """The symbol family of a qualified mixed repair, or None when the fill does not take it."""
    metadata = request.metadata
    if (request.exchange, request.market_type) != ("binance", "futures") or PIECE_MARKER in metadata:
        return None
    if not (metadata.get("required_history_composition") or metadata.get("bounded_history_batch_contract")):
        return None
    contract = _contract(request.exchange, request.market_type, request.interval)
    if contract is None or contract not in (metadata.get("required_history_composition"),
                                            metadata.get("bounded_history_batch_contract")):
        return None
    identity = identity_from_metadata(request.exchange, metadata)
    if identity is not None and not identity.is_legacy_default_for(request.exchange):
        return None
    return request.exchange, request.market_type, request.symbol


def _month_start(ms):
    day = datetime.fromtimestamp(ms / 1000, tz=_UTC)
    return int(datetime(day.year, day.month, 1, tzinfo=_UTC).timestamp() * 1000)


def _next_month(ms):
    day = datetime.fromtimestamp(ms / 1000, tz=_UTC)
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return int(datetime(year, month, 1, tzinfo=_UTC).timestamp() * 1000)


def _width(interval):
    return parse_interval_spec(interval).nominal_ms


def _widen(interval, start, stop):
    """Where a piece of [start, stop) may write: the archive objects holding it."""
    if 31 * DAY // _width(interval) <= MAX_USDM_ARCHIVE_OBJECT_ROWS:
        return _month_start(start), _next_month(stop - 1)
    return start // DAY * DAY, (stop - 1) // DAY * DAY + DAY


def _merged(spans):
    out = []
    for start, stop in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], stop))
        else:
            out.append((start, stop))
    return out


def _subtract(spans, taken):
    out = []
    for start, stop in spans:
        at = start
        for lo, hi in sorted(taken):
            if hi <= at or lo >= stop:
                continue
            if lo > at:
                out.append((at, lo))
            at = max(at, hi)
        if at < stop:
            out.append((at, stop))
    return out


def _failed(outcome):
    status = getattr(outcome, "status", None)
    return str(getattr(status, "value", status)).lower() == "failed"


class FamilyFillManager:
    """The scheduler's family gate: at most one active fill per symbol family."""

    def __init__(self, coordinator):
        self._coordinator = coordinator
        self._fills = {}
        self.metrics = {"fills": 0, "planned_chunks": 0, "pieces": 0, "piece_failures": 0,
                        "declined": 0, "stalls": 0, "planned_cells": 0}

    def note(self, request):
        """A new repair was submitted: start this family's fill if it has none."""
        if not _reasons(request) & FILL_REASONS:
            return
        family = family_of(request)
        if family is None or family in self._fills:
            return
        fill = FamilyFill(self, family)
        self._fills[family] = fill
        self.metrics["fills"] += 1
        fill.task = asyncio.get_running_loop().create_task(fill.run())

    def holds(self, request):
        """Whether this chunk must wait for its family's sources."""
        if not self._fills:
            return False
        family = family_of(request)
        fill = self._fills.get(family) if family is not None else None
        return fill is not None and fill.holds(request)

    def finished(self, fill):
        if self._fills.get(fill.family) is fill:
            del self._fills[fill.family]
        self.wake()

    def wake(self):
        self._coordinator._scheduler._drain()

    def snapshot(self):
        return {**self.metrics, "active": [
            {"family": list(fill.family), "planning": fill.planning, "pending_pieces": len(fill.pending)}
            for fill in self._fills.values()]}

    async def shutdown(self):
        tasks = [fill.task for fill in self._fills.values() if fill.task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._fills.clear()


class FamilyFill:
    def __init__(self, manager, family):
        self.manager, self.family = manager, family
        self.planning = True
        # Chunks planned first (each chart's newest): not held while the
        # others are planned, only by the pieces they overlap.
        self.early = set()
        self.pending = {}
        self.task = None
        self._pieces_running = set()
        self._turns = None

    def holds(self, request):
        if self.planning and (request.interval, request.start_ms, request.end_ms) not in self.early:
            return True
        if not self.pending:
            return False
        spec = parse_interval_spec(request.interval)
        lo = request.start_ms
        hi = spec.next_ms(spec.floor_ms(request.end_ms)) if spec is not None else request.end_ms + 1
        return any(start < hi and lo < end for start, end in self.pending.values())

    async def run(self):
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
            chunks = self._pending_chunks()
            newest = {}
            for request in chunks:
                if request.request_id not in newest or request.end_ms > newest[request.request_id].end_ms:
                    newest[request.request_id] = request
            first = list(newest.values())
            acquired = {}
            self._start(await self._plan_pieces(first, acquired))
            self.early = {(request.interval, request.start_ms, request.end_ms) for request in first}
            self.manager.wake()
            rest = [request for request in chunks
                    if (request.interval, request.start_ms, request.end_ms) not in self.early]
            if rest:
                self._start(await self._plan_pieces(rest, acquired))
            self.planning = False
            self.manager.wake()
            await self._wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.manager.metrics["declined"] += 1
            logger.info("Family fill for %s declined: %s", "/".join(self.family), exc)
        finally:
            self.planning = False
            self.pending = {}
            self.manager.finished(self)

    def _pending_chunks(self):
        scheduler = self.manager._coordinator._scheduler
        chunks = []
        for state in list(scheduler._requests.values()):
            if state.stale or state.failed is not None or family_of(state.request) != self.family:
                continue
            for chunk_id in state.chunk_ids:
                chunk = scheduler._chunks.get(chunk_id)
                if chunk is not None and chunk_id not in scheduler._tasks:
                    chunks.append(chunk.request)
        return chunks

    def _start(self, pieces):
        if self._turns is None:
            self._turns = asyncio.Semaphore(PIECE_CONCURRENCY)
        loop = asyncio.get_running_loop()
        for piece in pieces:
            self.pending[piece.metadata[PIECE_MARKER]] = _widen(
                piece.interval, piece.start_ms, piece.end_ms + _width(piece.interval))
            self._pieces_running.add(loop.create_task(self._one(piece)))
        self.manager.metrics["pieces"] += len(pieces)

    async def _one(self, piece):
        try:
            async with self._turns:
                outcome = await self.manager._coordinator.request_and_wait(piece)
            if _failed(outcome):
                self.manager.metrics["piece_failures"] += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            self.manager.metrics["piece_failures"] += 1
        finally:
            self.pending.pop(piece.metadata[PIECE_MARKER], None)
            self.manager.wake()

    async def _wait(self):
        while self._pieces_running:
            done, self._pieces_running = await asyncio.wait(
                self._pieces_running, timeout=STALL_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                # Release the chunks; the remaining pieces continue as
                # ordinary native repairs.
                self.manager.metrics["stalls"] += 1
                return

    async def _plan_pieces(self, chunks, acquired):
        """Pieces for these chunks, given what earlier pieces already acquire."""
        engine = self.manager._coordinator._engine
        if not chunks or engine is None or not callable(getattr(engine, "plan_mixed_sources", None)):
            return []
        demands = []
        for request in chunks:
            plan, diagnostics = None, {}
            for _ in range(PLAN_ATTEMPTS):
                try:
                    plan, diagnostics = await engine.plan_mixed_sources(
                        symbol=request.symbol, interval=request.interval, range_start_ms=request.start_ms,
                        range_end_ms=request.end_ms, exchange=request.exchange, market_type=request.market_type,
                        metadata={**request.metadata, "reason": request.reason, "requester": request.requester,
                                  "request_id": request.request_id})
                    break
                except (StaleAcquisition, MemoryBudgetExceeded):
                    # Earlier pieces are writing into this range, or hold the
                    # planning memory. Without a plan this chunk acquires for
                    # itself, as without a fill.
                    plan, diagnostics = None, {}
                    await asyncio.sleep(PLAN_RETRY_SECONDS)
            if plan is None and not diagnostics:
                continue
            decomposition = plan.decompositions[0] if plan is not None and plan.decompositions else None
            if decomposition is not None and decomposition.composition_target_range is not None:
                demands.append(self._demand(request, decomposition.composition_target_range, diagnostics))
            elif diagnostics.get("mixed_plan_fallback") and not request.metadata.get("required_history_composition"):
                # A declined optional batch (e.g. a cold prime period, where
                # fine REST is cheaper) runs on its single base grid: all of
                # its base rows. Its finer rows still refine other charts.
                demands.append(self._base_demand(request))
        self.manager.metrics["planned_chunks"] += len(demands)
        if not demands:
            return []
        stored = await self._stored(engine._storage, demands)
        extra = {interval: [opened for start, stop in spans for opened in range(start, stop, _width(interval))]
                 for interval, spans in acquired.items()}
        plan = await run_preparation(plan_family_sources, demands, stored, extra=extra)
        self.manager.metrics["planned_cells"] += sum(len(cells) for cells in plan.cells.values())
        ranges = {}
        for interval, spans in self._ranges(plan, demands).items():
            spans = _subtract(spans, acquired.get(interval, ()))
            if spans:
                ranges[interval] = spans
                acquired[interval] = _merged([*acquired.get(interval, ()), *spans])
        return self._pieces(ranges, demands[0].target)

    @staticmethod
    def _ranges(plan, demands):
        """Half-open source ranges the fill acquires, per grid (see module docstring)."""
        lo, hi = min(d.start_ms for d in demands), max(d.stop_ms for d in demands)
        boundaries = sorted({d.start_ms for d in demands} | {d.stop_ms for d in demands})
        out = {}
        coarse = {interval: cells for interval, cells in plan.cells.items() if _width(interval) >= HOUR}
        hourly = all(any(source.series.interval == "1h" for source in demand.sources) for demand in demands
                     if any(source.width_ms >= HOUR for source in demand.sources))
        if coarse and hourly:
            months = sorted({_month_start(opened) for cells in coarse.values() for opened in cells})
            start, stop = max(months[0], lo // HOUR * HOUR), min(_next_month(months[-1]), hi // HOUR * HOUR)
            if start < stop:
                out["1h"] = [(start, stop)]
        else:
            for interval in coarse:
                out[interval] = list(plan.windows[interval])
        for interval, windows in plan.windows.items():
            width = _width(interval)
            if width >= HOUR:
                continue
            for start, stop in windows:
                if (stop - start) // width >= DENSE_CELLS:
                    out.setdefault(interval, []).append((start, stop))
                elif any(start - DAY < boundary < stop + DAY for boundary in boundaries):
                    day_stop = min((stop - 1) // DAY * DAY + DAY, hi // width * width)
                    out.setdefault(interval, []).append((start // DAY * DAY, max(stop, day_stop)))
        return {interval: _merged(spans) for interval, spans in out.items()}

    @staticmethod
    def _pieces(ranges, target):
        """Contiguous native repairs of at most PIECE_ROWS rows, newest first."""
        pieces = []
        for interval, spans in ranges.items():
            width = _width(interval)
            for start, stop in spans:
                while stop > start:
                    first = max(start, stop - PIECE_ROWS * width)
                    pieces.append(RepairRequest(
                        symbol=target.symbol, interval=interval, start_ms=first, end_ms=stop - width,
                        exchange=target.exchange, market_type=target.market_type, reason="initial_history",
                        requester="family_fill", metadata={PIECE_MARKER: uuid.uuid4().hex}))
                    stop = first
        pieces.sort(key=lambda piece: piece.end_ms, reverse=True)
        return pieces

    @staticmethod
    def _demand(request, target_range, diagnostics):
        spec = parse_interval_spec(request.interval)
        target = SeriesKey(request.symbol, spec.canonical, exchange=request.exchange, market_type=request.market_type)
        policy, routes, precedence = _resolver.history_composition_routes(
            exchange=request.exchange, market_type=request.market_type, interval=request.interval)
        first, stop = target_range
        selected = set(diagnostics.get("mixed_selected_sources") or (route.canonical_interval for route in routes))
        sources = tuple(FixedHistorySource(replace(target, interval=route.canonical_interval), route.spec.nominal_ms,
                                           0, ((0, stop),), frozenset(policy.fields), policy.contract_id)
                        for route in routes if route.canonical_interval in selected)
        precedences = tuple((replace(target, interval=route.canonical_interval), route.spec.nominal_ms)
                            for route in precedence)
        return ChartDemand(target, first, stop, sources, precedences, frozenset(policy.fields))

    @staticmethod
    def _base_demand(request):
        spec = parse_interval_spec(request.interval)
        target = SeriesKey(request.symbol, spec.canonical, exchange=request.exchange, market_type=request.market_type)
        policy, _, _ = _resolver.history_composition_routes(
            exchange=request.exchange, market_type=request.market_type, interval=request.interval)
        base = parse_interval_spec(_resolver.resolve(exchange=request.exchange, market_type=request.market_type,
            interval=request.interval, purpose=IntervalPurpose.HISTORY).base_interval)
        first, stop = spec.floor_ms(request.start_ms), spec.next_ms(spec.floor_ms(request.end_ms))
        source = FixedHistorySource(replace(target, interval=base.canonical), base.nominal_ms, 0, ((0, stop),),
                                    frozenset(policy.fields), policy.contract_id)
        return ChartDemand(target, first, stop, (source,), (), frozenset(policy.fields))

    @staticmethod
    async def _stored(storage, demands):
        """What the planner's reads would see, over every demand's range."""
        return await read_stored_series(storage, demands, max_rows=MAX_STORED_ROWS)
