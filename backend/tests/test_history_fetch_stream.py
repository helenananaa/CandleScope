"""Explicit paged consumption preserves the ordinary full-result API."""
import asyncio
import gc
from dataclasses import replace

import pytest

from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.fetch_stream import PageConsumer, stream_grid
from app.data_engine.backfill.models import BackfillStatus, BackfillTask, FetchedBar, FetchReceipt, FetchResult
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.memory_budget import MemoryBudget, MemoryBudgetExceeded, retained_size
from tests.test_binance_backfill_fetcher import _FakeBinanceTransport, _make_binance_rows


def make(count=1100, batch=64, max_total=100_000):
    transport = _FakeBinanceTransport(_make_binance_rows(count, 60_000), page_cap=batch)
    fetcher = HistoricalFetcher(BackfillConfig(fetch_batch_size=batch,
        fetch_rate_limit_delay=0, fetch_concurrency=1, fetch_max_total_bars=max_total),
        transport, IngestionConfig())
    task = BackfillTask('STREAMUSDT', '1m', 0, (max(count, 1)-1)*60_000,
                        estimated_bars=count)
    return fetcher, transport, task


def budget(limit=2_000_000):
    value = MemoryBudget(limit)
    value.register('history-backfill', limit_bytes=limit, usage=lambda:dict(estimated_bytes=0))
    return value


def test_explicit_stream_releases_prior_pages_and_preserves_counts_and_values():
    fetcher, transport, task = make()
    observed, page_sizes, live = [], [], []
    async def consume(page):
        page_sizes.append(len(page.bars))
        observed.extend((bar.open_time,bar.volume) for bar in page.bars)
        live.append(sum(isinstance(item, FetchedBar) and item.symbol == task.symbol
                        for item in gc.get_objects()))
    async def check():
        receipt, = await fetcher.fetch([task], on_native_page=consume)
        assert isinstance(receipt, FetchReceipt) and not hasattr(receipt, 'bars')
        assert receipt.bars_count == 1100 and receipt.status == BackfillStatus.COMPLETED
        assert max(page_sizes) == 64 and max(live) <= 65
        assert receipt.metadata['stream_dedup_bytes'] == 138
        assert retained_size((receipt,))[0] < 16_384
        full, = await fetcher.fetch([task])
        assert isinstance(full, FetchResult) and len(full.bars) == full.bars_count == 1100
        assert observed == [(bar.open_time,bar.volume) for bar in full.bars]
        assert full.to_dict()['bars_count'] == receipt.to_dict()['bars_count']
        assert 'payload_kind' not in full.to_dict() and receipt.to_dict()['payload_kind'] == 'receipt'
    asyncio.run(check())


@pytest.mark.parametrize('cancel', [False, True])
def test_page_consumer_applies_backpressure_and_cancellation_releases_admission(cancel):
    fetcher, transport, task = make(count=130)
    fetcher.memory_budget = budget()
    async def check():
        entered, released = asyncio.Event(), asyncio.Event()
        async def consume(page):
            if len(transport.requests) == 1:
                entered.set()
                await released.wait()
        pending = asyncio.create_task(fetcher.fetch([task], on_native_page=consume))
        await asyncio.wait_for(entered.wait(), 5)
        assert len(transport.requests) == 1
        assert fetcher.memory_budget.snapshot()['reserved_bytes'] >= 64*8192
        if cancel:
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert len(transport.requests) == 1
        else:
            released.set()
            receipt, = await pending
            assert receipt.bars_count == 130 and len(transport.requests) == 3
        assert fetcher.memory_budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(check())


def test_budget_admission_fails_before_the_first_physical_request():
    fetcher, transport, task = make()
    fetcher.memory_budget = budget(1000)
    async def consume(_page):
        pytest.fail('unadmitted page')
    result, = asyncio.run(fetcher.fetch([task], on_native_page=consume))
    assert result.status == BackfillStatus.FAILED and result.errors
    assert not transport.requests and fetcher.memory_budget.snapshot()['reserved_bytes'] == 0


def test_work_cap_is_partial_not_source_exhaustion_and_requests_only_remaining_work():
    fetcher, transport, task = make(count=10, batch=2, max_total=3)
    received = []
    async def consume(page): received.extend(bar.open_time for bar in page.bars)
    result, = asyncio.run(fetcher.fetch([task], on_native_page=consume))
    assert isinstance(result, FetchReceipt) and result.bars_count == 3
    assert result.status == BackfillStatus.PARTIAL and result.retryable
    assert not result.source_complete and result.exhausted_before_ms is None
    assert 'fetch_work_budget_exhausted' in result.errors
    assert received == [0,60_000,120_000]
    assert [req.limit for req in transport.requests] == [2,1]


