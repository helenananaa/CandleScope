"""Composed-history permissions through real DM, HTTP and the old scheduler."""
import asyncio
import sys
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.klines as api
from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.history.cover_plan import CoverBudgetExceeded
from app.data_engine.interval_resolution import IntervalResolutionError
from app.data_engine.history.exchange_policy import ExchangeHistoryPolicyResolver
from app.data_engine.history.service import HistoryAvailabilityService
from app.data_engine.storage import klines_repo
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_backfill_pipeline import Upstream, META
from tests.test_mixed_history_reader import row, MINUTE

CONTRACT = 'binance.usdm.trade-klines/base-utc/1'
WIDTH = 10007 * MINUTE


class ClosingUpstream(Upstream):
    async def close(self):
        pass


@pytest.fixture
def composed_dm(tmp_path, monkeypatch):
    database = tmp_path / 'composed.sqlite'
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', database)
    monkeypatch.setattr(core_config, 'KLINES_DB_PATH', database)
    klines_repo.init_klines_storage()
    config = DataManagerConfig()
    config.query.auto_backfill = False
    manager = DataManager(config)
    manager.set_storage(klines_repo.KlinesRepoAdapter())
    yield manager
    asyncio.run(manager.shutdown())
    assert manager.memory_budget.snapshot()['reserved_bytes'] == 0


def forbidden(*args, **kwargs):
    raise AssertionError('forbidden composed-history outlet: ' + sys._getframe(1).f_code.co_name)


def options(manager):
    return dict(start_ms=0, end_ms=WIDTH - 1, limit=1, market_type='futures',
        composition_contract=CONTRACT, min_revision=manager.query_engine.storage.revision_store.head())


def enough_count_to_reach_cover(manager):
    # Counts deliberately include the last day crossing a target boundary.
    # Their upper bound must never replace the actual exact-cover checks.
    day = 1440 * MINUTE
    manager.query_engine.storage.upsert_bars('BTCUSDT', '1d',
        [row(opened, day) for opened in range(0, 21 * day, day)],
        source='backfill', market_type='futures')
    manager.query_engine._cache.revision_consumer.sync(force=True)


def test_missing_composed_sources_submit_the_target_with_the_same_contract(composed_dm, monkeypatch):
    manager = composed_dm
    monkeypatch.setattr(manager.query_engine.custom_intervals, '_base_query', forbidden)
    submissions = []
    manager.set_backfill_trigger(lambda *args, **kwargs: submissions.append((args, kwargs)) or 'composed-1')
    result = manager.query_composed('BTCUSDT', '10007m', auto_backfill=True, **options(manager))
    assert not result.bars and not result.complete and result.retryable
    assert result.history_state == 'pending' and result.backfill_triggered
    assert len(submissions) == 1 and submissions[0][0][1] == '10007m'
    assert submissions[0][1]['metadata']['required_history_composition'] == CONTRACT


@pytest.mark.parametrize('fault', ['disabled', 'contract', 'calendar'])
def test_unsupported_composed_mode_never_enters_the_legacy_reader(composed_dm, monkeypatch, fault):
    manager = composed_dm
    monkeypatch.setattr(manager.query_engine.custom_intervals, '_base_query', forbidden)
    arguments = options(manager)
    if fault == 'disabled':
        manager.query_engine._cfg.mixed_custom_history = False
    elif fault == 'contract':
        arguments['composition_contract'] = 'unavailable-version'
    else:
        monkeypatch.setattr(manager.query_engine, '_calendar_for', lambda *args: None)
        manager.query_engine.set_history_policy(ExchangeHistoryPolicyResolver(HistoryAvailabilityService()))
    with pytest.raises(IntervalResolutionError) as failed:
        manager.query_composed('BTCUSDT', '10007m', **arguments)
    assert failed.value.code.value == 'history_composition_unavailable'


def test_planning_work_limit_retains_stored_partial_without_new_repair(composed_dm, monkeypatch):
    manager = composed_dm
    enough_count_to_reach_cover(manager)
    manager.query_engine.storage.upsert_bars('BTCUSDT', '10007m', [row(0, WIDTH)],
        source='backfill_aggregated', market_type='futures')
    @contextmanager
    def exhausted(*args, **kwargs):
        raise CoverBudgetExceeded('controlled work bound')
        yield
    monkeypatch.setattr(manager.query_engine, 'read_mixed_history_blocks', exhausted)
    monkeypatch.setattr(manager.query_engine.custom_intervals, '_base_query', forbidden)
    manager.set_backfill_trigger(forbidden)
    result = manager.query_composed('BTCUSDT', '10007m', **{
        **options(manager), 'end_ms': 2 * WIDTH - 1, 'limit': 2, 'auto_backfill': True})
    assert len(result.bars) == 1 and result.bars[0].trusted_final
    assert not result.complete and result.retryable and result.history_state == 'pending'
    assert result.metadata['history_composition_deferred']
    assert not result.missing_ranges and not result.backfill_triggered
    assert result.metadata['target_materialized_written'] == 0


