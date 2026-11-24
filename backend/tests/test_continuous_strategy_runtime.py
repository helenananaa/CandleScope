"""Real async market bus, SQLite, Provider and owned serial worker lifecycle.

Only public transport leases are replaced; no remote feed is opened in tests.
"""
import asyncio
import json
from threading import Event

import pytest

from app.backtest.continuous_runtime import ContinuousStrategyRuntime
from app.backtest.errors import BacktestError
from app.data_engine.data_manager.models import BarData,DataEvent,DataEventType
from app.data_engine.ingestion.models import DataSource,RawMessage,StreamDescriptor,StreamType
from app.data_engine.storage import klines_repo,kline_sources
from app.exchanges.ccxt_ext.fork_kline import SPOT_SCHEMA,normalize_fork_kline
from tests.test_kline_revision_contract import storage as storage
from tests.test_continuous_bar_source import source_setup,create_frozen,START,STEP,END,KEY,SOURCE,_row


async def wait_row(store,run_id,predicate):
    subscription=store.updates.subscribe(run_id)
    try:
        async with asyncio.timeout(10):
            while True:
                subscription.clear_before_read()
                row=store.summary(run_id)
                if predicate(row):return row
                await subscription.wait()
    finally:subscription.close()


def leases(monkeypatch,manager):
    active=set();calls=[]
    async def acquire(*args,**kwargs):
        active.add(kwargs["consumer_id"]);calls.append(("acquire",args,kwargs))
    async def release(*args,**kwargs):
        active.discard(kwargs["consumer_id"]);calls.append(("release",args,kwargs))
    monkeypatch.setattr(manager.bars,"ensure_stream",acquire)
    monkeypatch.setattr(manager,"release_stream",release)
    return active,calls


def test_backend_execution_survives_view_close_and_resumes_only_new_input(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    active,calls=leases(monkeypatch,manager)
    now=[START+20*STEP]
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:now[0],max_active_runs=1)
    async def scenario():
        view=store.updates.subscribe("cs_source")
        try:
            await runtime.start_existing("cs_source")
            row=await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE")
            assert row["sequence"]==20
            assert (await runtime.start_existing("cs_source"))["generation"]==row["generation"]
            with pytest.raises(BacktestError,match="capacity"):
                await runtime.start_existing("another-run")
            view.close()
            now[0]=END+1
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
            row=await wait_row(store,"cs_source",lambda row:row["sequence"]==25)
            old=store.load("cs_source")
            assert row["phase"]=="LIVE" and active
            actor=runtime.actors["cs_source"]
            await runtime.shutdown()
            assert not active and not runtime.actors and actor.executor.snapshot()["active"]==0
            assert store.load("cs_source")==old
            # Owned shutdown preserves the active durable phase for restart.
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,
                [_row(START+i*STEP,100+i%7) for i in range(25,30)],source=SOURCE)
            now[0]=START+30*STEP
            restored=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:now[0])
            try:
                assert (await restored.restore_active())["started"]==["cs_source"]
                current=await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE" and row["sequence"]==30)
                assert current["generation"]==row["generation"]+1
                previous_fills=old["checkpoint"]["engine"]["fills"]
                assert store.load("cs_source")["checkpoint"]["engine"]["fills"][:len(previous_fills)]==previous_fills
                assert (await restored.pause("cs_source"))["phase"]=="PAUSED"
                assert not restored.actors and not active
                assert (await restored.restore_active())["started"]==[]
            finally:await restored.shutdown()
            assert len([call for call in calls if call[0]=="acquire"])==2
            assert len([call for call in calls if call[0]=="release"])==2
        finally:
            view.close();await runtime.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


