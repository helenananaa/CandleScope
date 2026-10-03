"""Backfill execution, durable gap recovery and cache delivery for DataManager."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol

from app.core.executors import run_storage
from app.data_engine.history.calendar import (
    TradingCalendar,
    expected_bucket_end_ms,
    latest_closed_expected_open_ms,
)
from app.data_engine.history.models import (
    BoundaryReason,
    BoundarySide,
    BoundaryState,
    HistoryDisposition,
    HistoryPlan,
)
from app.data_engine.history.service import HistoryAvailabilityService
from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    last_closed_bar_open_ms,
    parse_interval_ms,
)
from app.data_engine.kline_quality import (
    repair_requires_trusted_finality,
    source_is_trusted_final,
)
from app.data_engine.series_identity import (
    identity_from_metadata,
)
from app.exchanges.models import (
    HistoryAvailabilityPolicy,
    HistoryEmptyPageSemantics,
)
from app.exchanges.rate_limits import RateLimitDeferred
from .backfill_contracts import (
    BACKFILL_REASON_PRIORITIES,
    HistoryPolicyResolver,
    LedgerReconciliationReport,
    RepairOutcome,
    RepairReconcileSummary,
    RepairReportSummary,
    RepairRequest,
    RepairRetryDeferred,
    RepairWrittenRangeSummary,
    ScanReport,
    _merge_derived_repair_targets,
    priority_for_reason,
)
from .backfill_history import BackfillHistoryPlanner
from .backfill_scheduler import BackfillScheduler
from .models import BarData, DataEvent, DataEventType, SeriesKey, audience_for_backfill_reason

logger = logging.getLogger("data_manager.backfill_coordinator")


# Public API waits are capped at eight seconds; retain useful late-wait results
# while bounding memory in a long-running process.
_COORDINATOR_OUTCOME_HISTORY_LIMIT = 512
_REQUEST_ID_ALIAS_HISTORY_LIMIT = 2048
_RETAINED_OUTCOME_TTL_SECONDS = 60.0
_LEDGER_STALE_AFTER_MS = 15 * 60 * 1000
_LEDGER_COMPACTION_INTERVAL_SECONDS = 60 * 60
_TERMINAL_LEDGER_RETRY_MS = 24 * 60 * 60 * 1000
_TAIL_AUDIT_LOOKBACK_BARS = 1_000
_LEDGER_RECONCILE_MAX_PAGES_PER_RANGE = 20
_LEDGER_RECONCILE_MAX_TOTAL_PAGES = 40
_LEDGER_RECONCILIATION_SNAPSHOT_KEY = "_ledger_reconciliation_snapshot"


def _decode_metadata_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


class BackfillEngineLike(Protocol):
    """Minimal engine contract used by BackfillCoordinator."""

    async def run(self, **kwargs: Any) -> Any:
        ...


class BackfillStorageLike(Protocol):
    """Minimal storage contract used by BackfillCoordinator."""

    def get_bounds(self, *args: Any, **kwargs: Any) -> dict:
        ...

    def query_bars(self, **kwargs: Any) -> list[dict]:
        ...


BarsBackfilledCallback = Callable[..., Awaitable[None]]
EventEmitter = Callable[[DataEvent], Awaitable[None]]


class GapLedgerLike(Protocol):
    """Optional persistent state sink for gap lifecycle transitions."""

    def upsert_detected(self, request: RepairRequest, *, status: str = "queued") -> None:
        ...

    def mark_started(self, request: RepairRequest, *, attempt: int) -> None:
        ...

    def mark_retry_wait(
        self,
        request: RepairRequest,
        *,
        attempt: int,
        error: str | None,
        next_retry_at: int,
    ) -> None:
        ...

    def mark_verifying(self, request: RepairRequest) -> None:
        ...

    def mark_resolved(
        self,
        request: RepairRequest,
        *,
        status: str,
        missing_count: int | None = None,
        error: str | None = None,
    ) -> None:
        ...

    def get_status(self, request: RepairRequest) -> dict[str, Any] | None:
        ...


class BackfillCoordinator:
    """Coordinate repair execution, ledger verification and cache delivery."""

    def __init__(
        self,
        *,
        storage: BackfillStorageLike,
        bars_backfilled: BarsBackfilledCallback,
        emit_event: EventEmitter,
        engine: BackfillEngineLike | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        max_retries: int = 3,
        base_delay_seconds: float = 5.0,
        gap_ledger: GapLedgerLike | None = None,
        max_concurrency: int = 4,
        chunk_bars: int = 1000,
        history_service: HistoryAvailabilityService | None = None,
        history_policy_resolver: HistoryPolicyResolver | None = None,
    ) -> None:
        self._storage = storage
        self._bars_backfilled = bars_backfilled
        self._emit_event = emit_event
        self._engine = engine
        self._loop = loop
        self._max_retries = max(1, max_retries)
        self._base_delay_seconds = base_delay_seconds
        self._gap_ledger = gap_ledger
        self._history_service = history_service
        self._history_planner = BackfillHistoryPlanner(history_service, history_policy_resolver)
        self._gap_audit_cursors: dict[tuple[str, str, str, str], int] = {}
        self._gap_audit_tail_cursors: dict[tuple[str, str, str, str], int] = {}
        self._gap_audit_series_rotation = 0
        self._ledger_pending_upserts: OrderedDict[str, RepairRequest] = OrderedDict()
        self._ledger_pending_operations: deque[tuple[Callable[..., Any], tuple[Any, ...]]] = deque()
        self._ledger_write_task: asyncio.Task | None = None
        self._ledger_open_cache: list[dict[str, Any]] = []
        self._ledger_health_cache: dict[str, Any] = {}
        self._ledger_suppression_cache: dict[
            tuple[str, str, str, str],
            tuple[dict[str, Any], ...],
        ] = {}
        self._ledger_last_compaction_at: float | None = None
        self._ledger_open_cache_updated_at = 0.0
        self._ledger_open_refresh_task: asyncio.Task | None = None

        self._futures: dict[str, asyncio.Future[RepairOutcome]] = {}
        self._outcomes: dict[str, RepairOutcome] = {}
        self._outcome_expires_at: dict[str, float] = {}
        self._request_id_aliases: dict[str, str] = {}
        self._request_id_alias_expires_at: dict[str, float | None] = {}
        self._max_retained_outcomes = _COORDINATOR_OUTCOME_HISTORY_LIMIT
        self._max_request_id_aliases = _REQUEST_ID_ALIAS_HISTORY_LIMIT
        self._retained_outcome_ttl_seconds = _RETAINED_OUTCOME_TTL_SECONDS
        self._progress_snapshots: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._progress_waiters: dict[
            str,
            set[asyncio.Future[dict[str, Any]]],
        ] = {}
        self._scope_generations: OrderedDict[str, int] = OrderedDict()
        self._revoked_demand_owners: OrderedDict[str, str] = OrderedDict()
        self._shutdown = False
        self._scheduler = BackfillScheduler(
            execute=self._run_with_retries,
            future_for=self._future_for,
            complete=self._complete,
            finalize=self._ledger_finalize_parent,
            on_queued=self._ledger_upsert_detected,
            on_progress=self._note_progress,
            max_concurrency=max_concurrency,
            chunk_bars=chunk_bars,
        )

    def set_engine(self, engine: BackfillEngineLike) -> None:
        self._engine = engine

    def trigger(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        exchange: str = "binance",
        market_type: str = "spot",
        *,
        reason: str = "query_gap",
        priority: int | None = None,
        requester: str = "query",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Synchronous QueryEngine-compatible callback."""
        return self.request(RepairRequest(
            symbol=symbol,
            interval=interval,
            start_ms=int(start_ms),
            end_ms=int(end_ms),
            exchange=exchange,
            market_type=market_type,
            reason=reason,
            priority=priority,
            requester=requester,
            metadata=metadata or {},
        ))

    def request(self, request: RepairRequest) -> str:
        """Submit a repair request and return its request id."""
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                raise RuntimeError("BackfillCoordinator requires an event loop")

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            return self._request_in_loop(request)[0]

        self._loop.call_soon_threadsafe(self._request_in_loop, request)
        return request.request_id

    async def request_and_wait(self, request: RepairRequest) -> RepairOutcome:
        _request_id, future = self._request_in_loop(request)
        return await asyncio.shield(future)

    def progress_for_request(self, request_id: str) -> dict[str, Any] | None:
        canonical_id = self._canonical_request_id(request_id)
        snapshot = self._progress_snapshots.get(canonical_id)
        return dict(snapshot) if snapshot is not None else None

    async def wait_for_progress(
        self,
        request_id: str,
        *,
        after_revision: int = 0,
    ) -> dict[str, Any] | None:
        """Wait for the next physical chunk revision, not the whole parent."""
        canonical_id = self._canonical_request_id(request_id)
        snapshot = self._progress_snapshots.get(canonical_id)
        if snapshot is not None and (
            int(snapshot.get("revision", 0)) > int(after_revision)
            or bool(snapshot.get("terminal"))
        ):
            return dict(snapshot)
        if canonical_id in self._outcomes:
            return dict(snapshot) if snapshot is not None else None

        waiter: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        waiters = self._progress_waiters.setdefault(canonical_id, set())
        waiters.add(waiter)
        snapshot = self._progress_snapshots.get(canonical_id)
        if snapshot is not None and (
            int(snapshot.get("revision", 0)) > int(after_revision)
            or bool(snapshot.get("terminal"))
        ):
            waiter.set_result(dict(snapshot))
        try:
            while True:
                observed = await waiter
                if (
                    int(observed.get("revision", 0)) > int(after_revision)
                    or bool(observed.get("terminal"))
                ):
                    return observed
        finally:
            waiters.discard(waiter)
            if not waiters:
                self._progress_waiters.pop(canonical_id, None)

    async def acquire_demand(
        self,
        request_id: str,
        *,
        owner_id: str,
        scope: str | None = None,
        generation: int | None = None,
    ) -> bool:
        canonical_id = self._canonical_request_id(request_id)
        normalized_scope = str(scope or "").strip() or None
        normalized_generation = (
            max(0, int(generation))
            if generation is not None
            else None
        )
        stale_generation = bool(
            normalized_scope is not None
            and normalized_generation is not None
            and (
                current := self._scope_generations.get(normalized_scope)
            ) is not None
            and normalized_generation < current
        )
        acquired = self._scheduler.acquire_demand(
            canonical_id,
            owner_id=owner_id,
            scope=normalized_scope,
            generation=normalized_generation,
        )
        if acquired and stale_generation:
            # Close the race where generation N schedules its repair after
            # generation N+1 already advanced the pane scope. Acquiring then
            # immediately releasing lets the scheduler cancel the otherwise
            # unowned request with the same pending/chunk-boundary semantics.
            await self._scheduler.release_demand(
                canonical_id,
                owner_id=owner_id,
                cancel_if_unobserved=True,
                reason=(
                    f"scope_stale:{normalized_scope}:{normalized_generation}"
                ),
            )
            return False
        return acquired

    async def release_demand(
        self,
        request_id: str,
        *,
        owner_id: str,
        cancel_if_unobserved: bool = True,
        reason: str = "demand_released",
    ) -> bool:
        canonical_id = self._canonical_request_id(request_id)
        return await self._scheduler.release_demand(
            canonical_id,
            owner_id=owner_id,
            cancel_if_unobserved=cancel_if_unobserved,
            reason=reason,
        )

    async def advance_demand_scope(self, scope: str, generation: int) -> int:
        normalized_scope = str(scope or "").strip()
        if not normalized_scope:
            return 0
        normalized_generation = max(0, int(generation))
        current = self._scope_generations.get(normalized_scope)
        if current is not None and normalized_generation <= current:
            return 0
        self._scope_generations.pop(normalized_scope, None)
        self._scope_generations[normalized_scope] = normalized_generation
        while len(self._scope_generations) > _REQUEST_ID_ALIAS_HISTORY_LIMIT:
            self._scope_generations.popitem(last=False)
        return await self._scheduler.supersede_scope(
            normalized_scope,
            normalized_generation,
        )

    async def revoke_demand_owner(
        self,
        owner_id: str,
        *,
        reason: str = "demand_owner_revoked",
    ) -> int:
        normalized_owner = str(owner_id or "").strip()
        if not normalized_owner:
            return 0
        self._revoked_demand_owners.pop(normalized_owner, None)
        self._revoked_demand_owners[normalized_owner] = str(reason or "demand_owner_revoked")
        while len(self._revoked_demand_owners) > _REQUEST_ID_ALIAS_HISTORY_LIMIT:
            self._revoked_demand_owners.popitem(last=False)
        return await self._scheduler.revoke_owner(
            normalized_owner,
            reason=str(reason or "demand_owner_revoked"),
        )

    def is_demand_generation_current(self, scope: str, generation: int) -> bool:
        normalized_scope = str(scope or "").strip()
        if not normalized_scope:
            return True
        current = self._scope_generations.get(normalized_scope)
        return current is None or int(generation) >= current

    def has_foreground_work(self) -> bool:
        """Expose scheduler foreground ownership to speculative producers."""

        return self._scheduler.has_foreground_work()

    def has_backfill_work(self) -> bool:
        """Expose all scheduler ownership to speculative producers."""

        return self._scheduler.has_backfill_work()

    def foreground_idle_seconds(self) -> float:
        """Return continuous scheduler idle time since foreground ownership."""

        return self._scheduler.foreground_idle_seconds()

    def _note_progress(
        self,
        request: RepairRequest,
        progress: dict[str, Any],
    ) -> None:
        request_id = request.request_id
        snapshot = dict(progress)
        previous = self._progress_snapshots.get(request_id)
        should_notify = bool(snapshot.get("terminal")) or previous is None or (
            int(snapshot.get("revision", 0))
            > int(previous.get("revision", 0))
        )
        self._progress_snapshots.pop(request_id, None)
        self._progress_snapshots[request_id] = snapshot
        while len(self._progress_snapshots) > self._max_retained_outcomes:
            self._progress_snapshots.popitem(last=False)
        if not should_notify:
            return
        waiters = self._progress_waiters.pop(request_id, set())
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(dict(snapshot))

    async def refresh_suppressions(self) -> int:
        """Refresh the non-blocking submission cache from durable ledger state."""
        if self._gap_ledger is None:
            self._ledger_suppression_cache = {}
            return 0
        list_suppressions = getattr(self._gap_ledger, "list_suppressions", None)
        if not callable(list_suppressions):
            self._ledger_suppression_cache = {}
            return 0
        now_ms = int(time.time() * 1000)
        try:
            rows = await run_storage(list_suppressions, now_ms=now_ms)
        except Exception:
            logger.exception("Gap ledger suppression refresh failed")
            return sum(len(rows) for rows in self._ledger_suppression_cache.values())

        grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for raw in rows or ():
            if not isinstance(raw, dict):
                continue
            try:
                start_ms = int(raw["start_ms"])
                end_ms = int(raw["end_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            if start_ms > end_ms:
                continue
            status = str(raw.get("status") or "")
            if status not in {"source_empty", "failed", "unavailable"}:
                continue
            retry_at_raw = raw.get("next_retry_at")
            try:
                retry_at_ms = (
                    int(retry_at_raw) if retry_at_raw is not None else None
                )
            except (TypeError, ValueError):
                continue
            if status != "source_empty" and retry_at_ms is None:
                continue
            if retry_at_ms is not None and retry_at_ms <= now_ms:
                continue
            key = (
                str(raw.get("exchange") or "binance").strip().lower(),
                str(raw.get("market_type") or "spot").strip().lower(),
                str(raw.get("symbol") or "").strip().upper(),
                str(raw.get("interval") or "").strip(),
            )
            if not key[2] or not key[3]:
                continue
            observation_raw = raw.get("resolved_at") or raw.get("last_checked_at")
            try:
                observed_at_ms = (
                    int(observation_raw) if observation_raw is not None else None
                )
            except (TypeError, ValueError):
                observed_at_ms = None
            cache_request = RepairRequest(
                exchange=key[0],
                market_type=key[1],
                symbol=key[2],
                interval=key[3],
                start_ms=start_ms,
                end_ms=end_ms,
                reason="suppression_cache",
                requester="suppression_cache",
                metadata=_decode_metadata_object(raw.get("metadata_json")),
            )
            calendar, calendar_resolved = self._calendar_for_reconciliation(
                cache_request
            )
            grouped.setdefault(key, []).append({
                "suppressed": True,
                "source": "gap_ledger",
                "ledger_id": raw.get("id"),
                "ledger_status": status,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "reason": str(
                    raw.get("last_error")
                    or raw.get("reason")
                    or f"gap_ledger_{status}"
                ),
                "retry_at_ms": retry_at_ms,
                # It may become eligible after retry_at_ms, but there is no
                # useful immediate retry while this record is current.
                "retryable": False,
                "terminal": True,
                "observed_at_ms": observed_at_ms,
                # Private, in-memory-only fields keep synchronous submission
                # checks free of policy/SQLite resolution while preserving
                # session-calendar closed-bar semantics.
                "_calendar": calendar,
                "_calendar_resolved": calendar_resolved,
            })
        self._ledger_suppression_cache = {
            key: tuple(sorted(values, key=lambda row: (
                int(row["end_ms"]) - int(row["start_ms"]),
                -int(row.get("ledger_id") or 0),
            )))
            for key, values in grouped.items()
        }
        return sum(len(values) for values in self._ledger_suppression_cache.values())

    def get_repair_suppression(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        exchange: str = "binance",
        market_type: str = "spot",
    ) -> dict[str, Any] | None:
        """Return an exact/covering current cooldown without SQLite I/O."""
        key = (
            str(exchange or "binance").strip().lower(),
            str(market_type or "spot").strip().lower(),
            str(symbol or "").strip().upper(),
            str(interval or "").strip(),
        )
        requested_start = int(start_ms)
        requested_end = int(end_ms)
        now_ms = int(time.time() * 1000)
        for record in self._ledger_suppression_cache.get(key, ()):
            retry_at_ms = record.get("retry_at_ms")
            if retry_at_ms is not None and int(retry_at_ms) <= now_ms:
                continue
            if (
                int(record["start_ms"]) <= requested_start
                and int(record["end_ms"]) >= requested_end
            ):
                if record.get("ledger_status") == "source_empty":
                    request = RepairRequest(
                        exchange=key[0],
                        market_type=key[1],
                        symbol=key[2],
                        interval=key[3],
                        start_ms=requested_start,
                        end_ms=requested_end,
                        reason="suppression_lookup",
                        requester="suppression_lookup",
                    )
                    target = self._target_open_range_with_calendar(
                        request,
                        calendar=record.get("_calendar"),
                        calendar_resolved=bool(record.get("_calendar_resolved")),
                    )
                    # Unknown calendars and still-forming windows remain
                    # fail-closed.  Once the range has closed, however, a
                    # source-empty observation made before that close is stale
                    # evidence and must not suppress the first closed repair.
                    if target is not None and target[2] <= now_ms:
                        observed_at_ms = record.get("observed_at_ms")
                        if (
                            observed_at_ms is None
                            or target[2] > int(observed_at_ms)
                        ):
                            continue
                return {
                    **{
                        name: value
                        for name, value in record.items()
                        if not name.startswith("_")
                    },
                    "requested_start_ms": requested_start,
                    "requested_end_ms": requested_end,
                }
        return None

    async def wait_for_request(self, request_id: str) -> RepairOutcome | None:
        """Wait for an already-submitted repair request by id."""
        while not self._shutdown:
            self._prune_retained_state()
            canonical_id = self._canonical_request_id(request_id)
            outcome = self._outcomes.get(canonical_id)
            if outcome is not None:
                return outcome
            future = self._futures.get(canonical_id)
            if future is not None:
                return await asyncio.shield(future)
            await asyncio.sleep(0.01)
        return None

    async def startup_scan(
        self,
        targets: list[tuple[str, str, str]],
        intervals: tuple[str, ...],
        *,
        delay_seconds: float = 5.0,
    ) -> ScanReport:
        """Scan configured startup targets and repair stale tails."""
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        report = ScanReport()
        now_ms = int(time.time() * 1000)

        # A restart loses the in-memory scheduler but not its durable ledger.
        # Recheck stale rows against exact storage before either closing or
        # requeueing them; never infer work solely from the saved status.
        ledger_report = await self.reconcile_gap_ledger(limit=100)
        report.ledger_scanned += ledger_report.scanned
        report.ledger_resolved += ledger_report.resolved
        report.ledger_requeued += ledger_report.requeued
        report.ledger_compacted += ledger_report.compacted
        report.ledger_skipped += ledger_report.skipped
        report.ledger_failed += ledger_report.failed
        report.errors.extend(ledger_report.errors)

        for exchange, market_type, symbol in targets:
            for interval in intervals:
                if self._shutdown:
                    return report
                try:
                    bounds = await run_storage(
                        self._storage.get_bounds,
                        symbol,
                        interval,
                        exchange=exchange,
                        market_type=market_type,
                    )
                    latest = bounds.get("latest_open_time")
                    if not latest:
                        continue

                    interval_ms = parse_interval_ms(interval) or 60_000
                    if now_ms - int(latest) <= interval_ms * 3:
                        continue

                    report.scanned += 1
                    outcome = await self.request_and_wait(RepairRequest(
                        symbol=symbol,
                        interval=interval,
                        start_ms=int(latest),
                        end_ms=now_ms,
                        exchange=exchange,
                        market_type=market_type,
                        reason="startup_gap_scan",
                        priority=priority_for_reason("startup_gap_scan"),
                        requester="startup_scan",
                    ))
                    if self._is_failed(outcome.status):
                        report.failed += 1
                        if outcome.error:
                            report.errors.append(outcome.error)
                    else:
                        report.repaired += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    report.failed += 1
                    report.errors.append(
                        f"{exchange}:{market_type}:{symbol}@{interval}: {exc}"
                    )
                    logger.warning(
                        "Startup gap scan failed for %s:%s:%s@%s: %s",
                        exchange,
                        market_type,
                        symbol,
                        interval,
                        exc,
                    )

        return report

    async def audit_storage_gaps(
        self,
        targets: list[tuple[str, str, str]],
        intervals: tuple[str, ...],
        *,
        scan_limit: int = 50_000,
        max_gaps: int = 100,
        repair: bool = True,
    ) -> ScanReport:
        """Scan tracked series for stored interior gaps and optionally queue repairs."""
        exact_series = [
                (exchange, market_type, symbol, interval)
                for exchange, market_type, symbol in targets
                for interval in intervals
        ]
        return await self.audit_storage_series(
            exact_series,
            scan_limit=scan_limit,
            max_gaps=max_gaps,
            repair=repair,
            tail_series=exact_series,
        )

    async def audit_storage_series(
        self,
        series: Iterable[tuple[str, str, str, str]],
        *,
        scan_limit: int = 50_000,
        max_gaps: int = 100,
        repair: bool = True,
        tail_series: Iterable[tuple[str, str, str, str]] | None = None,
    ) -> ScanReport:
        """Scan exact series and optionally queue repairs.

        Inventory-only series are scanned for interior continuity.  Only the
        explicit ``tail_series`` set is extended to the current closed-bar
        edge, preventing abandoned storage series from causing a catch-up
        storm merely because they still exist on disk.
        """
        report = ScanReport()
        scanner = getattr(self._storage, "scan_gaps", None)
        if not callable(scanner):
            report.errors.append("storage does not support gap scanning")
            return report

        queued = 0
        seen_series: set[tuple[str, str, str, str]] = set()
        normalized_series: list[tuple[str, str, str, str]] = []
        for raw_exchange, raw_market_type, raw_symbol, raw_interval in series:
            exchange = str(raw_exchange or "binance").strip().lower()
            market_type = str(raw_market_type or "spot").strip().lower()
            symbol = str(raw_symbol or "").strip().upper()
            interval = str(raw_interval or "").strip()
            if not symbol or not interval:
                continue
            series_key = (exchange, market_type, symbol, interval)
            if series_key in seen_series:
                continue
            seen_series.add(series_key)
            normalized_series.append(series_key)

        normalized_tail_series: set[tuple[str, str, str, str]] = set()
        for raw in tail_series or ():
            try:
                raw_exchange, raw_market_type, raw_symbol, raw_interval = raw
            except (TypeError, ValueError):
                continue
            tail_key = (
                str(raw_exchange or "binance").strip().lower(),
                str(raw_market_type or "spot").strip().lower(),
                str(raw_symbol or "").strip().upper(),
                str(raw_interval or "").strip(),
            )
            if tail_key[2] and tail_key[3]:
                normalized_tail_series.add(tail_key)

        async def _queue_scan_gaps(
            scan: dict[str, Any],
            *,
            exchange: str,
            market_type: str,
            symbol: str,
            interval: str,
            lane: str,
        ) -> int | None:
            nonlocal queued
            priority = priority_for_reason(
                "tail_gap" if lane == "tail" else "background_gap_audit"
            )
            for gap in scan.get("gaps", []):
                if not isinstance(gap, dict):
                    continue
                if queued >= max_gaps:
                    return int(gap["start_ms"])
                request = RepairRequest(
                    symbol=symbol,
                    interval=interval,
                    start_ms=int(gap["start_ms"]),
                    end_ms=int(gap["end_ms"]),
                    exchange=exchange,
                    market_type=market_type,
                    reason="background_gap_audit",
                    priority=priority,
                    requester="background_audit",
                    metadata={
                        "origin": "background_gap_audit",
                        "audit_lane": lane,
                        "gap_type": gap.get("reason", "unknown"),
                    },
                )
                if await self._should_skip_audited_gap(request):
                    continue
                if repair:
                    canonical_id = self.request(request)
                    # Scheduler dedupe/merge returns the already-owned parent
                    # id.  It did not consume another queue slot, so it must
                    # not consume this audit's gap budget either.
                    if canonical_id == request.request_id:
                        queued += 1
                        report.queued += 1
                else:
                    report.repaired += 1
            return None

        def _next_audit_cursor(
            raw_cursor_ms: int,
            interval_value: str,
            calendar: TradingCalendar | None,
        ) -> int:
            if calendar is not None:
                next_open_ms = calendar.next_expected_open(
                    int(raw_cursor_ms),
                    interval_value,
                )
                if next_open_ms is None:
                    raise ValueError(
                        f"no next expected open for interval: {interval_value}"
                    )
                return next_open_ms
            interval_width_ms = parse_interval_ms(interval_value)
            if interval_width_ms is None or interval_width_ms <= 0:
                raise ValueError(f"unsupported interval: {interval_value}")
            bucket_start_ms = compute_bucket_start_ms(
                int(raw_cursor_ms),
                interval_width_ms,
                interval=interval_value,
            )
            return compute_bucket_end_ms(
                bucket_start_ms,
                interval_width_ms,
                interval=interval_value,
            )

        if normalized_series:
            start_index = self._gap_audit_series_rotation % len(normalized_series)
            normalized_series = (
                normalized_series[start_index:] + normalized_series[:start_index]
            )
        else:
            start_index = 0

        processed_series = 0
        for exchange, market_type, symbol, interval in normalized_series:
            series_key = (exchange, market_type, symbol, interval)
            if self._shutdown:
                return report
            if queued >= max_gaps:
                break
            try:
                processed_series += 1
                calendar_request = RepairRequest(
                    symbol=symbol,
                    interval=interval,
                    start_ms=0,
                    end_ms=0,
                    exchange=exchange,
                    market_type=market_type,
                    reason="background_gap_audit",
                    requester="background_audit",
                )
                audit_calendar, calendar_resolved = (
                    self._calendar_for_reconciliation(calendar_request)
                )
                if not calendar_resolved:
                    raise ValueError("history calendar is unavailable")
                if series_key in normalized_tail_series:
                    audit_now_ms = int(time.time() * 1000)
                    closed_end_ms = (
                        latest_closed_expected_open_ms(
                            audit_calendar,
                            audit_now_ms,
                            interval,
                        )
                        if audit_calendar is not None
                        else last_closed_bar_open_ms(audit_now_ms, interval)
                    )
                    if closed_end_ms is None:
                        raise ValueError(f"unsupported interval: {interval}")
                    get_bounds = getattr(self._storage, "get_bounds", None)
                    if callable(get_bounds):
                        try:
                            bounds = await run_storage(
                                get_bounds,
                                symbol,
                                interval,
                                exchange=exchange,
                                market_type=market_type,
                            )
                            latest_open_ms = (
                                bounds.get("latest_open_time")
                                if isinstance(bounds, dict)
                                else None
                            )
                            if (
                                latest_open_ms is not None
                                and int(latest_open_ms) <= int(closed_end_ms)
                            ):
                                interval_ms = parse_interval_ms(interval)
                                if interval_ms is None or interval_ms <= 0:
                                    raise ValueError(
                                        f"unsupported interval: {interval}"
                                    )
                                raw_tail_start_ms = max(
                                    0,
                                    int(closed_end_ms)
                                    - interval_ms * (_TAIL_AUDIT_LOOKBACK_BARS - 1),
                                )
                                tail_start_ms = (
                                    audit_calendar.first_expected_open(
                                        raw_tail_start_ms,
                                        int(closed_end_ms),
                                        interval,
                                    )
                                    if audit_calendar is not None
                                    else compute_bucket_start_ms(
                                        raw_tail_start_ms,
                                        interval_ms,
                                        interval=interval,
                                    )
                                )
                                if tail_start_ms is None:
                                    raise ValueError(
                                        "tail audit range has no expected bars"
                                    )
                                earliest_open_ms = bounds.get("earliest_open_time")
                                if earliest_open_ms is not None:
                                    bounded_start_ms = max(
                                        int(tail_start_ms),
                                        int(earliest_open_ms),
                                    )
                                    if audit_calendar is not None:
                                        tail_start_ms = audit_calendar.first_expected_open(
                                            bounded_start_ms,
                                            int(closed_end_ms),
                                            interval,
                                        )
                                        if tail_start_ms is None:
                                            raise ValueError(
                                                "bounded tail audit range has no expected bars"
                                            )
                                    else:
                                        tail_start_ms = bounded_start_ms
                                tail_cursor_ms = self._gap_audit_tail_cursors.get(
                                    series_key
                                )
                                if (
                                    tail_cursor_ms is not None
                                    and tail_start_ms <= tail_cursor_ms <= closed_end_ms
                                ):
                                    tail_start_ms = tail_cursor_ms
                                elif tail_cursor_ms is not None:
                                    # The rolling lookback or storage bounds moved
                                    # past an old checkpoint.  Restart within the
                                    # current exact tail window, never outside it.
                                    self._gap_audit_tail_cursors.pop(series_key, None)
                                tail_scan = await run_storage(
                                    scanner,
                                    symbol=symbol,
                                    interval=interval,
                                    start_ms=int(tail_start_ms),
                                    end_ms=int(closed_end_ms),
                                    exchange=exchange,
                                    market_type=market_type,
                                    limit=_TAIL_AUDIT_LOOKBACK_BARS,
                                )
                                report.scanned += 1
                                if not isinstance(tail_scan, dict):
                                    raise ValueError(
                                        "storage tail scan returned a malformed result"
                                    )
                                if tail_scan.get("error"):
                                    raise ValueError(str(tail_scan["error"]))
                                first_unprocessed_tail_gap_ms = await _queue_scan_gaps(
                                    tail_scan,
                                    exchange=exchange,
                                    market_type=market_type,
                                    symbol=symbol,
                                    interval=interval,
                                    lane="tail",
                                )
                                if first_unprocessed_tail_gap_ms is not None:
                                    self._gap_audit_tail_cursors[series_key] = (
                                        first_unprocessed_tail_gap_ms
                                    )
                                else:
                                    resume_from_ms = tail_scan.get("resume_from_ms")
                                    if (
                                        tail_scan.get("truncated")
                                        and resume_from_ms is not None
                                    ):
                                        resume_value = _next_audit_cursor(
                                            int(resume_from_ms),
                                            interval,
                                            audit_calendar,
                                        )
                                        if resume_value <= tail_start_ms:
                                            resume_value = _next_audit_cursor(
                                                tail_start_ms,
                                                interval,
                                                audit_calendar,
                                            )
                                        if resume_value <= closed_end_ms:
                                            self._gap_audit_tail_cursors[series_key] = (
                                                resume_value
                                            )
                                        else:
                                            self._gap_audit_tail_cursors.pop(
                                                series_key,
                                                None,
                                            )
                                    else:
                                        self._gap_audit_tail_cursors.pop(
                                            series_key,
                                            None,
                                        )
                                if queued >= max_gaps:
                                    continue
                        except asyncio.CancelledError:
                            raise
                        except Exception as tail_exc:
                            report.failed += 1
                            report.errors.append(
                                f"{exchange}:{market_type}:{symbol}@{interval} "
                                f"tail: {tail_exc}"
                            )
                            logger.warning(
                                "Background tail audit failed for %s:%s:%s@%s: %s",
                                exchange,
                                market_type,
                                symbol,
                                interval,
                                tail_exc,
                            )

                cursor_ms = self._gap_audit_cursors.get(
                    (exchange, market_type, symbol, interval)
                )
                scan_kwargs: dict[str, Any] = {
                    "symbol": symbol,
                    "interval": interval,
                    "exchange": exchange,
                    "market_type": market_type,
                    "limit": scan_limit,
                }
                if cursor_ms is not None:
                    scan_kwargs["start_ms"] = cursor_ms
                scan = await run_storage(scanner, **scan_kwargs)
                if not isinstance(scan, dict):
                    raise ValueError("storage gap scan returned a malformed result")
                if scan.get("error"):
                    raise ValueError(str(scan["error"]))
                report.scanned += 1
                first_unprocessed_gap_ms = await _queue_scan_gaps(
                    scan,
                    exchange=exchange,
                    market_type=market_type,
                    symbol=symbol,
                    interval=interval,
                    lane="interior",
                )

                if first_unprocessed_gap_ms is not None:
                    # The page may contain more gaps than this audit's global
                    # queue budget.  Resume at the first untouched gap, not at
                    # the page tail, or that work is skipped forever.
                    self._gap_audit_cursors[series_key] = first_unprocessed_gap_ms
                else:
                    resume_from_ms = scan.get("resume_from_ms")
                    if scan.get("truncated") and resume_from_ms is not None:
                        resume_value = _next_audit_cursor(
                            int(resume_from_ms),
                            interval,
                            audit_calendar,
                        )
                        if cursor_ms is not None and resume_value <= cursor_ms:
                            resume_value = _next_audit_cursor(
                                cursor_ms,
                                interval,
                                audit_calendar,
                            )
                        self._gap_audit_cursors[series_key] = resume_value
                    else:
                        self._gap_audit_cursors.pop(series_key, None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                report.failed += 1
                report.errors.append(
                    f"{exchange}:{market_type}:{symbol}@{interval}: {exc}"
                )
                logger.warning(
                    "Background gap audit failed for %s:%s:%s@%s: %s",
                    exchange,
                    market_type,
                    symbol,
                    interval,
                    exc,
                )

        if normalized_series:
            self._gap_audit_series_rotation = (
                start_index + max(1, processed_series)
            ) % len(normalized_series)

        ledger_report = await self.reconcile_gap_ledger(
            limit=max_gaps,
            scan_limit=scan_limit,
        )
        report.ledger_scanned += ledger_report.scanned
        report.ledger_resolved += ledger_report.resolved
        report.ledger_requeued += ledger_report.requeued
        report.ledger_compacted += ledger_report.compacted
        report.ledger_skipped += ledger_report.skipped
        report.ledger_failed += ledger_report.failed
        if ledger_report.errors:
            report.errors.extend(ledger_report.errors)
        return report

    async def reconcile_gap_ledger(
        self,
        *,
        ranges: Iterable[RepairRequest] | None = None,
        limit: int = 100,
        scan_limit: int = 50_000,
        stale_after_ms: int = _LEDGER_STALE_AFTER_MS,
    ) -> LedgerReconciliationReport:
        """Close stale ledger decisions only after an exact storage recheck.

        A past repair can populate storage before this process knows about it,
        leaving a legacy ``source_empty`` or ``failed`` row behind.  This
        method never trusts the caller or the ledger by itself: every target
        range is normalised to target-bar opens, must be fully closed, and is
        then scanned for head/interior/tail gaps before any ledger mutation.

        With ``ranges=None`` it reconciles inactive ledger rows.  Internal
        callers may supply exact known ranges (for example, after importing
        authoritative history); overlapping inactive rows are still closed
        only if their entire range is covered by the verified scan.
        """
        report = LedgerReconciliationReport()
        if self._gap_ledger is None:
            return report
        await self.refresh_suppressions()

        compact_source_empty = getattr(
            self._gap_ledger,
            "compact_source_empty_drift",
            None,
        )
        compaction_now = time.monotonic()
        if (
            callable(compact_source_empty)
            and (
                self._ledger_last_compaction_at is None
                or compaction_now - self._ledger_last_compaction_at
                >= _LEDGER_COMPACTION_INTERVAL_SECONDS
            )
        ):
            try:
                report.compacted = max(0, int(await run_storage(
                    compact_source_empty,
                    limit=max(10_000, int(limit) * 1_000),
                ) or 0))
            except Exception:
                logger.exception("Gap ledger source-empty compaction failed")
            finally:
                self._ledger_last_compaction_at = compaction_now

        mark_covered = getattr(self._gap_ledger, "mark_covered_resolved", None)
        if not callable(mark_covered):
            report.errors.append("gap ledger does not support coverage reconciliation")
            report.failed += 1
            return report

        if ranges is None:
            list_reconcilable = getattr(self._gap_ledger, "list_reconcilable", None)
            if not callable(list_reconcilable):
                return report
            try:
                lookup_now_ms = int(time.time() * 1000)
                rows = await run_storage(
                    list_reconcilable,
                    limit=max(1, int(limit)),
                    stale_before_ms=(
                        lookup_now_ms - max(0, int(stale_after_ms))
                    ),
                    due_before_ms=lookup_now_ms,
                )
            except Exception as exc:
                report.failed += 1
                report.errors.append(f"gap ledger reconciliation lookup failed: {exc}")
                logger.exception("Gap ledger reconciliation lookup failed")
                return report
            candidates: list[tuple[RepairRequest, int | None]] = []
            for row in rows:
                if not isinstance(row, dict):
                    report.failed += 1
                    report.errors.append("gap ledger returned a malformed row")
                    continue
                try:
                    candidates.append((
                        self._repair_request_from_ledger_row(row),
                        int(row["id"]) if row.get("id") is not None else None,
                    ))
                except (KeyError, TypeError, ValueError) as exc:
                    report.failed += 1
                    report.errors.append(f"invalid gap-ledger row: {exc}")
                    await self._defer_ledger_reconciliation(
                        row_id=(
                            int(row["id"])
                            if row.get("id") is not None
                            else None
                        ),
                        reason=f"invalid gap-ledger row: {exc}",
                        row_snapshot=row,
                    )
        else:
            candidates = [(request, None) for request in ranges]

        scanner = getattr(self._storage, "scan_gaps", None)
        if not callable(scanner):
            report.failed += 1
            report.errors.append("storage does not support gap scanning")
            for raw_request, ledger_row_id in candidates:
                if ledger_row_id is not None:
                    await self._defer_ledger_reconciliation(
                        request=raw_request,
                        row_id=ledger_row_id,
                        reason="storage does not support gap scanning",
                    )
            return report

        now_ms = int(time.time() * 1000)
        remaining_page_budget = _LEDGER_RECONCILE_MAX_TOTAL_PAGES
        seen_ranges: set[tuple[tuple[str, ...], int, int]] = set()
        for raw_request, ledger_row_id in candidates:
            if self._shutdown:
                break
            try:
                request = self._canonical_reconciliation_request(raw_request)
            except (AttributeError, TypeError, ValueError) as exc:
                report.failed += 1
                report.errors.append(f"invalid gap-ledger range: {exc}")
                if ledger_row_id is not None:
                    await self._defer_ledger_reconciliation(
                        request=raw_request,
                        row_id=ledger_row_id,
                        reason=f"invalid gap-ledger range: {exc}",
                    )
                continue
            if request is None:
                report.skipped += 1
                if ledger_row_id is not None:
                    await self._defer_ledger_reconciliation(
                        request=raw_request,
                        row_id=ledger_row_id,
                        reason="unsupported ledger interval",
                    )
                continue
            range_key = (request.series_key, request.start_ms, request.end_ms)
            if range_key in seen_ranges:
                continue
            seen_ranges.add(range_key)
            if not self._request_range_is_fully_closed(request, now_ms):
                report.skipped += 1
                if ledger_row_id is not None:
                    await self._defer_ledger_reconciliation(
                        request=request,
                        row_id=ledger_row_id,
                        reason="ledger range is not fully closed",
                    )
                continue

            if remaining_page_budget <= 0:
                report.skipped += 1
                if ledger_row_id is not None:
                    await self._defer_ledger_reconciliation(
                        request=request,
                        row_id=ledger_row_id,
                        reason="global ledger reconciliation page budget exhausted",
                    )
                continue

            try:
                scan = await self._scan_reconciliation_range(
                    scanner,
                    request,
                    scan_limit=max(1, int(scan_limit)),
                    max_pages=min(
                        _LEDGER_RECONCILE_MAX_PAGES_PER_RANGE,
                        remaining_page_budget,
                    ),
                )
                scanned_pages = int(scan.get("pages", 1) or 1)
                report.scanned += scanned_pages
                remaining_page_budget = max(
                    0,
                    remaining_page_budget - scanned_pages,
                )
                if not isinstance(scan, dict) or scan.get("error"):
                    report.skipped += 1
                    if ledger_row_id is not None:
                        checkpoint_ms = scan.get("checkpoint_ms")
                        if checkpoint_ms is not None:
                            await self._checkpoint_ledger_reconciliation(
                                row_id=ledger_row_id,
                                cursor_ms=int(checkpoint_ms),
                                scanned_bars=int(
                                    scan.get(
                                        "verified_unique_bars",
                                        scan.get("scanned_bars", 0),
                                    )
                                    or 0
                                ),
                                reason=str(
                                    scan.get("error") or "malformed storage scan"
                                ),
                                row_snapshot=self._reconciliation_snapshot(request),
                            )
                        else:
                            await self._defer_ledger_reconciliation(
                                request=request,
                                row_id=ledger_row_id,
                                reason=str(
                                    scan.get("error") or "malformed storage scan"
                                ),
                            )
                    continue
                if scan.get("truncated"):
                    report.skipped += 1
                    if ledger_row_id is not None:
                        await self._checkpoint_ledger_reconciliation(
                            row_id=ledger_row_id,
                            cursor_ms=int(
                                scan.get("checkpoint_ms", request.start_ms)
                            ),
                            scanned_bars=int(
                                scan.get(
                                    "verified_unique_bars",
                                    scan.get("scanned_bars", 0),
                                )
                                or 0
                            ),
                            reason="exact storage scan page budget exhausted",
                            row_snapshot=self._reconciliation_snapshot(request),
                        )
                    continue
                gap_count = int(scan.get("gap_count", 0) or 0)
                scanned_bars = int(scan.get("scanned_bars", 0) or 0)
                if (
                    gap_count == 0
                    and scanned_bars > 0
                    and repair_requires_trusted_finality(
                        request.metadata,
                        reason=request.reason,
                    )
                ):
                    _plan, history_context = self._history_planner.plan(request)
                    trusted_verification = await self._verify_request_range(
                        request,
                        context=history_context,
                    )
                    verified_trusted = trusted_verification.get(
                        "verified_contiguous"
                    )
                    if verified_trusted is None:
                        report.skipped += 1
                        if ledger_row_id is not None:
                            await self._defer_ledger_reconciliation(
                                request=request,
                                row_id=ledger_row_id,
                                reason=(
                                    "storage cannot verify trusted-finality "
                                    "provenance during ledger reconciliation"
                                ),
                            )
                        continue
                    if verified_trusted is False:
                        gap_count = max(
                            1,
                            int(
                                trusted_verification.get(
                                    "remaining_missing_bars",
                                    1,
                                )
                                or 1
                            ),
                        )
                if gap_count == 0 and scanned_bars > 0:
                    checkpoint = request.metadata.get(
                        "reconciliation_checkpoint"
                    )
                    used_checkpoint = False
                    if isinstance(checkpoint, dict):
                        try:
                            used_checkpoint = (
                                int(checkpoint.get("cursor_ms"))
                                > int(request.start_ms)
                            )
                        except (TypeError, ValueError):
                            used_checkpoint = False
                    if used_checkpoint or int(scan.get("pages", 1) or 1) > 1:
                        verifier = getattr(
                            self._storage,
                            "verify_contiguous_range",
                            None,
                        )
                        verification_error: str | None = None
                        if not callable(verifier):
                            verification_error = (
                                "storage cannot exactly revalidate a persisted "
                                "reconciliation checkpoint"
                            )
                        else:
                            try:
                                exact = await run_storage(
                                    verifier,
                                    symbol=request.symbol,
                                    interval=request.interval,
                                    start_ms=request.start_ms,
                                    end_ms=request.end_ms,
                                    exchange=request.exchange,
                                    market_type=request.market_type,
                                )
                                if (
                                    not isinstance(exact, dict)
                                    or exact.get("verified_contiguous") is not True
                                ):
                                    verification_error = (
                                        str(exact.get("error") or "")
                                        if isinstance(exact, dict)
                                        else ""
                                    ) or (
                                        "storage changed during checkpointed "
                                        "reconciliation"
                                    )
                            except Exception as exc:
                                verification_error = (
                                    "checkpoint count verification failed: "
                                    f"{exc}"
                                )
                        if verification_error is not None:
                            if ledger_row_id is not None:
                                await self._defer_ledger_reconciliation(
                                    request=request,
                                    row_id=ledger_row_id,
                                    reason=verification_error,
                                    clear_checkpoint=True,
                                )
                            report.skipped += 1
                            continue
                    coverage = request.metadata.get("canonical_coverage_range")
                    if not isinstance(coverage, dict):
                        report.skipped += 1
                        continue
                    resolved = await run_storage(
                        mark_covered,
                        request,
                        coverage_start_ms=int(coverage["start_ms"]),
                        coverage_end_ms=int(coverage["end_ms"]),
                        row_snapshot=self._reconciliation_snapshot(request),
                    )
                    report.resolved += max(0, int(resolved or 0))
                    continue

                prior_status = str(request.metadata.get("ledger_status") or "")
                if gap_count > 0 and prior_status in {
                    "queued",
                    "repairing",
                    "verifying",
                    "partial",
                    "retry_wait",
                    "failed",
                    "unavailable",
                    "not_expected",
                }:
                    if ledger_row_id is not None:
                        claimed = await self._defer_ledger_reconciliation(
                            request=request,
                            row_id=ledger_row_id,
                            reason="storage gap confirmed; scheduling recovery",
                            delay_ms=1,
                            clear_checkpoint=True,
                        )
                        if not claimed:
                            report.skipped += 1
                            continue
                    recovery_metadata = dict(request.metadata)
                    recovery_metadata.pop("reconciliation_checkpoint", None)
                    recovery_metadata.pop(
                        _LEDGER_RECONCILIATION_SNAPSHOT_KEY,
                        None,
                    )
                    try:
                        recovery_count = max(
                            0,
                            int(
                                recovery_metadata.get(
                                    "ledger_recovery_count",
                                    0,
                                )
                                or 0
                            ),
                        )
                    except (TypeError, ValueError):
                        recovery_count = 0
                    recovery_metadata["ledger_recovery_count"] = min(
                        recovery_count + 1,
                        32,
                    )
                    recovery = RepairRequest(
                        symbol=request.symbol,
                        interval=request.interval,
                        start_ms=request.start_ms,
                        end_ms=request.end_ms,
                        exchange=request.exchange,
                        market_type=request.market_type,
                        reason="ledger_recovery",
                        priority=priority_for_reason("query_gap"),
                        requester="ledger_reconcile",
                        metadata={
                            **recovery_metadata,
                            "origin": "stale_ledger_recovery",
                        },
                        request_id=request.request_id,
                    )
                    self.request(recovery)
                    report.requeued += 1
                    continue
                if ledger_row_id is not None:
                    await self._defer_ledger_reconciliation(
                        request=request,
                        row_id=ledger_row_id,
                        reason="storage range remains non-contiguous",
                        delay_ms=(
                            86_400_000
                            if prior_status == "source_empty"
                            else _LEDGER_STALE_AFTER_MS
                        ),
                        clear_checkpoint=True,
                    )
                report.skipped += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                report.failed += 1
                report.errors.append(
                    f"{request.exchange}:{request.market_type}:"
                    f"{request.symbol}@{request.interval}: {exc}"
                )
                logger.warning(
                    "Gap ledger storage reconciliation failed for %s:%s:%s@%s: %s",
                    request.exchange,
                    request.market_type,
                    request.symbol,
                    request.interval,
                    exc,
                )
                if ledger_row_id is not None:
                    await self._defer_ledger_reconciliation(
                        request=request,
                        row_id=ledger_row_id,
                        reason=f"storage reconciliation failed: {exc}",
                    )
        await self.refresh_suppressions()
        return report

    async def _scan_reconciliation_range(
        self,
        scanner: Callable[..., Any],
        request: RepairRequest,
        *,
        scan_limit: int,
        max_pages: int = _LEDGER_RECONCILE_MAX_PAGES_PER_RANGE,
    ) -> dict[str, Any]:
        """Page an exact ledger range until continuity is proven or disproven."""
        cursor_ms = int(request.start_ms)
        total_scanned = 0
        total_unique_scanned = 0
        checkpoint_scanned = 0
        pages = 0
        interval_ms = parse_interval_ms(request.interval) or 60_000
        calendar, calendar_resolved = self._calendar_for_reconciliation(request)
        if not calendar_resolved:
            return {
                "error": "history calendar became unavailable during reconciliation",
                "truncated": False,
                "gap_count": 0,
                "scanned_bars": 0,
                "pages": 0,
            }
        raw_checkpoint = request.metadata.get("reconciliation_checkpoint")
        if isinstance(raw_checkpoint, dict):
            try:
                checkpoint_ms = int(raw_checkpoint["cursor_ms"])
            except (KeyError, TypeError, ValueError):
                checkpoint_ms = cursor_ms
            if request.start_ms <= checkpoint_ms <= request.end_ms:
                canonical_checkpoint = (
                    calendar.first_expected_open(
                        checkpoint_ms,
                        request.end_ms,
                        request.interval,
                    )
                    if calendar is not None
                    else compute_bucket_start_ms(
                        checkpoint_ms,
                        interval_ms,
                        interval=request.interval,
                    )
                )
                if (
                    canonical_checkpoint is not None
                    and request.start_ms <= canonical_checkpoint <= request.end_ms
                ):
                    cursor_ms = canonical_checkpoint
                    if cursor_ms > request.start_ms:
                        try:
                            checkpoint_scanned = max(
                                0,
                                int(raw_checkpoint.get("scanned_bars", 0) or 0),
                            )
                        except (TypeError, ValueError):
                            checkpoint_scanned = 0
        while pages < max(1, int(max_pages)):
            scan = await run_storage(
                scanner,
                symbol=request.symbol,
                interval=request.interval,
                start_ms=cursor_ms,
                end_ms=request.end_ms,
                exchange=request.exchange,
                market_type=request.market_type,
                limit=max(1, int(scan_limit)),
            )
            pages += 1
            if not isinstance(scan, dict):
                return {
                    "error": "storage gap scan returned a malformed result",
                    "truncated": False,
                    "gap_count": 0,
                    "scanned_bars": total_scanned,
                    "pages": pages,
                    "checkpoint_ms": cursor_ms,
                    "verified_unique_bars": (
                        checkpoint_scanned + total_unique_scanned
                    ),
                }
            if scan.get("error"):
                return {
                    **scan,
                    "scanned_bars": total_scanned + int(
                        scan.get("scanned_bars", 0) or 0
                    ),
                    "pages": pages,
                    "checkpoint_ms": cursor_ms,
                    "verified_unique_bars": (
                        checkpoint_scanned + total_unique_scanned
                    ),
                }
            page_scanned = max(0, int(scan.get("scanned_bars", 0) or 0))
            total_scanned += page_scanned
            total_unique_scanned += page_scanned
            raw_gap_count = scan.get("gap_count")
            gap_count = int(
                raw_gap_count
                if raw_gap_count is not None
                else len(scan.get("gaps", []) or [])
            )
            if gap_count > 0:
                return {
                    **scan,
                    "gap_count": gap_count,
                    "scanned_bars": total_scanned,
                    "truncated": False,
                    "pages": pages,
                    "verified_unique_bars": (
                        checkpoint_scanned + total_unique_scanned
                    ),
                }
            if not scan.get("truncated"):
                return {
                    **scan,
                    "gap_count": 0,
                    "scanned_bars": total_scanned,
                    "truncated": False,
                    "pages": pages,
                    "verified_unique_bars": (
                        checkpoint_scanned + total_unique_scanned
                    ),
                }
            resume_from_ms = scan.get("resume_from_ms")
            if resume_from_ms is None:
                return {
                    **scan,
                    "error": "truncated storage scan did not provide a resume cursor",
                    "scanned_bars": total_scanned,
                    "truncated": True,
                    "pages": pages,
                    "checkpoint_ms": cursor_ms,
                    "verified_unique_bars": (
                        checkpoint_scanned + total_unique_scanned
                    ),
                }
            resume_value = int(resume_from_ms)
            if calendar is not None:
                next_cursor_ms = calendar.next_expected_open(
                    resume_value,
                    request.interval,
                )
            else:
                resume_bucket_ms = compute_bucket_start_ms(
                    resume_value,
                    interval_ms,
                    interval=request.interval,
                )
                # Storage exposes an inclusive last-open cursor.  Exact scans
                # resume at the next canonical UTC bucket in legacy mode.
                next_cursor_ms = compute_bucket_end_ms(
                    resume_bucket_ms,
                    interval_ms,
                    interval=request.interval,
                )
            if next_cursor_ms is None:
                return {
                    **scan,
                    "error": "storage scan resume cursor has no next expected open",
                    "gap_count": 0,
                    "scanned_bars": total_scanned,
                    "truncated": True,
                    "pages": pages,
                    "checkpoint_ms": cursor_ms,
                    "verified_unique_bars": (
                        checkpoint_scanned + total_unique_scanned
                    ),
                }
            if next_cursor_ms <= cursor_ms:
                return {
                    **scan,
                    "error": "storage scan resume cursor did not advance",
                    "gap_count": 0,
                    "scanned_bars": total_scanned,
                    "truncated": True,
                    "pages": pages,
                    "checkpoint_ms": cursor_ms,
                    "verified_unique_bars": (
                        checkpoint_scanned + total_unique_scanned
                    ),
                }
            if next_cursor_ms > request.end_ms:
                return {
                    **scan,
                    "error": "storage scan resume cursor exceeded the requested range",
                    "gap_count": 0,
                    "scanned_bars": total_scanned,
                    "truncated": True,
                    "pages": pages,
                    "checkpoint_ms": cursor_ms,
                    "verified_unique_bars": (
                        checkpoint_scanned + total_unique_scanned
                    ),
                }
            cursor_ms = next_cursor_ms

        return {
            "gap_count": 0,
            "scanned_bars": total_scanned,
            "truncated": True,
            "pages": pages,
            "checkpoint_ms": cursor_ms,
            "verified_unique_bars": checkpoint_scanned + total_unique_scanned,
        }

    async def _checkpoint_ledger_reconciliation(
        self,
        *,
        row_id: int,
        cursor_ms: int,
        scanned_bars: int,
        reason: str,
        delay_ms: int = _LEDGER_STALE_AFTER_MS,
        row_snapshot: dict[str, Any] | None = None,
    ) -> None:
        """Lease and persist progress for a bounded exact-storage scan."""
        if self._gap_ledger is None:
            return
        checkpoint = getattr(
            self._gap_ledger,
            "checkpoint_reconciliation_row",
            None,
        )
        next_retry_at = int(time.time() * 1000) + max(1, int(delay_ms))
        if callable(checkpoint):
            try:
                persisted = await run_storage(
                    checkpoint,
                    int(row_id),
                    cursor_ms=int(cursor_ms),
                    scanned_bars=max(0, int(scanned_bars)),
                    next_retry_at=next_retry_at,
                    error=reason,
                    row_snapshot=row_snapshot,
                )
                if persisted:
                    return
            except Exception:
                logger.exception("Gap ledger reconciliation checkpoint failed")
        await self._defer_ledger_reconciliation(
            row_id=row_id,
            reason=reason,
            delay_ms=delay_ms,
            row_snapshot=row_snapshot,
        )

    async def _clear_ledger_reconciliation_checkpoint(
        self,
        row_id: int,
        *,
        row_snapshot: dict[str, Any] | None = None,
    ) -> bool:
        if self._gap_ledger is None:
            return False
        clear = getattr(
            self._gap_ledger,
            "clear_reconciliation_checkpoint_row",
            None,
        )
        if not callable(clear):
            return True
        try:
            return bool(await run_storage(
                clear,
                int(row_id),
                row_snapshot=row_snapshot,
            ))
        except Exception:
            logger.exception("Gap ledger reconciliation checkpoint cleanup failed")
            return False

    async def _defer_ledger_reconciliation(
        self,
        *,
        request: RepairRequest | None = None,
        row_id: int | None = None,
        reason: str,
        delay_ms: int = _LEDGER_STALE_AFTER_MS,
        row_snapshot: dict[str, Any] | None = None,
        clear_checkpoint: bool = False,
    ) -> bool:
        """Lease a skipped candidate so it cannot starve the next ledger rows."""
        if self._gap_ledger is None:
            return False
        if row_snapshot is None:
            row_snapshot = self._reconciliation_snapshot(request)
        next_retry_at = int(time.time() * 1000) + max(1, int(delay_ms))
        defer_row = getattr(self._gap_ledger, "defer_reconciliation_row", None)
        if row_id is not None and callable(defer_row):
            try:
                return bool(await run_storage(
                    defer_row,
                    row_id,
                    next_retry_at=next_retry_at,
                    error=reason,
                    row_snapshot=row_snapshot,
                    clear_checkpoint=clear_checkpoint,
                ))
            except Exception:
                logger.exception("Gap ledger row defer failed")
        mark_checked = getattr(self._gap_ledger, "mark_reconciled_checked", None)
        if request is not None and callable(mark_checked):
            try:
                await run_storage(
                    mark_checked,
                    request,
                    next_retry_at=next_retry_at,
                )
                return True
            except Exception:
                logger.exception("Gap ledger reconciliation defer failed")
        return False

    async def shutdown(self) -> None:
        """Cancel active and pending repairs."""
        self._shutdown = True
        await self._scheduler.shutdown()
        for request_id, waiters in list(self._progress_waiters.items()):
            snapshot = dict(self._progress_snapshots.get(request_id) or {})
            snapshot.update({
                "request_id": request_id,
                "status": "cancelled",
                "terminal": True,
            })
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_result(dict(snapshot))
        self._progress_waiters.clear()
        ledger_task = self._ledger_write_task
        if ledger_task is not None:
            await asyncio.gather(ledger_task, return_exceptions=True)
        refresh_task = self._ledger_open_refresh_task
        if refresh_task is not None:
            await asyncio.gather(refresh_task, return_exceptions=True)

    def snapshot(self) -> dict:
        snapshot = self._scheduler.snapshot()
        snapshot["gap_ledger_open"] = self._ledger_open_snapshot()
        snapshot["gap_ledger_health"] = dict(self._ledger_health_cache)
        return snapshot

    async def snapshot_async(self) -> dict:
        """Return an exact snapshot without performing SQLite on the loop."""
        snapshot = self._scheduler.snapshot()
        if self._gap_ledger is None:
            snapshot["gap_ledger_open"] = []
            snapshot["gap_ledger_health"] = {
                "open_total": 0,
                "by_status": {},
                "age_buckets": {},
            }
            return snapshot
        list_open = getattr(self._gap_ledger, "list_open", None)
        if not callable(list_open):
            snapshot["gap_ledger_open"] = []
            return snapshot
        try:
            rows = await run_storage(list_open, limit=50)
            self._ledger_open_cache = [
                dict(row)
                for row in rows
                if isinstance(row, dict)
            ]
            self._ledger_open_cache_updated_at = time.monotonic()
        except Exception:
            logger.exception("Gap ledger open snapshot failed")
        health_summary = getattr(self._gap_ledger, "health_summary", None)
        if callable(health_summary):
            try:
                health = await run_storage(health_summary, sample_limit=50)
                if isinstance(health, dict):
                    self._ledger_health_cache = dict(health)
            except Exception:
                logger.exception("Gap ledger health summary failed")
        if not self._ledger_health_cache:
            self._ledger_health_cache = {
                "open_total": len(self._ledger_open_cache),
                "by_status": {},
                "age_buckets": {},
                "sample_limit": 50,
            }
        snapshot["gap_ledger_open"] = [dict(row) for row in self._ledger_open_cache]
        snapshot["gap_ledger_health"] = dict(self._ledger_health_cache)
        return snapshot

    def _request_in_loop(
        self,
        request: RepairRequest,
    ) -> tuple[str, asyncio.Future[RepairOutcome]]:
        if self._shutdown:
            raise RuntimeError("BackfillCoordinator is shut down")

        self._prune_retained_state()
        rejected_reason = self._demand_rejection_reason(request)
        if rejected_reason is not None:
            future = self._future_for(request)
            outcome = RepairOutcome(
                request=request,
                status="cancelled",
                verified_contiguous=False,
                error=rejected_reason,
                terminal_reason="demand_superseded",
                retryable=False,
            )
            self._complete(request, outcome)
            self._note_progress(request, {
                "request_id": request.request_id,
                "revision": 0,
                "status": "cancelled",
                "terminal": True,
                "completed_chunks": 0,
                "total_chunks": 0,
                "pending_chunks": 0,
                "bars_loaded": 0,
                "priority": request.priority,
                "demand_count": 0,
                "cancel_requested": True,
                "updated_at_ms": int(time.time() * 1000),
            })
            return request.request_id, future
        suppression = self.get_repair_suppression(
            request.symbol,
            request.interval,
            request.start_ms,
            request.end_ms,
            request.exchange,
            request.market_type,
        )
        if suppression is not None:
            future = self._future_for(request)
            outcome = RepairOutcome(
                request=request,
                status="suppressed",
                verified_contiguous=False,
                terminal_reason=f"gap_ledger_{suppression['ledger_status']}",
                retryable=False,
                retry_at_ms=suppression.get("retry_at_ms"),
                suppressed=True,
                ledger_status=str(suppression["ledger_status"]),
                suppression=dict(suppression),
            )
            self._complete(request, outcome)
            return request.request_id, future
        prepared = self._history_planner.prepare(request)
        if prepared.request is None:
            self._ledger_mark_history_deferred(request, prepared.plan)
            future = self._future_for(request)
            outcome = self._history_planner.no_fetch_outcome(request, prepared.plan)
            self._complete(request, outcome)
            return request.request_id, future

        canonical_id, future = self._scheduler.submit(prepared.request)
        if canonical_id != request.request_id:
            self._request_id_aliases[request.request_id] = canonical_id
            self._request_id_alias_expires_at[request.request_id] = None
            self._prune_retained_state()
        return canonical_id, future

    def _demand_rejection_reason(self, request: RepairRequest) -> str | None:
        metadata = request.metadata or {}
        owner_id = str(metadata.get("demand_owner_id") or "").strip()
        if owner_id and owner_id in self._revoked_demand_owners:
            return self._revoked_demand_owners[owner_id]
        scope = str(metadata.get("demand_scope") or "").strip()
        generation_raw = metadata.get("demand_generation")
        if not scope or generation_raw is None:
            return None
        try:
            generation = int(generation_raw)
        except (TypeError, ValueError):
            return "invalid_demand_generation"
        current = self._scope_generations.get(scope)
        if current is not None and generation < current:
            return f"scope_superseded:{scope}:{generation}<{current}"
        return None


    def _canonical_request_id(self, request_id: str) -> str:
        canonical_id = request_id
        seen: set[str] = set()
        while canonical_id not in seen:
            seen.add(canonical_id)
            next_id = self._request_id_aliases.get(canonical_id)
            if next_id is None:
                break
            canonical_id = next_id
        return canonical_id

    def _prune_retained_state(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        expired_outcomes = [
            request_id
            for request_id, expires_at in self._outcome_expires_at.items()
            if expires_at <= current
        ]
        for request_id in expired_outcomes:
            self._drop_retained_outcome(request_id)

        expired_aliases = [
            request_id
            for request_id, expires_at in self._request_id_alias_expires_at.items()
            if expires_at is not None and expires_at <= current
        ]
        for request_id in expired_aliases:
            self._drop_request_id_alias(request_id)

        while len(self._outcomes) > self._max_retained_outcomes:
            self._drop_retained_outcome(next(iter(self._outcomes)))
        while len(self._request_id_aliases) > self._max_request_id_aliases:
            self._drop_request_id_alias(next(iter(self._request_id_aliases)))

    def _drop_retained_outcome(self, request_id: str) -> None:
        self._outcomes.pop(request_id, None)
        self._outcome_expires_at.pop(request_id, None)
        aliases = [
            alias_id
            for alias_id in self._request_id_aliases
            if self._canonical_request_id(alias_id) == request_id
        ]
        for alias_id in aliases:
            self._drop_request_id_alias(alias_id)

    def _drop_request_id_alias(self, request_id: str) -> None:
        self._request_id_aliases.pop(request_id, None)
        self._request_id_alias_expires_at.pop(request_id, None)

    def _retain_completed_outcome(
        self,
        request: RepairRequest,
        outcome: RepairOutcome,
    ) -> None:
        now = time.monotonic()
        expires_at = now + self._retained_outcome_ttl_seconds
        self._outcomes[request.request_id] = outcome
        self._outcome_expires_at[request.request_id] = expires_at
        aliases = [
            alias_id
            for alias_id in self._request_id_aliases
            if self._canonical_request_id(alias_id) == request.request_id
        ]
        for alias_id in aliases:
            self._request_id_alias_expires_at[alias_id] = expires_at
        self._prune_retained_state(now)

    def _future_for(self, request: RepairRequest) -> asyncio.Future[RepairOutcome]:
        future = self._futures.get(request.request_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._futures[request.request_id] = future
        return future

    async def _run_with_retries(self, request: RepairRequest) -> RepairOutcome:
        next_attempt = request._retry_attempt
        prepared = self._history_planner.prepare(request)
        if prepared.request is None:
            return self._history_planner.no_fetch_outcome(request, prepared.plan)
        request = prepared.request
        history_context = prepared.context

        if self._engine is None:
            return RepairOutcome(
                request=request,
                status="failed",
                error="BackfillEngine is not configured",
            )

        last_error: str | None = None
        report: Any | None = None

        for attempt in range(next_attempt, self._max_retries + 1):
            try:
                await self._ledger_mark_started(request, attempt=attempt)
                report = await self._engine.run(
                    symbol=request.symbol,
                    intervals=[request.interval],
                    range_start_ms=request.start_ms,
                    range_end_ms=request.end_ms,
                    exchange=request.exchange,
                    market_type=request.market_type,
                    metadata={
                        **request.metadata,
                        "reason": request.reason,
                        "priority": request.priority,
                        "requester": request.requester,
                        "request_id": request.request_id,
                    },
                )
                if self._is_failed(report.status) and attempt < self._max_retries:
                    delay = self._backoff(attempt)
                    await self._ledger_mark_retry_wait(
                        request,
                        attempt=attempt,
                        error="; ".join(report.errors) if report.errors else None,
                        delay_seconds=delay,
                    )
                    raise RepairRetryDeferred(delay, attempt)

                bars_loaded = 0
                verification: dict[str, Any] = {
                    "verified_contiguous": None,
                    "remaining_missing_bars": None,
                }
                verification_incomplete = False
                terminal_reason: str | None = None
                exhausted_before_ms: int | None = None
                boundary_checked = False
                requires_trusted_finality = repair_requires_trusted_finality(
                    request.metadata,
                    reason=request.reason,
                )
                if not self._is_failed(report.status):
                    await self._ledger_mark_verifying(request)
                    verification = await self._verify_request_range(
                        request,
                        context=history_context,
                        include_rows=True,
                    )
                    verification_incomplete = bool(
                        verification.get("verified_contiguous") is False
                    )
                    if verification_incomplete and not requires_trusted_finality:
                        terminal_reason, exhausted_before_ms = (
                            await self._record_confirmed_left_boundary(
                                request,
                                report,
                                context=history_context,
                            )
                        )
                        boundary_checked = True
                    confirmed_terminal = terminal_reason is not None
                    if (
                        verification_incomplete
                        and not confirmed_terminal
                        and attempt < self._max_retries
                    ):
                        delay = self._backoff(attempt)
                        remaining = verification.get("remaining_missing_bars")
                        await self._ledger_mark_retry_wait(
                            request,
                            attempt=attempt,
                            error=(
                                "backfill verification incomplete"
                                f" ({remaining} rows remain)"
                            ),
                            delay_seconds=delay,
                        )
                        raise RepairRetryDeferred(delay, attempt)
                    bars_loaded = await self._load_backfilled_to_cache(
                        request,
                        report,
                        verification,
                    )
                    await self._emit_completion_if_needed(
                        request,
                        report,
                        bars_loaded,
                        verification,
                    )

                if self._is_failed(report.status):
                    await self._emit_failed(request, report)

                if (
                    not self._is_failed(report.status)
                    and not boundary_checked
                    and not (
                        verification_incomplete
                        and requires_trusted_finality
                    )
                ):
                    terminal_reason, exhausted_before_ms = (
                        await self._record_confirmed_left_boundary(
                            request,
                            report,
                            context=history_context,
                        )
                    )

                return RepairOutcome(
                    request=request,
                    status=report.status,
                    report=self._summarize_report(report),
                    attempts=attempt,
                    bars_loaded=bars_loaded,
                    verified_contiguous=verification.get("verified_contiguous"),
                    remaining_missing_bars=verification.get("remaining_missing_bars"),
                    error="; ".join(report.errors) if report.errors else None,
                    terminal_reason=terminal_reason,
                    exhausted_before_ms=exhausted_before_ms,
                    retryable=(
                        (
                            verification_incomplete
                            and terminal_reason is None
                        )
                        or self._report_retryable(report)
                    ),
                )
            except RepairRetryDeferred:
                raise
            except RateLimitDeferred as exc:
                await self._ledger_mark_retry_wait(
                    request,
                    attempt=attempt,
                    error=(
                        f"rate_limit_deferred:{exc.bucket_key}:{exc.reason}"
                    ),
                    delay_seconds=exc.retry_after_seconds,
                )
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = str(exc)
                logger.error(
                    "Backfill task error for %s@%s attempt %d/%d: %s",
                    request.symbol,
                    request.interval,
                    attempt,
                    self._max_retries,
                    exc,
                    exc_info=True,
                )
                if attempt < self._max_retries:
                    delay = self._backoff(attempt)
                    await self._ledger_mark_retry_wait(
                        request,
                        attempt=attempt,
                        error=last_error,
                        delay_seconds=delay,
                    )
                    raise RepairRetryDeferred(delay, attempt)

        await self._emit_failed(request, report, last_error)
        return RepairOutcome(
            request=request,
            status="failed",
            report=self._summarize_report(report),
            attempts=self._max_retries,
            error=last_error,
        )

    async def _load_backfilled_to_cache(
        self,
        request: RepairRequest,
        report: Any,
        verification: dict[str, Any] | None = None,
    ) -> int:
        if self._total_bars_written(report) <= 0:
            return 0

        total_loaded = 0
        series_identity = identity_from_metadata(request.exchange, request.metadata)
        identity_kwargs = (
            {"series_identity": series_identity}
            if series_identity is not None
            else {}
        )
        derived_targets = _merge_derived_repair_targets(
            request.metadata.get("derived_repair_targets"),
        )
        verified_rows = (
            (verification or {}).get("_rows")
            if isinstance(verification, dict)
            else None
        )
        for written_range in self._written_ranges_for_request(request, report):
            if isinstance(verified_rows, list):
                range_start = int(written_range["start_ms"])
                range_end = int(written_range["end_ms"])
                rows = [
                    row
                    for row in verified_rows
                    if range_start <= int(row["open_time"]) <= range_end
                ]
            else:
                rows = await run_storage(
                    self._storage.query_bars,
                    symbol=written_range["symbol"],
                    interval=written_range["interval"],
                    start_ms=written_range["start_ms"],
                    end_ms=written_range["end_ms"],
                    order="ASC",
                    exchange=written_range["exchange"],
                    market_type=written_range["market_type"],
                    **identity_kwargs,
                )
            bars = [
                BarData.from_storage_row(
                    row,
                    exchange=written_range["exchange"],
                    market_type=written_range["market_type"],
                )
                for row in rows
            ]

            if not bars:
                continue

            await self._bars_backfilled(
                written_range["symbol"],
                written_range["interval"],
                bars,
                exchange=written_range["exchange"],
                market_type=written_range["market_type"],
                **(
                    {"series_identity": series_identity}
                    if series_identity is not None
                    else {}
                ),
                event_detail={
                    "request_id": request.request_id,
                    "status": self._status_value(report.status),
                    "reason": request.reason,
                    "priority": request.priority,
                    "requester": request.requester,
                    "range_start_ms": written_range["start_ms"],
                    "range_end_ms": written_range["end_ms"],
                    "request_start_ms": request.start_ms,
                    "request_end_ms": request.end_ms,
                    "verified_contiguous": (
                        verification or {}
                    ).get("verified_contiguous"),
                    "remaining_missing_bars": (
                        verification or {}
                    ).get("remaining_missing_bars"),
                    **(
                        {"derived_repair_targets": derived_targets}
                        if derived_targets else {}
                    ),
                },
            )
            total_loaded += len(bars)

        return total_loaded

    async def _emit_completion_if_needed(
        self,
        request: RepairRequest,
        report: Any,
        bars_loaded: int,
        verification: dict[str, Any] | None = None,
    ) -> None:
        if bars_loaded > 0:
            return
        derived_targets = _merge_derived_repair_targets(
            request.metadata.get("derived_repair_targets"),
        )
        series_identity = identity_from_metadata(request.exchange, request.metadata)
        await self._emit_event(DataEvent(
            event_type=DataEventType.BACKFILL_COMPLETED,
            key=SeriesKey(
                request.symbol,
                request.interval,
                exchange=request.exchange,
                market_type=request.market_type,
                **(series_identity.to_dict() if series_identity is not None else {}),
            ),
            audience=audience_for_backfill_reason(request.reason),
            detail={
                "request_id": request.request_id,
                "status": self._status_value(report.status),
                "reason": request.reason,
                "priority": request.priority,
                "requester": request.requester,
                "bars_count": 0,
                "range_start_ms": request.start_ms,
                "range_end_ms": request.end_ms,
                "request_start_ms": request.start_ms,
                "request_end_ms": request.end_ms,
                "verified_contiguous": (
                    verification or {}
                ).get("verified_contiguous"),
                "remaining_missing_bars": (
                    verification or {}
                ).get("remaining_missing_bars"),
                **(
                    {"derived_repair_targets": derived_targets}
                    if derived_targets else {}
                ),
            },
        ))

    async def _emit_failed(
        self,
        request: RepairRequest,
        report: Any | None = None,
        error: str | None = None,
    ) -> None:
        series_identity = identity_from_metadata(request.exchange, request.metadata)
        await self._emit_event(DataEvent(
            event_type=DataEventType.BACKFILL_FAILED,
            key=SeriesKey(
                request.symbol,
                request.interval,
                exchange=request.exchange,
                market_type=request.market_type,
                **(series_identity.to_dict() if series_identity is not None else {}),
            ),
            detail={
                "request_id": request.request_id,
                "status": self._status_value(report.status) if report is not None else "failed",
                "reason": request.reason,
                "priority": request.priority,
                "requester": request.requester,
                "errors": report.errors if report is not None else ([error] if error else []),
            },
        ))

    async def _verify_request_range(
        self,
        request: RepairRequest,
        *,
        context: Any | None = None,
        include_rows: bool = False,
    ) -> dict[str, Any]:
        query_bars = getattr(self._storage, "query_bars", None)
        if not callable(query_bars):
            return {
                "verified_contiguous": None,
                "remaining_missing_bars": None,
            }

        interval_ms = parse_interval_ms(request.interval)
        if interval_ms is None or interval_ms <= 0 or request.start_ms > request.end_ms:
            return {
                "verified_contiguous": None,
                "remaining_missing_bars": None,
            }

        series_identity = identity_from_metadata(request.exchange, request.metadata)
        identity_kwargs = (
            {"series_identity": series_identity}
            if series_identity is not None
            else {}
        )
        try:
            rows = await run_storage(
                query_bars,
                symbol=request.symbol,
                interval=request.interval,
                start_ms=request.start_ms,
                end_ms=request.end_ms,
                order="ASC",
                exchange=request.exchange,
                market_type=request.market_type,
                **identity_kwargs,
            )
        except Exception as exc:
            logger.warning(
                "Backfill verification query failed for %s:%s:%s@%s %d-%d: %s",
                request.exchange,
                request.market_type,
                request.symbol,
                request.interval,
                request.start_ms,
                request.end_ms,
                exc,
            )
            return {
                "verified_contiguous": None,
                "remaining_missing_bars": None,
            }

        physical_actual = {int(row["open_time"]) for row in rows}
        requires_trusted_finality = repair_requires_trusted_finality(
            request.metadata,
            reason=request.reason,
        )
        trusted_rows = [
            row for row in rows
            if source_is_trusted_final(row.get("source"))
        ]
        actual = (
            {int(row["open_time"]) for row in trusted_rows}
            if requires_trusted_finality
            else physical_actual
        )
        if request.metadata.get("history_verification") == "provider_authoritative_sparse":
            result = {
                "verified_contiguous": True,
                "remaining_missing_bars": 0,
                "expected_bars": None,
                "actual_bars": len(physical_actual),
                "verified_bars": len(actual),
                "verification_mode": "provider_authoritative_sparse",
            }
            if include_rows:
                result["_rows"] = (
                    trusted_rows if requires_trusted_finality else rows
                )
            return result
        calendar = self._history_planner.calendar(
            context,
            self._history_planner.availability(context),
        )
        if calendar is None and self._history_service is not None:
            calendar = self._history_service.calendars.get(
                request.metadata.get("history_calendar_id")
            )
        if calendar is not None:
            try:
                expected_opens = set(calendar.expected_opens(
                    request.start_ms,
                    request.end_ms,
                    request.interval,
                ))
            except Exception as exc:
                logger.warning(
                    "Calendar verification failed for %s:%s:%s@%s: %s",
                    request.exchange,
                    request.market_type,
                    request.symbol,
                    request.interval,
                    exc,
                )
                return {
                    "verified_contiguous": None,
                    "remaining_missing_bars": None,
                }
        else:
            expected_opens: set[int] = set()
            current = int(request.start_ms)
            while current <= request.end_ms:
                expected_opens.add(current)
                current += interval_ms

        missing = len(expected_opens - actual)

        result = {
            "verified_contiguous": missing == 0,
            "remaining_missing_bars": missing,
            "expected_bars": len(expected_opens),
            "actual_bars": len(physical_actual),
        }
        if requires_trusted_finality:
            result.update({
                "verified_bars": len(actual),
                "requires_trusted_finality": True,
                "untrusted_final_bars": len(
                    expected_opens & (physical_actual - actual)
                ),
            })
        if include_rows:
            # Private handoff to cache reload: verification already paid for
            # this exact storage range, so do not immediately query it again.
            result["_rows"] = trusted_rows if requires_trusted_finality else rows
        return result

    def _ledger_upsert_detected(self, request: RepairRequest) -> None:
        if self._gap_ledger is None:
            return
        # Persist exactly one durable row for the scheduler parent.  Chunk
        # requests inherit this immutable identity and may update progress,
        # but only the aggregate parent completion writes a terminal state.
        request.metadata["ledger_range"] = {
            "start_ms": int(request.start_ms),
            "end_ms": int(request.end_ms),
        }
        # Scheduler submission is synchronous, but SQLite is not.  Coalesce
        # merged requests by id and let one short-lived writer drain them.
        self._ledger_pending_upserts[request.request_id] = request
        self._ledger_pending_upserts.move_to_end(request.request_id)
        self._ensure_ledger_writer()

    def _ensure_ledger_writer(self) -> None:
        task = self._ledger_write_task
        if task is not None and not task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self._drain_ledger_writes_sync()
            return
        self._ledger_write_task = asyncio.create_task(
            self._drain_ledger_writes(),
            name="backfill-gap-ledger-writer",
        )

    def _drain_ledger_writes_sync(self) -> None:
        while self._ledger_pending_upserts or self._ledger_pending_operations:
            if self._ledger_pending_upserts:
                requests = list(self._ledger_pending_upserts.values())
                self._ledger_pending_upserts.clear()
                self._persist_ledger_upserts(requests)
            while self._ledger_pending_operations:
                func, args = self._ledger_pending_operations.popleft()
                func(*args)

    async def _drain_ledger_writes(self) -> None:
        while self._ledger_pending_upserts or self._ledger_pending_operations:
            if self._ledger_pending_upserts:
                requests = list(self._ledger_pending_upserts.values())
                self._ledger_pending_upserts.clear()
                try:
                    await run_storage(self._persist_ledger_upserts, requests)
                except Exception:
                    logger.exception("Gap ledger queued upsert batch failed")
            while self._ledger_pending_operations:
                func, args = self._ledger_pending_operations.popleft()
                try:
                    await run_storage(func, *args)
                except Exception:
                    logger.exception("Gap ledger deferred write failed")

    def _persist_ledger_upserts(self, requests: list[RepairRequest]) -> None:
        if self._gap_ledger is None or not requests:
            return
        upsert_many = getattr(self._gap_ledger, "upsert_detected_many", None)
        if callable(upsert_many):
            upsert_many(requests, status="queued")
            return
        for request in requests:
            self._gap_ledger.upsert_detected(request, status="queued")

    async def _ledger_mark_started(self, request: RepairRequest, *, attempt: int) -> None:
        if self._gap_ledger is None:
            return
        try:
            # The synchronous scheduler callback only enqueues the durable
            # "queued" row.  Preserve lifecycle ordering before marking it
            # repairing, while keeping all SQLite work off the event loop.
            queued_write = self._ledger_write_task
            if queued_write is not None and not queued_write.done():
                await asyncio.shield(queued_write)
            await run_storage(self._gap_ledger.mark_started, request, attempt=attempt)
        except Exception:
            logger.exception("Gap ledger start update failed for %s", request.request_id)

    async def _ledger_mark_retry_wait(
        self,
        request: RepairRequest,
        *,
        attempt: int,
        error: str | None,
        delay_seconds: float,
    ) -> None:
        if self._gap_ledger is None:
            return
        try:
            await run_storage(
                self._gap_ledger.mark_retry_wait,
                request,
                attempt=attempt,
                error=error,
                next_retry_at=int(time.time() * 1000 + delay_seconds * 1000),
            )
        except Exception:
            logger.exception("Gap ledger retry update failed for %s", request.request_id)

    async def _ledger_mark_verifying(self, request: RepairRequest) -> None:
        if self._gap_ledger is None:
            return
        try:
            await run_storage(self._gap_ledger.mark_verifying, request)
        except Exception:
            logger.exception("Gap ledger verifying update failed for %s", request.request_id)

    async def _ledger_finalize_parent(
        self,
        request: RepairRequest,
        outcome: RepairOutcome,
    ) -> None:
        """Commit one terminal ledger decision after all parent chunks settle."""
        if self._gap_ledger is None:
            return
        if self._is_failed(outcome.status):
            status = "failed"
            missing_count = outcome.remaining_missing_bars
        elif outcome.verified_contiguous is True:
            status = "filled"
            missing_count = 0
        elif (
            outcome.verified_contiguous is False
            and (
                outcome.terminal_reason is None
                or outcome.retryable
            )
        ):
            status = "partial"
            missing_count = outcome.remaining_missing_bars
        else:
            reconcile = getattr(outcome.report, "reconcile_result", None)
            written = int(getattr(reconcile, "bars_written", 0) or 0)
            has_loaded_data = written > 0 or int(outcome.bars_loaded or 0) > 0
            if (
                outcome.terminal_reason is not None
                and not outcome.retryable
            ):
                status = "unavailable" if has_loaded_data else "source_empty"
            elif (
                outcome.verified_contiguous is None
                or outcome.retryable
                or self._status_value(outcome.status) == "partial"
            ):
                status = "partial"
            elif not has_loaded_data:
                status = "source_empty"
            else:
                status = "partial"
            missing_count = outcome.remaining_missing_bars

        verified_coverage: tuple[int, int] | None = None
        if status == "filled":
            target_range = self._target_open_range(request)
            if target_range is not None:
                start_open_ms, _end_open_ms, end_exclusive_ms = target_range
                verified_coverage = (start_open_ms, end_exclusive_ms - 1)

        def _persist() -> None:
            finalize_parent = getattr(self._gap_ledger, "finalize_parent", None)
            if callable(finalize_parent):
                finalize_parent(
                    request,
                    status=status,
                    missing_count=missing_count,
                    error=(
                        outcome.terminal_reason
                        if status == "unavailable"
                        else outcome.error
                    ),
                    attempts=int(outcome.attempts or 0),
                    coverage_start_ms=(
                        verified_coverage[0]
                        if verified_coverage is not None
                        else None
                    ),
                    coverage_end_ms=(
                        verified_coverage[1]
                        if verified_coverage is not None
                        else None
                    ),
                    next_retry_at=(
                        int(time.time() * 1000) + _TERMINAL_LEDGER_RETRY_MS
                        if status == "unavailable"
                        else None
                    ),
                )
                return
            if status == "unavailable":
                mark_deferred = getattr(self._gap_ledger, "mark_deferred", None)
                if callable(mark_deferred):
                    mark_deferred(
                        request,
                        status="unavailable",
                        reason=outcome.terminal_reason,
                        next_retry_at=(
                            int(time.time() * 1000) + _TERMINAL_LEDGER_RETRY_MS
                        ),
                    )
                else:
                    self._gap_ledger.mark_resolved(
                        request,
                        status="partial",
                        missing_count=missing_count,
                        error=outcome.terminal_reason or outcome.error,
                    )
            else:
                self._gap_ledger.mark_resolved(
                    request,
                    status=status,
                    missing_count=missing_count,
                    error=outcome.error,
                )
            mark_attempts = getattr(self._gap_ledger, "mark_attempts", None)
            if callable(mark_attempts):
                mark_attempts(request, attempts=int(outcome.attempts or 0))
            if status == "filled":
                mark_covered = getattr(self._gap_ledger, "mark_covered_resolved", None)
                if callable(mark_covered) and verified_coverage is not None:
                    mark_covered(
                        request,
                        coverage_start_ms=verified_coverage[0],
                        coverage_end_ms=verified_coverage[1],
                    )

        try:
            await run_storage(_persist)
        except Exception:
            logger.exception(
                "Gap ledger parent finalization failed for %s",
                request.request_id,
            )
        else:
            await self.refresh_suppressions()

    @staticmethod
    def _repair_request_from_ledger_row(row: dict[str, Any]) -> RepairRequest:
        """Build a non-scheduled verification request from a ledger row."""
        symbol = str(row.get("symbol") or "").strip().upper()
        interval = str(row.get("interval") or "").strip()
        if not symbol or not interval:
            raise ValueError("ledger row is missing symbol or interval")
        ledger_id = row.get("id")
        metadata: dict[str, Any] = {
            "origin": "ledger_storage_reconciliation",
            "ledger_id": ledger_id,
            "ledger_status": row.get("status"),
            _LEDGER_RECONCILIATION_SNAPSHOT_KEY: {
                "id": ledger_id,
                "status": row.get("status"),
                "last_seen_at": row.get("last_seen_at"),
                "metadata_json": row.get("metadata_json"),
                "repair_ticket": row.get("repair_ticket"),
            },
        }
        raw_metadata = row.get("metadata_json")
        decoded_metadata = _decode_metadata_object(raw_metadata)
        if repair_requires_trusted_finality(
            decoded_metadata,
            reason=row.get("reason"),
        ):
            metadata["requires_trusted_finality"] = True
        checkpoint = decoded_metadata.get("reconciliation_checkpoint")
        if isinstance(checkpoint, dict):
            metadata["reconciliation_checkpoint"] = dict(checkpoint)
        recovery_count = decoded_metadata.get("ledger_recovery_count")
        try:
            metadata["ledger_recovery_count"] = min(
                32,
                max(0, int(recovery_count or 0)),
            )
        except (TypeError, ValueError):
            pass
        return RepairRequest(
            symbol=symbol,
            interval=interval,
            start_ms=int(row["start_ms"]),
            end_ms=int(row["end_ms"]),
            exchange=str(row.get("exchange") or "binance").strip().lower(),
            market_type=str(row.get("market_type") or "spot").strip().lower(),
            reason="ledger_reconcile",
            requester="ledger_reconcile",
            metadata=metadata,
            request_id=f"ledger-reconcile-{ledger_id}",
        )

    @staticmethod
    def _reconciliation_snapshot(
        request: RepairRequest | None,
    ) -> dict[str, Any] | None:
        if request is None:
            return None
        raw = request.metadata.get(_LEDGER_RECONCILIATION_SNAPSHOT_KEY)
        return dict(raw) if isinstance(raw, dict) else None

    def _calendar_for_reconciliation(
        self,
        request: RepairRequest,
    ) -> tuple[TradingCalendar | None, bool]:
        """Resolve a calendar, distinguishing legacy UTC fallback from unknown.

        Embeddings that provide no history policy retain the historical
        always-open UTC behavior.  Once a policy/service is configured, a
        failed or unknown calendar must fail closed rather than silently
        reinterpret a session series on UTC boundaries.
        """
        if not self._history_planner.configured:
            return None, True
        plan, context = self._history_planner.plan(request)
        availability = self._history_planner.availability(context)
        calendar = self._history_planner.calendar(context, availability)
        if calendar is None and self._history_service is not None and plan is not None:
            calendar = self._history_service.calendars.get(plan.calendar_id)
        return calendar, calendar is not None

    @staticmethod
    def _target_open_range_with_calendar(
        request: RepairRequest,
        *,
        calendar: TradingCalendar | None,
        calendar_resolved: bool,
    ) -> tuple[int, int, int] | None:
        """Return first/last target opens and the last exclusive close edge."""
        interval_ms = parse_interval_ms(request.interval)
        if interval_ms is None or interval_ms <= 0:
            return None
        if not calendar_resolved:
            return None
        if calendar is not None:
            start_ms = calendar.first_expected_open(
                int(request.start_ms),
                int(request.end_ms),
                request.interval,
            )
            end_ms = calendar.last_expected_open(
                int(request.start_ms),
                int(request.end_ms),
                request.interval,
            )
            if start_ms is None or end_ms is None or end_ms < start_ms:
                return None
            end_exclusive_ms = expected_bucket_end_ms(
                calendar,
                end_ms,
                request.interval,
            )
            if end_exclusive_ms <= end_ms:
                return None
            return start_ms, end_ms, end_exclusive_ms
        start_ms = compute_bucket_start_ms(
            int(request.start_ms),
            interval_ms,
            interval=request.interval,
        )
        end_ms = compute_bucket_start_ms(
            int(request.end_ms),
            interval_ms,
            interval=request.interval,
        )
        if end_ms < start_ms:
            return None
        end_exclusive_ms = compute_bucket_end_ms(
            end_ms,
            interval_ms,
            interval=request.interval,
        )
        return start_ms, end_ms, end_exclusive_ms

    def _target_open_range(
        self,
        request: RepairRequest,
    ) -> tuple[int, int, int] | None:
        calendar, calendar_resolved = self._calendar_for_reconciliation(request)
        return self._target_open_range_with_calendar(
            request,
            calendar=calendar,
            calendar_resolved=calendar_resolved,
        )

    def _canonical_reconciliation_request(
        self,
        request: RepairRequest,
    ) -> RepairRequest | None:
        """Return the target-open version of a range for strict storage scans."""
        target_range = self._target_open_range(request)
        if target_range is None:
            return None
        start_ms, end_ms, end_exclusive_ms = target_range
        metadata = dict(getattr(request, "metadata", {}) or {})
        metadata["canonical_target_range"] = {
            "start_ms": start_ms,
            "end_ms": end_ms,
        }
        metadata["canonical_coverage_range"] = {
            "start_ms": start_ms,
            "end_ms": end_exclusive_ms - 1,
        }
        return RepairRequest(
            symbol=request.symbol,
            interval=request.interval,
            start_ms=start_ms,
            end_ms=end_ms,
            exchange=request.exchange,
            market_type=request.market_type,
            reason=request.reason,
            priority=request.priority,
            requester=request.requester,
            wait_policy=request.wait_policy,
            metadata=metadata,
            request_id=request.request_id,
        )

    def _request_range_is_fully_closed(
        self,
        request: RepairRequest,
        now_ms: int,
    ) -> bool:
        """Whether every target bucket represented by ``request`` is closed."""
        target_range = self._target_open_range(request)
        if target_range is None:
            return False
        _, _, end_exclusive_ms = target_range
        return end_exclusive_ms <= int(now_ms)

    async def _should_skip_audited_gap(self, request: RepairRequest) -> bool:
        if self._gap_ledger is None:
            return False
        now_ms = int(time.time() * 1000)
        get_covering = getattr(self._gap_ledger, "get_covering_status", None)
        get_status = getattr(self._gap_ledger, "get_status", None)
        if not callable(get_covering) and not callable(get_status):
            return False
        try:
            if callable(get_covering):
                status = await run_storage(
                    get_covering,
                    exchange=request.exchange,
                    market_type=request.market_type,
                    symbol=request.symbol,
                    interval=request.interval,
                    start_ms=request.start_ms,
                    end_ms=request.end_ms,
                    now_ms=now_ms,
                )
            else:
                status = await run_storage(get_status, request)
        except Exception:
            logger.exception("Gap ledger status lookup failed for %s", request.request_id)
            return False
        if not status:
            return False
        status_value = str(status.get("status") or "")

        next_retry_at = status.get("next_retry_at")
        retry_is_future = (
            next_retry_at is not None and int(next_retry_at) > now_ms
        )

        if status_value in {"failed", "unavailable"}:
            return retry_is_future

        if status_value in {
            "queued",
            "repairing",
            "verifying",
            "partial",
            "retry_wait",
        }:
            if retry_is_future:
                return True
            last_activity = next(
                (
                    status.get(key)
                    for key in (
                        "last_checked_at",
                        "last_seen_at",
                        "first_seen_at",
                    )
                    if status.get(key) is not None
                ),
                None,
            )
            if last_activity is None:
                return True
            return now_ms - int(last_activity) < _LEDGER_STALE_AFTER_MS

        if status_value == "not_expected":
            # A forming range becomes actionable naturally once the entire
            # recorded target window has closed.  Never let its old ledger
            # marker suppress that later audit.
            return not self._request_range_is_fully_closed(request, now_ms)

        if status_value != "source_empty":
            return False

        # A source-empty record is only a safe suppression while the exact
        # range remains closed.  Older versions could write this state after
        # asking the provider for a forming daily bar; once that bar closes it
        # must re-enter the normal audit path even if the 24-hour cooldown has
        # not elapsed yet.
        if not self._request_range_is_fully_closed(request, now_ms):
            return True
        resolved_at = status.get("resolved_at") or status.get("last_checked_at")
        if resolved_at is not None:
            if not self._request_range_is_fully_closed(request, int(resolved_at)):
                return False
        if next_retry_at is None:
            return True
        return int(next_retry_at) > now_ms

    def _ledger_mark_history_deferred(
        self,
        request: RepairRequest,
        plan: HistoryPlan | None,
    ) -> None:
        """Persist explicit forming/unavailable decisions without source-empty.

        Fetch planning happens before the scheduler, so no queued ledger row
        exists for a no-fetch outcome unless we create one here.  Keeping these
        semantics distinct prevents a transient/forming request from becoming
        a durable source-empty hole.
        """
        if self._gap_ledger is None or plan is None:
            return
        if plan.disposition not in {
            HistoryDisposition.NOT_EXPECTED,
            HistoryDisposition.RETRYABLE,
            HistoryDisposition.UNKNOWN,
        }:
            return
        def _persist() -> None:
            self._gap_ledger.upsert_detected(request, status="queued")
            mark_deferred = getattr(self._gap_ledger, "mark_deferred", None)
            if not callable(mark_deferred):
                return
            if plan.disposition is HistoryDisposition.NOT_EXPECTED:
                exclusion = plan.exclusions[0] if plan.exclusions else None
                mark_deferred(
                    request,
                    status="not_expected",
                    reason=(exclusion.reason.value if exclusion is not None else None),
                )
                return
            mark_deferred(
                request,
                status="unavailable",
                reason=("history availability is unknown" if plan.unknown else None),
                next_retry_at=(
                    int(plan.retry_at_ms)
                    if plan.retry_at_ms is not None
                    else int(time.time() * 1000) + _LEDGER_STALE_AFTER_MS
                ),
            )

        self._ledger_pending_operations.append((_persist, ()))
        self._ensure_ledger_writer()

    def _ledger_open_snapshot(self) -> list[dict[str, Any]]:
        if self._gap_ledger is None:
            return []
        list_open = getattr(self._gap_ledger, "list_open", None)
        if not callable(list_open):
            return []
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                return list_open(limit=50)
            except Exception:
                logger.exception("Gap ledger open snapshot failed")
                return []

        now = time.monotonic()
        refresh_task = self._ledger_open_refresh_task
        if (
            now - self._ledger_open_cache_updated_at >= 1.0
            and (refresh_task is None or refresh_task.done())
        ):
            self._ledger_open_refresh_task = asyncio.create_task(
                self._refresh_ledger_open_cache(list_open),
                name="backfill-gap-ledger-snapshot-refresh",
            )
        return [dict(row) for row in self._ledger_open_cache]

    async def _refresh_ledger_open_cache(self, list_open: Callable[..., Any]) -> None:
        try:
            rows = await run_storage(list_open, limit=50)
            self._ledger_open_cache = [
                dict(row)
                for row in rows
                if isinstance(row, dict)
            ]
            self._ledger_open_cache_updated_at = time.monotonic()
        except Exception:
            logger.exception("Gap ledger open snapshot failed")

    def _complete(self, request: RepairRequest, outcome: RepairOutcome) -> None:
        self._retain_completed_outcome(request, outcome)
        future = self._futures.pop(request.request_id, None)
        if future is not None and not future.done():
            future.set_result(outcome)

    @staticmethod
    def _total_bars_written(report: Any) -> int:
        reconcile_result = getattr(report, "reconcile_result", None)
        if reconcile_result is None:
            return 0
        return int(getattr(reconcile_result, "bars_written", 0) or 0) + int(
            getattr(reconcile_result, "custom_bars_written", 0) or 0
        )

    @classmethod
    def _summarize_report(cls, report: Any | None) -> RepairReportSummary | None:
        """Drop fetched bar payloads before outcomes enter retained history."""
        if report is None:
            return None
        reconcile = getattr(report, "reconcile_result", None)
        reconcile_summary = None
        if reconcile is not None:
            failed_batches = list(getattr(reconcile, "failed_batches", None) or [])
            written_ranges = list(getattr(reconcile, "written_ranges", None) or [])
            reconcile_summary = RepairReconcileSummary(
                bars_received=int(getattr(reconcile, "bars_received", 0) or 0),
                bars_written=int(getattr(reconcile, "bars_written", 0) or 0),
                bars_skipped=int(getattr(reconcile, "bars_skipped", 0) or 0),
                bars_deduplicated=int(getattr(reconcile, "bars_deduplicated", 0) or 0),
                custom_bars_generated=int(
                    getattr(reconcile, "custom_bars_generated", 0) or 0
                ),
                custom_bars_written=int(
                    getattr(reconcile, "custom_bars_written", 0) or 0
                ),
                bars_cached=int(getattr(reconcile, "bars_cached", 0) or 0),
                write_errors=int(getattr(reconcile, "write_errors", 0) or 0),
                failed_batch_count=len(failed_batches),
                written_range_count=len(written_ranges),
                elapsed_ms=int(getattr(reconcile, "elapsed_ms", 0) or 0),
            )

        fetch_results = cls._report_fetch_results(report)
        errors = [str(error) for error in getattr(report, "errors", None) or []]
        report_ranges = cls._raw_written_ranges(report)
        range_summaries: list[RepairWrittenRangeSummary] = []
        for raw_range in report_ranges[:256]:
            normalized = cls._normalize_written_range(raw_range)
            if normalized is None:
                continue
            range_summaries.append(RepairWrittenRangeSummary(
                exchange=normalized["exchange"],
                market_type=normalized["market_type"],
                symbol=normalized["symbol"],
                interval=normalized["interval"],
                start_ms=normalized["start_ms"],
                end_ms=normalized["end_ms"],
            ))
        return RepairReportSummary(
            status=getattr(report, "status", "unknown"),
            errors=tuple(error[:500] for error in errors[:20]),
            error_count=len(errors),
            reconcile_result=reconcile_summary,
            fetch_result_count=len(fetch_results),
            fetched_bar_count=sum(
                int(getattr(result, "bars_count", 0) or len(getattr(result, "bars", ()) or ()))
                for result in fetch_results
            ),
            written_range_count=len(report_ranges),
            written_ranges=tuple(range_summaries),
            elapsed_ms=int(getattr(report, "elapsed_ms", 0) or 0),
        )

    @staticmethod
    def _report_fetch_results(report: Any) -> list[Any]:
        return list(getattr(report, "fetch_results", None) or [])

    @classmethod
    def _report_exhausted_before_ms(cls, report: Any) -> int | None:
        values = [
            int(value)
            for result in cls._report_fetch_results(report)
            if (value := getattr(result, "exhausted_before_ms", None)) is not None
        ]
        return min(values) if values else None

    @classmethod
    def _report_retryable(cls, report: Any) -> bool:
        return any(
            bool(getattr(result, "retryable", False))
            for result in cls._report_fetch_results(report)
        )

    async def _record_confirmed_left_boundary(
        self,
        request: RepairRequest,
        report: Any,
        *,
        context: Any | None,
    ) -> tuple[str | None, int | None]:
        """Persist only policy-authorised, non-retryable empty-page evidence."""
        empty_results = [
            result
            for result in self._report_fetch_results(report)
            if bool(getattr(result, "source_complete", False))
        ]
        if not empty_results:
            return None, None
        if self._report_retryable(report) or bool(getattr(report, "errors", None)):
            return None, None

        semantics = self._context_empty_page_semantics(context)
        if semantics is HistoryEmptyPageSemantics.UNKNOWN:
            return None, None

        boundary_ms = await self._left_boundary_value(
            request,
            report,
            context=context,
            allow_without_local_edge=(
                semantics is HistoryEmptyPageSemantics.TERMINAL_EXHAUSTION
            ),
        )
        if boundary_ms is None:
            return None, None

        if self._history_service is None:
            if semantics is HistoryEmptyPageSemantics.TERMINAL_EXHAUSTION:
                return "provider_exhausted", boundary_ms
            return None, None

        availability = self._history_planner.availability(context)
        revision = availability.revision if availability is not None else ""
        try:
            if semantics is HistoryEmptyPageSemantics.TERMINAL_EXHAUSTION:
                record = self._history_service.record_boundary(
                    self._history_planner.series_key(request),
                    BoundarySide.LEFT,
                    value_ms=boundary_ms,
                    reason=BoundaryReason.SOURCE_EXHAUSTED,
                    state=BoundaryState.CONFIRMED,
                    revision=revision,
                )
            else:
                record = self._history_service.record_boundary(
                    self._history_planner.series_key(request),
                    BoundarySide.LEFT,
                    value_ms=boundary_ms,
                    reason=BoundaryReason.SOURCE_EXHAUSTED,
                    state=BoundaryState.CANDIDATE,
                    revision=revision,
                    promote_after=2,
                )
        except (RuntimeError, ValueError) as exc:
            logger.warning(
                "History boundary evidence rejected for %s:%s:%s@%s: %s",
                request.exchange,
                request.market_type,
                request.symbol,
                request.interval,
                exc,
            )
            return None, None

        if record.bound.state is not BoundaryState.CONFIRMED:
            return None, None
        return "provider_exhausted", record.bound.value_ms

    @staticmethod
    def _context_empty_page_semantics(
        context: Any | None,
    ) -> HistoryEmptyPageSemantics:
        value = getattr(context, "empty_page_semantics", None)
        if value is None:
            policy = (
                context
                if isinstance(context, HistoryAvailabilityPolicy)
                else getattr(context, "policy", None)
            )
            value = getattr(policy, "empty_page_semantics", None)
        try:
            return HistoryEmptyPageSemantics(value)
        except (TypeError, ValueError):
            return HistoryEmptyPageSemantics.UNKNOWN

    async def _left_boundary_value(
        self,
        request: RepairRequest,
        report: Any,
        *,
        context: Any | None,
        allow_without_local_edge: bool,
    ) -> int | None:
        reported = self._report_exhausted_before_ms(report)
        earliest: int | None = None
        get_bounds = getattr(self._storage, "get_bounds", None)
        if callable(get_bounds):
            try:
                bounds = await run_storage(
                    get_bounds,
                    request.symbol,
                    request.interval,
                    exchange=request.exchange,
                    market_type=request.market_type,
                )
                raw_earliest = (bounds or {}).get("earliest_open_time")
                if raw_earliest is not None:
                    earliest = int(raw_earliest)
            except Exception as exc:
                logger.warning(
                    "History boundary bounds lookup failed for %s:%s:%s@%s: %s",
                    request.exchange,
                    request.market_type,
                    request.symbol,
                    request.interval,
                    exc,
                )

        if reported is not None and (earliest is None or reported <= earliest):
            return reported
        if earliest is not None:
            if request.start_ms <= earliest <= request.end_ms:
                return earliest
            if request.end_ms < earliest and self._request_touches_left_edge(
                request,
                earliest,
                context=context,
            ):
                return earliest
        if not allow_without_local_edge:
            return None
        if request.reason not in {
            "initial_history",
            "visible_load_more",
            "query_left_gap",
            "query_shortfall",
        }:
            return None

        calendar = self._history_planner.calendar(
            context,
            self._history_planner.availability(context),
        )
        if calendar is not None:
            last = calendar.last_expected_open(
                request.start_ms,
                request.end_ms,
                request.interval,
            )
            if last is None:
                return None
            return calendar.next_expected_open(last, request.interval)
        interval_ms = parse_interval_ms(request.interval)
        return request.end_ms + interval_ms if interval_ms else None

    def _request_touches_left_edge(
        self,
        request: RepairRequest,
        earliest_ms: int,
        *,
        context: Any | None,
    ) -> bool:
        calendar = self._history_planner.calendar(
            context,
            self._history_planner.availability(context),
        )
        if calendar is not None:
            previous = calendar.previous_expected_open(
                earliest_ms,
                request.interval,
            )
            last = calendar.last_expected_open(
                request.start_ms,
                request.end_ms,
                request.interval,
            )
            return previous is not None and last == previous
        interval_ms = parse_interval_ms(request.interval)
        if interval_ms is None:
            return False
        return request.end_ms == earliest_ms - interval_ms

    def _written_ranges_for_request(
        self,
        request: RepairRequest,
        report: Any,
    ) -> list[dict[str, Any]]:
        raw_ranges = self._raw_written_ranges(report)
        ranges = [
            written_range
            for raw in raw_ranges
            if (written_range := self._normalize_written_range(raw)) is not None
            and written_range["exchange"] == request.exchange.lower().strip()
            and written_range["market_type"] == request.market_type.lower().strip()
            and written_range["symbol"] == request.symbol.upper().strip()
            and written_range["interval"] == request.interval
        ]
        if ranges:
            return ranges
        # A report that explicitly describes writes for other intervals is
        # authoritative: it did not write this request's target series.  The
        # full-request fallback exists only for legacy reports that carry no
        # written-range metadata at all.
        if raw_ranges:
            return []
        return [{
            "exchange": request.exchange.lower().strip(),
            "market_type": request.market_type.lower().strip(),
            "symbol": request.symbol.upper().strip(),
            "interval": request.interval,
            "start_ms": request.start_ms,
            "end_ms": request.end_ms,
        }]

    @staticmethod
    def _raw_written_ranges(report: Any) -> list[Any]:
        report_ranges = getattr(report, "written_ranges", None)
        if report_ranges:
            return list(report_ranges)
        reconcile_result = getattr(report, "reconcile_result", None)
        reconcile_ranges = (
            getattr(reconcile_result, "written_ranges", None)
            if reconcile_result is not None
            else None
        )
        return list(reconcile_ranges or [])

    @classmethod
    def _normalize_written_range(cls, raw: Any) -> dict[str, Any] | None:
        start_ms = cls._range_value(raw, "start_ms")
        end_ms = cls._range_value(raw, "end_ms")
        if start_ms is None or end_ms is None:
            return None
        return {
            "exchange": str(cls._range_value(raw, "exchange", "binance")).lower().strip(),
            "market_type": str(cls._range_value(raw, "market_type", "spot")).lower().strip(),
            "symbol": str(cls._range_value(raw, "symbol", "")).upper().strip(),
            "interval": cls._range_value(raw, "interval", ""),
            "start_ms": int(start_ms),
            "end_ms": int(end_ms),
        }

    @staticmethod
    def _range_value(raw: Any, key: str, default: Any = None) -> Any:
        if isinstance(raw, dict):
            return raw.get(key, default)
        return getattr(raw, key, default)

    def _backoff(self, attempt: int) -> float:
        return self._base_delay_seconds * (3 ** (attempt - 1))

    @staticmethod
    def _status_value(status: Any) -> str:
        return getattr(status, "value", str(status))

    @classmethod
    def _is_failed(cls, status: Any) -> bool:
        return cls._status_value(status) == "failed"
