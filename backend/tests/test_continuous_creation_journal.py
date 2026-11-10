"""Crash windows and stale creation fenced by real source/financial SQLite."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import sqlite3

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.continuous_definition import prepare_definition
from app.backtest.continuous_provider import ContinuousProviderFactory
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.continuous_runtime import ContinuousStrategyRuntime
from app.backtest.errors import BacktestError
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.storage import klines_repo
from app.data_engine.storage.prefix_watches import PrefixAcquisitionChanged
from app.local_data.service import LocalDatasetService
from tests.test_continuous_provider import spec
from tests.test_kline_revision_contract import storage as storage
from tests.test_query_cache_fencing import START,STEP,SOURCE,_row
from tests.test_continuous_strategy_store import create
from tests.test_continuous_strategy_runtime import leases,wait_row

KEY=SeriesKey("BTCUSDT","1m")
CUTOFF=START+20*STEP-1
END=START+25*STEP-1


def journal_setup(storage,tmp_path,*,history=True,max_runs=64):
    manager=DataManager();manager.set_storage(storage)
    klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(25)],source=SOURCE)
    store=ContinuousStrategyStore(tmp_path/'creation.db',max_runs=max_runs)
    definition=prepare_definition(spec(),{"account_model":"SPOT_CASH_V1"},KEY)
    row=store.creations.reserve("request",definition=definition,mode="HISTORY_LIVE" if history else "LIVE_ONLY",
        cutoff_ms=CUTOFF,**({"from_ms":START} if history else {}))
    source=ContinuousMarketBarSource(manager,LocalDatasetService(tmp_path/'owned-inputs'),KEY,clock_ms=lambda:END+1)
    return store,manager,definition,row,source


def ready(store,row,source):
    point=source.register(row["run_id"],from_ms=row["from_ms"])
    row=store.creations.register_watch("request",revision=row["revision"],receipt=point.to_dict())
    if row["mode"]=="HISTORY_LIVE":
        frozen=source.freeze_initial(point,through_ms=row["cutoff_ms"],dataset_id=row["dataset_id"])
        row=store.creations.freeze_input("request",revision=row["revision"],descriptor=frozen.descriptor,proof=frozen.proof.to_dict())
    return store.creations.creation_context("request")


def publish(store,manager,context,factory):
    point=context["receipt"]
    return ContinuousBarHost.create_run(store,context["run_id"],definition=context["definition"],mode=context["mode"],
        data_revision=point.incarnation,event_time_ms=point.through_ms,source_receipt=point,provider_factory=factory,
        creation_request=(context["request_key"],context["revision"]),
        commit_checkpoint=lambda write:manager.bars.prefixes.commit(context["proof"],write,committed_through_ms=point.through_ms))


@pytest.mark.parametrize("history",[False,True])
def test_retry_and_store_restart_keep_first_cutoff_then_continue_same_account(storage,tmp_path,history):
    store,manager,definition,row,source=journal_setup(storage,tmp_path,history=history)
    factory=ContinuousProviderFactory(scratch_root=tmp_path);host=None
    try:
        context=ready(store,row,source);store.close()
        store=ContinuousStrategyStore(tmp_path/'creation.db')
        retry=store.creations.reserve("request",definition=definition,mode=row["mode"],cutoff_ms=END+200_001*STEP,
            **({"from_ms":START} if history else {}))
        assert retry["run_id"]==row["run_id"] and retry["cutoff_ms"]==CUTOFF
        context=store.creations.creation_context("request")
        initial=publish(store,manager,context,factory)
        assert initial["sequence"]==0 and store.creations.describe("request")["phase"]=="COMMITTED"
        assert store.db.execute("SELECT definition_json FROM creation_requests").fetchone()[0] is None
        assert store.creations.list_unstarted()==[row["run_id"]]
        host=ContinuousBarHost.resume(store,row["run_id"],factory)
        while host.row["event_time_ms"]<END:
            source.acquire(host,revealed_through_ms=END,limit=7).apply(host,manager)
        assert host.row["sequence"]==(25 if history else 5) and host.row["phase"]=="LIVE"
        assert store.creations.list_unstarted()==[]
        before=store.load(row["run_id"])
        def forbidden(_):raise AssertionError("Uncertain create must not prepare another provider")
        assert publish(store,manager,context,forbidden)["sequence"]==before["run"]["sequence"]
        assert store.load(row["run_id"])==before and store.creations.list_pending()==[]
        retry=store.creations.reserve("request",definition=definition,mode=row["mode"],cutoff_ms=END,
            **({"from_ms":START} if history else {}))
        assert retry["definition"]==definition and retry["cutoff_ms"]==CUTOFF
    finally:
        if host is not None:host.close()
        source.close();store.close()


def test_first_account_and_intent_commit_or_rollback_together(storage,tmp_path):
    store,manager,_,row,source=journal_setup(storage,tmp_path)
    try:
        context=ready(store,row,source)
        store.db.execute("CREATE TRIGGER fail_intent BEFORE UPDATE ON creation_requests WHEN NEW.phase='COMMITTED' BEGIN SELECT RAISE(ABORT,'intent-write-failure'); END")
        with pytest.raises(sqlite3.IntegrityError,match="intent-write-failure"):
            publish(store,manager,context,ContinuousProviderFactory(scratch_root=tmp_path))
        assert store.list_summaries()==[] and store.db.execute("SELECT count(*) FROM checkpoints").fetchone()[0]==0
        assert store.creations.describe("request")["phase"]=="READY"
        assert manager.bars.prefixes.inspect("strategy:"+row["run_id"])["committed_acquisition"]==0
        store.db.execute("DROP TRIGGER fail_intent")
        publish(store,manager,context,ContinuousProviderFactory(scratch_root=tmp_path))
        assert store.creations.describe("request")["phase"]=="COMMITTED"
    finally:source.close();store.close()


def test_changed_initial_source_cannot_publish_then_explicit_refresh_keeps_cutoff(storage,tmp_path):
    store,manager,_,row,source=journal_setup(storage,tmp_path)
    factory=ContinuousProviderFactory(scratch_root=tmp_path)
    try:
        context=ready(store,row,source)
        def changed(value):
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+3*STEP,220)],source=SOURCE)
            return factory(value)
        with pytest.raises(PrefixAcquisitionChanged):publish(store,manager,context,changed)
        assert store.list_summaries()==[] and store.creations.describe("request")["phase"]=="READY"
        failure=store.creations.fail("request",revision=context["revision"],code="INITIAL_SOURCE_CHANGED",message="Initial preparation source changed")
        retry=store.creations.retry_failed("request",revision=failure["revision"],refresh_input=True)
        assert retry["phase"]=="WATCHED" and retry["cutoff_ms"]==CUTOFF and retry["input"] is None
        from app.data_engine.storage.prefix_watches import PrefixReceipt
        original=PrefixReceipt.from_dict(retry["watch"])
        frozen=source.freeze_initial(original,through_ms=retry["cutoff_ms"],dataset_id=retry["dataset_id"])
        store.creations.freeze_input("request",revision=retry["revision"],descriptor=frozen.descriptor,proof=frozen.proof.to_dict())
        new_context=store.creations.creation_context("request")
        assert new_context["definition"]["initial_snapshot"]["data_epoch"]!=context["definition"]["initial_snapshot"]["data_epoch"]
        def forbidden(_):raise AssertionError("Old preparation cannot start a new provider")
        with pytest.raises(BacktestError):publish(store,manager,context,forbidden)
        publish(store,manager,new_context,factory)
        assert store.creations.describe("request")["phase"]=="COMMITTED"
    finally:source.close();store.close()


def test_failed_creation_reserves_capacity_and_stale_job_cannot_start_provider(storage,tmp_path):
    store,manager,definition,row,source=journal_setup(storage,tmp_path,history=False,max_runs=1)
    try:
        context=ready(store,row,source)
        failure=store.creations.fail("request",revision=context["revision"],code="SOURCE_FAILURE",message="visible failed preparation")
        with pytest.raises(BacktestError):store.creations.creation_context("request")
        with pytest.raises(BacktestError):create(store)
        with pytest.raises(BacktestError):store.creations.reserve("other",definition=definition,mode="LIVE_ONLY",cutoff_ms=END)
        retry=store.creations.retry_failed("request",revision=failure["revision"])
        def forbidden(_):raise AssertionError("Stale creation must fail before starting provider")
        with pytest.raises(BacktestError):publish(store,manager,context,forbidden)
        assert store.list_summaries()==[] and retry["revision"]>context["revision"]
        publish(store,manager,store.creations.creation_context("request"),ContinuousProviderFactory(scratch_root=tmp_path))
        assert len(store.list_summaries())==1
    finally:source.close();store.close()


def test_two_connections_converge_on_one_creation_and_reject_different_code(tmp_path):
    path=tmp_path/'race.db';one=ContinuousStrategyStore(path);two=ContinuousStrategyStore(path)
    definition=prepare_definition(spec(),{"account_model":"SPOT_CASH_V1"},KEY)
    try:
        def reserve(store):return store.creations.reserve("same",definition=definition,mode="LIVE_ONLY",cutoff_ms=CUTOFF)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,[one,two]))
        assert results[0]==results[1] and len(one.creations.list_pending())==1
        changed={**definition,"provider":{**definition["provider"],"parameters":{"fast":4,"slow":5}}}
        with pytest.raises(BacktestError,match="CONTINUOUS_COMMIT_CONFLICT"):
            two.creations.reserve("same",definition=changed,mode="LIVE_ONLY",cutoff_ms=END)
    finally:one.close();two.close()


def test_schema1_upgrade_preserves_existing_financial_state(tmp_path):
    path=tmp_path/'legacy.db';store=ContinuousStrategyStore(path);create(store);before=store.load("cs_test")
    for table in ('continuous_auto_repair','active_continuous_epochs','epoch_result_items','epoch_result_heads','continuous_epochs'):
        store.db.execute('DROP TABLE '+table)
    store.db.execute("DROP TABLE creation_requests")
    store.db.execute("DROP TABLE result_items");store.db.execute("DROP TABLE result_heads")
    store.db.execute("PRAGMA user_version=1");store.close()
    store=ContinuousStrategyStore(path)
    try:
        assert store.db.execute("PRAGMA user_version").fetchone()[0]==5
        assert store.load("cs_test")==before and store.creations.list_pending()==[]
    finally:store.close()


def test_pause_before_first_actor_cancels_durable_initial_start(storage,tmp_path):
    store,manager,_,row,source=journal_setup(storage,tmp_path,history=False)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,ContinuousProviderFactory(scratch_root=tmp_path),clock_ms=lambda:END+1)
    async def scenario():
        try:
            context=ready(store,row,source);publish(store,manager,context,runtime.provider_factory)
            assert store.creations.list_unstarted()==[row["run_id"]]
            paused=await runtime.pause(row["run_id"])
            assert paused["phase"]=="PAUSED" and paused["revision"]==2
            assert store.creations.list_unstarted()==[]
            assert await runtime.pause(row["run_id"])==paused
        finally:source.close();await runtime.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("pause_during_restore",[False,True])
def test_runtime_restore_includes_initial_intent_but_never_overrides_later_pause(storage,tmp_path,monkeypatch,pause_during_restore):
    store,manager,_,row,source=journal_setup(storage,tmp_path,history=False)
    runtime=ContinuousStrategyRuntime(store,manager,source.local_datasets,ContinuousProviderFactory(scratch_root=tmp_path),clock_ms=lambda:END+1)
    active,calls=leases(monkeypatch,manager)
    async def scenario():
        try:
            context=ready(store,row,source);publish(store,manager,context,runtime.provider_factory)
            if pause_during_restore:
                original=runtime.start_existing
                async def raced(run_id,**kwargs):
                    await runtime.pause(run_id)
                    return await original(run_id,**kwargs)
                monkeypatch.setattr(runtime,"start_existing",raced)
            result=await runtime.restore_active()
            if pause_during_restore:
                assert result["started"]==[] and result["not_admitted"][row["run_id"]]["code"]=="CONTINUOUS_COMMIT_CONFLICT"
                assert store.summary(row["run_id"])["phase"]=="PAUSED" and not calls
            else:
                assert result["started"]==[row["run_id"]]
                current=await wait_row(store,row["run_id"],lambda value:value["phase"]=="LIVE")
                assert current["sequence"]==5 and current["generation"]==2
                await runtime.pause(row["run_id"])
                assert (await runtime.restore_active())["started"]==[]
                assert not active and len(calls)==2
        finally:source.close();await runtime.close()
    asyncio.run(scenario())
