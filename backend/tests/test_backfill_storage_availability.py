"""A durable partial repair can prove one gap before its parent verifies."""
import asyncio

from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from app.data_engine.data_manager.backfill_contracts import RepairRequest,RepairRetryDeferred
from app.data_engine.storage import klines_repo,native_empty_seconds
from types import SimpleNamespace
import pytest
from tests.test_backfill_coordinator import _RepairReport

START=1793232000000


def test_empty_proof_commit_can_release_exact_gap_before_whole_request_retry(tmp_path,monkeypatch):
    monkeypatch.setattr(klines_repo,'KLINES_DB_PATH',tmp_path/'bars.sqlite')
    klines_repo.init_klines_storage()
    async def run():
        store=klines_repo.KlinesRepoAdapter();dm=DataManager();dm.set_storage(store)
        key=SeriesKey('BTC/KRW','1s',exchange='upbit')
        ready,_=dm.source_gaps.open(key,START,START)
        unknown,_=dm.source_gaps.open(key,START+1000,START+1000)
        class Engine:
            async def run(self,**kwargs):
                native_empty_seconds.record(key.symbol,[(START,START)])
                return _RepairReport(status='completed')
        coordinator=BackfillCoordinator(storage=store,bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.emit_event,engine=Engine(),max_retries=3,base_delay_seconds=.01,
            source_available=dm.source_storage_available)
        request=RepairRequest(symbol=key.symbol,interval='1s',start_ms=START,end_ms=START+1000,
            exchange='upbit',metadata={'requires_trusted_finality':True})
        try:
            try:await coordinator._run_with_retries(request)
            except RepairRetryDeferred:pass
            else:raise AssertionError('The unproven second must leave the whole request pending')
            assert ready.completed_at is not None,'Committed exact absence proof was hidden until whole parent verification'
            assert unknown.completed_at is None
            assert store.query_bars(key.symbol,'1s',exchange='upbit')==[]
        finally:await dm.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize('foreign',[False,True])
def test_custom_request_can_notify_committed_native_dependency_without_crossing_identity(tmp_path,monkeypatch,foreign):
    monkeypatch.setattr(klines_repo,'KLINES_DB_PATH',tmp_path/'bars.sqlite')
    klines_repo.init_klines_storage()
    async def run():
        store=klines_repo.KlinesRepoAdapter();dm=DataManager();dm.set_storage(store)
        native=SeriesKey('BTCUSDT','1s')
        if foreign:native=SeriesKey('BTCUSDT','1s',provider_id='foreign')
        gap,_=dm.source_gaps.open(native,START,START)
        store.upsert_bars('BTCUSDT','1s',[dict(open_time=START,close_time=START+999,
            open=1,high=1,low=1,close=1,volume=1,quote_volume=1,trades=1,
            taker_buy_base=0,taker_buy_quote=0)],source='backfill')
        metadata={'series_identity':native.identity.to_dict()} if foreign else {}
        request=RepairRequest(symbol='BTCUSDT',interval='7s',start_ms=START,end_ms=START,metadata=metadata)
        report=SimpleNamespace(reconcile_result=SimpleNamespace(written_ranges=[dict(
            exchange='binance',market_type='spot',symbol='BTCUSDT',interval='1s')]))
        coordinator=BackfillCoordinator(storage=store,bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.emit_event,source_available=dm.source_storage_available)
        try:
            await coordinator._notify_source_storage(request,report)
            assert (gap.completed_at is None)==foreign
        finally:await dm.shutdown()
    asyncio.run(run())


def test_notification_never_turns_status_or_unproven_empty_rows_into_source_proof(tmp_path,monkeypatch):
    monkeypatch.setattr(klines_repo,'KLINES_DB_PATH',tmp_path/'bars.sqlite')
    klines_repo.init_klines_storage()
    async def run():
        store=klines_repo.KlinesRepoAdapter();dm=DataManager();dm.set_storage(store)
        key=SeriesKey('BTC/KRW','1s',exchange='upbit');gap,_=dm.source_gaps.open(key,START,START)
        coordinator=BackfillCoordinator(storage=store,bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.emit_event,source_available=dm.source_storage_available)
        request=RepairRequest(symbol=key.symbol,interval='1s',exchange='upbit',start_ms=START,end_ms=START)
        try:
            await coordinator._notify_source_storage(request,_RepairReport(status='completed'))
            assert gap.completed_at is None
        finally:await dm.shutdown()
    asyncio.run(run())


def test_notification_is_bounded_and_filters_other_market_families():
    async def run():
        calls=[]
        async def notified(key):calls.append(key)
        coordinator=BackfillCoordinator(storage=SimpleNamespace(),bars_backfilled=notified,
            emit_event=notified,source_available=notified)
        request=RepairRequest(symbol='BTCUSDT',interval='7s',start_ms=START,end_ms=START)
        ranges=[dict(exchange='binance',market_type='spot',symbol='ETHUSDT',interval='1m')]
        ranges += [dict(exchange='binance',market_type='spot',symbol='BTCUSDT',interval=f'{i}s') for i in range(1,101)]
        await coordinator._notify_source_storage(request,SimpleNamespace(reconcile_result=SimpleNamespace(written_ranges=ranges)))
        assert len(calls)==32 and len(set(calls))==32
        assert all(key.symbol=='BTCUSDT' for key in calls)
        assert any(key.interval=='7s' for key in calls)
    asyncio.run(run())


def test_notification_cancellation_is_not_swallowed():
    async def run():
        async def cancelled(key):raise asyncio.CancelledError
        coordinator=BackfillCoordinator(storage=SimpleNamespace(),bars_backfilled=cancelled,
            emit_event=cancelled,source_available=cancelled)
        request=RepairRequest(symbol='BTCUSDT',interval='1s',start_ms=START,end_ms=START)
        with pytest.raises(asyncio.CancelledError):
            await coordinator._notify_source_storage(request,_RepairReport(status='completed'))
    asyncio.run(run())
