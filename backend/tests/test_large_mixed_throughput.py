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
            # This grid is now fetched by the cheaper cover. Change its
            # content rather than issuing an identical, correctly no-op upsert.
            write_elsewhere(query, at=0, interval='1d', width=1440*MINUTE, close=100.5)
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
@pytest.mark.parametrize('local', [False, True])
def test_standard_canonical_reducer_uses_its_own_range_proof(mixed_query, monkeypatch, change, local):
    if local:
        mixed_query.storage.upsert_bars('BTCUSDT', '1m',
            [row(at, MINUTE) for at in range(0, 4*89*MINUTE, MINUTE)], source='backfill', market_type='futures')
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


def test_complete_native_stream_is_selected_before_optional_mixed_work(mixed_query, monkeypatch):
    mixed_query.storage.upsert_bars('BTCUSDT', '1m',
        [row(at, MINUTE) for at in range(0, 2*WIDTH, MINUTE)],
        source='backfill', market_type='futures')
    def forbidden(*args, **kwargs):
        raise AssertionError('complete base history must not enter optional mixed planning')
    monkeypatch.setattr(mixed_query, 'read_mixed_history_blocks', forbidden)
    calls = []
    mixed_query.set_backfill_trigger(lambda *args: calls.append(args))
    result = mixed_query.query('BTCUSDT', '10007m', start_ms=0, end_ms=2*WIDTH-1,
        limit=2, market_type='futures', auto_backfill=True, min_revision=mixed_query.storage.revision_store.head())
    assert result.complete and len(result.bars) == 2 and not calls
    assert all(bar.volume == bar.trades == 10007 for bar in result.bars)


def test_nearly_complete_native_stream_reports_its_actual_hole(mixed_query, monkeypatch):
    mixed_query.storage.upsert_bars('BTCUSDT', '1m',
        [row(at, MINUTE) for at in range(0, 2*WIDTH, MINUTE) if at != 100*MINUTE],
        source='backfill', market_type='futures')
    def forbidden(*args, **kwargs):
        raise AssertionError('one real native hole should use the bounded base route')
    monkeypatch.setattr(mixed_query, 'read_mixed_history_blocks', forbidden)
    calls = []
    mixed_query.set_backfill_trigger(lambda *args: calls.append(args))
    result = mixed_query.query('BTCUSDT', '10007m', start_ms=0, end_ms=2*WIDTH-1,
        limit=2, market_type='futures', auto_backfill=True, min_revision=mixed_query.storage.revision_store.head())
    assert not result.complete and result.retryable and result.missing_ranges
    assert [(gap.interval, gap.start_ms, gap.end_ms) for gap in result.missing_ranges] == [('1m', 100*MINUTE, 100*MINUTE)]


def test_multi_target_source_choice_prices_the_merged_http_envelopes(mixed_query):
    from tests.test_mixed_backfill_plan import propose, gap
    plan, report = propose(engine_for(mixed_query), mixed_query, gap(count=16))
    assert plan is not None, report
    # Counting each boundary independently favored >10k fine rows and roughly
    # 32 requests. The actual envelope cost admits a much smaller coarse cover.
    assert plan.estimated_requests <= 22
    assert report['mixed_source_rows'] < 6000


def test_archive_rest_slices_clip_the_exact_read_ahead_selection():
    from types import SimpleNamespace
    from app.data_engine.backfill.fetcher import _slice_task
    from app.data_engine.backfill.fetch_windows import selected_fetch_rows
    width = 4*60*MINUTE
    item = coalesce_mixed_fetches([task(0), task(420*width)], page_size=1000, row_budget=16384)[0]
    first = _slice_task(item, 0, 100*width, lane='rest_tail')
    assert first.metadata['mixed_fetch_windows'] == [(0, 0)]
    rows = [SimpleNamespace(open_time=at) for at in (0, width, 50*width)]
    assert selected_fetch_rows(first, rows) == [rows[0]]
    empty = _slice_task(item, 100*width, 200*width, lane='rest_fallback')
    assert selected_fetch_rows(empty, rows) == []


def test_partly_materialized_chunk_with_two_gaps_completes_from_canonical_inputs(mixed_query):
    mixed_query.storage.upsert_bars('BTCUSDT', '10007m', [row(2*WIDTH, WIDTH)],
        source='backfill_aggregated', market_type='futures')
    engine = engine_for(mixed_query)
    engine.config.fetch_binance_futures_rate_limit_delay = 0
    engine._fetcher = HistoricalFetcher(engine.config, IntervalTransport(), IngestionConfig())
    metadata = {'history_calendar_id': 'crypto.24x7.utc', 'required_history_composition': 'binance.usdm.trade-klines/base-utc/1'}
    report = asyncio.run(engine.run('BTCUSDT', intervals=['10007m'], range_start_ms=0,
        range_end_ms=3*WIDTH, exchange='binance', market_type='futures', metadata=metadata))
    assert report.status == BackfillStatus.COMPLETED, report.errors
    assert len(report.plan.gaps) == 2
    assert report.reconcile_result.custom_bars_written == 4
    assert mixed_query.storage.count_bars('BTCUSDT', '10007m', 0, 4*WIDTH-1, market_type='futures') == 4


