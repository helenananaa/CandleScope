"""Bounded REST-page acceptance with explicit no-payload completion receipts.

One bit per admitted source slot, scalar progress and bounded diagnostics;
the awaited consumer owns persistence/backpressure. No queue or second writer.
"""
from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size
from app.data_engine.series_identity import identity_from_metadata
from .models import BackfillStatus, FetchReceipt, FetchResult
from .models import ReconcileResult
from dataclasses import replace
import time
from app.exchanges.rate_limits import RateLimitDeferred

MAX_SLOTS = 100_000
MAX_PAGE_ROWS = 1000
PAGE_BYTES_PER_ROW = 8192


class StreamBackfillDeferred(RateLimitDeferred):
    """Existing quota deferral plus already committed, payload-free progress."""
    def __init__(self, deferred, result):
        super().__init__(deferred.admission)
        self.reconcile_result = result


class StreamReconcile:
    MAX_RANGES = 4096

    def __init__(self):
        self.result = ReconcileResult()
        self.pages = self.error_count = self.failure_count = self.clipped_ranges = 0
        self.failure_details_clipped = False

    def add(self, part):
        total = self.result
        for name in ('bars_received','bars_written','bars_skipped','bars_deduplicated',
                     'custom_bars_generated','custom_bars_written','bars_cached','write_errors',
                     'archive_objects_imported','archive_dependent_rows_invalidated','elapsed_ms'):
            setattr(total, name, getattr(total,name)+getattr(part,name))
        self.error_count += len(part.errors)
        self.failure_count += len(part.failed_batches)
        total.errors.extend(str(error)[:500] for error in part.errors[:max(0,20-len(total.errors))])
        for failure in part.failed_batches[:max(0,20-len(total.failed_batches))]:
            bounded = {}
            if len(failure) > 32:
                self.failure_details_clipped = True
            for key,value in list(failure.items())[:32]:
                if isinstance(value,str):
                    self.failure_details_clipped |= len(value) > 500
                    value = value[:500]
                elif type(value) not in (int,bool,float,type(None)):
                    self.failure_details_clipped = True
                    value = '<'+type(value).__name__[:64]+'>'
                bounded[str(key)[:100]] = value
            total.failed_batches.append(bounded)
        ranges = sorted([*total.written_ranges, *part.written_ranges], key=lambda r:(
            r.exchange,r.market_type,r.symbol,r.interval,r.source,r.phase,r.start_ms))
        merged = []
        for item in ranges:
            previous = merged[-1] if merged else None
            spec = parse_interval_spec(item.interval)
            if (previous is not None and spec is not None
                    and (previous.exchange,previous.market_type,previous.symbol,previous.interval,previous.source,previous.phase)
                    == (item.exchange,item.market_type,item.symbol,item.interval,item.source,item.phase)
                    and item.start_ms <= spec.next_ms(previous.end_ms)):
                merged[-1] = replace(previous,end_ms=max(previous.end_ms,item.end_ms),
                                     bars_written=previous.bars_written+item.bars_written)
            else:
                merged.append(item)
        total.written_ranges = merged[:self.MAX_RANGES]
        self.clipped_ranges += max(0,len(merged)-self.MAX_RANGES)
        if self.clipped_ranges:
            if 'stream_output_range_budget_exhausted' not in total.errors:
                total.errors.append('stream_output_range_budget_exhausted')
                self.error_count += 1
            raise MemoryBudgetExceeded('stream output range budget exhausted; committed rows remain canonical')

    def snapshot(self):
        return dict(native_pages=self.pages, error_count=self.error_count,
            failed_batch_count=self.failure_count, clipped_ranges=self.clipped_ranges,
            failure_details_clipped=self.failure_details_clipped,
            errors_truncated=self.error_count > len(self.result.errors),
            failed_batches_truncated=self.failure_count > len(self.result.failed_batches))


def stream_grid(task, batch_size):
    spec = parse_interval_spec(task.interval)
    identity = identity_from_metadata(task.exchange, task.metadata)
    if (task.exchange not in {'binance', 'okx'} or spec is None
            or spec.alignment is not IntervalAlignment.FIXED_EPOCH or spec.phase_ms
            or not 60_000 <= spec.nominal_ms <= 86_400_000
            or any(type(t) is not int for t in (task.start_ms, task.end_ms))
            or not 0 <= task.start_ms <= task.end_ms
            or task.start_ms % spec.nominal_ms or task.end_ms % spec.nominal_ms
            or type(batch_size) is not int or not 1 <= batch_size <= MAX_PAGE_ROWS
            or (identity is not None and not identity.is_legacy_default_for(task.exchange))):
        return None
    slots = (task.end_ms-task.start_ms) // spec.nominal_ms+1
    return (spec.nominal_ms, slots) if slots <= MAX_SLOTS else None


