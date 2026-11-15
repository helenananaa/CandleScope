"""Request work bounds and range-fenced native/mixed adoption under live writes."""
import asyncio
from contextvars import Context
from dataclasses import replace

import pytest

from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.mixed_plan import coalesce_mixed_fetches
from app.data_engine.backfill.models import BackfillTask, BackfillStatus
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.storage import klines_repo
from app.data_engine.storage.revisions import StaleAcquisition
from tests.history_stream_transport import IntervalTransport
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_history_reader import row, MINUTE

WIDTH = 10007 * MINUTE
META = dict(requires_trusted_finality=True, requester='klines_range', history_calendar_id='crypto.24x7.utc')


def task(at):
    return BackfillTask(symbol='BTCUSDT', interval='4h', exchange='binance', market_type='futures',
        start_ms=at, end_ms=at, estimated_bars=1,
        metadata={'history_composition_contract': 'test', 'custom_interval': '10007m'})


def test_read_ahead_reduces_requests_with_a_total_source_bound():
    tasks = [task(i * 42 * 4 * 60 * MINUTE) for i in range(16)]
    merged = coalesce_mixed_fetches(tasks, page_size=1000, row_budget=16384)
    assert len(merged) == 1
    assert merged[0].estimated_bars == 631
    bounded = coalesce_mixed_fetches(tasks, page_size=1000, row_budget=100)
    assert sum(t.estimated_bars for t in bounded) <= 100
    assert len(bounded) > 1
    foreign = replace(tasks[0], market_type='spot')
    other = replace(tasks[0], metadata={**tasks[0].metadata, 'custom_interval': '89m'})
    assert len(coalesce_mixed_fetches([tasks[0], foreign, other], page_size=1000, row_budget=16384)) == 3


def write_elsewhere(query, *, at=100 * WIDTH, interval='1m', width=MINUTE, close=101):
    Context().run(query.storage.upsert_bars, 'BTCUSDT', interval, [{**row(at, width), 'close': close}],
                  source='backfill', market_type='futures')


@pytest.mark.parametrize('moment', ['fetch', 'reduce'])
def test_unrelated_tail_write_does_not_discard_mixed_native_or_target_history(mixed_query, monkeypatch, moment):
    query = mixed_query
    engine = engine_for(query)
    upstream = IntervalTransport()
    cfg = engine.config
    cfg.fetch_binance_futures_rate_limit_delay = 0
    engine._fetcher = HistoricalFetcher(cfg, upstream, IngestionConfig())
    if moment == 'fetch':
        original = upstream.http_fetch
        async def fetch(request):
            write_elsewhere(query)
            return await original(request)
        monkeypatch.setattr(upstream, 'http_fetch', fetch)
    else:
        original = engine.reconciler._stream_component_windows
        async def reduce(*args, **kwargs):
            values = await original(*args, **kwargs)
            write_elsewhere(query)
            return values
        monkeypatch.setattr(engine.reconciler, '_stream_component_windows', reduce)
    report = asyncio.run(engine.run('BTCUSDT', intervals=['10007m'], range_start_ms=0,
        range_end_ms=3*WIDTH, exchange='binance', market_type='futures', metadata=META))
    assert report.status == BackfillStatus.COMPLETED, report.errors
    assert report.reconcile_result.custom_bars_written == 4
    bars = query.storage.query_bars('BTCUSDT', '10007m', start_ms=0, end_ms=4*WIDTH-1, market_type='futures')
    assert len(bars) == 4 and all(b['volume'] == 10007 and b['trades'] == 10007 for b in bars)
    assert any(call.limit < 100 for call in upstream.calls)


