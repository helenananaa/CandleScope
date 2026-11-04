"""Real source/financial SQLite, Provider and event bus; no public transports."""
import asyncio
import json
import os
import subprocess
import sys
import textwrap
from threading import Event

import pytest

from app.backtest.continuous_controller import ContinuousStrategyController
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.continuous_inputs import ContinuousInputs, ProfileLease
from app.backtest.continuous_provider import ContinuousProviderFactory
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.continuous_creation_journal import ContinuousCreationJournal
from app.backtest.errors import BacktestError
from app.core import config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import DataEvent, DataEventType
from app.data_engine.storage import klines_repo
from tests.test_continuous_provider import spec
from tests.test_kline_revision_contract import storage as storage
from tests.test_query_cache_fencing import START, STEP, SOURCE, KEY, _row
from tests.test_continuous_strategy_runtime import leases, wait_row


def market(storage,monkeypatch,count=25):
    monkeypatch.setattr(config,"RUNTIME_MODE","LIVE")
    manager=DataManager();manager.set_storage(storage)
    if count:klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(count)],source=SOURCE)
    active,calls=leases(monkeypatch,manager)
    return manager,active,calls


async def open_owner(tmp_path,manager,now,**options):
    return await ContinuousStrategyController.open(tmp_path/'continuous.db',manager,
        clock_ms=lambda:now[0],provider_factory=ContinuousProviderFactory(scratch_root=tmp_path),**options)


async def submit(owner,*,history=True,python=False,key="request"):
    return await owner.create(key,provider=spec(python=python),execution={"account_model":"SPOT_CASH_V1"},
        series=KEY,mode="HISTORY_LIVE" if history else "LIVE_ONLY",**({"from_ms":START} if history else {}))


async def creation_phase(owner,phase,key="request"):
    subscription=owner.store.updates.subscribe("creation:"+key)
    try:
        async with asyncio.timeout(10):
            while True:
                subscription.clear_before_read()
                row=owner.store.creations.describe(key)
                if row["phase"]==phase:return row
                await subscription.wait()
    finally:subscription.close()