def test_consumer_error_stops_before_another_page_and_keeps_fetched_count():
    fetcher, transport, task = make(count=200)
    async def consume(_page): raise RuntimeError('controlled write failure')
    result, = asyncio.run(fetcher.fetch([task], on_native_page=consume))
    assert isinstance(result, FetchReceipt) and result.bars_count == 64
    assert result.status == BackfillStatus.PARTIAL and result.retryable
    assert len(transport.requests) == 1 and not result.source_complete
    assert 'controlled write failure' in result.errors[0]


def test_empty_success_and_unusable_payload_remain_distinct():
    fetcher, _transport, task = make(count=0)
    async def consume(_page): pytest.fail('empty source has no page')
    result, = asyncio.run(fetcher.fetch([task], on_native_page=consume))
    assert result.bars_count == 0 and result.source_complete and result.empty_reason == 'source_empty'
    assert not result.retryable


def test_bounded_seen_grid_handles_old_hole_fill_and_first_fetch_precedence():
    _fetcher, _transport, task = make(count=10)
    kept = []
    def bar(index, volume=1):
        return FetchedBar(task.symbol,task.interval,index*60_000,(index+1)*60_000-1,
                          1,2,0,1,volume)
    async def consume(page): kept.extend((b.open_time,b.volume) for b in page.bars)
    collector = PageConsumer(task,4,consume)
    async def check():
        await collector.accept([bar(4),bar(0)])
        await collector.accept([bar(1),bar(4,99),bar(5)])
        await collector.accept([bar(0,99),bar(2),bar(3)])
    asyncio.run(check())
    assert kept == [(0,1),(240_000,1),(60_000,1),(300_000,1),(120_000,1),(180_000,1)]
    assert collector.count == 6 and len(collector.seen) == 2


@pytest.mark.parametrize('variant', ['foreign', 'off_grid', 'cross_close', 'too_many'])
def test_malformed_page_does_not_reach_the_consumer(variant):
    _fetcher, _transport, task = make(count=10)
    base = FetchedBar(task.symbol,task.interval,0,59_999,1,2,0,1,1)
    rows = [base]
    if variant == 'foreign': rows = [replace(base,symbol='OTHER')]
    if variant == 'off_grid': rows = [replace(base,open_time=1)]
    if variant == 'cross_close': rows = [replace(base,close_time=60_000)]
    if variant == 'too_many': rows *= 5
    async def consume(_page): pytest.fail('malformed page')
    with pytest.raises(ValueError): asyncio.run(PageConsumer(task,4,consume).accept(rows))


def test_unqualified_grid_has_no_streaming_admission():
    _,_,task = make()
    for value in [replace(task,exchange='bybit'), replace(task,interval='1M'),
                  replace(task,end_ms=100_000*60_000), replace(task,start_ms=1)]:
        assert stream_grid(value,64) is None


def test_overlapping_source_tasks_keep_batch_precedence_instead_of_streaming_competing_writes():
    fetcher,transport,task = make(count=130)
    fallback = []
    async def consume(_page): pytest.fail('overlapping tasks require the full precedence path')
    values = asyncio.run(fetcher.fetch([task,replace(task,start_ms=60_000)],
        on_native_page=consume,on_full_task=lambda task:fallback.append(task.task_key)))
    assert len(fallback) == 2 and all(isinstance(item,FetchResult) for item in values)
    assert [item.bars_count for item in values] == [130,129]


def test_output_ranges_and_failure_details_are_bounded_and_clipping_is_explicit(monkeypatch):
    from app.data_engine.backfill.fetch_stream import StreamReconcile
    from app.data_engine.backfill.models import ReconcileResult,WrittenRange
    aggregate = StreamReconcile()
    monkeypatch.setattr(aggregate,'MAX_RANGES',3)
    aggregate.add(ReconcileResult(bars_written=3,written_ranges=[
        WrittenRange('STREAMUSDT','1m',i*120_000,i*120_000,1) for i in range(3)],
        failed_batches=[{'error':'x'*10000,'unexpected':object()}]))
    assert len(aggregate.result.failed_batches[0]['error']) == 500
    assert aggregate.snapshot()['failure_details_clipped']
    with pytest.raises(MemoryBudgetExceeded):
        aggregate.add(ReconcileResult(bars_written=1,written_ranges=[
            WrittenRange('STREAMUSDT','1m',600_000,600_000,1)]))
    assert len(aggregate.result.written_ranges) == 3
    assert aggregate.result.bars_written == 4
    assert aggregate.snapshot()['clipped_ranges'] == 1