def test_early_source_close_wakes_again_at_local_boundary(storage, tmp_path, monkeypatch):
    service, _, definition, factory, store, manager, source, receipt = source_setup(storage, tmp_path, monkeypatch)
    create_frozen(source, receipt, definition, factory, store)
    active, _ = leases(monkeypatch, manager)
    now = [START + 20 * STEP]
    runtime = ContinuousStrategyRuntime(store, manager, source.local_datasets, factory, clock_ms=lambda: now[0])

    async def scenario():
        try:
            await runtime.start_existing("cs_source")
            initial = await wait_row(store, "cs_source", lambda row: row["phase"] == "LIVE")
            assert initial["sequence"] == 20
            actor = runtime.actors["cs_source"]
            stepped = asyncio.Event()
            loop = asyncio.get_running_loop()
            step = actor.step

            def observe_step(*args):
                result = step(*args)
                loop.call_soon_threadsafe(stepped.set)
                return result

            monkeypatch.setattr(actor, "step", observe_step)
            boundary = START + 21 * STEP
            now[0] = boundary - 200
            bar = BarData((boundary - STEP) // 1000, 100, 102, 99, 101, 100, source=SOURCE)
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED, KEY, bar))
            await asyncio.wait_for(stepped.wait(), 2)
            assert store.summary("cs_source")["sequence"] == 20
            now[0] = boundary
            row = await asyncio.wait_for(wait_row(store, "cs_source", lambda r: r["sequence"] == 21), 2)
            assert row["event_time_ms"] == boundary - 1
        finally:
            await runtime.shutdown()
            await manager.event_bus.close()
        assert not active and not runtime.actors

    try:
        asyncio.run(scenario())
    finally:
        source.close()
        store.close()
        service.shutdown()


def test_history_amendment_stops_actor_and_keeps_financial_recovery_point(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    active,_=leases(monkeypatch,manager)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:END+1)
    async def scenario():
        try:
            await runtime.start_existing("cs_source")
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE")
            old=store.load("cs_source");actor=runtime.actors["cs_source"]
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START,220)],source=SOURCE)
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED,KEY))
            await wait_row(store,"cs_source",lambda row:row["phase"]=="REPAIR_REQUIRED")
            await asyncio.wait_for(asyncio.shield(actor.task),10)
            assert not active and not runtime.actors
            assert store.load("cs_source")["checkpoint"]==old["checkpoint"]
            with pytest.raises(BacktestError,match="repair resolution"):
                await runtime.start_existing("cs_source",retry_failed=True)
        finally:await runtime.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


SPOT=StreamDescriptor(KEY.symbol,StreamType.KLINE,interval=KEY.interval,market_type="spot")
CANDLE=("timestamp","open","high","low","close","volume","closeTime","quoteVolume","trades","takerBuyBaseVolume","takerBuyQuoteVolume")


def _candle(opened,source,*,close,volume,quote,trades,at):
    """A Binance spot fork candle for ``_row(opened, 105)``'s stored bar."""
    row=[opened,"100","250","50",close,volume,opened+STEP-1,quote,trades,"5","500","0"]
    payload={"schema":SPOT_SCHEMA,"exchange":"binance","marketType":"spot","marketId":KEY.symbol,
        "symbol":"BTC/USDT","timeframe":KEY.interval,"volumeUnit":"base","quoteVolumeUnit":"quote",**dict(zip(CANDLE,row))}
    if source is DataSource.WEBSOCKET:
        kline=dict(zip(("t","o","h","l","c","v","T","q","n","V","Q"),row[:11]))
        frame={"e":"kline","E":at,"s":KEY.symbol,"k":{**kline,"s":KEY.symbol,"i":KEY.interval,"x":True,"B":"0"}}
        payload.update(closed=True,closeEvidence="ws_x",eventTime=at,raw=json.dumps(frame))
    else:
        payload.update(closed=None,closeEvidence="rest_close_time",_source_rest_server_time_ms=at,raw=json.dumps(row))
    return normalize_fork_kline(RawMessage(payload,source,StreamType.KLINE,at),SPOT)


