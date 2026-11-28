"""DataManager's side of the planner: which missing ranges it takes, and their lifecycle (ADR-DATA-001 S5).

With ``HISTORY_SYMBOL_PLANNER_ENABLED``, base history for a single-base derived
interval on a 1m-or-wider base (89m on 1m) becomes planner demand instead of its
own repair: a chart read's missing range (S5a), the forming bucket's closed
components a warm-start seed lacks (``forming``) and the warm-start tail rebuild
(``tail``, S5b). Pieces run as source-interval repairs (``CoordinatorPieceExecutor``),
so the source table has one writer lane and overlapping demand is fetched once;
a read's request ids go back to the API, which waits on and leases them as before.
Everything else (native charts, composed history, non-default identities, other
requesters, sub-minute bases such as 90s on 1s) keeps the existing path.

Once every source slot of a demand is present or handed back, the demand is
served and the planner forgets it:
- a read or a tail sends its target window to the existing target-interval path
  as one ordinary repair. With the base present that run only derives and writes
  the target bars (``backfill_aggregated``), which warm reopens read; slots of
  failed pieces are fetched there as without the planner (the engine reuses
  stored base for read repairs and for the warm-start tail);
- a seed needs no target run: the next ``/klines/latest`` poll seeds the forming
  bucket from the stored components.

Queries run in storage worker threads; the planner lives on the event loop.
``register`` hands the demand to the loop and waits briefly for the request
ids; when the loop does not answer in time, or the planner serves nothing of
the range, the caller keeps the existing path.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from collections.abc import Callable
from typing import Any

from app.data_engine.interval_policy import (
    IntervalAlignment, last_closed_bar_open_ms, parse_interval_ms, parse_interval_spec,
)
from app.data_engine.interval_resolution import IntervalPurpose, IntervalResolver, IntervalRouteKind

from .coordinator_executor import CoordinatorPieceExecutor, request_fields
from .demands import Demand, DemandOwner, kind_for_reason
from .pieces import Piece, PieceResult
from .planner import PlannerRegistry, SymbolHistoryPlanner, SymbolKey

logger = logging.getLogger("data_manager.symbol_history")

REGISTER_TIMEOUT_SECONDS = 2.0
# The scheduler runs one request per series at a time; this only bounds queued pieces.
MAX_SUBMITTED_PIECES = 16
# Chart reads (api/v1/klines.py). The engine reuses stored base slots for these and the tail.
READ_REQUESTERS = frozenset({"klines_history", "klines_history_before", "klines_range"})
# Warm-start demand (data_manager/warm_start.py): the forming bucket's components and the tail rebuild.
SEED_REQUESTER = "warm_start_custom_seed"
TAIL_REQUESTER = "warm_start_custom_tail"
PLANNED_REQUESTERS = READ_REQUESTERS | {SEED_REQUESTER, TAIL_REQUESTER}
# ...and only on these routes (BackfillEngine._reuse_derived_components): elsewhere, such as 90s on
# 1s, a served read's target run would fetch the whole base again, so those keep the existing path.
REUSED_BASE_EXCHANGES = frozenset({"binance", "okx"})
MIN_REUSED_BASE_MS = 60_000

# project_base_repair_to_target(symbol=, target_interval=, base_interval=, start_ms=, end_ms=,
#                               exchange=, market_type=) -> {"interval", "start_ms", "end_ms"} | None
ProjectTarget = Callable[..., dict[str, Any] | None]
# The existing submission: (symbol, interval, start_ms, end_ms, exchange, market_type, *, reason=,
#                           priority=, requester=, metadata=) -> request id
TriggerTarget = Callable[..., Any]


class HistoryDemandRouter:
    def __init__(
        self,
        coordinator: Any,
        *,
        loop: asyncio.AbstractEventLoop,
        project_target: ProjectTarget,
        trigger_target: TriggerTarget,
        resolver: IntervalResolver | None = None,
        clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self._coordinator = coordinator
        self._loop = loop
        self._project = project_target
        self._trigger_target = trigger_target
        self._resolver = resolver or IntervalResolver()
        self._clock_ms = clock_ms
        self._registry = PlannerRegistry(self._make_planner)
        # (symbol key, demand key) -> (requester, metadata) of the read that registered it
        self._origins: dict[tuple[SymbolKey, Any], tuple[str, dict[str, Any]]] = {}
        self.metrics = {"registered": 0, "fallbacks": 0, "served_derive": 0, "served_with_fetch": 0,
                        "served_forming": 0}
        add_listener = getattr(coordinator, "add_demand_listener", None)
        if callable(add_listener):
            add_listener(self.on_demand_event)

    # Which ranges -----------------------------------------------------------

    def takes(self, *, exchange: str, market_type: str, target_interval: str, base_interval: str,
              requester: str, metadata: dict[str, Any] | None) -> bool:
        """Whether this missing base range goes to the planner (Q1: single-base intervals)."""
        if requester not in PLANNED_REQUESTERS:
            return False
        if metadata and (metadata.get("required_history_composition") is not None
                         or metadata.get("bounded_history_batch_contract") is not None
                         or metadata.get("series_identity") is not None):
            return False
        if exchange not in REUSED_BASE_EXCHANGES:
            return False
        if self.base_for(exchange, market_type, target_interval) != base_interval:
            return False
        for interval, min_ms in ((base_interval, MIN_REUSED_BASE_MS), (target_interval, 0)):
            spec = parse_interval_spec(interval)
            if (spec is None or spec.alignment is not IntervalAlignment.FIXED_EPOCH or spec.phase_ms
                    or spec.nominal_ms < min_ms):
                return False
        return True

    def base_for(self, exchange: str, market_type: str, interval: str) -> str | None:
        """The history base of a derived interval, or None (native or unknown)."""
        try:
            route = self._resolver.resolve(exchange=exchange, market_type=market_type, interval=interval,
                                           purpose=IntervalPurpose.HISTORY)
        except Exception:  # noqa: BLE001 - unknown routes keep the existing path
            return None
        if route.kind is not IntervalRouteKind.DERIVED or not route.base_interval:
            return None
        return route.base_interval

    # Registration (any thread) -----------------------------------------------

    def register(self, *, symbol: str, exchange: str, market_type: str, target_interval: str,
                 base_interval: str, start_ms: int, end_ms: int, reason: str | None, requester: str,
                 metadata: dict[str, Any] | None) -> list[str] | None:
        """Register a missing base range ``[start_ms, end_ms]`` (inclusive opens).

        Returns the request ids of the pieces serving it, or None when the
        caller should use the existing path (nothing to serve, or the loop did
        not answer).
        """
        width = parse_interval_ms(base_interval)
        if not width:
            return None
        metadata = dict(metadata or {})
        generation = metadata.get("demand_generation")
        owner = DemandOwner(
            str(metadata.get("demand_owner_id") or f"{requester}:{exchange}:{market_type}:{symbol}@{target_interval}"),
            str(metadata["demand_scope"]) if metadata.get("demand_scope") else None,
            int(generation) if isinstance(generation, int) and not isinstance(generation, bool) else None,
        )
        demand = Demand(owner, target_interval, int(start_ms), int(end_ms) + width, kind_for_reason(reason))
        key = SymbolKey(exchange, market_type, symbol)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        try:
            if running is self._loop:
                ids = self._register_in_loop(key, demand, requester, metadata)
            else:
                ids = self._register_from_thread(key, demand, requester, metadata)
        except (concurrent.futures.TimeoutError, concurrent.futures.CancelledError, RuntimeError) as error:
            self.metrics["fallbacks"] += 1
            logger.warning("history planner did not take %s %s@%s: %r", exchange, symbol, target_interval, error)
            return None
        if not ids:
            self.metrics["fallbacks"] += 1
            return None
        self.metrics["registered"] += 1
        return [str(request_id) for request_id in ids]

    def _register_from_thread(self, key: SymbolKey, demand: Demand, requester: str,
                              metadata: dict[str, Any]) -> list[Any]:
        """Register on the loop and wait for the ids; after a timeout the loop registers nothing.

        The caller falls back to the existing path on a timeout, so a late
        registration would fetch the range twice.
        """
        done: concurrent.futures.Future[list[Any]] = concurrent.futures.Future()

        def register_in_loop() -> None:
            if not done.set_running_or_notify_cancel():
                return
            try:
                done.set_result(self._register_in_loop(key, demand, requester, metadata))
            except BaseException as error:  # noqa: BLE001 - re-raised in the waiting thread
                done.set_exception(error)

        self._loop.call_soon_threadsafe(register_in_loop)
        try:
            return done.result(timeout=REGISTER_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            if done.cancel():
                raise
            return done.result()  # it started meanwhile: use what it registered

    def _register_in_loop(self, key: SymbolKey, demand: Demand, requester: str,
                          metadata: dict[str, Any]) -> list[Any]:
        self._registry.prune()
        planner = self._registry.get(key)
        self._origins[(key, demand.key)] = (requester, metadata)
        handles = planner.register_now(demand)
        if not handles:
            # Nothing of it is planned or running here (present, handed back or
            # beyond the closed slots): the existing path keeps it.
            planner.drop(demand)
            self._origins.pop((key, demand.key), None)
        return handles

    # Planner per symbol ------------------------------------------------------

    def _make_planner(self, key: SymbolKey) -> SymbolHistoryPlanner:
        holder: dict[str, SymbolHistoryPlanner] = {}
        executor = CoordinatorPieceExecutor(self._coordinator, key)
        planner = SymbolHistoryPlanner(
            key, executor=executor, source_for=lambda interval: self._source_for(key, interval),
            closed_until=self._closed_until, max_running=MAX_SUBMITTED_PIECES,
            on_committed=lambda piece, result: self._settle(key, holder["planner"], piece),
            on_handed_back=lambda piece, ranges, error: self._settle(key, holder["planner"], piece),
        )
        holder["planner"] = planner
        return planner

    def _source_for(self, key: SymbolKey, interval: str) -> tuple[str, int]:
        base = self.base_for(key.exchange, key.market_type, interval) or interval
        width = parse_interval_ms(base)
        if not width:
            raise ValueError(f"no fixed width for history source {base}")
        return base, width

    def _closed_until(self, source_interval: str) -> int:
        now = self._clock_ms()
        width = parse_interval_ms(source_interval) or 60_000
        last_open = last_closed_bar_open_ms(now, source_interval)
        return last_open + width if last_open is not None else now - now % width

    def _settle(self, key: SymbolKey, planner: SymbolHistoryPlanner, piece: Piece) -> None:
        """Serve demands with nothing left to plan through the existing target path."""
        for demand, (start, end), complete in planner.settled(piece):
            requester, origin = self._origins.pop((key, demand.key), ("klines_history", {}))
            planner.drop(demand)
            if requester == SEED_REQUESTER:
                # The next /klines/latest poll seeds the bucket from the stored components.
                self.metrics["served_forming"] += 1
                continue
            target = self._project(symbol=key.symbol, target_interval=demand.target_interval,
                                   base_interval=piece.source_interval, start_ms=start,
                                   end_ms=end - piece.width_ms, exchange=key.exchange,
                                   market_type=key.market_type)
            if target is None:
                continue
            reason, priority = request_fields(demand.urgency)
            if requester in READ_REQUESTERS:
                carried = {name: origin[name] for name in ("demand_owner_id", "demand_scope", "demand_generation",
                                                           "query_reason") if name in origin}
                carried["requires_trusted_finality"] = True
            else:
                # The tail keeps its warm-start fields and, like its existing repair, asks for no
                # trusted finality, so the engine reuses the stored base (_reuse_derived_components).
                carried = dict(origin)
            metadata = {
                **carried,
                "requested_range": {"start_ms": int(target["start_ms"]), "end_ms": int(target["end_ms"])},
                "derived_from": piece.source_interval,
                "base_missing_range": {"start_ms": start, "end_ms": end - piece.width_ms},
                "symbol_history_served": "derive" if complete else "fetch_handed_back",
            }
            try:
                self._trigger_target(
                    key.symbol, str(target["interval"]), int(target["start_ms"]), int(target["end_ms"]),
                    key.exchange, key.market_type, reason=reason, priority=priority, requester=requester,
                    metadata=metadata)
            except Exception:  # noqa: BLE001 - the next read registers it again
                logger.exception("history planner could not serve %s %s", key.symbol, target)
                continue
            self.metrics["served_derive" if complete else "served_with_fetch"] += 1

    # Lifecycle -----------------------------------------------------------------

    def on_demand_event(self, kind: str, *args: Any) -> None:
        """The coordinator's demand scopes and owners end planner demand too (§6)."""
        for planner_key in self._registry.keys():
            planner = self._registry.existing(planner_key)
            if planner is None:
                continue
            if kind == "scope":
                planner.advance_scope(str(args[0]), int(args[1]))
            elif kind == "owner":
                planner.release_owner_id(str(args[0]))
        live = {(planner_key, demand_key) for planner_key in self._registry.keys()
                for demand_key in self._registry.existing(planner_key).demand_keys()}
        for origin_key in [origin_key for origin_key in self._origins if origin_key not in live]:
            del self._origins[origin_key]
        self._registry.prune()

    def snapshot(self) -> dict[str, Any]:
        return {"planners": self._registry.snapshot(), **self.metrics}

    async def close(self) -> None:
        await self._registry.close()