@pytest.mark.parametrize("history",[False,True])
@pytest.mark.parametrize("python",[False,True])
def test_both_modes_continue_after_view_release_and_profile_restart(storage,tmp_path,monkeypatch,history,python):
    manager,active,calls=market(storage,monkeypatch)
    now=[START+20*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            accepted=await submit(owner,history=history,python=python)
            initial=await asyncio.wait_for(owner.wait_initial("request"),10)
            run_id=accepted["run_id"]
            row=await wait_row(owner.store,run_id,lambda row:row["phase"]=="LIVE")
            assert initial["run"]["event_time_ms"]==accepted["cutoff_ms"]
            assert row["sequence"]==(20 if history else 0)
            current=owner.store.creations.describe("request")
            view=owner.store.updates.subscribe(run_id);view.close()
            now[0]=START+25*STEP
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
            row=await wait_row(owner.store,run_id,lambda value:value["sequence"]==(25 if history else 5))
            saved=owner.store.load(run_id)
            if history:assert saved["checkpoint"]["engine"]["fills"]
            assert (await submit(owner,history=history,python=python))["run_id"]==run_id
            assert owner.store.load(run_id)==saved
            # Runtime acquired before preparation released its own demand.
            acquired=[value[2]["consumer_id"] for value in calls if value[0]=="acquire"]
            released=[value[2]["consumer_id"] for value in calls if value[0]=="release"]
            assert acquired==["strategy:prepare:"+run_id,"strategy:continuous:"+run_id]
            assert released==["strategy:prepare:"+run_id]
            await owner.close()
            assert not active and owner.resources_closed
            assert not list(tmp_path.glob("candlescope-continuous-*"))
            owner=await open_owner(tmp_path,manager,now)
            restored=await owner.restore()
            assert restored["started"]==[run_id]
            await wait_row(owner.store,run_id,lambda value:value["phase"]=="LIVE")
            after=owner.store.load(run_id)
            assert after["checkpoint"]["engine"]==saved["checkpoint"]["engine"]
            assert after["run"]["sequence"]==saved["run"]["sequence"]
            await owner.control("request","pause",revision=current["revision"])
            paused=owner.store.load(run_id)
            assert paused["run"]["phase"]=="PAUSED" and not active
            await owner.close()
            owner=await open_owner(tmp_path,manager,now)
            assert (await owner.restore())["started"]==[]
            assert owner.store.load(run_id)==paused
            assert (await submit(owner,history=history,python=python))["phase"]=="COMMITTED"
            assert not active and owner.store.load(run_id)==paused
        finally:
            await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_missing_history_waits_for_manager_event_and_survives_request_cancel(storage,tmp_path,monkeypatch):
    manager,active,calls=market(storage,monkeypatch,count=0)
    now=[START+20*STEP]
    queries=[]
    original=manager.bars.query
    def counted(*args,**kwargs):queries.append(kwargs);return original(*args,**kwargs)
    monkeypatch.setattr(manager.bars,"query",counted)
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            accepted=await submit(owner)
            waiting=asyncio.create_task(owner.wait_initial("request"))
            row=await creation_phase(owner,"WATCHED")
            # Wait until the exact missing-window query has durably deferred.
            updates=owner.store.updates.subscribe("creation:request")
            try:
                async with asyncio.timeout(10):
                    while not row["error"]:
                        updates.clear_before_read();row=owner.store.creations.describe("request")
                        if not row["error"]:await updates.wait()
            finally:updates.close()
            assert len(queries)==1 and not owner.store.list_summaries()
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):await waiting
            assert active and owner.jobs
            with pytest.raises(BacktestError,match="capacity"):
                await submit(owner,key="rejected")
            assert len(owner.store.creations.list_pending())==1
            # No periodic SQL retry: only an actual Manager completion wakes it.
            await asyncio.sleep(0.03)
            assert len(queries)==1
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(20)],source=SOURCE)
            await manager.event_bus.emit(DataEvent(DataEventType.BACKFILL_COMPLETED,KEY))
            result=await asyncio.wait_for(owner.wait_initial("request"),10)
            assert result["run"]["sequence"]==20 and result["run"]["id"]==accepted["run_id"]
        finally:await owner.close();await manager.event_bus.close()
        assert not active
    asyncio.run(scenario())