def _observe_and_project(candle):
    """Record a source observation; the canonical projection accepts only the selected head."""
    watermark=kline_sources.rest_watermark() if candle.source is not DataSource.WEBSOCKET else None
    receipt=kline_sources.record(candle,SPOT,rest_watermark=watermark)
    klines_repo.upsert_klines(KEY.symbol,KEY.interval,[{name:candle.data[name] for name in (
        "open_time","close_time","open","high","low","close","volume","quote_volume","trades",
        "taker_buy_base","taker_buy_quote")}],source=SOURCE)
    return receipt["status"]


def test_lagging_rest_snapshot_of_processed_close_keeps_actor_live_until_a_real_correction(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    active,_=leases(monkeypatch,manager)
    now=[START+20*STEP]
    last=START+19*STEP  # RC 35: the dirty range was the last processed bar.
    closed=last+STEP-1
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:now[0])
    def stored_close():
        return next(row["close"] for row in klines_repo.query_klines(KEY.symbol,KEY.interval) if row["open_time"]==last)
    async def scenario():
        try:
            await runtime.start_existing("cs_source")
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE" and row["sequence"]==20)
            # Restart reload: the same processed bars are written again.
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(20)],source=SOURCE)
            await manager.event_bus.emit(DataEvent(DataEventType.BACKFILL_COMPLETED,KEY))
            # The exchange-confirmed WS close that the run processed...
            ws=_candle(last,DataSource.WEBSOCKET,close="105",volume="10",quote="1000",trades=10,at=closed+97)
            assert kline_sources.record(ws,SPOT)["status"]=="selected"
            # ...then REST reads serve the cache's pre-close snapshot: still
            # settling 2 s after the close, and (a longer lag) after settling.
            pending=_candle(last,DataSource.HTTP,close="104",volume="9",quote="990",trades=9,at=closed+2_000)
            assert pending.data["is_closed"] is False and _observe_and_project(pending)=="stale"
            lagging=_candle(last,DataSource.HTTP,close="104",volume="9",quote="990",trades=9,at=closed+20_000)
            assert lagging.data["is_closed"] is True
            status=_observe_and_project(lagging)
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED,KEY))
            now[0]=END+1
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
            row=await wait_row(store,"cs_source",lambda row:row["sequence"]==25 or row["phase"] in {"REPAIR_REQUIRED","FAILED"})
            assert (row["phase"],row["sequence"],row["error"])==("LIVE",25,None)
            assert (status,stored_close())==("stale",105)
            old=store.load("cs_source")
            # A real exchange correction of the processed bar still stops the run.
            corrected=_candle(last,DataSource.HTTP,close="106",volume="11",quote="1100",trades=11,at=closed+21_000)
            assert _observe_and_project(corrected)=="selected"
            assert stored_close()==106
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED,KEY))
            row=await wait_row(store,"cs_source",lambda row:row["phase"]=="REPAIR_REQUIRED")
            assert row["error"]["code"]=="CONTINUOUS_HISTORY_REVISED"
            assert store.load("cs_source")["checkpoint"]==old["checkpoint"]
        finally:await runtime.shutdown();await manager.event_bus.close()
        assert not active and not runtime.actors
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