@pytest.mark.parametrize('wait', [0, 1500])
def test_real_http_work_deferral_cannot_become_a_verification_repair(composed_dm, monkeypatch, wait):
    manager = composed_dm
    enough_count_to_reach_cover(manager)
    monkeypatch.setattr('time.time', lambda: (2 * WIDTH + 1000) / 1000)
    entered = []
    @contextmanager
    def exhausted(*args, **kwargs):
        entered.append(True)
        raise CoverBudgetExceeded('controlled work bound')
        yield
    monkeypatch.setattr(manager.query_engine, 'read_mixed_history_blocks', exhausted)
    monkeypatch.setattr(manager.query_engine.custom_intervals, '_base_query', forbidden)
    monkeypatch.setattr(api, '_submit_verification_repairs', forbidden)
    monkeypatch.setattr(api, '_schedule_related_interval_warmup', forbidden)
    manager.set_backfill_trigger(forbidden)
    app = FastAPI()
    app.state.data_manager = manager
    app.include_router(api.router, prefix='/api/v1')
    with TestClient(app) as client:
        response = client.get('/api/v1/klines/history/composed', params=dict(symbol='BTCUSDT',
            interval='10007m', count_back=2, market_type='futures', max_wait_ms=wait,
            composition_contract=CONTRACT))
    assert entered
    assert response.status_code == 200, response.text
    result = response.json()
    assert not result['complete'] and result['retryable'] and result['history_state'] == 'pending'
    assert not result['backfill_triggered'] and result['cache']['history_composition_deferred']


def test_required_composition_cannot_fall_back_when_engine_rollout_is_off(composed_dm):
    engine = engine_for(composed_dm.query_engine)
    engine.config.mixed_custom_history = False
    upstream = ClosingUpstream()
    engine._fetcher = upstream
    async def run():
        try:
            return await engine.run('BTCUSDT', intervals=['10007m'], range_start_ms=0,
                range_end_ms=0, exchange='binance', market_type='futures',
                metadata={**META, 'required_history_composition': CONTRACT})
        finally:
            await engine.close()
    report = asyncio.run(run())
    assert report.status.value == 'failed' and not upstream.calls
    assert any('composed history' in error.lower() for error in report.errors)