def test_prepare_pause_resume_and_cancel_clean_only_owned_unreferenced_inputs(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch,count=0)
    now=[START+20*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            await submit(owner)
            current=await creation_phase(owner,"WATCHED")
            # The journal can advance once while source preparation defers.
            job=owner.jobs["request"];job.request_stop();await job.task
            current=owner.store.creations.describe("request")
            paused=await owner.control("request","pause",revision=current["revision"])
            assert paused["phase"]=="PAUSED" and not active
            assert not owner.jobs and (await submit(owner))["phase"]=="PAUSED"
            resumed=await owner.control("request","resume",revision=paused["revision"])
            assert resumed["cutoff_ms"]==paused["cutoff_ms"]
            job=owner.jobs["request"];job.request_stop();await job.task
            current=owner.store.creations.describe("request")
            private=owner.inputs.datasets.root/current["dataset_id"]
            private.mkdir(parents=True);(private/'reproducible').write_text("unused")
            user_data=tmp_path/'local-data'/'user-import.csv'
            user_data.parent.mkdir();user_data.write_text("must remain")
            cancelled=await owner.control("request","cancel",revision=current["revision"])
            assert cancelled["phase"]=="CANCELLED" and not cancelled["watch"] and not cancelled["input"]
            assert not private.exists() and user_data.read_text()=="must remain"
            assert manager.bars.prefixes.inspect("strategy:"+current["run_id"]) is None
            assert (await submit(owner))["phase"]=="CANCELLED" and not active
            assert owner.store.list_summaries()==[]
        finally:await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_shutdown_during_copy_drains_worker_and_preserves_restart_intent(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch)
    now=[START+20*STEP]
    entered,release=Event(),Event()
    original=ContinuousMarketBarSource.freeze_initial
    def held(source,*args,**kwargs):
        entered.set();assert release.wait(10)
        return original(source,*args,**kwargs)
    monkeypatch.setattr(ContinuousMarketBarSource,"freeze_initial",held)
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            accepted=await submit(owner)
            assert await asyncio.to_thread(entered.wait,10)
            closing=asyncio.create_task(owner.close());await asyncio.sleep(0)
            closing.cancel();await asyncio.sleep(0);closing.cancel();await asyncio.sleep(0)
            assert not closing.done() and active and not owner.store.closed
            with pytest.raises(BacktestError,match="owner holds"):
                await open_owner(tmp_path,manager,now)
            release.set()
            with pytest.raises(asyncio.CancelledError):await closing
            assert owner.resources_closed and not active
            monkeypatch.setattr(ContinuousMarketBarSource,"freeze_initial",original)
            owner=await open_owner(tmp_path,manager,now)
            assert owner.store.creations.describe("request")["phase"]=="WATCHED"
            assert (await owner.restore())["preparing"]==[accepted["run_id"]]
            assert (await asyncio.wait_for(owner.wait_initial("request"),10))["run"]["sequence"]==20
        finally:
            release.set();await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_uncommitted_source_correction_recopies_but_committed_correction_requires_repair(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch)
    now=[START+20*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        factory=owner.runtime.provider_factory;calls=[]
        def amend_once(definition):
            if not calls:klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+3*STEP,220)],source=SOURCE)
            calls.append(1);return factory(definition)
        owner.runtime.provider_factory=amend_once
        try:
            accepted=await submit(owner)
            result=await asyncio.wait_for(owner.wait_initial("request"),10)
            assert result["run"]["sequence"]==20 and len(calls)>=3
            assert len(owner.store.list_summaries())==1
            pinned=owner.store.load(accepted["run_id"])["checkpoint"]
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+2*STEP,230)],source=SOURCE)
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED,KEY))
            await wait_row(owner.store,accepted["run_id"],lambda row:row["phase"]=="REPAIR_REQUIRED")
            assert owner.store.load(accepted["run_id"])["checkpoint"]==pinned
            row=owner.store.creations.describe("request")
            with pytest.raises(BacktestError,match="repair"):
                await owner.control("request","retry",revision=row["revision"],refresh_input=True)
            await owner.control("request","cancel",revision=row["revision"])
            assert owner.store.summary(accepted["run_id"])["phase"]=="CANCELLED"
            assert owner.store.load(accepted["run_id"])["checkpoint"]==pinned
            assert owner.inputs.collect()==[]  # Terminal financial input retained.
            assert not active
        finally:await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_profile_ownership_and_input_preservation(tmp_path):
    store=ContinuousStrategyStore(tmp_path/'run.db')
    try:
        lease=ProfileLease(tmp_path/'lock')
        with pytest.raises(BacktestError,match="owner holds"):ProfileLease(tmp_path/'lock')
        lease.close();ProfileLease(tmp_path/'lock').close()
        foreign=tmp_path/'continuous-strategy-inputs';foreign.mkdir();(foreign/'user.csv').write_text("data")
        with pytest.raises(BacktestError,match="unmarked"):ContinuousInputs(store)
        assert (foreign/'user.csv').read_text()=="data"
        (foreign/'user.csv').unlink()
        inputs=ContinuousInputs(store)
        target=tmp_path/'unrelated';target.mkdir();(target/'keep').write_text("source")
        inputs.datasets.start();(inputs.datasets.root/('local-'+'a'*32)).symlink_to(target,target_is_directory=True)
        with pytest.raises(BacktestError,match="symlink"):inputs.collect()
        assert (target/'keep').read_text()=="source"
    finally:store.close()