def test_rest_only_close_waits_for_settled_read_and_keeps_actor_live(storage,tmp_path,monkeypatch):
    """RC 35 recheck: the WS stream was reconnecting, so REST was the only source."""
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    active,_=leases(monkeypatch,manager)
    bar=START+25*STEP  # the first bar after the stored history
    closed=bar+STEP-1
    now=[END+1]
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:now[0])
    async def scenario():
        try:
            await runtime.start_existing("cs_source")
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE" and row["sequence"]==25)
            # 3.4 s after the close REST serves a pre-close snapshot of the bar.
            now[0]=closed+3_407
            lagging=_candle(bar,DataSource.HTTP,close="104",volume="9",quote="990",trades=9,at=closed+3_407)
            assert _observe_and_project(lagging)=="selected"
            assert not [row for row in klines_repo.query_klines(KEY.symbol,KEY.interval) if row["open_time"]==bar]
            await manager.event_bus.emit(DataEvent(DataEventType.BACKFILL_COMPLETED,KEY))
            row=await wait_row(store,"cs_source",lambda row:row["phase"]!="LIVE")
            assert (row["phase"],row["sequence"],row["error"]["code"])==("CATCHING_UP",25,"CONTINUOUS_SOURCE_GAP")
            # The settled read stores the final bar; the run consumes it once.
            now[0]=closed+20_000
            final=_candle(bar,DataSource.HTTP,close="106",volume="11",quote="1100",trades=11,at=closed+16_000)
            assert _observe_and_project(final)=="selected"
            await manager.event_bus.emit(DataEvent(DataEventType.BACKFILL_COMPLETED,KEY))
            row=await wait_row(store,"cs_source",lambda row:row["sequence"]==26 or row["phase"] in {"REPAIR_REQUIRED","FAILED"})
            assert (row["phase"],row["event_time_ms"],row["error"])==("LIVE",closed,None)
            # Later reads of the same final candle do not revise the processed bar.
            again=_candle(bar,DataSource.HTTP,close="106",volume="11",quote="1100",trades=11,at=closed+40_000)
            assert _observe_and_project(again)=="selected"
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED,KEY))
            await manager.event_bus.emit(DataEvent(DataEventType.BACKFILL_COMPLETED,KEY))
            await asyncio.sleep(0.2)
            assert store.summary("cs_source")["phase"]=="LIVE"
        finally:await runtime.shutdown();await manager.event_bus.close()
        assert not active and not runtime.actors
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


@pytest.mark.parametrize("close_store",[False,True])
def test_repeated_shutdown_cancellation_drains_provider_before_releasing_lease_or_database(storage,tmp_path,monkeypatch,close_store):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    old=store.load("cs_source")["checkpoint"]
    active,_=leases(monkeypatch,manager)
    entered,release=Event(),Event()
    def paused(value):
        provider=factory(value);step=provider.step
        def wait(frame):
            entered.set()
            assert release.wait(10),"test provider was not released"
            return step(frame)
        provider.step=wait
        return provider
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,paused,clock_ms=lambda:END+1)
    async def scenario():
        try:
            await runtime.start_existing("cs_source")
            assert await asyncio.to_thread(entered.wait,10)
            actor=runtime.actors["cs_source"]
            shutdown=asyncio.create_task(runtime.close() if close_store else runtime.shutdown())
            await asyncio.sleep(0)
            assert runtime.closed and actor.stopping
            shutdown.cancel();await asyncio.sleep(0);shutdown.cancel();await asyncio.sleep(0)
            assert not shutdown.done() and active and not store.closed
            release.set()
            with pytest.raises(asyncio.CancelledError):await shutdown
            assert not active and not runtime.actors and actor.executor.snapshot()["active"]==0
            if close_store:
                from app.backtest.continuous_store import ContinuousStrategyStore
                assert store.closed
                recovered=ContinuousStrategyStore(store.path)
                try:
                    assert recovered.load("cs_source")["checkpoint"]==old
                    assert recovered.summary("cs_source")["phase"]=="CATCHING_UP"
                finally:recovered.close()
            else:
                assert store.load("cs_source")["checkpoint"]==old
                assert store.summary("cs_source")["phase"]=="CATCHING_UP"
            store.close()  # No detached strategy write may survive this close.
        finally:
            release.set();await runtime.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


def test_failed_transport_release_retains_owner_and_shutdown_reports_then_retries(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    active,_=leases(monkeypatch,manager)
    release=manager.release_stream;attempts=[]
    async def fail_once(*args,**kwargs):
        attempts.append(1)
        if len(attempts)==1:raise RuntimeError("release-failed")
        return await release(*args,**kwargs)
    monkeypatch.setattr(manager,"release_stream",fail_once)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:END+1)
    async def scenario():
        try:
            await runtime.start_existing("cs_source")
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE")
            with pytest.raises(BacktestError,match="CONTINUOUS_SHUTDOWN_FAILED"):
                await runtime.shutdown()
            assert active and runtime.actors and not store.closed
            assert runtime.diagnostics()["failures"]["cs_source"]["message"]=="release-failed"
            await runtime.shutdown()
            assert not active and not runtime.actors and len(attempts)==2
        finally:await runtime.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


