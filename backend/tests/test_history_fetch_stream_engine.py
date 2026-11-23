"""Receipt-mode native writes, public payload demand and recovery contracts."""
import asyncio
import threading

import pytest

from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.fetch_stream import StreamBackfillDeferred
from app.data_engine.backfill.models import BackfillStatus, FetchReceipt, FetchResult
from app.data_engine.ingestion.config import IngestionConfig
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_plan import engine_for
from tests.test_binance_backfill_fetcher import _FakeBinanceTransport, _make_binance_rows
from tests.test_backfill_coordinator import _quota_deferral


def native_engine(query, count=130):
    engine = engine_for(query)
    engine.config.fetch_batch_size = 32
    engine.config.fetch_concurrency = 1
    engine.config.fetch_global_concurrency = 1
    engine.config.fetch_rate_limit_delay = 0
    engine.config.fetch_binance_futures_rate_limit_delay = 0
    transport = _FakeBinanceTransport(_make_binance_rows(count,60_000),page_cap=32)
    engine._fetcher = HistoricalFetcher(engine.config,transport,IngestionConfig())
    return engine, transport


def repair(engine):
    return engine.run_receipt('BTCUSDT',intervals=['1m'],range_start_ms=0,
        range_end_ms=129*60_000,exchange='binance',market_type='futures')


def test_native_receipt_writes_every_page_and_keeps_accurate_report_counts(mixed_query):
    engine, transport = native_engine(mixed_query)
    report = asyncio.run(repair(engine))
    assert report.status == BackfillStatus.COMPLETED, report.errors
    assert report.metadata['fetch_payload_mode'] == 'receipt'
    assert report.metadata['stream_reconciliation']['native_pages'] == 5
    assert all(isinstance(item,FetchReceipt) and not hasattr(item,'bars') for item in report.fetch_results)
    assert sum(item.bars_count for item in report.fetch_results) == 130
    assert report.reconcile_result.bars_received == report.reconcile_result.bars_written == 130
    assert len(report.written_ranges) == 1 and report.written_ranges[0].bars_written == 130
    assert len(transport.requests) == 5
    assert mixed_query.storage.count_bars('BTCUSDT','1m',0,129*60_000,market_type='futures') == 130
    assert mixed_query.memory_budget.snapshot()['reserved_bytes'] == 0


@pytest.mark.parametrize('demand', ['callback','formatter','filter','preview','false_formatter','false_filter'])
def test_full_payload_extensions_keep_the_complete_result_contract(mixed_query,demand):
    engine, transport = native_engine(mixed_query)
    observed = []
    def inspect_report(report):
        assert all(isinstance(item,FetchResult) and len(item.bars) == item.bars_count for item in report.fetch_results)
        assert sum(item.bars_count for item in report.fetch_results) == 130
        observed.append(report.run_id)
        return True
    if demand == 'callback':
        async def callback(report): inspect_report(report)
        engine.publisher.on_report(callback)
    if demand == 'formatter': engine.publisher.set_report_formatter(inspect_report)
    if demand == 'filter': engine.publisher.set_report_filter(inspect_report)
    class FalseCallable:
        def __bool__(self): return False
        def __call__(self,report): return inspect_report(report)
    if demand == 'false_formatter': engine.publisher.set_report_formatter(FalseCallable())
    if demand == 'false_filter': engine.publisher.set_report_filter(FalseCallable())
    if demand == 'preview': engine.config.publish_include_data_preview = True
    report = asyncio.run(repair(engine))
    assert report.status == BackfillStatus.COMPLETED, report.errors
    assert all(isinstance(item,FetchResult) and len(item.bars) == item.bars_count for item in report.fetch_results)
    if demand != 'preview': assert observed == [report.run_id]
    else: assert len(report.data_preview) == engine.config.publish_max_preview_rows
    assert engine.publisher._receipt_runs == 0