def test_scheduler_refines_work_without_failing_or_replacing_the_parent_owner():
    from app.data_engine.data_manager.backfill_contracts import RepairRequest, RepairOutcome, RepairChunkSplit
    from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
    async def run():
        loop = asyncio.get_running_loop()
        futures, completed = {}, []
        def future(request):
            return futures.setdefault(request.request_id, loop.create_future())
        def complete(request, outcome):
            if not future(request).done(): future(request).set_result(outcome)
        async def execute(request):
            count = (request.end_ms-request.start_ms)//WIDTH+1
            if count > 2: raise RepairChunkSplit('source_row_budget')
            completed.extend(range(request.start_ms, request.end_ms+1, WIDTH))
            return RepairOutcome(request, 'completed', bars_loaded=count, verified_contiguous=True, attempts=1)
        async def noop(*args, **kwargs): pass
        scheduler = BackfillScheduler(execute=execute, future_for=future, complete=complete,
            finalize=noop, on_queued=lambda *_: None, max_concurrency=1)
        request = RepairRequest('BTCUSDT', '10007m', 0, 7*WIDTH, market_type='futures',
            reason='initial_history', metadata={'required_history_composition': 'binance.usdm.trade-klines/base-utc/1'})
        try:
            _, result = scheduler.submit(request)
            outcome = await asyncio.wait_for(result, 5)
            assert outcome.status == 'completed' and outcome.bars_loaded == 8
            assert outcome.request.request_id == request.request_id
            assert sorted(completed) == list(range(0, 8*WIDTH, WIDTH))
            assert scheduler.mixed_chunk_refinements == 3
        finally:
            await scheduler.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize('qualified', [False, True])
def test_dense_fine_history_refines_the_real_coordinator_request(mixed_query, qualified):
    from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    mixed_query.storage.upsert_bars('BTCUSDT', '1m',
        [row(at, MINUTE) for at in range(0, 4*WIDTH, MINUTE)], source='backfill', market_type='futures')
    engine = engine_for(mixed_query)
    upstream = IntervalTransport()
    engine._fetcher = HistoricalFetcher(engine.config, upstream, IngestionConfig())
    async def run():
        async def noop(*args, **kwargs): pass
        coordinator = BackfillCoordinator(storage=mixed_query.storage, engine=engine,
            bars_backfilled=noop, emit_event=noop, loop=asyncio.get_running_loop(), max_concurrency=1, max_retries=1)
        request = RepairRequest('BTCUSDT', '10007m', 0, 3*WIDTH, market_type='futures', reason='initial_history',
            metadata={'acquisition_revision': mixed_query.storage.revision_store.head(), 'history_calendar_id': 'crypto.24x7.utc'})
        if qualified:
            request.metadata['required_history_composition'] = 'binance.usdm.trade-klines/base-utc/1'
        try:
            outcome = await asyncio.wait_for(coordinator.request_and_wait(request), 30)
            assert outcome.verified_contiguous is True, outcome.error
            assert coordinator.snapshot()['mixed_chunk_refinements'] == 3
            assert not upstream.calls
        finally:
            await coordinator.shutdown()
    asyncio.run(run())
    assert mixed_query.storage.count_bars('BTCUSDT', '10007m', 0, 4*WIDTH-1, market_type='futures') == 4


@pytest.mark.parametrize('excluded', ['disabled', 'custom_reducer', 'custom_mapping', 'shifted_epoch',
                                    'foreign_calendar', 'small_target', 'explicit_contract', 'forming'])
def test_automatic_large_repair_qualification_preserves_other_contracts(mixed_query, excluded):
    from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    engine = engine_for(mixed_query)
    async def noop(*args, **kwargs): pass
    coordinator = BackfillCoordinator(storage=mixed_query.storage, engine=engine,
        bars_backfilled=noop, emit_event=noop)
    request = RepairRequest('BTCUSDT', '10007m', 0, 0, market_type='futures',
        metadata={'history_calendar_id': 'crypto.24x7.utc'})
    if excluded == 'disabled': engine.config.mixed_custom_history = False
    elif excluded == 'custom_reducer': engine.reconciler._custom_aggregator = lambda *args: []
    elif excluded == 'custom_mapping': engine.planner._interval_mappings['10007m'] = []
    elif excluded == 'shifted_epoch': engine.config.alignment_epoch_ms = 1
    elif excluded == 'foreign_calendar': request.metadata['history_calendar_id'] = 'other'
    elif excluded == 'small_target': request.interval = '89m'
    elif excluded == 'explicit_contract': request.metadata['required_history_composition'] = 'caller-contract'
    elif excluded == 'forming':
        import time
        request.end_ms = int(time.time()*1000)
    before = dict(request.metadata)
    coordinator._qualify_large_history_repair(request)
    assert request.metadata == before

