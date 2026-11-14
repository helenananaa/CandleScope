"""
Backfill Engine — orchestrates gap detection, planning, fetching, reconciliation, and publishing.

Architecture::

    ┌─────────────────────────────────────────────────────────────────┐
    │                      BackfillEngine                            │
    │                                                                │
    │  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐   │
    │  │ Gap Detector  │──▶│   Planner    │──▶│ Historical       │   │
    │  │              │   │              │   │ Fetcher          │   │
    │  └──────────────┘   └──────────────┘   └────────┬─────────┘   │
    │                                                  │             │
    │                                        ┌─────────▼─────────┐  │
    │                                        │    Reconciler      │  │
    │                                        │  (dedup + write)   │  │
    │                                        └─────────┬─────────┘  │
    │                                                  │             │
    │                                        ┌─────────▼─────────┐  │
    │                                        │ Repair Publisher   │  │
    │                                        └───────────────────┘  │
    └─────────────────────────────────────────────────────────────────┘

Usage::

    from app.data_engine.backfill import BackfillEngine, BackfillConfig

    config = BackfillConfig(fetch_concurrency=5)
    engine = BackfillEngine(config, storage=my_storage, transport=my_transport)

    # Simple one-shot backfill
    report = await engine.run("BTCUSDT")

    # With custom intervals and explicit range
    report = await engine.run(
        symbol="BTCUSDT",
        intervals=["1m", "5m", "91m"],
        range_start_ms=1700000000000,
        range_end_ms=1700100000000,
    )

    # Access sub-components for advanced customization
    engine.planner.add_interval_mapping("91m", [...])
    engine.detector.set_gap_filter(lambda g: g.missing_bars >= 10)
    engine.publisher.on_report(my_webhook)
"""
from __future__ import annotations

from app.data_engine.storage.revisions import (fenced_acquisition, prepare_native_history_views, StaleAcquisition,
                                               prepare_derived_targets, prepare_warmup_view)
from app.data_engine.memory_budget import budgeted_work, reserve_work, MemoryBudgetExceeded

import logging
import time
from dataclasses import replace
from itertools import groupby
from typing import Any, Iterator

from app.exchanges.symbols import normalize_symbol
from app.exchanges.rate_limits import RateLimitDeferred

from ..ingestion.config import IngestionConfig
from ..ingestion.metrics import LayerMetrics
from ..ingestion.transport import TransportLayer
from ..aggregation.semantics import valid_ohlcv
from ..interval_policy import IntervalAlignment, parse_interval_spec, row_is_closed
from ..kline_quality import (
    bybit_recovery_source_gap_id,
    repair_requires_trusted_finality,
    reuses_bybit_gap_inputs,
    source_is_trusted_final,
)
from ..series_identity import identity_from_metadata
from ..interval_resolution import IntervalPurpose, IntervalResolutionError, IntervalResolutionErrorCode

from .config import BackfillConfig
from .models import (
    BackfillPlan,
    BackfillStatus,
    CacheBackend,
    FetchResult,
    FetchReceipt,
    GapInfo,
    GapType,
    ReconcileResult,
    RepairReport,
    StorageBackend,
    WrittenRange,
)
from .gap_detector import GapDetector
from .planner import BackfillPlanner
from .fetcher import FetchBatchDeferred, HistoricalFetcher
from .native_progress import NativeBackfillDeferred, NativeBackfillProgress
from .reconciler import Reconciler
from .publisher import RepairPublisher
from .fetch_stream import stream_plan, StreamReconcile, StreamBackfillDeferred

logger = logging.getLogger("backfill.Engine")

_BYBIT_WARMUP_SOURCE = ("bybit", "swap.linear", "5m")

_READ_REPAIR_REQUESTERS = frozenset({"klines_history", "klines_history_before", "klines_range"})


def _is_read_repair(metadata: dict[str, Any]) -> bool:
    requester = metadata.get("requester")
    if isinstance(requester, str) and requester in _READ_REPAIR_REQUESTERS:
        return True
    kinds = metadata.get("requester_kinds")
    return (requester == "mixed" and isinstance(kinds, (list, tuple))
            and 0 < len(kinds) <= 32 and all(isinstance(kind, str) and kind in _READ_REPAIR_REQUESTERS for kind in kinds))