@pytest.mark.parametrize('change', ['finer_insert', 'source_correction', 'empty_delete', 'target_write', 'journal_overrun'])
def test_intersecting_change_during_reduction_cannot_publish_stale_targets(mixed_query, monkeypatch, change):
    query = mixed_query
    engine = engine_for(query)
    engine.config.fetch_binance_futures_rate_limit_delay = 0
    engine._fetcher = HistoricalFetcher(engine.config, IntervalTransport(), IngestionConfig())
    original = engine.reconciler._stream_component_windows
    async def reduce(*args, **kwargs):
        values = await original(*args, **kwargs)
        if change == 'finer_insert':
            write_elsewhere(query, at=MINUTE)
        elif change == 'source_correction':
            write_elsewhere(query, at=0, interval='1d', width=1440*MINUTE)
        elif change == 'empty_delete':
            Context().run(query.storage.delete_bars, 'BTCUSDT', '1m', 100*WIDTH, 100*WIDTH, market_type='futures')
        elif change == 'target_write':
            write_elsewhere(query, at=0, interval='10007m', width=WIDTH)
        else:
            for i in range(1030):
                write_elsewhere(query, at=100*WIDTH+i*MINUTE)
        return values
    monkeypatch.setattr(engine.reconciler, '_stream_component_windows', reduce)
    report = asyncio.run(engine.run('BTCUSDT', intervals=['10007m'], range_start_ms=0,
        range_end_ms=0, exchange='binance', market_type='futures', metadata=META))
    assert report.status != BackfillStatus.COMPLETED
    assert report.reconcile_result is None or report.reconcile_result.custom_bars_written == 0


def test_ingestion_and_backfill_share_the_configured_physical_usdm_limit(monkeypatch):
    from app.exchanges.plugins.binance.plugin import BinancePlugin
    from app.exchanges.rate_limits import HistoricalRequest
    monkeypatch.setenv('BACKFILL_FETCH_BINANCE_FUTURES_CONCURRENCY', '3')
    request = HistoricalRequest(exchange='binance', market_type='futures',
        symbol='BTCUSDT', interval='1m', endpoint='/fapi/v1/klines', limit=3)
    for cfg in (IngestionConfig(), BackfillConfig()):
        assert BinancePlugin._rate_limit_policy(cfg).rule_for(request).max_concurrency == 3


def test_local_burst_expires_and_network_work_ends_it():
    from types import SimpleNamespace
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
    unused = lambda *args: None
    scheduler = BackfillScheduler(execute=unused, future_for=unused, complete=unused,
        finalize=unused, on_queued=unused)
    request = RepairRequest('BTCUSDT', '89m', 0, 0, reason='initial_history', requester='chart')
    chunk = SimpleNamespace(request=request, dispatched_at_monotonic=100.0)
    local = SimpleNamespace(status='completed', report=SimpleNamespace(network_free=True))
    scheduler._note_local_burst(chunk, local)
    assert scheduler._continues_local_burst(request, 101.9)
    assert not scheduler._continues_local_burst(request, 102.1)
    scheduler._note_local_burst(chunk, SimpleNamespace(status='completed', report=SimpleNamespace(network_free=False)))
    assert not scheduler._continues_local_burst(request, 101.0)


def test_only_qualified_composed_requests_get_larger_target_chunks():
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
    unused = lambda *args: None
    scheduler = BackfillScheduler(execute=unused, future_for=unused, complete=unused,
        finalize=unused, on_queued=unused)
    request = RepairRequest('BTCUSDT', '10007m', 0, 39*WIDTH, market_type='futures')
    assert scheduler._source_aware_chunk_plan(request, 40).effective_target_bars == 1
    policy = scheduler._interval_resolver.history_composition_routes(
        exchange='binance', market_type='futures', interval='10007m')[0]
    request.metadata['required_history_composition'] = policy.contract_id
    assert scheduler._source_aware_chunk_plan(request, 40).effective_target_bars == 16


def test_calendar_month_request_preserves_exchange_owned_pagination():
    from types import SimpleNamespace
    calls = []
    async def fetch(request):
        calls.append(request)
        return []
    item = replace(task(0), interval='1M', end_ms=90*1440*MINUTE, metadata={})
    cfg = BackfillConfig(history_archive_enabled=False, fetch_binance_futures_rate_limit_delay=0)
    fetcher = HistoricalFetcher(cfg, SimpleNamespace(http_fetch=fetch), IngestionConfig())
    asyncio.run(fetcher.fetch([item]))
    assert len(calls) == 1 and calls[0].limit == cfg.fetch_batch_size