def test_semantic_series_callback_keeps_same_symbol_feeds_separate(storage,tmp_path,monkeypatch):
    from app.data_engine.series_identity import KlineSeriesIdentity
    from app.data_engine.data_manager.models import SeriesKey
    service,_,_,_,store,manager,source,_=source_setup(storage,tmp_path,monkeypatch)
    adjusted=SeriesKey.create(KEY.symbol,KEY.interval,identity=KlineSeriesIdentity.for_exchange("binance",price_adjustment="split_adjusted"))
    async def scenario():
        received=[];arrived=asyncio.Event()
        async def callback(event):received.append(event.key);arrived.set()
        handle=await manager.subscribe_async(callback,symbol=adjusted.symbol,interval=adjusted.interval,
            series_identity=adjusted.identity,event_types={DataEventType.BAR_CLOSED},continuity="gap_aware")
        try:
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,adjusted))
            await asyncio.wait_for(arrived.wait(),5)
            assert received==[adjusted]
        finally:await manager.unsubscribe_async(handle);await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


def test_authorized_start_outlives_cancelled_request_while_setup_is_owned(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    active,calls=leases(monkeypatch,manager)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:END+1)
    async def scenario():
        entered,release=asyncio.Event(),asyncio.Event();ensure=manager.bars.ensure_stream
        async def pending(*args,**kwargs):
            entered.set();await release.wait();return await ensure(*args,**kwargs)
        monkeypatch.setattr(manager.bars,"ensure_stream",pending)
        try:
            request=asyncio.create_task(runtime.start_existing("cs_source"))
            await asyncio.wait_for(entered.wait(),5)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):await request
            assert runtime.starts and runtime.actors
            release.set()
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE")
            assert active and runtime.actors
        finally:
            release.set();await runtime.shutdown();await manager.event_bus.close()
        assert not active and [call[0] for call in calls]==["acquire","release"]
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()


def test_stream_loss_and_retained_gap_wait_before_empty_live_confirmation(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    create_frozen(source,receipt,definition,factory,store)
    leases(monkeypatch,manager)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,factory,clock_ms=lambda:END+1)
    async def scenario():
        try:
            await runtime.start_existing("cs_source")
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE")
            before=store.load("cs_source")["checkpoint"]
            await manager.event_bus.emit(DataEvent(DataEventType.STREAM_ERROR,KEY))
            await wait_row(store,"cs_source",lambda row:row["phase"]=="CATCHING_UP" and row["error"] is not None)
            assert store.load("cs_source")["checkpoint"]==before
            await manager.event_bus.emit(DataEvent(DataEventType.STREAM_STARTED,KEY))
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE")
            for key in ("engine","planner"):
                assert store.load("cs_source")["checkpoint"][key]==before[key]
            gap,_=manager.source_gaps.open(KEY,START,START)
            await manager.event_bus.emit(gap.event())
            await wait_row(store,"cs_source",lambda row:row["phase"]=="CATCHING_UP" and row["error"] is not None)
            bar=manager.bars.query(KEY.symbol,KEY.interval,start_ms=START,end_ms=START,limit=1,auto_backfill=False).bars[0]
            resolved,_=manager.source_gaps.accept(KEY,[bar])
            assert resolved==[gap]
            await manager.event_bus.emit(gap.event(resolved=True))
            await wait_row(store,"cs_source",lambda row:row["phase"]=="LIVE")
            for key in ("engine","planner"):
                assert store.load("cs_source")["checkpoint"][key]==before[key]
            assert store.summary("cs_source")["sequence"]==25
        finally:await runtime.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:source.close();store.close();service.shutdown()