def test_failed_page_keeps_successful_siblings_without_claiming_completion(mixed_query,monkeypatch):
    engine, transport = native_engine(mixed_query)
    original = engine._storage.upsert_bars
    calls = 0
    async def fail_second(*args,**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2: raise RuntimeError('controlled physical write rejection')
        return await original(*args,**kwargs)
    monkeypatch.setattr(engine._storage,'upsert_bars',fail_second)
    report = asyncio.run(repair(engine))
    assert report.status == BackfillStatus.PARTIAL and report.errors
    assert len(transport.requests) == 5
    assert report.reconcile_result.bars_written == 98 and report.reconcile_result.write_errors == 1
    assert sum(item.bars_count for item in report.fetch_results) == 130
    assert any(item.retryable for item in report.fetch_results)
    assert mixed_query.storage.count_bars('BTCUSDT','1m',0,129*60_000,market_type='futures') == 98
    assert mixed_query.memory_budget.snapshot()['reserved_bytes'] == 0
    engine.publisher.on_report(lambda _report:None)  # Demand guard is released.


def test_cancelled_receipt_run_releases_payload_demand_and_memory_admission(mixed_query,monkeypatch):
    engine, transport = native_engine(mixed_query)
    async def check():
        entered, released = asyncio.Event(),asyncio.Event()
        original = engine._storage.upsert_bars
        async def held(*args,**kwargs):
            entered.set()
            await released.wait()
            return await original(*args,**kwargs)
        monkeypatch.setattr(engine._storage,'upsert_bars',held)
        pending = asyncio.create_task(repair(engine))
        try:
            await asyncio.wait_for(entered.wait(),5)
            assert len(transport.requests) == 1
            assert mixed_query.memory_budget.snapshot()['reserved_bytes'] > 0
            with pytest.raises(RuntimeError,match='between active receipt runs'):
                engine.publisher.on_report(lambda _report:None)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError): await pending
        finally:
            released.set()
            await asyncio.gather(pending,return_exceptions=True)
        assert engine.publisher._receipt_runs == 0
        assert mixed_query.memory_budget.snapshot()['reserved_bytes'] == 0
        engine.publisher.on_report(lambda _report:None)
    asyncio.run(check())


def test_quota_deferral_preserves_committed_pages_and_retry_fetches_only_missing_rows(mixed_query,monkeypatch):
    engine, transport = native_engine(mixed_query)
    original = transport.http_fetch
    once = True
    async def defer(*args,**kwargs):
        nonlocal once
        if len(transport.requests) == 1 and once:
            once = False
            raise _quota_deferral(.01)
        return await original(*args,**kwargs)
    monkeypatch.setattr(transport,'http_fetch',defer)
    async def check():
        with pytest.raises(StreamBackfillDeferred) as caught:
            await repair(engine)
        assert caught.value.reconcile_result.bars_written == 98
        assert mixed_query.storage.count_bars('BTCUSDT','1m',0,129*60_000,market_type='futures') == 98
        assert mixed_query.memory_budget.snapshot()['reserved_bytes'] == 0
        before = len(transport.requests)
        final = await repair(engine)
        assert final.status == BackfillStatus.COMPLETED, final.errors
        assert transport.requests[before].start_ms == 32*60_000
        assert final.reconcile_result.bars_written == 32
        assert mixed_query.storage.count_bars('BTCUSDT','1m',0,129*60_000,market_type='futures') == 130
    asyncio.run(check())


def test_cancellation_waits_for_physical_sqlite_work_before_releasing_page_admission(mixed_query,monkeypatch):
    from app.data_engine.storage import klines_repo
    engine, transport = native_engine(mixed_query)
    entered, released = threading.Event(),threading.Event()
    original = klines_repo.upsert_klines
    def blocked(*args,**kwargs):
        entered.set()
        assert released.wait(10)
        return original(*args,**kwargs)
    monkeypatch.setattr(klines_repo,'upsert_klines',blocked)
    async def check():
        pending = asyncio.create_task(repair(engine))
        try:
            async with asyncio.timeout(5):
                while not entered.is_set(): await asyncio.sleep(.01)
            pending.cancel()
            await asyncio.sleep(.05)
            assert not pending.done()
            assert mixed_query.memory_budget.snapshot()['reserved_bytes'] > 0
            assert engine.publisher._receipt_runs == 1
            assert len(transport.requests) == 1
            released.set()
            with pytest.raises(asyncio.CancelledError): await pending
            assert mixed_query.storage.count_bars('BTCUSDT','1m',0,129*60_000,market_type='futures') == 32
        finally:
            released.set()
            await asyncio.gather(pending,return_exceptions=True)
        assert mixed_query.memory_budget.snapshot()['reserved_bytes'] == 0
        assert engine.publisher._receipt_runs == 0
    asyncio.run(check())