__all__ = [
    # Engine
    "BackfillEngine",
    # Config
    "BackfillConfig",
    # Sub-components (for direct access / testing)
    "GapDetector",
    "BackfillPlanner",
    "HistoricalFetcher",
    "Reconciler",
    "RepairPublisher",
    # Models & Protocols
    "BackfillPlan",
    "BackfillStatus",
    "CacheBackend",
    "FetchResult",
    "FetchReceipt",
    "GapInfo",
    "ReconcileResult",
    "RepairReport",
    "StorageBackend",
    "WrittenRange",
]


class BackfillEngine:
    """Top-level orchestrator for the Backfill Engine.

    Wires together Gap Detector → Planner → Fetcher → Reconciler → Publisher
    into a single ``run()`` call, while exposing every sub-component for
    advanced customization.

    Args:
        config:           Backfill configuration.
        storage:          Storage backend (implements ``StorageBackend`` protocol).
        transport:        Ingestion TransportLayer for REST fetching.
        cache:            Optional cache backend (implements ``CacheBackend`` protocol).
        ingestion_config: Optional ingestion config (for NormalizeLayer reuse).
    """

    def __init__(
        self,
        config: BackfillConfig | None = None,
        storage: StorageBackend | None = None,
        transport: TransportLayer | None = None,
        cache: CacheBackend | None = None,
        ingestion_config: IngestionConfig | None = None,
    ) -> None:
        self._cfg = config or BackfillConfig()
        self._storage = storage
        self._transport = transport
        self._cache = cache
        self._ingestion_cfg = ingestion_config
        self._metrics = LayerMetrics("BackfillEngine")

        # Lazily initialized sub-components
        self._detector: GapDetector | None = None
        self._planner: BackfillPlanner | None = None
        self._fetcher: HistoricalFetcher | None = None
        self._reconciler: Reconciler | None = None
        self._publisher: RepairPublisher | None = None

    # ── Public: Sub-component access ─────────────────────────

    @property
    def config(self) -> BackfillConfig:
        """Access the engine configuration."""
        return self._cfg

    @property
    def detector(self) -> GapDetector:
        """Access the Gap Detector sub-component."""
        if self._detector is None:
            if self._storage is None:
                raise RuntimeError(
                    "StorageBackend is required for GapDetector. "
                    "Pass storage= to BackfillEngine()."
                )
            self._detector = GapDetector(self._cfg, self._storage)
        return self._detector

    @property
    def planner(self) -> BackfillPlanner:
        """Access the Backfill Planner sub-component."""
        if self._planner is None:
            self._planner = BackfillPlanner(self._cfg)
        return self._planner

    @property
    def fetcher(self) -> HistoricalFetcher:
        """Access the Historical Fetcher sub-component."""
        if self._fetcher is None:
            if self._transport is None:
                raise RuntimeError(
                    "TransportLayer is required for HistoricalFetcher. "
                    "Pass transport= to BackfillEngine()."
                )
            self._fetcher = HistoricalFetcher(
                self._cfg, self._transport, self._ingestion_cfg,
                import_proof_lookup=getattr(self._storage, "get_history_archive_import_proofs", None),
            )
            self._fetcher.memory_budget = getattr(self,'memory_budget',None)
        return self._fetcher

    @property
    def reconciler(self) -> Reconciler:
        """Access the Reconciler sub-component."""
        if self._reconciler is None:
            if self._storage is None:
                raise RuntimeError(
                    "StorageBackend is required for Reconciler. "
                    "Pass storage= to BackfillEngine()."
                )
            self._reconciler = Reconciler(self._cfg, self._storage, self._cache)
        return self._reconciler

    @property
    def publisher(self) -> RepairPublisher:
        """Access the Repair Publisher sub-component."""
        if self._publisher is None:
            self._publisher = RepairPublisher(self._cfg)
        return self._publisher

    # ── Public: Metrics / Snapshot ───────────────────────────

    @property
    def metrics(self) -> LayerMetrics:
        return self._metrics

    def snapshot(self) -> dict:
        """Return a JSON-serializable snapshot of the entire engine state."""
        return {
            "component": "BackfillEngine",
            "config": self._cfg.snapshot(),
            "detector": self._detector.snapshot() if self._detector else None,
            "planner": self._planner.snapshot() if self._planner else None,
            "fetcher": self._fetcher.snapshot() if self._fetcher else None,
            "reconciler": self._reconciler.snapshot() if self._reconciler else None,
            "publisher": self._publisher.snapshot() if self._publisher else None,
            "metrics": self._metrics.snapshot(),
        }

    # ── Public: Run ──────────────────────────────────────────

    def start_archive_cleanup(self) -> None:
        self.fetcher.request_archive_cleanup()

    async def close(self) -> None:
        if self._fetcher is not None:
            await self._fetcher.close()

    async def run_receipt(self, *args, **kwargs) -> RepairReport:
        """Explicit coordinator API: accept bounded pages and return receipts.

        Ordinary run() retains its complete fetched-bar payload contract.
        Existing payload extensions/preview or overridden run implementations
        select that ordinary path. Payload registrations must happen between
        active receipt runs, before their fetch contract has been selected.
        """
        if getattr(self.run,'__func__',None) is not BackfillEngine.run:
            return await self.run(*args,**kwargs)
        if type(self.publisher) is not RepairPublisher:
            return await self.run(*args,**kwargs)
        with self.publisher.receipt_scope() as enabled:
            return await self.run(*args,**kwargs, _receipt_mode=enabled)

    @fenced_acquisition
    @budgeted_work
    async def run(
        self,
        symbol: str,
        intervals: list[str] | None = None,
        range_start_ms: int | None = None,
        range_end_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
        exchange: str = "binance",
        market_type: str = "spot",
        *,
        native_progress: NativeBackfillProgress | None = None,
        _receipt_mode: bool = False,
    ) -> RepairReport:
        """Execute a complete backfill run.

        Pipeline: Detect → Plan → Fetch → Reconcile → Publish

        Args:
            symbol:         Trading pair, e.g. "BTCUSDT".
            intervals:      Intervals to backfill (default: config.gap_scan_intervals).
            range_start_ms: Start of desired data range (ms).
            range_end_ms:   End of desired data range (ms).
            metadata:       Arbitrary metadata to attach to the report.

        Returns:
            A ``RepairReport`` describing what happened.
        """
        started_at_ms = int(time.time() * 1000)
        symbol = normalize_symbol(symbol, exchange=exchange, market_type=market_type)
        metadata = dict(metadata or {})
        bybit_gap = reuses_bybit_gap_inputs(exchange, market_type, metadata.get("requester"))
        bybit_derived_gap = bybit_gap or (
            metadata.get("requester") == "ledger_reconcile"
            and bybit_recovery_source_gap_id(exchange, market_type, metadata.get("reason"), metadata) is not None
        )
        self._metrics.inc("runs")
        self._metrics.mark("last_run_at")

        logger.info(
            "Backfill run started: symbol=%s intervals=%s",
            symbol, intervals or "default",
        )

        errors: list[str] = []
        plan: BackfillPlan | None = None
        fetch_results: list[FetchResult | FetchReceipt] = []
        reconcile_result: ReconcileResult | None = None
        status = BackfillStatus.PENDING
        streamed = StreamReconcile() if _receipt_mode else None
        page_binding = None

        def check_page_binding():
            if page_binding is None:
                return
            refs, flags = page_binding
            current = (self._storage,self._cfg,self._reconciler,self._fetcher,
                getattr(self,'memory_budget',None),getattr(self._reconciler,'_custom_dedup_fn',None),
                getattr(self._reconciler,'_custom_aggregator',None))
            if (any(a is not b for a,b in zip(current,refs))
                    or flags != (getattr(self._cfg,'reconcile_dedup_strategy',None),
                                 getattr(self._cfg,'reconcile_generate_custom',None))):
                raise StaleAcquisition('paged backfill owner/config binding changed')

        async def consume_native_page(page):
            nonlocal reconcile_result
            check_page_binding()
            if streamed.clipped_ranges:
                raise MemoryBudgetExceeded('stream output range budget is exhausted')
            part = await self.reconciler.reconcile([page],BackfillPlan(gaps=[]))
            streamed.pages += 1
            streamed.add(part)
            reconcile_result = streamed.result
            check_page_binding()
            if part.errors:
                raise RuntimeError('native page reconciliation failed: '+str(part.errors[0])[:500])

        try:
            if native_progress is not None:
                await native_progress.verify(
                    self._storage, exchange=exchange, market_type=market_type, symbol=symbol,
                    start_ms=range_start_ms, end_ms=range_end_ms, metadata=metadata,
                )
            # ── Phase 1: Detect ──
            status = BackfillStatus.DETECTING
            if repair_requires_trusted_finality(metadata):
                gaps = self._trusted_finality_refresh_gaps(
                    symbol=symbol,
                    intervals=intervals,
                    range_start_ms=range_start_ms,
                    range_end_ms=range_end_ms,
                    exchange=exchange,
                    market_type=market_type,
                )
                gaps = await self._reuse_native_gap_inputs(
                    gaps, metadata, bybit_gap=bybit_gap, native_progress=native_progress,
                )
                metadata["repair_mode"] = "authoritative_refresh"
                logger.info(
                    "Forcing authoritative refresh for %s intervals=%s range=[%s,%s]",
                    symbol,
                    intervals or "default",
                    range_start_ms,
                    range_end_ms,
                )
            else:
                gaps = await self.detector.detect(
                    symbol=symbol,
                    intervals=intervals,
                    range_start_ms=range_start_ms,
                    range_end_ms=range_end_ms,
                    exchange=exchange,
                    market_type=market_type,
                )

            if not gaps:
                logger.info("No gaps detected for %s — nothing to do", symbol)
                status = BackfillStatus.COMPLETED
                if native_progress is not None:
                    reconcile_result = ReconcileResult()
                    native_progress.include_writes(reconcile_result)
                report = self.publisher.build_report(
                    symbol=symbol,
                    exchange=exchange,
                    status=status,
                    plan=None,
                    fetch_results=[],
                    reconcile_result=reconcile_result,
                    started_at_ms=started_at_ms,
                    metadata=metadata,
                )
                await self.publisher.publish(report)
                return report

            # ── Phase 2: Plan ──
            status = BackfillStatus.PLANNING
            from .mixed_plan import build_mixed_backfill_plan
            mixed_diagnostics = {}
            required_contract = metadata.get('required_history_composition')
            if required_contract is not None:
                for gap in gaps:
                    self.planner._interval_resolver.require_history_composition(
                        exchange=gap.exchange, market_type=gap.market_type, interval=gap.interval,
                        contract_id=required_contract, identity=identity_from_metadata(gap.exchange, metadata),
                        enabled=self._cfg.mixed_custom_history and self._cfg.reconcile_generate_custom
                            and self._cfg.custom_alignment_mode == 'epoch' and not self._cfg.alignment_epoch_ms)
            plan = await build_mixed_backfill_plan(self, gaps, metadata, mixed_diagnostics)
            if plan is None:
                if required_contract is not None:
                    raise IntervalResolutionError(
                        IntervalResolutionErrorCode.HISTORY_COMPOSITION_UNAVAILABLE,
                        'Qualified composed history could not admit this bounded repair',
                        exchange=exchange, market_type=market_type, interval=gaps[0].interval,
                        purpose=IntervalPurpose.HISTORY)
                plan = self.planner.plan(gaps)
            plan.metadata.update(mixed_diagnostics)
            metadata.update(mixed_diagnostics)

            if not plan.tasks and not plan.derived_source_windows:
                logger.info("Planner produced no tasks for %s", symbol)
                status = BackfillStatus.COMPLETED
                report = self.publisher.build_report(
                    symbol=symbol,
                    exchange=exchange,
                    status=status,
                    plan=plan,
                    fetch_results=[],
                    reconcile_result=None,
                    started_at_ms=started_at_ms,
                    metadata=metadata,
                )
                await self.publisher.publish(report)
                return report

            reserve_work(getattr(self, "memory_budget", None), "history-backfill",
                         max(1, plan.estimated_bars, plan.metadata.get("mixed_source_rows", 0)) * 2048)
            # ── Phase 3: Fetch ──
            # Set market_type on all tasks so the fetcher routes correctly
            for task in plan.tasks:
                task.exchange = exchange
                task.market_type = market_type
                # The scheduler intentionally page-bounds each physical run.
                # Preserve its parent-range metadata on the lower-level task
                # so archive routing can still decide from the complete user
                # demand (not from a single ~1000-source-row chunk).
                task.metadata = {**metadata, **task.metadata}
            if (self._cfg.reconcile_generate_custom and len(intervals or ()) == 1
                    and (bybit_derived_gap or metadata.get("requester") == "warm_start_custom_tail"
                         or _is_read_repair(metadata))):
                await self._reuse_derived_components(plan, metadata, bybit_gap=bybit_derived_gap)
            page_mode = (_receipt_mode and native_progress is None and stream_plan(plan,self._cfg.fetch_batch_size)
                         and getattr(self._storage,'revision_store',None) is not None
                         and getattr(self.fetcher.fetch,'__func__',None) is HistoricalFetcher.fetch
                         and getattr(self.reconciler.reconcile,'__func__',None) is Reconciler.reconcile
                         and self.reconciler._custom_dedup_fn is None
                         and self.reconciler._custom_aggregator is None)
            page_options = {'on_native_page':consume_native_page} if page_mode else {}
            if page_mode:
                self.fetcher.memory_budget = getattr(self,'memory_budget',None)
                page_binding = ((self._storage,self._cfg,self._reconciler,self._fetcher,
                    getattr(self,'memory_budget',None),self._reconciler._custom_dedup_fn,
                    self._reconciler._custom_aggregator),
                    (self._cfg.reconcile_dedup_strategy,self._cfg.reconcile_generate_custom))
            status = BackfillStatus.FETCHING
            await prepare_native_history_views(self._storage, plan.tasks)
            await prepare_derived_targets(self._storage, plan)
            if plan.derived_source_windows:
                prepare_warmup_view(plan.derived_source_windows)
                fetch_results = await self.fetcher.fetch(plan.tasks, on_deferred=self._commit_warmup_progress, **page_options)
            elif (exchange == "bybit" and not plan.decompositions
                    and metadata.get("chunk_sequence") is not None
                    and callable(getattr(self._storage, "query_time_range", None))):
                native_progress = native_progress or NativeBackfillProgress()
                pending = [task for task in plan.tasks if not native_progress.covers_task(task)]
                try:
                    fetch_results = await self.fetcher.fetch(pending, keep_completed=True)
                except FetchBatchDeferred as exc:
                    committed = await self.reconciler.reconcile(exc.completed, plan)
                    await native_progress.remember(self._storage, exc.completed, committed)
                    raise NativeBackfillDeferred(exc, native_progress, committed) from exc
            else:
                native_progress = None
                fetch_results = await self.fetcher.fetch(plan.tasks, **page_options)

            fetch_error_summaries: list[str] = []
            check_page_binding()
            for result in fetch_results:
                if not result.errors and result.status not in {
                    BackfillStatus.FAILED,
                    BackfillStatus.PARTIAL,
                }:
                    continue
                error_text = "; ".join(result.errors) or "no error detail"
                summary = (
                    f"Fetch task {result.status.value}: "
                    f"task={result.task.task_key} "
                    f"interval={result.task.interval} "
                    f"range=[{result.task.start_ms},{result.task.end_ms}] "
                    f"errors={error_text}"
                )
                fetch_error_summaries.append(summary)
                logger.warning(
                    "Backfill fetch task issue: task=%s interval=%s "
                    "range=[%d,%d] status=%s errors=%s",
                    result.task.task_key,
                    result.task.interval,
                    result.task.start_ms,
                    result.task.end_ms,
                    result.status.value,
                    error_text,
                )

            # Check if all tasks failed
            all_failed = bool(fetch_results) and all(
                fr.status == BackfillStatus.FAILED for fr in fetch_results
            )
            if all_failed and not plan.derived_source_windows:
                status = BackfillStatus.FAILED
                errors.append("All fetch tasks failed")
                errors.extend(fetch_error_summaries)
                logger.error("All fetch tasks failed for %s", symbol)
            else:
                errors.extend(fetch_error_summaries)
                # ── Phase 4: Reconcile ──
                status = BackfillStatus.RECONCILING
                receipts = tuple(item for item in fetch_results if isinstance(item,FetchReceipt))
                if receipts:
                    # A failed native commit must not regenerate targets from
                    # an older canonical value that merely still has coverage.
                    final_plan = BackfillPlan(gaps=[]) if streamed.result.errors else plan
                    final = await self.reconciler.reconcile(
                        [item for item in fetch_results if isinstance(item,FetchResult)],
                        final_plan,native_receipts=receipts)
                    streamed.add(final)
                    reconcile_result = streamed.result
                else:
                    reconcile_result = await self.reconciler.reconcile(fetch_results,plan)
                if native_progress is not None:
                    native_progress.include_writes(reconcile_result)
                # Successful object transactions remain eligible even if a
                # different task/derived calculation failed. The worker reads
                # durable proofs; fetch metadata and whole-run status grant
                # no deletion authority.
                request_cleanup = getattr(self.fetcher, "request_archive_cleanup", None)
                if callable(request_cleanup):
                    request_cleanup()

                if not reconcile_result.errors:
                    # Do not suppress a parent archive object until its base
                    # rows, receipt, derived bars and range publication have
                    # all completed successfully.  Failed/cancelled passes
                    # remain eligible for the next scheduler retry.
                    acknowledge_imports = getattr(
                        self.fetcher,
                        "acknowledge_archive_imports",
                        None,
                    )
                    if callable(acknowledge_imports):
                        acknowledge_imports(fetch_results)

                if reconcile_result.errors:
                    errors.extend(reconcile_result.errors)

                # Determine final status
                any_failed = any(
                    fr.status in {BackfillStatus.FAILED, BackfillStatus.PARTIAL}
                    for fr in fetch_results
                )
                if all_failed and fetch_results and not reconcile_result.custom_bars_written:
                    status = BackfillStatus.FAILED
                elif any_failed or reconcile_result.errors:
                    status = BackfillStatus.PARTIAL
                else:
                    status = BackfillStatus.COMPLETED

        except RateLimitDeferred as exc:
            # Quota deferral never publishes a terminal report for the batch.
            if plan is not None:
                plan.mixed_binding = None
            if streamed is not None and streamed.pages:
                raise StreamBackfillDeferred(exc,streamed.result) from exc
            raise
        except Exception as exc:
            status = BackfillStatus.FAILED
            errors.append(str(exc))
            self._metrics.inc("run_errors")
            logger.error(
                "Backfill run failed for %s: %s", symbol, exc, exc_info=True,
            )

        # Runtime fences must not keep engine/storage owners alive through
        # retained reports after this run has completed.
        if plan is not None:
            plan.mixed_binding = None
        if _receipt_mode:
            count = sum(isinstance(item,FetchReceipt) for item in fetch_results)
            metadata['fetch_payload_mode'] = ('receipt' if count == len(fetch_results) and count
                                               else 'mixed' if count else 'full')
            metadata['stream_reconciliation'] = streamed.snapshot()
        # ── Phase 5: Publish ──
        report = self.publisher.build_report(
            symbol=symbol,
            exchange=exchange,
            status=status,
            plan=plan,
            fetch_results=fetch_results,
            reconcile_result=reconcile_result,
            started_at_ms=started_at_ms,
            errors=errors,
            metadata=metadata,
            receipt_mode=_receipt_mode,
        )

        try:
            await self.publisher.publish(report)
        except Exception as exc:
            logger.error("Failed to publish report: %s", exc, exc_info=True)

        self._metrics.inc(f"runs_{status.value}")
        logger.info(
            "Backfill run finished: symbol=%s status=%s elapsed=%dms",
            symbol, status.value, report.elapsed_ms,
        )
        return report

    async def _reuse_derived_components(
        self, plan: BackfillPlan, metadata: dict[str, Any], *, bybit_gap: bool,
    ) -> None:
        """Keep complete target inputs for reconciliation, fetching only unqualified source slots."""
        if plan.metadata.get("mixed_history"):
            # The qualified planner already retained the exact canonical cover
            # and selected only missing native runs for the existing fetcher.
            return
        if (self._storage is None or (not bybit_gap and repair_requires_trusted_finality(metadata)
                                     and not _is_read_repair(metadata))
                or metadata.get("history_calendar_id") != "crypto.24x7.utc"
                or len(plan.custom_intervals) != 1 or self._cfg.alignment_epoch_ms != 0):
            return

        target = parse_interval_spec(plan.custom_intervals[0])
        if target is None or target.alignment is not IntervalAlignment.FIXED_EPOCH or target.phase_ms:
            return

        tasks = []
        now_ms = int(time.time() * 1000)
        for task in plan.tasks:
            source = parse_interval_spec(task.interval)
            identity = identity_from_metadata(task.exchange, metadata)
            qualified_source = (
                task.interval == "5m" if bybit_gap
                else task.exchange in {"binance", "okx"}
                or (task.exchange, task.market_type, task.interval) == _BYBIT_WARMUP_SOURCE
            )
            if (task.metadata.get("custom_interval") != target.canonical
                    or not qualified_source
                    or (identity is not None and not identity.is_legacy_default_for(task.exchange))
                    or source is None or source.alignment is not IntervalAlignment.FIXED_EPOCH
                    or source.phase_ms or source.nominal_ms < 60_000):
                tasks.append(task)
                continue

            step = source.nominal_ms
            rows = await self._storage.query_time_range(
                task.symbol, task.interval, task.start_ms, task.end_ms,
                exchange=task.exchange, market_type=task.market_type,
            )
            plan.derived_source_windows.append(task)
            for first, last, count in self._unqualified_warmup_ranges(
                rows, task.start_ms, task.end_ms, step, now_ms,
            ):
                tasks.append(replace(task, start_ms=first, end_ms=last, estimated_bars=count))

        if plan.derived_source_windows:
            plan.tasks = tasks
            plan.estimated_requests = len(tasks)
            plan.estimated_bars = sum(task.estimated_bars for task in tasks)

    def _unqualified_warmup_ranges(
        self, rows: list[dict], start_ms: int, end_ms: int, step: int, now_ms: int,
    ) -> Iterator[tuple[int, int, int]]:
        trusted = {
            int(row["open_time"]) for row in rows
            if self._is_reusable_warmup_component(row, step, now_ms)
        }
        for local, slots in groupby(range(start_ms, end_ms + 1, step), trusted.__contains__):
            if not local:
                missing = list(slots)
                yield missing[0], missing[-1], len(missing)

    @staticmethod
    def _is_reusable_warmup_component(row: dict, step: int, now_ms: int) -> bool:
        if not source_is_trusted_final(row.get("source")) or not row_is_closed(row):
            return False
        try:
            close_ms = int(row["close_time"])
            values = tuple(float(row[field]) for field in ("open", "high", "low", "close", "volume"))
            return close_ms == int(row["open_time"]) + step - 1 and close_ms < now_ms and valid_ohlcv(values)
        except (KeyError, OverflowError, TypeError, ValueError):
            return False

    async def _commit_warmup_progress(self, results: list[FetchResult]) -> None:
        # If another missing run hit shared quota, preserve admitted source
        # rows under the current write fence. Retry recomputes the remaining
        # holes and only publishes derived results after normal reconciliation.
        await self.reconciler.reconcile(results, BackfillPlan(gaps=[]))

    async def _reuse_native_gap_inputs(
        self, gaps: list[GapInfo], metadata: dict[str, Any], *, bybit_gap: bool,
        native_progress: NativeBackfillProgress | None,
    ) -> list[GapInfo]:
        if (self._storage is None or len(gaps) != 1
                or (not bybit_gap and metadata.get("requester") != "warm_start_custom_seed")
                or metadata.get("history_calendar_id") != "crypto.24x7.utc"):
            return gaps
        gap = gaps[0]
        if bybit_gap:
            if gap.interval != "5m":
                return gaps
        elif (gap.exchange, gap.market_type, gap.interval) != _BYBIT_WARMUP_SOURCE:
            # Multiple custom targets can queue the same already-closed native
            # seed before the first repair commits. Recheck the canonical owner
            # at dispatch, as on the qualified Bybit route; do not widen source
            # admission or reuse provisional/manual/unknown rows.
            if gap.exchange not in {"binance", "okx"} or gap.market_type not in {"spot", "futures"}:
                return gaps
            from app.data_engine.interval_resolution import IntervalResolver, IntervalPurpose, IntervalResolutionError
            try:
                route = IntervalResolver().resolve(exchange=gap.exchange, market_type=gap.market_type,
                    interval=gap.interval, purpose=IntervalPurpose.HISTORY)
            except IntervalResolutionError:
                return gaps
            if (not route.is_native or route.canonical_interval != gap.interval
                    or route.spec.alignment is not IntervalAlignment.FIXED_EPOCH
                    or route.spec.phase_ms or not 60_000 <= route.spec.nominal_ms <= 86_400_000):
                return gaps
        identity = identity_from_metadata(gap.exchange, metadata)
        if identity is not None and not identity.is_legacy_default_for(gap.exchange):
            return gaps

        # Re-read at dispatch: a live close or another repair may have
        # committed canonical input since the current bucket was seeded.
        spec = parse_interval_spec(gap.interval)
        assert spec is not None
        step = spec.nominal_ms
        now_ms = int(time.time() * 1000)
        first = spec.floor_ms(gap.start_ms)
        if first < gap.start_ms:
            first = spec.next_ms(first)
        last = min(gap.end_ms, spec.floor_ms(now_ms) - step)
        if first > last:
            return []
        rows = await self._storage.query_time_range(
            gap.symbol, gap.interval, first, last, exchange=gap.exchange, market_type=gap.market_type,
        )
        if native_progress is not None:
            invalidated_opens = {
                opened
                for lower, upper in native_progress.invalidated_ranges(gap.interval)
                for opened in range(max(first, lower), min(last, upper) + 1, step)
            }
            rows = [row for row in rows if row["open_time"] not in invalidated_opens]
        return [
            replace(gap, start_ms=start, end_ms=end, missing_bars=count)
            for start, end, count in self._unqualified_warmup_ranges(rows, first, last, step, now_ms)
        ]

    def _trusted_finality_refresh_gaps(
        self,
        *,
        symbol: str,
        intervals: list[str] | None,
        range_start_ms: int | None,
        range_end_ms: int | None,
        exchange: str,
        market_type: str,
    ) -> list[GapInfo]:
        """Build forced fetch ranges for physically present, untrusted rows."""

        if range_start_ms is None or range_end_ms is None:
            raise ValueError("trusted-finality refresh requires an explicit range")
        if range_start_ms > range_end_ms:
            raise ValueError("trusted-finality refresh range is inverted")

        refresh_intervals = intervals or list(self._cfg.gap_scan_intervals)
        gaps: list[GapInfo] = []
        for interval in refresh_intervals:
            spec = parse_interval_spec(interval)
            if spec is None:
                raise ValueError(f"invalid trusted-finality refresh interval: {interval!r}")

            cursor = spec.floor_ms(range_start_ms)
            if cursor < range_start_ms:
                cursor = spec.next_ms(cursor)
            missing_bars = 0
            while cursor <= range_end_ms:
                missing_bars += 1
                cursor = spec.next_ms(cursor)

            gaps.append(GapInfo(
                symbol=symbol,
                interval=spec.canonical,
                gap_type=GapType.INTERIOR,
                start_ms=int(range_start_ms),
                end_ms=int(range_end_ms),
                missing_bars=missing_bars,
                exchange=exchange,
                market_type=market_type,
                metadata={"repair_mode": "authoritative_refresh"},
            ))
        return gaps

    # ── Public: Detect-only (dry run) ────────────────────────

    async def detect_only(
        self,
        symbol: str,
        intervals: list[str] | None = None,
        range_start_ms: int | None = None,
        range_end_ms: int | None = None,
        exchange: str = "binance",
        market_type: str = "spot",
    ) -> list[GapInfo]:
        """Run gap detection only, without planning or fetching.

        Useful for diagnostics and dry runs.
        """
        symbol = normalize_symbol(symbol, exchange=exchange, market_type=market_type)
        return await self.detector.detect(
            symbol=symbol,
            intervals=intervals,
            range_start_ms=range_start_ms,
            range_end_ms=range_end_ms,
            exchange=exchange,
            market_type=market_type,
        )

    # ── Public: Plan-only (dry run) ──────────────────────────

    async def plan_only(
        self,
        symbol: str,
        intervals: list[str] | None = None,
        range_start_ms: int | None = None,
        range_end_ms: int | None = None,
        exchange: str = "binance",
        market_type: str = "spot",
    ) -> BackfillPlan:
        """Run gap detection + planning only, without fetching.

        Useful for cost estimation and previewing what would happen.
        """
        symbol = normalize_symbol(symbol, exchange=exchange, market_type=market_type)
        gaps = await self.detector.detect(
            symbol=symbol,
            intervals=intervals,
            range_start_ms=range_start_ms,
            range_end_ms=range_end_ms,
            exchange=exchange,
            market_type=market_type,
        )
        return self.planner.plan(gaps)
