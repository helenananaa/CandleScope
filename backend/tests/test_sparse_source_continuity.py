"""Durable empty-second evidence resolves strict waits without fabricated bars."""
import asyncio
from dataclasses import replace
import pytest
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, SeriesKey
from app.data_engine.storage import klines_repo, native_empty_seconds, trade_empty_buckets
from app.data_engine.series_identity import KlineSeriesIdentity

START=1_793_232_000_000

@pytest.fixture(params=['upbit', 'kraken'])
def sparse(request, tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo,'KLINES_DB_PATH',tmp_path/'bars.sqlite')
    klines_repo.init_klines_storage()
    store=klines_repo.KlinesRepoAdapter()
    exchange=request.param; symbol='BTC/KRW' if exchange=='upbit' else 'BTC/USD'
    key=SeriesKey(symbol,'1s',exchange=exchange)
    record=(lambda ranges: native_empty_seconds.record(symbol,ranges)) if exchange=='upbit' else (lambda ranges: trade_empty_buckets.record(exchange,'spot',symbol,'1s',ranges))
    return store,key,record

async def complete(dm,key):
    await dm.emit_event(DataEvent(DataEventType.BACKFILL_COMPLETED,key,detail={'verified_contiguous': True,'bars_count':0}))

@pytest.mark.anyio
async def test_verified_empty_gap_releases_strict_waiter_without_inventing_candle(sparse):
    store,key,record=sparse;dm=DataManager();dm.set_storage(store)
    events=[];errors=[]
    async def receive(event):events.append(event)
    async def recover(error):errors.append(error)
    dm.subscribe(receive,symbol=key.symbol,interval=key.interval,exchange=key.exchange,on_recovery=recover,event_types={DataEventType.BAR_CLOSED})
    try:
        gap,_=dm.source_gaps.open(key,START,START+1000)
        await dm.event_bus.emit(gap.event())
        tail=BarData((START+2000)//1000,1,1,1,1,1,source='backfill_rest_verified')
        await dm.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,key,tail))
        await asyncio.sleep(.01);assert events==[]
        record([(START,START+1000)])
        await complete(dm,key)
        assert gap.completed_at is not None
        for _ in range(100):
            if events:break
            await asyncio.sleep(.005)
        assert [e.bar.time_ms for e in events]==[START+2000]
        assert errors==[] and store.query_bars(key.symbol,'1s',exchange=key.exchange)==[]
    finally:await dm.shutdown()

@pytest.mark.anyio
async def test_completion_status_and_partial_absence_cannot_prove_gap(sparse):
    store,key,record=sparse;dm=DataManager();dm.set_storage(store)
    try:
        gap,_=dm.source_gaps.open(key,START,START+1000)
        await complete(dm,key);assert gap.completed_at is None
        record([(START,START)])
        await complete(dm,key);assert gap.completed_at is None
        row=dict(open_time=START+1000,close_time=START+1999,open=1,high=1,low=1,close=1,volume=1,quote_volume=1,trades=1,taker_buy_base=0,taker_buy_quote=0)
        store.upsert_bars(key.symbol,'1s',[row],'backfill_rest_verified',exchange=key.exchange)
        await complete(dm,key)
        assert gap.completed_at is not None
        assert set(gap.repaired)=={START+1000}
    finally:await dm.shutdown()

@pytest.mark.anyio
async def test_other_identity_and_deleted_proof_cannot_release_gap(sparse):
    store,key,record=sparse;dm=DataManager();dm.set_storage(store)
    try:
        foreign=replace(key,provider_id='other-provider')
        a,_=dm.source_gaps.open(key,START,START+1000)
        b,_=dm.source_gaps.open(foreign,START,START+1000)
        record([(START,START+1000)])
        await complete(dm,foreign);assert b.completed_at is None and a.completed_at is None
        klines_repo.delete_klines(key.symbol,'1s',START,START+1000,exchange=key.exchange)
        await complete(dm,key);assert a.completed_at is None
    finally:await dm.shutdown()

@pytest.mark.anyio
async def test_delayed_live_final_resolves_gap_only_after_canonical_commit(sparse):
    store,_,_=sparse;key=SeriesKey('BTC/USDT','1s',exchange='gate')
    dm=DataManager();dm.set_storage(store)
    try:
        gap,_=dm.source_gaps.open(key,START,START)
        bar=BarData(START//1000,1,1,1,1,1,source='backfill_rest_verified')
        await dm.emit_event(DataEvent(DataEventType.BAR_CLOSED,key,bar))
        assert gap.completed_at is None
        row=dict(open_time=START,close_time=START+999,open=1,high=1,low=1,close=1,volume=1,quote_volume=1,trades=1,taker_buy_base=0,taker_buy_quote=0)
        store.upsert_bars(key.symbol,'1s',[row],'backfill_rest_verified',exchange=key.exchange)
        await dm.emit_event(DataEvent(DataEventType.BAR_CLOSED,key,bar))
        assert gap.completed_at is not None and set(gap.repaired)=={START}
    finally:await dm.shutdown()

@pytest.mark.anyio
async def test_proof_deleted_during_adoption_never_resolves_gap(sparse,monkeypatch):
    store,key,record=sparse;dm=DataManager();dm.set_storage(store)
    try:
        gap,_=dm.source_gaps.open(key,START,START+1000)
        record([(START,START+1000)])
        original=store.query_bars;deleted=False
        def racing_read(*args,**kwargs):
            nonlocal deleted
            if not deleted:
                deleted=True
                klines_repo.delete_klines(key.symbol,'1s',START,START+1000,exchange=key.exchange)
            return original(*args,**kwargs)
        monkeypatch.setattr(store,'query_bars',racing_read)
        await complete(dm,key)
        assert deleted and gap.completed_at is None
    finally:await dm.shutdown()