@pytest.mark.parametrize('interval', ['89m', '97m', '101m'])
def test_large_prime_viewport_qualification_uses_page_source_cost(mixed_query, interval):
    from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
    from app.data_engine.interval_policy import parse_interval_spec
    engine = engine_for(mixed_query)
    async def noop(*args, **kwargs): pass
    coordinator = BackfillCoordinator(storage=mixed_query.storage, engine=engine,
        bars_backfilled=noop, emit_event=noop)
    width = parse_interval_spec(interval).nominal_ms
    request = RepairRequest('BTCUSDT', interval, 0, 127 * width, market_type='futures',
        metadata={'history_calendar_id': 'crypto.24x7.utc'})
    unused = lambda *args: None
    scheduler = BackfillScheduler(execute=unused, future_for=unused, complete=unused,
        finalize=unused, on_queued=unused)
    before = scheduler._source_aware_chunk_plan(request, 128).effective_target_bars
    coordinator._qualify_large_history_repair(request)
    assert request.metadata.get('bounded_history_batch_contract') == 'binance.usdm.trade-klines/base-utc/1'
    assert 'required_history_composition' not in request.metadata
    plan = scheduler._source_aware_chunk_plan(request, 128)
    assert plan.effective_target_bars == 16 and plan.effective_target_bars > before
    assert plan.planned_source_rows <= (16 + 3) * (width // MINUTE)

def test_qualified_short_period_keeps_larger_ordinary_batch():
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
    unused = lambda *args: None
    scheduler = BackfillScheduler(execute=unused, future_for=unused, complete=unused,
        finalize=unused, on_queued=unused)
    request = RepairRequest('BTCUSDT', '7m', 0, 127*7*MINUTE, market_type='futures',
        metadata={'required_history_composition': 'binance.usdm.trade-klines/base-utc/1'})
    assert scheduler._source_aware_chunk_plan(request, 128).effective_target_bars == 128

@pytest.mark.parametrize('interval,minutes', [('89m', 89), ('97m', 97), ('101m', 101)])
def test_qualified_prime_page_preserves_all_canonical_fields(mixed_query, interval, minutes):
    from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    engine = engine_for(mixed_query)
    upstream = IntervalTransport()
    engine._fetcher = HistoricalFetcher(engine.config, upstream, IngestionConfig())
    width = minutes * MINUTE
    async def run():
        async def noop(*args, **kwargs): pass
        coordinator = BackfillCoordinator(storage=mixed_query.storage, engine=engine,
            bars_backfilled=noop, emit_event=noop, loop=asyncio.get_running_loop(), max_concurrency=1, max_retries=1)
        request = RepairRequest('BTCUSDT', interval, 0, 15*width, market_type='futures', reason='initial_history',
            metadata={'history_calendar_id': 'crypto.24x7.utc'})
        try:
            result = await asyncio.wait_for(coordinator.request_and_wait(request), 30)
            assert result.verified_contiguous is True, result.error
        finally:
            await coordinator.shutdown()
    asyncio.run(run())
    bars = mixed_query.storage.query_bars('BTCUSDT', interval, 0, 16*width-1, market_type='futures')
    assert len(bars) == 16
    for bar in bars:
        assert (bar['open'], bar['high'], bar['low'], bar['close'], bar['volume'], bar['quote_volume'],
                bar['trades'], bar['taker_buy_base'], bar['taker_buy_quote']) == (
                    100, 102, 99, 101, minutes, 2*minutes, minutes, minutes, 2*minutes)

@pytest.mark.parametrize('field', ['required_history_composition', 'bounded_history_batch_contract'])
@pytest.mark.parametrize('value', ['unknown-contract', {}, []])
def test_invalid_batch_contract_cannot_bypass_source_sizing(field, value):
    from app.data_engine.data_manager.backfill_contracts import RepairRequest
    from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
    unused = lambda *args: None
    scheduler = BackfillScheduler(execute=unused, future_for=unused, complete=unused,
        finalize=unused, on_queued=unused)
    request = RepairRequest('BTCUSDT', '89m', 0, 127*89*MINUTE, market_type='futures', metadata={field: value})
    plan = scheduler._source_aware_chunk_plan(request, 128)
    assert plan.source_factor == 89 and 0 < plan.effective_target_bars < 16