@pytest.mark.parametrize('endpoint,parameters', [
    ('/history/before/composed', {'before': 2 * WIDTH // 1000, 'bars': 2, 'max_wait_ms': 0}),
    ('/range/composed', {'start_ms': 0, 'end_ms': 2 * WIDTH - 1, 'repair': 'async'}),
])
def test_pagination_and_range_http_work_limits_cannot_expand_legacy_sources(composed_dm, monkeypatch, endpoint, parameters):
    manager = composed_dm
    enough_count_to_reach_cover(manager)
    monkeypatch.setattr('time.time', lambda: (3 * WIDTH + 1000) / 1000)
    @contextmanager
    def exhausted(*args, **kwargs):
        raise CoverBudgetExceeded('controlled work bound')
        yield
    monkeypatch.setattr(manager.query_engine, 'read_mixed_history_blocks', exhausted)
    monkeypatch.setattr(manager.query_engine.custom_intervals, '_base_query', forbidden)
    monkeypatch.setattr(manager.query_engine.custom_intervals, '_base_query_before', forbidden)
    monkeypatch.setattr(api, '_submit_verification_repairs', forbidden)
    manager.set_backfill_trigger(forbidden)
    app = FastAPI()
    app.state.data_manager = manager
    app.include_router(api.router, prefix='/api/v1')
    with TestClient(app) as client:
        response = client.get('/api/v1/klines' + endpoint, params={**parameters,
            'symbol': 'BTCUSDT', 'interval': '10007m', 'market_type': 'futures',
            'composition_contract': CONTRACT})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert not payload['complete'] and payload['retryable'] and not payload['backfill_triggered']
    assert payload['cache']['history_composition_deferred']


def test_missing_composed_manager_method_fails_closed_over_http(composed_dm, monkeypatch):
    monkeypatch.setattr(composed_dm, 'query_composed', None)
    monkeypatch.setattr(composed_dm, 'query', forbidden)
    app = FastAPI()
    app.state.data_manager = composed_dm
    app.include_router(api.router, prefix='/api/v1')
    with TestClient(app) as client:
        response = client.get('/api/v1/klines/history/composed', params={
            'symbol': 'BTCUSDT', 'interval': '10007m', 'market_type': 'futures',
            'composition_contract': CONTRACT, 'count_back': 128, 'max_wait_ms': 0})
    assert response.status_code == 503


def test_existing_source_aware_scheduler_completes_the_full_composed_demand(composed_dm):
    from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
    from app.data_engine.storage.gap_ledger import GapLedger
    manager = composed_dm
    engine = engine_for(manager.query_engine)
    upstream = ClosingUpstream()
    engine._fetcher = upstream
    async def run():
        coordinator = BackfillCoordinator(storage=manager.query_engine.storage,
            bars_backfilled=manager.on_bars_backfilled, emit_event=manager.emit_event,
            source_available=manager.source_storage_available, engine=engine,
            loop=asyncio.get_running_loop(), gap_ledger=GapLedger(klines_repo.KLINES_DB_PATH),
            max_concurrency=1, chunk_bars=1000, max_retries=1)
        manager.set_backfill_trigger(coordinator.trigger)
        try:
            initial = manager.query_composed('BTCUSDT', '10007m', **{
                **options(manager), 'end_ms': 8 * WIDTH - 1, 'limit': 8, 'auto_backfill': True,
                'backfill_reason': 'initial_history', 'backfill_requester': 'klines_history',
                'backfill_metadata': {'history_calendar_id': 'crypto.24x7.utc'}})
            assert not initial.complete and initial.backfill_triggered
            outcome = await asyncio.wait_for(coordinator.wait_for_request(
                initial.metadata['backfill_request_ids'][0]), timeout=30)
            assert outcome.verified_contiguous is True and outcome.remaining_missing_bars == 0, outcome.error
            result = manager.query_composed('BTCUSDT', '10007m', **{
                **options(manager), 'end_ms': 8 * WIDTH - 1, 'limit': 8})
            assert result.complete and len(result.bars) == 8
            assert all(bar.trusted_final and bar.volume == bar.trades == 10007 for bar in result.bars)
            assert {task.metadata['chunk_sequence'] for task in upstream.calls} == set(range(8))
            assert all(task.metadata['required_history_composition'] == CONTRACT for task in upstream.calls)
            assert len(upstream.calls) < 40
        finally:
            await coordinator.shutdown()
    asyncio.run(run())


def test_required_composition_reuses_complete_fine_inputs_without_fetch(composed_dm):
    manager = composed_dm
    manager.query_engine.storage.upsert_bars('BTCUSDT', '1m',
        [row(opened, MINUTE) for opened in range(0, WIDTH, MINUTE)],
        source='backfill', market_type='futures')
    engine = engine_for(manager.query_engine)
    upstream = ClosingUpstream()
    engine._fetcher = upstream
    async def run():
        try:
            return await engine.run('BTCUSDT', intervals=['10007m'], range_start_ms=0,
                range_end_ms=0, exchange='binance', market_type='futures',
                metadata={**META, 'required_history_composition': CONTRACT})
        finally:
            await engine.close()
    report = asyncio.run(run())
    assert report.status.value == 'completed', report.errors
    assert not upstream.calls and report.reconcile_result.custom_bars_written == 1
    result = manager.query_composed('BTCUSDT', '10007m', **options(manager))
    assert result.complete and len(result.bars) == 1 and result.bars[0].volume == 10007


@pytest.mark.parametrize('partial_targets', [0, 20])
def test_obvious_local_coverage_shortage_skips_cover_planning_without_losing_partial(composed_dm, monkeypatch, partial_targets):
    manager = composed_dm
    if partial_targets:
        manager.query_engine.storage.upsert_bars('BTCUSDT', '10007m',
            [row(index * WIDTH, WIDTH) for index in range(128-partial_targets, 128)],
            source='backfill_aggregated', market_type='futures')
    monkeypatch.setattr(manager.query_engine, 'read_mixed_history_blocks', forbidden)
    monkeypatch.setattr(manager.query_engine.custom_intervals, '_base_query', forbidden)
    result = manager.query_composed('BTCUSDT', '10007m', **{
        **options(manager), 'end_ms': 128 * WIDTH - 1, 'limit': 128})
    assert not result.complete and result.retryable and result.history_state == 'pending'
    assert len(result.bars) == partial_targets
    assert all(bar.trusted_final and bar.volume == 10007 for bar in result.bars)
    assert result.metadata['mixed_impossible_local_cover']
    assert result.metadata['mixed_local_coverage_upper_ms'] == 0
    assert result.metadata['mixed_count_reads'] == 6 and result.metadata['mixed_page_reads'] == 0
    assert result.metadata['target_materialized_written'] == 0
    assert [(gap.start_ms, gap.end_ms) for gap in result.missing_ranges] == [(0, (127-partial_targets)*WIDTH)]


def test_overlapping_or_cross_boundary_counts_never_prove_a_complete_cover(composed_dm, monkeypatch):
    manager = composed_dm
    enough_count_to_reach_cover(manager)
    original = manager.query_engine.read_mixed_history_blocks
    calls = []
    def read(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(manager.query_engine, 'read_mixed_history_blocks', read)
    monkeypatch.setattr(manager.query_engine.custom_intervals, '_base_query', forbidden)
    result = manager.query_composed('BTCUSDT', '10007m', **options(manager))
    assert calls and result.metadata['mixed_local_coverage_upper_ms'] >= WIDTH
    assert not result.complete and result.history_state == 'pending' and not result.bars
    assert not result.metadata.get('mixed_impossible_local_cover')
    assert result.metadata['target_materialized_written'] == 0


def test_coverage_count_failure_cannot_authorize_a_new_repair(composed_dm, monkeypatch):
    manager = composed_dm
    storage = manager.query_engine.storage
    original = storage.count_bars
    def count(*args, **kwargs):
        if kwargs.get('interval') == '4h':
            raise OSError('controlled count failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(storage, 'count_bars', count)
    monkeypatch.setattr(manager.query_engine, 'read_mixed_history_blocks', forbidden)
    monkeypatch.setattr(manager.query_engine.custom_intervals, '_base_query', forbidden)
    manager.set_backfill_trigger(forbidden)
    result = manager.query_composed('BTCUSDT', '10007m', **{**options(manager), 'auto_backfill': True})
    assert not result.complete and result.retryable and not result.backfill_triggered
    assert not result.missing_ranges and result.metadata['history_composition_deferred']
    assert result.metadata['mixed_count_failures'] == 1


@pytest.mark.parametrize('fault', ['revision_unavailable', 'memory_budget_deferred'])
@pytest.mark.parametrize('endpoint,parameters', [
    ('/history/composed', {'count_back': 2, 'max_wait_ms': 1500}),
    ('/range/composed', {'start_ms': 0, 'end_ms': 2 * WIDTH - 1, 'repair': 'async'}),
])
def test_durable_or_memory_read_deferral_never_becomes_verification_repair(composed_dm, monkeypatch, fault, endpoint, parameters):
    from app.data_engine.memory_budget import MemoryBudgetExceeded
    manager = composed_dm
    if fault == 'revision_unavailable':
        # Keep the legitimate cache poll watermark behind a new SQLite commit.
        consumer = manager.query_engine._cache.revision_consumer
        consumer.sync(force=True)
        consumer.poll_seconds = 60
        manager.query_engine.storage.upsert_bars('BTCUSDT', '1d', [row(0, 1440*MINUTE)],
            source='backfill', market_type='futures')
    else:
        original_reserve = manager.memory_budget.reserve
        def reserve(owner, *args, **kwargs):
            if owner == 'history-query':
                raise MemoryBudgetExceeded('controlled history reservation refusal')
            return original_reserve(owner, *args, **kwargs)
        monkeypatch.setattr(manager.memory_budget, 'reserve', reserve)
    monkeypatch.setattr(api, '_submit_verification_repairs', forbidden)
    manager.set_backfill_trigger(forbidden)
    app = FastAPI()
    app.state.data_manager = manager
    app.include_router(api.router, prefix='/api/v1')
    with TestClient(app) as client:
        response = client.get('/api/v1/klines'+endpoint, params={**parameters,
            'symbol':'BTCUSDT','interval':'10007m','market_type':'futures','composition_contract':CONTRACT})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['cache'][fault] and not result['complete'] and result['retryable']
    assert not result['backfill_triggered']