def test_partial_fine_history_is_included_in_multi_target_cost_budget(mixed_query):
    from tests.test_mixed_backfill_plan import propose, gap
    # One complete fine bucket plus fifteen cold buckets. A cheap-HTTP proposal
    # must leave space for the mandatory existing finer canonical inputs.
    mixed_query.storage.upsert_bars('BTCUSDT', '1m',
        [row(at, MINUTE) for at in range(15*WIDTH, 16*WIDTH, MINUTE)],
        source='backfill', market_type='futures')
    plan, report = propose(engine_for(mixed_query), mixed_query, gap(count=16))
    assert plan is not None, report
    assert report['mixed_cold_candidates'] > 0
    assert report['mixed_source_rows'] <= 16384
    assert plan.estimated_requests < 100


@pytest.mark.parametrize('receipt', [False, True])
def test_transport_read_ahead_never_becomes_unrequested_canonical_data(mixed_query, receipt):
    engine = engine_for(mixed_query)
    engine.config.fetch_binance_futures_rate_limit_delay = 0
    upstream = IntervalTransport()
    engine._fetcher = HistoricalFetcher(engine.config, upstream, IngestionConfig())
    run = engine.run_receipt if receipt else engine.run
    report = asyncio.run(run('BTCUSDT', intervals=['10007m'], range_start_ms=0,
        range_end_ms=3*WIDTH, exchange='binance', market_type='futures', metadata=META))
    assert report.status == BackfillStatus.COMPLETED, report.errors
    assert report.reconcile_result.custom_bars_written == 4
    assert any(task.metadata.get('mixed_fetch_windows') for task in report.plan.tasks)
    # The canonical rows are precisely the reduction windows; transport-only
    # holes must not cause derived invalidation or a precedence replan.
    for interval in {task.interval for task in report.plan.tasks}:
        spec = next(component for component in report.plan.decompositions[0].components if component.interval == interval)
        stored = mixed_query.storage.count_bars('BTCUSDT', interval, 0, 4*WIDTH-1, market_type='futures')
        assert stored == spec.count


def test_outside_source_change_before_plan_capture_does_not_restart_planning(mixed_query, monkeypatch):
    from tests.test_mixed_backfill_plan import propose, gap
    engine = engine_for(mixed_query)
    original = engine._storage.count_bars
    async def count(*args, **kwargs):
        result = await original(*args, **kwargs)
        write_elsewhere(mixed_query)
        return result
    monkeypatch.setattr(engine._storage, 'count_bars', count)
    plan, report = propose(engine, mixed_query, gap(count=4))
    assert plan is not None, report


@pytest.mark.parametrize('change', ['outside', 'inside'])
def test_standard_canonical_reducer_uses_its_own_range_proof(mixed_query, monkeypatch, change):
    engine = engine_for(mixed_query)
    engine.config.fetch_binance_futures_rate_limit_delay = 0
    engine._fetcher = HistoricalFetcher(engine.config, IntervalTransport(), IngestionConfig())
    original = engine.reconciler._reduce_custom_rows
    def reduce(*args, **kwargs):
        values = original(*args, **kwargs)
        write_elsewhere(mixed_query, at=100*WIDTH if change == 'outside' else 0, close=100.5)
        return values
    monkeypatch.setattr(engine.reconciler, '_reduce_custom_rows', reduce)
    report = asyncio.run(engine.run('BTCUSDT', intervals=['89m'], range_start_ms=0,
        range_end_ms=3*89*MINUTE, exchange='binance', market_type='futures', metadata=META))
    if change == 'outside':
        assert report.status == BackfillStatus.COMPLETED, report.errors
        assert report.reconcile_result.custom_bars_written == 4
    else:
        assert report.status != BackfillStatus.COMPLETED
        assert report.reconcile_result is None or report.reconcile_result.custom_bars_written == 0


def test_multi_batch_target_write_retains_the_computation_proof(mixed_query):
    engine = engine_for(mixed_query)
    engine.config.fetch_binance_futures_rate_limit_delay = 0
    engine.config.reconcile_write_batch_size = 2
    engine._fetcher = HistoricalFetcher(engine.config, IntervalTransport(), IngestionConfig())
    report = asyncio.run(engine.run('BTCUSDT', intervals=['10007m'], range_start_ms=0,
        range_end_ms=3*WIDTH, exchange='binance', market_type='futures', metadata=META))
    assert report.status == BackfillStatus.COMPLETED, report.errors
    assert report.reconcile_result.custom_bars_written == 4