def stream_plan(plan, batch_size):
    """Preserve task-order precedence unless each source span is disjoint."""
    if not 0 < len(plan.tasks) <= 128:
        return False
    if plan.custom_intervals and (not plan.derived_source_windows or any(
            getattr(decomp,'composition_policy',None) is None for decomp in plan.decompositions)):
        return False
    for task in plan.tasks:
        if stream_grid(task,batch_size) is None:
            return False
    return disjoint_source_spans(plan.tasks)


def disjoint_source_spans(tasks):
    grouped = {}
    for task in tasks:
        grouped.setdefault((task.exchange,task.market_type,task.symbol,task.interval),[]).append((task.start_ms,task.end_ms))
    return all(all(a[1] < b[0] for a,b in zip(sorted(spans),sorted(spans)[1:])) for spans in grouped.values())


class PageConsumer:
    def __init__(self, task, batch_size, consume):
        width, slots = stream_grid(task, batch_size)
        self.task, self.width, self.consume = task, width, consume
        self.batch_size = batch_size
        self.seen = bytearray((slots+7)//8)
        self.raw_count = self.count = self.error_count = 0
        self.ack_elapsed_ns = 0
        self.first = None
        self.sources = set()
        self.errors = []

    def absorb_errors(self, errors):
        self.error_count += len(errors)
        self.errors.extend(str(error)[:500] for error in errors[:max(0, 20-len(self.errors))])

    async def accept(self, bars):
        if len(bars) > self.batch_size:
            raise ValueError('REST page exceeds its admitted row bound')
        if retained_size((bars,))[0] > self.batch_size*PAGE_BYTES_PER_ROW:
            raise MemoryBudgetExceeded('REST page exceeds its admitted payload allowance')
        self.raw_count += len(bars)
        selected = []
        task = self.task
        for bar in bars:
            if ((bar.exchange, bar.market_type, bar.symbol, bar.interval)
                    != (task.exchange, task.market_type, task.symbol, task.interval)
                    or (bar.series_identity is not None
                        and not bar.series_identity.is_legacy_default_for(task.exchange))
                    or type(bar.open_time) is not int or bar.open_time % self.width
                    or bar.close_time+1 != bar.open_time+self.width):
                raise ValueError('REST page differs from its admitted source/grid')
            if not task.start_ms <= bar.open_time <= task.end_ms:
                continue
            slot = (bar.open_time-task.start_ms)//self.width
            byte, bit = slot//8, 1 << (slot % 8)
            if self.seen[byte] & bit:
                continue
            self.seen[byte] |= bit
            selected.append(bar)
            self.count += 1
            self.first = bar.open_time if self.first is None else min(self.first, bar.open_time)
            self.sources.add(bar.source)
        if len(self.sources) > 16:
            raise ValueError('REST page has an unbounded source set')
        if selected:
            selected.sort(key=lambda bar: bar.open_time)
            started = time.perf_counter_ns()
            try:
                await self.consume(FetchResult(task=task, bars=selected))
            finally:
                self.ack_elapsed_ns += time.perf_counter_ns()-started

    def finish(self, *, errors, pages, elapsed_ms, source_complete, empty_reason):
        self.absorb_errors(errors)
        bad = bool(self.error_count)
        status = (BackfillStatus.PARTIAL if self.count else BackfillStatus.FAILED) if bad else BackfillStatus.COMPLETED
        complete = source_complete and not bad
        return FetchReceipt(task=self.task, bars_count=self.count, status=status,
            elapsed_ms=elapsed_ms, pages_fetched=pages, errors=tuple(self.errors),
            source_complete=complete, exhausted_before_ms=self.first if complete else None,
            empty_reason=empty_reason if complete else None, retryable=bad,
            metadata=dict(history_sources=sorted(self.sources or {'backfill'}),
                history_lane=self.task.metadata.get('history_lane', 'rest'), rest_pages=pages,
                error_count=self.error_count, errors_truncated=self.error_count > len(self.errors),
                page_consumer_elapsed_ms=self.ack_elapsed_ns//1_000_000,
                elapsed_scope='requests_and_page_acknowledgments',
                stream_dedup_bytes=len(self.seen), stream_slots=len(self.seen)*8))
