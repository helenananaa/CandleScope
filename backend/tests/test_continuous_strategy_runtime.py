"""Real async market bus, SQLite, Provider and owned serial worker lifecycle.

Only public transport leases are replaced; no remote feed is opened in tests.
"""
import asyncio
from threading import Event

import pytest

from app.backtest.continuous_runtime import ContinuousStrategyRuntime
from app.backtest.errors import BacktestError
from app.data_engine.data_manager.models import DataEvent,DataEventType
from app.data_engine.storage import klines_repo
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
