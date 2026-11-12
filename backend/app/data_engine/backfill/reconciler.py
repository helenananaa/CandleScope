"""
Reconciler — deduplicates, aggregates custom intervals, writes to DB, and pushes to cache.

Responsibilities:
  * Receive ``FetchResult`` objects from the Historical Fetcher
  * Deduplicate against existing DB data (skip / overwrite / backfill_wins)
  * Rebuild custom-interval candles from canonical stored components via K130
  * Write bars to ``StorageBackend`` in batches
  * Push recent bars to ``CacheBackend`` (optional)
  * Report per-phase statistics via ``ReconcileResult``

Extension points:
  * ``set_custom_aggregator(fn)``    — override OHLCV aggregation logic
  * ``set_dedup_fn(fn)``             — override deduplication logic
  * ``on_write_batch(callback)``     — per-batch callback
  * ``on_reconcile_done(callback)``  — completion callback

Usage::

    reconciler = Reconciler(config, storage, cache=my_cache)

    result = await reconciler.reconcile(fetch_results, plan)
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import logging
import time
from itertools import pairwise
from typing import Callable, Awaitable, Any

from app.core.executors import run_preparation
from app.data_engine.aggregation.semantics import valid_ohlcv
from app.data_engine.interval_policy import aggregate_kline_rows, parse_interval_spec
from app.data_engine.kline_quality import source_is_trusted_final, source_rank
from app.data_engine.storage.revisions import StaleAcquisition, fenced_acquisition, prepare_derived_inputs
from app.data_engine.storage.derived_history_fence import computation_scope
from app.data_engine.series_identity import KlineSeriesIdentity, resolve_kline_series_identity
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.custom_materialization import (
    MaterializationLease,
    custom_materialization_registry,
)

from ..ingestion.metrics import LayerMetrics
from .config import BackfillConfig
from .models import (
    BackfillPlan,
    BackfillStatus,
    BackfillTask,
    CacheBackend,
    DeduplicationStrategy,
    FetchedBar,
    FetchResult,
    IntervalDecomposition,
    ReconcileResult,
    StorageBackend,
    WrittenRange,
)

logger = logging.getLogger("backfill.Reconciler")


def _identity_kwargs(
    identity: KlineSeriesIdentity | None,
) -> dict[str, KlineSeriesIdentity]:
    return {"series_identity": identity} if identity is not None else {}

# Type aliases
CustomAggregator = Callable[[list[FetchedBar], str, str, int, int], FetchedBar | None]
DedupFn = Callable[[FetchedBar, dict], bool]  # (new_bar, existing_row) → keep_new?
WriteBatchCallback = Callable[[str, str, int], Awaitable[None]]  # symbol, interval, count
ReconcileDoneCallback = Callable[[ReconcileResult], Awaitable[None]]


class Reconciler:
    """Deduplicates fetched data, generates custom candles, writes to storage."""

    def __init__(
        self,
        config: BackfillConfig,
        storage: StorageBackend,
        cache: CacheBackend | None = None,
    ) -> None:
        self._cfg = config
        self._storage = storage
        self._cache = cache
        self._metrics = LayerMetrics("Reconciler")

        # Extension points
        self._custom_aggregator: CustomAggregator | None = None
        self._custom_dedup_fn: DedupFn | None = None
        self._write_batch_callbacks: list[WriteBatchCallback] = []
        self._done_callbacks: list[ReconcileDoneCallback] = []
        self._materialization_write_tasks: set[asyncio.Task[Any]] = set()

    # ── Public: Metrics / Snapshot ───────────────────────────

    @property
    def metrics(self) -> LayerMetrics:
        return self._metrics

    def snapshot(self) -> dict:
        return {
            "component": "Reconciler",
            "dedup_strategy": self._cfg.reconcile_dedup_strategy,
            "write_batch_size": self._cfg.reconcile_write_batch_size,
            "cache_enabled": self._cfg.reconcile_enable_cache_push,
            "materialization_writes_draining": len(
                self._materialization_write_tasks
            ),
            "metrics": self._metrics.snapshot(),
        }

    # ── Public: Extension points ─────────────────────────────

    def set_custom_aggregator(self, fn: CustomAggregator) -> None:
        """Override the OHLCV aggregation logic for custom intervals.

        The function signature::

            (bars: list[FetchedBar], symbol: str, custom_interval: str,
             bucket_start_ms: int, bucket_end_ms: int) → FetchedBar | None

        Example::

            def my_agg(bars, symbol, interval, start, end):
                if not bars:
                    return None
                return FetchedBar(
                    symbol=symbol, interval=interval,
                    open_time=start, close_time=end,
                    open=bars[0].open, high=max(b.high for b in bars),
                    low=min(b.low for b in bars), close=bars[-1].close,
                    volume=sum(b.volume for b in bars),
                )
            reconciler.set_custom_aggregator(my_agg)
        """
        self._custom_aggregator = fn

    def set_dedup_fn(self, fn: DedupFn) -> None:
        """Override the deduplication decision.

        The function receives ``(new_bar, existing_row_dict)`` and returns
        ``True`` if the new bar should replace the existing one.
        """
        self._custom_dedup_fn = fn

    def on_write_batch(self, callback: WriteBatchCallback) -> None:
        """Register a callback invoked after each DB write batch."""
        self._write_batch_callbacks.append(callback)

    def on_reconcile_done(self, callback: ReconcileDoneCallback) -> None:
        """Register a callback invoked when reconciliation completes."""
        self._done_callbacks.append(callback)

    # ── Public: Reconcile ────────────────────────────────────

    @fenced_acquisition
    async def reconcile(
        self,
        fetch_results: list[FetchResult],
        plan: BackfillPlan,
    ) -> ReconcileResult:
        """Run the full reconciliation pipeline.

        Steps:
          1. Collect all bars from fetch results
          2. Deduplicate against DB
          3. Write standard-interval bars
          4. Generate and write custom-interval bars
          5. Push recent bars to cache

        Args:
            fetch_results: Results from the Historical Fetcher.
            plan:          The backfill plan (for decomposition info).

        Returns:
            A ``ReconcileResult`` summarizing what happened.
        """
        start = time.monotonic()
        self._metrics.inc("reconcile_runs")
        self._metrics.mark("last_reconcile_at")

        result = ReconcileResult()

        try:
            archive_receipts = self._collect_archive_receipts(fetch_results)
            archive_receipts_by_key = {
                str(item["object_key"]): item
                for item in archive_receipts
            }
            handled_archive_receipts: set[str] = set()
            # 1. Collect all bars grouped by (exchange, market_type, symbol, interval)
            grouped = self._group_bars(fetch_results)
            total_received = sum(len(bars) for bars in grouped.values())
            result.bars_received = total_received
            record_empty = getattr(self._storage, "record_native_empty_seconds", None)
            record_trade_empty = getattr(self._storage, "record_trade_empty_buckets", None)
            if callable(record_trade_empty):
                for fetched in fetch_results:
                    ranges = fetched.metadata.get("trade_empty_ranges", [])
                    task = fetched.task
                    if ranges:
                        await record_trade_empty(task.exchange, task.market_type, task.symbol, task.interval, ranges)
            if callable(record_empty):
                for fetched in fetch_results:
                    task = fetched.task
                    ranges = fetched.metadata.get("native_empty_ranges", [])
                    if task.exchange == "upbit" and task.market_type == "spot" and task.interval == "1s" and ranges:
                        await record_empty(task.symbol, ranges)

            # 2 & 3. Dedup + write standard bars
            for (exchange, market_type, symbol, interval), bars in grouped.items():
                (
                    written,
                    skipped,
                    deduped,
                    failures,
                    written_ranges,
                    archive_imported,
                    archive_invalidated,
                    handled_receipts,
                ) = await self._dedup_and_write(
                    symbol,
                    interval,
                    bars,
                    exchange=exchange,
                    market_type=market_type,
                    archive_receipts=archive_receipts_by_key,
                )
                result.bars_written += written
                result.bars_skipped += skipped
                result.bars_deduplicated += deduped
                result.written_ranges.extend(written_ranges)
                result.archive_objects_imported += archive_imported
                result.archive_dependent_rows_invalidated += archive_invalidated
                handled_archive_receipts.update(handled_receipts)
                self._metrics.inc("archive_objects_imported", archive_imported)
                self._metrics.inc(
                    "archive_dependent_rows_invalidated",
                    archive_invalidated,
                )
                self._record_write_failures(result, failures)

            # Archive receipts are advisory metadata, but revision
            # invalidation is part of correctness and must happen after the
            # official base rows commit and before custom bars regenerate.
            remaining_archive_receipts = [
                item
                for item in archive_receipts
                if str(item["object_key"]) not in handled_archive_receipts
            ]
            if remaining_archive_receipts and result.write_errors == 0:
                await self._persist_archive_receipts(
                    remaining_archive_receipts,
                    result,
                )

            # 4. Generate custom-interval bars
            if (
                not result.errors
                and self._cfg.reconcile_generate_custom
                and plan.custom_intervals
            ):
                custom_started = time.monotonic()
                decompositions = plan.decompositions[:1] if plan.derived_source_windows else plan.decompositions
                for decomp in decompositions:
                    views = await prepare_derived_inputs(self._storage, decomp, grouped)
                    with computation_scope(views):
                        gen, wrt, failures, written_ranges = await self._generate_custom_bars(
                            decomp, grouped, plan.derived_source_windows,
                            **({"binding_check": plan.mixed_binding.validate if plan.mixed_binding is not None else None,
                                "confirmed_empty": bool(fetch_results) and all(
                                r.source_complete is True and not r.retryable and not r.errors and not r.bars and bool(r.empty_reason)
                                for r in fetch_results)} if getattr(decomp, "composition_policy", None) is not None else {}),
                        )
                    result.custom_bars_generated += gen
                    result.custom_bars_written += wrt
                    result.written_ranges.extend(written_ranges)
                    self._record_write_failures(result, failures)
                custom_elapsed_ms = int(
                    (time.monotonic() - custom_started) * 1_000
                )
                self._metrics.inc(
                    "custom_materialization_elapsed_ms_total",
                    custom_elapsed_ms,
                )
                self._metrics.set(
                    "last_custom_materialization_elapsed_ms",
                    custom_elapsed_ms,
                )

            # 5. Push to cache
            if self._cfg.reconcile_enable_cache_push and self._cache is not None:
                cached = await self._push_to_cache(grouped)
                result.bars_cached = cached

        except Exception as exc:
            result.errors.append(str(exc))
            self._metrics.inc("reconcile_errors")
            logger.error("Reconciliation error: %s", exc, exc_info=True)

        result.elapsed_ms = int((time.monotonic() - start) * 1000)
        self._metrics.inc("reconcile_elapsed_ms_total", result.elapsed_ms)
        self._metrics.set("last_reconcile_elapsed_ms", result.elapsed_ms)

        # Fire done callbacks
        for cb in self._done_callbacks:
            try:
                await cb(result)
            except Exception as exc:
                logger.error("Reconcile done callback error: %s", exc)

        self._metrics.inc("bars_written", result.bars_written)
        self._metrics.inc("bars_skipped", result.bars_skipped)
        logger.info(
            "Reconciliation done: received=%d written=%d skipped=%d "
            "custom_gen=%d cached=%d in %dms",
            result.bars_received, result.bars_written, result.bars_skipped,
            result.custom_bars_generated, result.bars_cached, result.elapsed_ms,
        )
        return result

    # ── Internal: Group bars ─────────────────────────────────

    @staticmethod
    def _group_bars(
        fetch_results: list[FetchResult],
    ) -> dict[tuple[str, str, str, str], list[FetchedBar]]:
        """Group all fetched bars by (exchange, market_type, symbol, interval)."""
        indexed: dict[
            tuple[str, str, str, str],
            dict[int, FetchedBar],
        ] = {}
        identities: dict[tuple[str, str, str, str], KlineSeriesIdentity] = {}
        defaults: dict[str, KlineSeriesIdentity] = {}
        for fr in fetch_results:
            if fr.status == BackfillStatus.FAILED:
                continue
            for bar in fr.bars:
                key = (bar.exchange, bar.market_type, bar.symbol, bar.interval)
                canonical = bar.series_identity
                if canonical is None:
                    canonical = defaults.get(bar.exchange)
                    if canonical is None:
                        canonical = resolve_kline_series_identity(bar.exchange, None)
                        defaults[bar.exchange] = canonical
                # Validate before timestamp deduplication can discard evidence
                # of a foreign identity, including fully overlapping batches.
                if identities.setdefault(key, canonical) != canonical:
                    raise ValueError("reconciliation group contains multiple K-line series identities")
                by_open_time = indexed.setdefault(key, {})
                existing = by_open_time.get(bar.open_time)
                if existing is None or Reconciler._prefer_grouped_bar(existing, bar):
                    by_open_time[bar.open_time] = bar

        return {
            key: sorted(values.values(), key=lambda bar: bar.open_time)
            for key, values in indexed.items()
        }

    @staticmethod
    def _prefer_grouped_bar(existing: FetchedBar, incoming: FetchedBar) -> bool:
        incoming_rank = source_rank(incoming.source)
        existing_rank = source_rank(existing.source)
        if incoming_rank != existing_rank:
            return incoming_rank > existing_rank
        # REST may carry a same-authority amendment for an archive row.  Keep
        # it when both arrive in the same reconciliation pass.
        incoming_is_archive = incoming.source.startswith("backfill_archive_")
        existing_is_archive = existing.source.startswith("backfill_archive_")
        if incoming_is_archive != existing_is_archive:
            return not incoming_is_archive
        return True

    @staticmethod
    def _collect_archive_receipts(
        fetch_results: list[FetchResult],
    ) -> list[dict[str, Any]]:
        receipts: dict[str, dict[str, Any]] = {}
        for fetch_result in fetch_results:
            if fetch_result.status == BackfillStatus.FAILED:
                continue
            raw_receipts = fetch_result.metadata.get("archive_objects")
            if not isinstance(raw_receipts, list):
                continue
            for raw in raw_receipts:
                if not isinstance(raw, dict):
                    continue
                object_key = str(raw.get("object_key") or "").strip()
                if object_key:
                    receipts[object_key] = dict(raw)
        return list(receipts.values())

    async def _persist_archive_receipts(
        self,
        receipts: list[dict[str, Any]],
        result: ReconcileResult,
    ) -> None:
        try:
            revised = [item for item in receipts if item.get("revision_changed")]
            invalidator = getattr(self._storage, "invalidate_archive_dependents", None)
            if revised and callable(invalidator):
                invalidated = int(await invalidator(revised) or 0)
                result.archive_dependent_rows_invalidated += invalidated
                self._metrics.inc(
                    "archive_dependent_rows_invalidated",
                    invalidated,
                )
            recorder = getattr(self._storage, "record_history_archive_imports", None)
            if callable(recorder):
                recorded = int(await recorder(receipts) or 0)
                result.archive_objects_imported += recorded
                self._metrics.inc("archive_objects_imported", recorded)
        except Exception as exc:
            message = f"Archive import receipt failed: {exc}"
            result.errors.append(message)
            self._metrics.inc("archive_receipt_errors")
            logger.error(message, exc_info=True)

    # ── Internal: Dedup + Write ──────────────────────────────

    async def _dedup_and_write(
        self,
        symbol: str,
        interval: str,
        bars: list[FetchedBar],
        exchange: str = "binance",
        market_type: str = "spot",
        archive_receipts: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[
        int,
        int,
        int,
        list[dict[str, Any]],
        list[WrittenRange],
        int,
        int,
        set[str],
    ]:
        """Deduplicate bars against DB and write in batches.

        Returns (written, skipped, deduplicated, failures, written_ranges).
        """
        if not bars:
            return 0, 0, 0, [], [], 0, 0, set()

        series_identity = bars[0].series_identity
        default_identity = resolve_kline_series_identity(exchange, None)
        canonical_identity = series_identity or default_identity
        if any((bar.series_identity or default_identity) != canonical_identity for bar in bars):
            raise ValueError(
                "reconciliation group contains multiple K-line series identities"
            )

        strategy = DeduplicationStrategy(self._cfg.reconcile_dedup_strategy)
        batch_size = self._cfg.reconcile_write_batch_size

        # Overwrite/backfill-wins are unconditional upserts.  Reading the
        # entire range first only produced a diagnostic dedup count and doubled
        # storage I/O, so reserve that lookup for policies that actually need
        # existence to make a write decision.
        existing: set[int] = set()
        if strategy is DeduplicationStrategy.SKIP or self._custom_dedup_fn is not None:
            min_ot = bars[0].open_time
            max_ot = bars[-1].open_time
            try:
                existing = await self._storage.get_existing_open_times(
                    symbol,
                    interval,
                    min_ot,
                    max_ot,
                    exchange=exchange,
                    market_type=market_type,
                    **_identity_kwargs(series_identity),
                )
            except Exception:
                existing = set()

        to_write: list[FetchedBar] = []
        skipped = 0
        deduped = 0

        for bar in bars:
            if bar.open_time in existing:
                deduped += 1
                keep_new = self._should_replace(bar, strategy)
                if not keep_new:
                    skipped += 1
                    continue
            to_write.append(bar)

        # Preserve provenance. Official archive groups are deliberately sent
        # to storage in one call so each selected archive range commits or
        # rolls back as a unit; ordinary REST remains bounded by the existing
        # write batch size.
        written = 0
        failures: list[dict[str, Any]] = []
        written_ranges: list[WrittenRange] = []
        archive_imported = 0
        archive_invalidated = 0
        handled_archive_receipts: set[str] = set()
        by_source: dict[tuple[str, str | None], list[FetchedBar]] = {}
        for bar in to_write:
            source = bar.source or "backfill"
            object_key = (
                bar.archive_object_key
                if source.startswith("backfill_archive_")
                else None
            )
            by_source.setdefault((source, object_key), []).append(bar)
        for (source, object_key), source_bars in by_source.items():
            effective_batch_size = (
                len(source_bars)
                if source.startswith("backfill_archive_")
                else batch_size
            )
            effective_batch_size = max(1, effective_batch_size)
            for i in range(0, len(source_bars), effective_batch_size):
                batch = source_bars[i : i + effective_batch_size]
                dicts = [b.to_storage_dict() for b in batch]
                archive_write_started = (
                    time.monotonic()
                    if source.startswith("backfill_archive_")
                    else None
                )
                try:
                    receipt = (
                        (archive_receipts or {}).get(object_key or "")
                        if source.startswith("backfill_archive_")
                        else None
                    )
                    archive_importer = getattr(
                        self._storage,
                        "import_history_archive",
                        None,
                    )
                    if receipt is not None and callable(archive_importer):
                        import_outcome = await archive_importer(
                            symbol,
                            interval,
                            dicts,
                            receipt,
                            source=source,
                            exchange=exchange,
                            market_type=market_type,
                        )
                        n = int(import_outcome.get("written") or 0)
                        archive_imported += int(
                            bool(import_outcome.get("imported"))
                        )
                        archive_invalidated += int(
                            import_outcome.get("invalidated") or 0
                        )
                        handled_archive_receipts.add(str(object_key))
                        if import_outcome.get("skipped"):
                            self._metrics.inc("archive_import_dedup_hits")
                    else:
                        n = await self._storage.upsert_bars(
                            symbol,
                            interval,
                            dicts,
                            source=source,
                            exchange=exchange,
                            market_type=market_type,
                            **_identity_kwargs(series_identity),
                        )
                    written += n
                    written_range = self._written_range_from_batch(
                        exchange=exchange,
                        market_type=market_type,
                        symbol=symbol,
                        interval=interval,
                        batch=batch,
                        bars_written=n,
                        source=source,
                        phase=(
                            "archive_standard"
                            if source.startswith("backfill_archive_")
                            else "standard"
                        ),
                    )
                    if written_range is not None:
                        written_ranges.extend(self._standard_written_ranges(written_range, batch))
                    if n > 0:
                        await self._fire_write_batch(symbol, interval, n)
                except Exception as exc:
                    logger.error(
                        "Write batch failed for %s@%s source=%s: %s",
                        symbol,
                        interval,
                        source,
                        exc,
                        exc_info=True,
                    )
                    self._metrics.inc("write_errors")
                    if isinstance(exc, StaleAcquisition):
                        self._metrics.inc("write_revision_conflicts")
                    failures.append(self._write_failure_detail(
                        exchange=exchange,
                        market_type=market_type,
                        symbol=symbol,
                        interval=interval,
                        batch=batch,
                        error=exc,
                        phase=(
                            "archive_standard"
                            if source.startswith("backfill_archive_")
                            else "standard"
                        ),
                    ))
                finally:
                    if archive_write_started is not None:
                        archive_write_elapsed_ms = int(
                            (time.monotonic() - archive_write_started) * 1_000
                        )
                        self._metrics.inc(
                            "archive_write_elapsed_ms_total",
                            archive_write_elapsed_ms,
                        )
                        self._metrics.set(
                            "last_archive_write_elapsed_ms",
                            archive_write_elapsed_ms,
                        )

        return (
            written,
            skipped,
            deduped,
            failures,
            written_ranges,
            archive_imported,
            archive_invalidated,
            handled_archive_receipts,
        )

    def _should_replace(
        self, bar: FetchedBar, strategy: DeduplicationStrategy,
    ) -> bool:
        """Decide whether to replace an existing bar."""
        if self._custom_dedup_fn is not None:
            return self._custom_dedup_fn(bar, {})

        if strategy == DeduplicationStrategy.SKIP:
            return False
        if strategy == DeduplicationStrategy.OVERWRITE:
            return True
        # BACKFILL_WINS (and the legacy newer_wins name) keeps the fetched
        # repair data without pretending we compared storage updated_at.
        return True

    # ── Internal: Custom interval aggregation ────────────────

    def _defer_materialization_lease_release(
        self,
        lease: MaterializationLease,
        storage_task: asyncio.Task[Any],
    ) -> None:
        """Keep ownership until a cancellation-resistant storage write ends.

        ``run_in_executor`` cannot stop a worker that has begun mutating
        SQLite.  The HTTP/coordinator task may still cancel immediately, but
        the materialization range must remain occupied until that physical
        worker's async wrapper reports completion.
        """
        self._materialization_write_tasks.add(storage_task)
        self._metrics.inc("custom_materialization_cancelled_writes_deferred")

        def _release(completed: asyncio.Task[Any]) -> None:
            self._materialization_write_tasks.discard(completed)
            try:
                completed.result()
            except BaseException as exc:
                lease.fail(exc)
                self._metrics.inc(
                    "custom_materialization_deferred_write_failures"
                )
            else:
                # The current batch may have committed, but cancellation
                # means later batches in this lease were never attempted.
                # Release as failed so a waiter retries the complete range,
                # only after the physical write is no longer in flight.
                lease.fail(
                    "materialization owner cancelled after storage write"
                )
                self._metrics.inc(
                    "custom_materialization_deferred_writes_drained"
                )

        storage_task.add_done_callback(_release)

    async def _write_custom_materialization(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        bars: list[FetchedBar],
        phase: str,
    ) -> tuple[int, list[dict[str, Any]], list[WrittenRange]]:
        """Write one target range under shared query/reconciler ownership."""
        if not bars:
            return 0, [], []

        bars = sorted(bars, key=lambda bar: bar.open_time)
        contiguous_runs: list[list[FetchedBar]] = [[bars[0]]]
        for bar in bars[1:]:
            if bar.open_time == contiguous_runs[-1][-1].close_time + 1:
                contiguous_runs[-1].append(bar)
            else:
                contiguous_runs.append([bar])
        if len(contiguous_runs) > 1:
            total_written = 0
            all_failures: list[dict[str, Any]] = []
            all_ranges: list[WrittenRange] = []
            for run in contiguous_runs:
                count, failures, ranges = await self._write_custom_materialization(
                    exchange=exchange,
                    market_type=market_type,
                    symbol=symbol,
                    interval=interval,
                    bars=run,
                    phase=phase,
                )
                total_written += count
                all_failures.extend(failures)
                all_ranges.extend(ranges)
            return total_written, all_failures, all_ranges

        start_ms = min(bar.open_time for bar in bars)
        end_ms = max(bar.open_time for bar in bars)
        series = custom_materialization_registry.series_key(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            interval=interval,
        )
        async def _claim_materialization():
            while True:
                claimed, partial_overlap = (
                    custom_materialization_registry.claim_nowait(
                        series=series,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        owner="reconciler",
                    )
                )
                if claimed is not None:
                    return claimed
                assert partial_overlap is not None
                await asyncio.shield(asyncio.wrap_future(partial_overlap))

        lease = await _claim_materialization()
        while not lease.is_owner:
            outcome = await asyncio.shield(asyncio.wrap_future(lease.future))
            if outcome.success:
                self._metrics.inc("custom_materialization_joins")
                covered_rows = min(len(bars), outcome.rows_covered)
                joined_range = (
                    WrittenRange(
                        symbol=symbol,
                        interval=interval,
                        exchange=exchange,
                        market_type=market_type,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        bars_written=covered_rows,
                        source="backfill_aggregated",
                        phase=f"{phase}_joined_{outcome.owner}",
                    )
                    if covered_rows > 0
                    else None
                )
                return (
                    covered_rows,
                    [],
                    [joined_range] if joined_range is not None else [],
                )
            lease = await _claim_materialization()

        self._metrics.inc("custom_materialization_owners")
        written = 0
        failures: list[dict[str, Any]] = []
        written_ranges: list[WrittenRange] = []
        batch_size = self._cfg.reconcile_write_batch_size
        lease_finished = False
        lease_release_deferred = False
        try:
            for i in range(0, len(bars), batch_size):
                batch = bars[i : i + batch_size]
                dicts = [bar.to_storage_dict() for bar in batch]
                try:
                    storage_task = asyncio.create_task(
                        self._storage.upsert_bars(
                            symbol,
                            interval,
                            dicts,
                            source="backfill_aggregated",
                            exchange=exchange,
                            market_type=market_type,
                        )
                    )
                    try:
                        storage_result = await asyncio.shield(storage_task)
                    except asyncio.CancelledError:
                        self._defer_materialization_lease_release(
                            lease,
                            storage_task,
                        )
                        lease_release_deferred = True
                        raise
                    count = int(storage_result or 0)
                    written += count
                    # A successful upsert returning zero commonly means the
                    # exact rows already existed.  Preserve durable coverage
                    # separately from the physical mutation count so repair
                    # completion never loses the target range.
                    written_range = self._written_range_from_batch(
                        exchange=exchange,
                        market_type=market_type,
                        symbol=symbol,
                        interval=interval,
                        batch=batch,
                        bars_written=len(batch),
                        source="backfill_aggregated",
                        phase=phase,
                    )
                    if written_range is not None:
                        written_ranges.append(written_range)
                except Exception as exc:
                    logger.error(
                        "Custom bar write failed for %s@%s phase=%s: %s",
                        symbol,
                        interval,
                        phase,
                        exc,
                        exc_info=True,
                    )
                    self._metrics.inc("write_errors")
                    if isinstance(exc, StaleAcquisition):
                        self._metrics.inc("write_revision_conflicts")
                    failures.append(self._write_failure_detail(
                        exchange=exchange,
                        market_type=market_type,
                        symbol=symbol,
                        interval=interval,
                        batch=batch,
                        error=exc,
                        phase=phase,
                    ))

            if failures:
                lease.fail(failures[0]["error"])
            else:
                lease.complete(written, rows_covered=len(bars))
            lease_finished = True
            return written, failures, written_ranges
        except BaseException as exc:
            if not lease_finished and not lease_release_deferred:
                lease.fail(exc)
            raise

    async def _generate_custom_bars(
        self,
        decomp: IntervalDecomposition,
        grouped: dict[tuple[str, str, str, str], list[FetchedBar]],
        source_windows: list[BackfillTask],
        *, confirmed_empty: bool = False, binding_check=None,
    ) -> tuple[int, int, list[dict[str, Any]], list[WrittenRange]]:
        """Reduce canonical source windows after any fetched rows have committed."""
        target = decomp.custom_interval
        component_intervals = {component.interval for component in decomp.components}
        by_target: dict[tuple[str, str, str], list[tuple[str, int, int, KlineSeriesIdentity | None]]] = {}
        local_sources = set()
        for task in source_windows:
            if task.metadata.get("custom_interval") == target:
                key = (task.exchange, task.market_type, task.symbol)
                local_sources.add((*key, task.interval))
                by_target.setdefault(key, []).append((task.interval, task.start_ms, task.end_ms, None))

        for (exchange, market_type, symbol, interval), bars in grouped.items():
            if interval not in component_intervals or not bars or (exchange, market_type, symbol, interval) in local_sources:
                continue
            identity = bars[0].series_identity
            if identity is not None and not identity.is_legacy_default_for(exchange):
                continue
            windows = by_target.setdefault((exchange, market_type, symbol), [])
            # Keep distant fetched spans separate so they never load untouched history.
            first = bars[0]
            for previous, bar in pairwise(bars):
                if bar.open_time != previous.close_time + 1:
                    windows.append((interval, first.open_time, previous.open_time, identity))
                    first = bar
            windows.append((interval, first.open_time, bars[-1].open_time, identity))

        generated = written = 0
        failures: list[dict[str, Any]] = []
        written_ranges: list[WrittenRange] = []
        for (exchange, market_type, symbol), windows in by_target.items():
            policy = getattr(decomp, "composition_policy", None)
            expected = None
            rejected_windows = False
            if policy is not None:
                from .mixed_plan import checked_mixed_windows, MAX_TARGETS
                if not callable(binding_check):
                    raise StaleAcquisition("mixed materialization has no owner binding fence")
                binding_check()
                if not self._cfg.mixed_custom_history or self._custom_aggregator is not None:
                    raise StaleAcquisition("mixed materialization rollout or reducer binding changed")
                bounds = decomp.composition_target_range
                spec = parse_interval_spec(target)
                if (not isinstance(bounds, tuple) or len(bounds) != 2 or spec is None
                        or any(type(v) is not int for v in bounds)
                        or not 0 <= bounds[0] < bounds[1]
                        or spec.floor_ms(bounds[0]) != bounds[0] or spec.floor_ms(bounds[1]) != bounds[1]
                        or (bounds[1] - bounds[0]) // spec.nominal_ms > MAX_TARGETS):
                    raise StaleAcquisition("mixed materialization target range is invalid")
                expected = set(range(*bounds, spec.nominal_ms))
                checked = await checked_mixed_windows(self._storage,
                    SeriesKey(symbol, target, exchange=exchange, market_type=market_type), policy, windows)
                rejected_windows = len(checked) != len(windows)
                windows = checked
            canonical_rows = {}
            observed_rows = 0
            for interval, start_ms, end_ms, identity in windows:
                rows = await self._read_component_window(
                    symbol, interval, start_ms, end_ms, exchange, market_type, identity,
                    **({"bounded": True} if policy is not None else {}),
                )
                observed_rows += len(rows)
                canonical_rows.update({(interval, row["open_time"]): row for row in rows
                                       if policy is None or source_is_trusted_final(row.get("source"))})
                if policy is not None:
                    from .mixed_plan import MAX_SOURCE_ROWS
                    if observed_rows > MAX_SOURCE_ROWS or len(canonical_rows) > MAX_SOURCE_ROWS:
                        raise StaleAcquisition("mixed canonical inputs exceed their planned row budget")

            custom_bars = await run_preparation(
                self._reduce_custom_rows, list(canonical_rows.values()), symbol, target,
                exchange, market_type, int(time.time() * 1000),
            )
            if policy is not None:
                core = {"open", "high", "low", "close", "volume"}
                enhanced = frozenset(policy.fields) - core
                custom_bars = [bar for bar in custom_bars
                               if bar.open_time in expected and enhanced <= bar.enhanced_fields]
                missing = expected - {bar.open_time for bar in custom_bars}
                if missing and not (confirmed_empty and observed_rows == 0 and not rejected_windows):
                    failures.append(dict(exchange=exchange, market_type=market_type, symbol=symbol,
                        interval=target, phase="mixed_coverage", write_error=False,
                        error=f"{len(missing)} target buckets lack trusted composition fields/coverage; replan from canonical inputs"))
            if policy is not None:
                binding_check()
            generated += len(custom_bars)
            count, write_failures, ranges = await self._write_custom_materialization(
                exchange=exchange, market_type=market_type, symbol=symbol,
                interval=target, bars=custom_bars, phase="custom",
            )
            written += count
            failures.extend(write_failures)
            written_ranges.extend(ranges)

        return generated, written, failures, written_ranges

    async def _read_component_window(
        self, symbol: str, interval: str, start_ms: int, end_ms: int,
        exchange: str, market_type: str, identity: KlineSeriesIdentity | None,
        *, bounded: bool = False,
    ) -> list[dict]:
        if bounded:
            from .mixed_plan import MAX_SOURCE_ROWS
            rows, cursor = [], start_ms
            while cursor <= end_ms:
                page = await self._storage.query_canonical_page(symbol, interval, cursor, end_ms, limit=256,
                    exchange=exchange, market_type=market_type, **_identity_kwargs(identity))
                self._metrics.inc("custom_canonical_input_reads")
                self._metrics.inc("custom_canonical_input_rows", len(page))
                times = [row.get("open_time") for row in page]
                if (len(page) > 256 or any(type(t) is not int or not cursor <= t <= end_ms for t in times)
                        or any(a >= b for a, b in pairwise(times)) or len(rows) + len(page) > MAX_SOURCE_ROWS):
                    raise StaleAcquisition("mixed canonical page violates its bounded read contract")
                rows.extend(page)
                if len(page) < 256:
                    break
                cursor = times[-1] + 1
        else:
            rows = await self._storage.query_time_range(
                symbol, interval, start_ms, end_ms, exchange=exchange, market_type=market_type,
                **_identity_kwargs(identity),
            )
            self._metrics.inc("custom_canonical_input_reads")
            self._metrics.inc("custom_canonical_input_rows", len(rows))
        return [
            row if row.get("interval") == interval else {**row, "interval": interval}
            for row in rows if bounded or source_is_trusted_final(row.get("source"))
        ]

    @staticmethod
    def _standard_written_ranges(written: WrittenRange, batch: list[FetchedBar]) -> list[WrittenRange]:
        if (written.exchange != "bybit" or written.phase != "standard"
                or written.bars_written != len(batch)):
            return [written]
        spec = parse_interval_spec(written.interval)
        if spec is None:
            return [written]
        # A resumed batch may straddle already committed receipt ranges.
        # Publish only actual writes, leaving intervening opens untouched.
        opens = sorted(bar.open_time for bar in batch)
        first = previous = opens[0]
        count = 1
        ranges = []
        for opened in opens[1:]:
            if opened != spec.next_ms(previous):
                ranges.append(replace(written, start_ms=first, end_ms=previous, bars_written=count))
                first, count = opened, 0
            previous = opened
            count += 1
        ranges.append(replace(written, start_ms=first, end_ms=previous, bars_written=count))
        return ranges

    @staticmethod
    def _written_range_from_batch(
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        batch: list[FetchedBar],
        bars_written: int,
        source: str,
        phase: str,
    ) -> WrittenRange | None:
        if bars_written <= 0 or not batch:
            return None
        open_times = [bar.open_time for bar in batch]
        return WrittenRange(
            symbol=symbol,
            interval=interval,
            exchange=exchange,
            market_type=market_type,
            start_ms=min(open_times),
            end_ms=max(open_times),
            bars_written=bars_written,
            source=source,
            phase=phase,
        )

    @staticmethod
    def _write_failure_detail(
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        batch: list[FetchedBar],
        error: Exception,
        phase: str,
    ) -> dict[str, Any]:
        open_times = [bar.open_time for bar in batch]
        return {
            "exchange": exchange,
            "market_type": market_type,
            "symbol": symbol,
            "interval": interval,
            "phase": phase,
            "batch_size": len(batch),
            "start_ms": min(open_times) if open_times else None,
            "end_ms": max(open_times) if open_times else None,
            "error": str(error),
        }

    @staticmethod
    def _record_write_failures(
        result: ReconcileResult,
        failures: list[dict[str, Any]],
    ) -> None:
        if not failures:
            return
        writes = [failure for failure in failures if failure.get("write_error", True)]
        result.write_errors += len(writes)
        result.failed_batches.extend(writes)
        for failure in failures:
            prefix = "Write batch failed for " if failure.get("write_error", True) else "History coverage incomplete for "
            result.errors.append(
                prefix +
                f"{failure['exchange']}:{failure['market_type']}:"
                f"{failure['symbol']}@{failure['interval']} "
                f"({failure['phase']}): {failure['error']}"
            )

    def _reduce_custom_rows(
        self,
        rows: list[dict],
        symbol: str,
        interval: str,
        exchange: str,
        market_type: str,
        now_ms: int,
    ) -> list[FetchedBar]:
        rebuilt = aggregate_kline_rows(
            rows, target_interval=interval, source_interval=None, now_ms=now_ms,
        )
        if self._custom_aggregator is None:
            return [
                self._fetched_from_row(row, symbol, interval, exchange, market_type, "backfill_aggregated")
                for row in rebuilt
            ]

        target = parse_interval_spec(interval)
        assert target is not None
        components: dict[int, list[dict]] = {}
        for row in rows:
            components.setdefault(target.floor_ms(int(row["open_time"])), []).append(row)
        result = []
        for row in rebuilt:
            start, end = row["open_time"], row["close_time"]
            bucket = [
                self._fetched_from_row(item, symbol, item["interval"], exchange, market_type, item["source"])
                for item in sorted(components[start], key=lambda item: item["open_time"])
            ]
            bar = self._custom_aggregator(bucket, symbol, interval, start, end)
            if bar is not None and (
                bar.symbol, bar.interval, bar.exchange, bar.market_type, bar.open_time, bar.close_time
            ) == (symbol, interval, exchange, market_type, start, end) and valid_ohlcv(
                (bar.open, bar.high, bar.low, bar.close, bar.volume)
            ):
                result.append(bar)
        return result

    @staticmethod
    def _fetched_from_row(row, symbol, interval, exchange, market_type, source) -> FetchedBar:
        enhanced = ("quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
        return FetchedBar(
            symbol=symbol, interval=interval, exchange=exchange, market_type=market_type,
            open_time=int(row["open_time"]), close_time=int(row["close_time"]),
            open=float(row["open"]), high=float(row["high"]), low=float(row["low"]),
            close=float(row["close"]), volume=float(row["volume"]), source=source,
            quote_volume=float(row.get("quote_volume") or 0),
            trades=int(row.get("trades") or 0),
            taker_buy_base=float(row.get("taker_buy_base") or 0),
            taker_buy_quote=float(row.get("taker_buy_quote") or 0),
            enhanced_fields=frozenset(field for field in enhanced if row.get(field) is not None),
        )

    # ── Internal: Cache push ─────────────────────────────────

    async def _push_to_cache(
        self,
        grouped: dict[tuple[str, str, str, str], list[FetchedBar]],
    ) -> int:
        """Push recent bars to the cache backend."""
        if self._cache is None:
            return 0

        now_ms = int(time.time() * 1000)
        window = self._cfg.reconcile_cache_window_ms
        cutoff = now_ms - window
        total_cached = 0

        for (exchange, market_type, symbol, interval), bars in grouped.items():
            recent = [b for b in bars if b.open_time >= cutoff]
            if not recent:
                continue
            try:
                dicts = [b.to_lightweight() for b in recent]
                try:
                    n = await self._cache.push_bars(
                        symbol, interval, dicts, exchange=exchange, market_type=market_type,
                    )
                except TypeError:
                    n = await self._cache.push_bars(symbol, interval, dicts)
                total_cached += n
            except Exception as exc:
                logger.warning(
                    "Cache push failed for %s:%s@%s: %s",
                    market_type,
                    symbol,
                    interval,
                    exc,
                )
                self._metrics.inc("cache_push_errors")

        self._metrics.inc("bars_cached", total_cached)
        return total_cached

    # ── Internal: Callbacks ──────────────────────────────────

    async def _fire_write_batch(
        self, symbol: str, interval: str, count: int,
    ) -> None:
        for cb in self._write_batch_callbacks:
            try:
                await cb(symbol, interval, count)
            except Exception as exc:
                logger.error("Write batch callback error: %s", exc)