def test_preflight_and_local_offline_never_acquire_demand(storage,tmp_path,monkeypatch):
    manager,active,calls=market(storage,monkeypatch)
    now=[START+20*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            with pytest.raises(BacktestError):
                await owner.create("bad",provider={"language":"pyne"},execution={},series=KEY,mode="LIVE_ONLY")
            assert owner.store.creations.list_pending()==[] and not owner.jobs and not calls
            monkeypatch.setattr(config,"RUNTIME_MODE","LOCAL_OFFLINE")
            with pytest.raises(BacktestError,match="LIVE profile"):await submit(owner)
            with pytest.raises(BacktestError,match="LIVE profile"):await owner.restore()
            assert not calls and not active and not owner.jobs
        finally:await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_cancelled_submit_still_owns_reserved_backend_work(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch)
    entered,release=Event(),Event()
    original=ContinuousCreationJournal.reserve
    def held(journal,*args,**kwargs):
        entered.set();assert release.wait(10)
        return original(journal,*args,**kwargs)
    monkeypatch.setattr(ContinuousCreationJournal,"reserve",held)
    async def scenario():
        owner=await open_owner(tmp_path,manager,[START+20*STEP])
        try:
            request=asyncio.create_task(submit(owner))
            assert await asyncio.to_thread(entered.wait,10)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):await request
            assert owner.jobs and not owner.store.list_summaries()
            release.set()
            await asyncio.shield(owner.jobs["request"].reserved)
            result=await asyncio.wait_for(owner.wait_initial("request"),10)
            assert result["run"]["sequence"]==20
            retry=await submit(owner)
            retry["run_id"]="caller-mutation"
            retry["definition"]["configuration"]["initial_balance"]="999999"
            await owner.close()
            assert not active and len(owner.store.updates._subscribers)==0
        finally:release.set();await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_disk_budget_failure_has_no_account_and_explicit_retry_keeps_first_cutoff(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch)
    now=[START+20*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now,input_options={"max_total_bytes":16_384,"max_snapshot_bytes":8192,"min_free_bytes":1})
        try:
            accepted=await submit(owner)
            job=owner.jobs.get("request")
            failed=await creation_phase(owner,"FAILED")
            if job is not None:await job.task
            assert failed["error"]["code"]=="BUDGET_EXCEEDED"
            assert owner.store.list_summaries()==[] and not active
            assert not (owner.inputs.datasets.root/accepted["dataset_id"]).exists()
            owner.inputs.max_total_bytes=2*1024*1024
            owner.inputs.max_snapshot_bytes=1024*1024
            now[0]=START+25*STEP
            await owner.control("request","retry",revision=failed["revision"])
            result=await asyncio.wait_for(owner.wait_initial("request"),10)
            assert result["creation"]["cutoff_ms"]==accepted["cutoff_ms"]
            assert result["run"]["id"]==accepted["run_id"]
            assert result["run"]["sequence"]>=20
            await wait_row(owner.store,accepted["run_id"],lambda row:row["sequence"]==25)
        finally:await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_failed_cleanup_retains_profile_store_and_capacity_until_retry(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch)
    release=manager.release_stream;broken=[True]
    async def fail(*args,**kwargs):
        if broken[0] and kwargs["consumer_id"].startswith("strategy:prepare:"):raise OSError("prepare-release-failed")
        return await release(*args,**kwargs)
    monkeypatch.setattr(manager,"release_stream",fail)
    async def scenario():
        owner=await open_owner(tmp_path,manager,[START+20*STEP])
        try:
            await submit(owner)
            job=owner.jobs.get("request")
            await asyncio.wait_for(owner.wait_initial("request"),10)
            assert job is not None
            with pytest.raises(OSError,match="prepare-release-failed"):await job.task
            with pytest.raises(OSError,match="prepare-release-failed"):await owner.close()
            assert not owner.resources_closed and not owner.store.closed and owner.jobs and active
            with pytest.raises(BacktestError,match="owner holds"):
                await open_owner(tmp_path,manager,[START+20*STEP])
            broken[0]=False
            await owner.close()
            assert not active and owner.resources_closed and owner.store.closed
            assert owner.executor.snapshot()["active"]==0
        finally:broken[0]=False;await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_cancelled_open_releases_store_and_profile_only_after_physical_acquisition(tmp_path,monkeypatch):
    manager=DataManager();entered,release=Event(),Event()
    original=ContinuousInputs._own_directory
    def held(inputs):
        entered.set();assert release.wait(10)
        return original(inputs)
    monkeypatch.setattr(ContinuousInputs,"_own_directory",held)
    async def scenario():
        opening=asyncio.create_task(open_owner(tmp_path,manager,[START+20*STEP]))
        try:
            assert await asyncio.to_thread(entered.wait,10)
            opening.cancel();await asyncio.sleep(0);opening.cancel();await asyncio.sleep(0)
            assert not opening.done()
            with pytest.raises(BacktestError,match="owner holds"):ProfileLease(tmp_path/'continuous-execution.lock')
            release.set()
            with pytest.raises(asyncio.CancelledError):await opening
            ProfileLease(tmp_path/'continuous-execution.lock').close()
        finally:release.set();await manager.event_bus.close()
    asyncio.run(scenario())