@pytest.mark.parametrize('mutation', ['delete','amend'])
def test_external_change_between_pages_does_not_grant_old_request_more_write_permission(mixed_query,monkeypatch,mutation):
    from app.core.executors import run_storage
    from app.data_engine.storage.revisions import acquisition_scope
    engine, transport = native_engine(mixed_query)
    original = engine._storage.upsert_bars
    once = True
    async def mutate(*args,**kwargs):
        nonlocal once
        result = await original(*args,**kwargs)
        if once:
            once = False
            def external():
                with acquisition_scope(None):
                    if mutation == 'delete':
                        mixed_query.storage.delete_bars('BTCUSDT','1m',0,0,market_type='futures')
                    else:
                        rows = mixed_query.storage.query_bars('BTCUSDT','1m',0,0,market_type='futures')
                        rows[0]['volume'] = 91
                        mixed_query.storage.upsert_bars('BTCUSDT','1m',rows,
                            source='data_manager_amended',market_type='futures')
            await run_storage(external)
        return result
    monkeypatch.setattr(engine._storage,'upsert_bars',mutate)
    async def check():
        report = await repair(engine)
        assert report.status == BackfillStatus.PARTIAL and report.reconcile_result.write_errors
        rows = mixed_query.storage.query_bars('BTCUSDT','1m',0,129*60_000,market_type='futures')
        assert len(rows) == (31 if mutation == 'delete' else 32)
        if mutation == 'delete': assert all(row['open_time'] != 0 for row in rows)
        else: assert next(row for row in rows if row['open_time'] == 0)['volume'] == 91
        assert mixed_query.memory_budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(check())


@pytest.mark.parametrize('mutation', ['storage', 'reconciler', 'dedup_policy'])
def test_owner_or_configuration_change_stops_receipt_run_after_legitimate_commit(mixed_query,monkeypatch,mutation):
    engine, transport = native_engine(mixed_query)
    original = engine._storage.upsert_bars
    once = True
    async def rebind(*args,**kwargs):
        nonlocal once
        result = await original(*args,**kwargs)
        if once:
            once = False
            if mutation == 'storage': engine._storage = object()
            elif mutation == 'reconciler': engine._reconciler = None
            else: engine.config.reconcile_generate_custom = not engine.config.reconcile_generate_custom
        return result
    monkeypatch.setattr(engine._storage,'upsert_bars',rebind)
    report = asyncio.run(repair(engine))
    assert report.status == BackfillStatus.FAILED
    assert any('owner/config binding changed' in error for error in report.errors)
    assert report.reconcile_result.bars_written == 32
    assert len(transport.requests) == 5
    assert mixed_query.storage.count_bars('BTCUSDT','1m',0,129*60_000,market_type='futures') == 32
    assert mixed_query.memory_budget.snapshot()['reserved_bytes'] == 0
    assert engine.publisher._receipt_runs == 0


def test_partial_fetch_work_budget_is_not_reported_as_completed(mixed_query):
    engine, transport = native_engine(mixed_query)
    engine.config.fetch_max_total_bars = 3
    report = asyncio.run(repair(engine))
    assert report.status == BackfillStatus.PARTIAL, report.errors
    assert any('fetch_work_budget_exhausted' in error for error in report.errors)
    assert report.reconcile_result.bars_written == 14
    assert [item.bars_count for item in report.fetch_results] == [3,3,3,3,2]
    assert all(item.retryable and not item.source_complete for item in report.fetch_results[:4])
    assert report.fetch_results[-1].status == BackfillStatus.COMPLETED