def test_committed_before_start_crash_window_restores_without_second_account(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch)
    now=[START+20*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        entered,release=asyncio.Event(),asyncio.Event()
        original=owner._start_committed
        async def held(creation):
            entered.set();await release.wait()
            return await original(creation)
        monkeypatch.setattr(owner,"_start_committed",held)
        try:
            accepted=await submit(owner)
            await asyncio.wait_for(entered.wait(),10)
            before=owner.store.load(accepted["run_id"])
            assert before["run"]["revision"]==1 and before["run"]["phase"]=="PAUSED"
            closing=asyncio.create_task(owner.close());await asyncio.sleep(0)
            release.set();await closing
            assert not active
            owner=await open_owner(tmp_path,manager,now)
            assert owner.store.load(accepted["run_id"])==before
            assert (await owner.restore())["started"]==[accepted["run_id"]]
            result=await asyncio.wait_for(owner.wait_initial("request"),10)
            assert result["run"]["sequence"]==20
            assert len(owner.store.list_summaries())==1
        finally:release.set();await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_fresh_backend_process_reconstructs_python_and_continues_same_financial_account(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch)
    async def first():
        owner=await open_owner(tmp_path,manager,[START+20*STEP])
        try:
            await submit(owner,python=True)
            initial=await asyncio.wait_for(owner.wait_initial("request"),10)
            await wait_row(owner.store,initial["run"]["id"],lambda row:row["phase"]=="LIVE")
            return owner.store.load(initial["run"]["id"])
        finally:await owner.close();await manager.event_bus.close()
    before=asyncio.run(first())
    assert not active
    child=textwrap.dedent('''
        import asyncio,json,os,sys
        from pathlib import Path
        from app.core import config
        from app.data_engine.storage import klines_repo
        from app.data_engine.data_manager import DataManager
        from app.backtest.continuous_controller import ContinuousStrategyController
        from app.backtest.continuous_provider import ContinuousProviderFactory
        from tests.test_continuous_strategy_runtime import wait_row
        config.RUNTIME_MODE='LIVE'
        config.KLINES_DB_PATH=klines_repo.KLINES_DB_PATH=Path(sys.argv[1])
        async def main():
            manager=DataManager();manager.set_storage(klines_repo.KlinesRepoAdapter())
            active=set()
            async def acquire(*args,**kwargs):active.add(kwargs['consumer_id'])
            async def release(*args,**kwargs):active.discard(kwargs['consumer_id'])
            manager.bars.ensure_stream=acquire;manager.release_stream=release
            owner=await ContinuousStrategyController.open(Path(sys.argv[2]),manager,clock_ms=lambda:int(sys.argv[3]),
                provider_factory=ContinuousProviderFactory(scratch_root=Path(sys.argv[2]).parent))
            try:
                result=await owner.restore()
                run_id=result['started'][0]
                await wait_row(owner.store,run_id,lambda row:row['phase']=='LIVE' and row['sequence']==25)
                state=owner.store.load(run_id)
            finally:await owner.close();await manager.event_bus.close()
            assert not active and owner.resources_closed
            print(json.dumps({'pid':os.getpid(),'state':state}))
        asyncio.run(main())
    ''')
    result=subprocess.run([sys.executable,'-B','-c',child,str(klines_repo.KLINES_DB_PATH),
        str(tmp_path/'continuous.db'),str(START+25*STEP)],text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    fresh=json.loads(result.stdout.strip().splitlines()[-1])
    after=fresh["state"]
    assert fresh["pid"]!=os.getpid()
    assert after["run"]["id"]==before["run"]["id"] and after["run"]["sequence"]==25
    assert after["run"]["generation"]==before["run"]["generation"]+1
    fills=before["checkpoint"]["engine"]["fills"]
    assert fills and after["checkpoint"]["engine"]["fills"][:len(fills)]==fills
    assert not list(tmp_path.glob("candlescope-continuous-*"))
