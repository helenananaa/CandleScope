"""Actual profile/controller/providers, source and financial SQLite; no feeds."""
import asyncio
from dataclasses import replace
import json
import os
import subprocess
import sys
import textwrap
from threading import Event

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.continuous_epochs import ContinuousEpochs
from app.backtest.continuous_publication import ContinuousRepairPublication
from app.backtest.continuous_source_identity import new_source_owner
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from app.data_engine.data_manager.models import DataEvent, DataEventType
from app.data_engine.storage import klines_repo
from app.data_engine.storage.prefix_watches import PrefixReceipt
from app.local_data.service import LocalDatasetService
from tests.test_continuous_controller import market, open_owner, submit
from tests.test_continuous_strategy_runtime import wait_row
from tests.test_kline_revision_contract import storage as storage
from tests.test_query_cache_fencing import START, STEP, SOURCE, KEY, _row


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate(): await asyncio.sleep(.001)


async def revised(owner, manager, now, *, python=False, index=12):
    accepted = await submit(owner, python=python)
    await owner.wait_initial('request')
    await wait_row(owner.store, accepted['run_id'], lambda row: row['phase']=='LIVE')
    await until(lambda: not owner.jobs)
    now[0] = START+25*STEP
    await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED, KEY))
    await wait_row(owner.store, accepted['run_id'], lambda row: row['sequence']==25)
    klines_repo.upsert_klines(KEY.symbol, KEY.interval, [_row(START+index*STEP, 220)], source=SOURCE)
    await manager.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED, KEY))
    await wait_row(owner.store, accepted['run_id'], lambda row: row['phase']=='REPAIR_REQUIRED')
    before = owner.store.load(accepted['run_id'])
    plan = await owner.repair_preview(accepted['run_id'], expected=owner.store.results.identity(before['run']), resume_after=False)
    return accepted, before, plan


async def confirm(owner, before, plan, *, key='repair-1'):
    return await owner.repair(before['run']['id'], key, expected=owner.store.results.identity(before['run']),
        plan_id=plan['plan_id'], resume_after=plan['resume_after'], confirmed=True)


async def finished(owner, key='repair-1'):
    subscription = owner.store.updates.subscribe('repair:'+key)
    try:
        async with asyncio.timeout(15):
            while True:
                subscription.clear_before_read()
                record = owner.store.epochs.request(key)
                if record and record['phase'] in {'COMMITTED','FAILED','CANCELLED'} and (record['progress'] or {}).get('resources_released'):
                    break
                await subscription.wait()
        await until(lambda: not owner.repairs.busy)
        return record
    finally: subscription.close()


def reference(owner, manager, before, tmp_path, *, count=25):
    definition = {**before['definition'], 'source_owner':new_source_owner(before['run']['id'])}
    definition.pop('initial_snapshot', None)
    stage = ContinuousStrategyStore(tmp_path/'reference.sqlite3')
    datasets = LocalDatasetService(tmp_path/'reference-data')
    source = ContinuousMarketBarSource(manager, datasets, KEY, clock_ms=lambda:START+count*STEP)
    host = None
    try:
        point = source.register(before['run']['id'], from_ms=START, definition=definition)
        ContinuousBarHost.create_run(stage, before['run']['id'], definition=definition, mode='HISTORY_LIVE',
            data_revision=point.incarnation, event_time_ms=START-1, provider_factory=owner.runtime.provider_factory, source_receipt=point)
        host = ContinuousBarHost.resume(stage, before['run']['id'], owner.runtime.provider_factory)
        while True:
            batch=source.acquire(host, revealed_through_ms=START+count*STEP-1)
            batch.apply(host, manager)
            if batch.caught_up:break
        return stage.load(before['run']['id'])['checkpoint']
    finally:
        if host: host.close()
        source.close();stage.close()


@pytest.mark.parametrize('python',[False,True])
@pytest.mark.parametrize('index',[5,12])
def test_confirmed_full_and_suffix_repairs_keep_account_and_match_fresh_corrected_provider(storage,tmp_path,monkeypatch,python,index):
    manager,active,_ = market(storage,monkeypatch)
    now = [START+10*STEP]
    async def scenario():
        owner = await open_owner(tmp_path,manager,now)
        try:
            accepted,before,plan = await revised(owner,manager,now,python=python,index=index)
            assert plan['full_reinitialization'] is (index==5)
            assert plan['anchor_sequence']==(0 if index==5 else 10)
            first = await confirm(owner,before,plan)
            record = await finished(owner)
            assert record['phase']=='COMMITTED',record
            after = owner.store.load(accepted['run_id'])
            expected = reference(owner,manager,before,tmp_path)
            assert after['checkpoint']['engine']==expected['engine']
            assert after['checkpoint']['provider']==expected['provider']
            assert after['run']['sequence']==25 and after['run']['phase']=='PAUSED'
            assert after['run']['id']==before['run']['id'] and after['run']['generation']>before['run']['generation']
            assert after['run']['data_revision']!=before['run']['data_revision']
            assert manager.bars.prefixes.inspect(plan['source']['owner']) is None
            assert manager.bars.prefixes.inspect(record['source_owner']) is not None
            assert not (tmp_path/'continuous-strategy-repairs'/record['id']).exists()
            assert (await confirm(owner,before,plan))['id']==first['id']
            assert owner.store.load(accepted['run_id'])==after and not active
            if index==5:
                assert after['definition']['initial_snapshot']['dataset_id']!=before['definition']['initial_snapshot']['dataset_id']
                assert (owner.inputs.datasets.root/before['definition']['initial_snapshot']['dataset_id']).exists()
        finally:await owner.close();await manager.event_bus.close()
        assert not active and not list(tmp_path.glob('candlescope-continuous-*'))
    asyncio.run(scenario())


def test_confirmation_rejects_changed_range_and_requires_explicit_consent(storage,tmp_path,monkeypatch):
    manager,active,_ = market(storage,monkeypatch);now=[START+10*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,plan=await revised(owner,manager,now)
            with pytest.raises(BacktestError,match='explicit confirmation'):
                await owner.repair(before['run']['id'],'unconfirmed',expected=plan['expected'],plan_id=plan['plan_id'],resume_after=False,confirmed=False)
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+5*STEP,230)],source=SOURCE)
            with pytest.raises(BacktestError,match='Source changed'):
                await confirm(owner,before,plan)
            assert not owner.repairs.busy and owner.store.epochs.pending()==[]
            assert owner.store.load(before['run']['id'])==before
        finally:await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_disconnected_confirm_caller_cannot_cancel_accepted_job_or_admit_another_preparation(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    entered,release=Event(),Event();original=ContinuousEpochs.reserve
    def held(self,*args,**kwargs):
        result=original(self,*args,**kwargs);entered.set();assert release.wait(15);return result
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,plan=await revised(owner,manager,now)
            monkeypatch.setattr(ContinuousEpochs,'reserve',held)
            caller=asyncio.create_task(confirm(owner,before,plan))
            assert await asyncio.to_thread(entered.wait,10)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):await caller
            assert owner.repairs.busy and owner.store.epochs.request('repair-1')['phase']=='REQUESTED'
            with pytest.raises(BacktestError,match='capacity'):
                await submit(owner,key='another')
            with pytest.raises(BacktestError,match='capacity'):
                await confirm(owner,before,plan,key='another-repair')
            release.set()
            assert (await finished(owner))['phase']=='COMMITTED'
        finally:release.set();await owner.close();await manager.event_bus.close()
        assert not active
    asyncio.run(scenario())


@pytest.mark.parametrize('boundary',['stage','publish'])
def test_shutdown_drains_physical_worker_then_restore_uses_original_confirmed_cutoff(storage,tmp_path,monkeypatch,boundary):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    entered,release=Event(),Event();original=getattr(ContinuousRepairPublication,boundary)
    def held(self,*args,**kwargs):
        entered.set();assert release.wait(15);return original(self,*args,**kwargs)
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,plan=await revised(owner,manager,now)
            monkeypatch.setattr(ContinuousRepairPublication,boundary,held)
            accepted=await confirm(owner,before,plan)
            assert await asyncio.to_thread(entered.wait,10)
            closing=asyncio.create_task(owner.close());await asyncio.sleep(0);closing.cancel();await asyncio.sleep(0)
            assert not closing.done() and not owner.store.closed
            with pytest.raises(BacktestError,match='owner holds'):
                await open_owner(tmp_path,manager,now)
            release.set()
            try:await closing
            except asyncio.CancelledError:pass
            assert owner.resources_closed and not active
            monkeypatch.setattr(ContinuousRepairPublication,boundary,original)
            now[0]=START+30*STEP
            owner=await open_owner(tmp_path,manager,now)
            restored=await owner.restore()
            assert restored['repairing']==[before['run']['id']]
            record=await finished(owner)
            assert record['id']==accepted['id'] and record['phase']=='COMMITTED'
            row=owner.store.summary(before['run']['id'])
            assert row['phase']=='PAUSED' and row['sequence']==25 and row['event_time_ms']==plan['through_ms']
            assert owner.store.load(row['id'])['checkpoint']['engine']==reference(owner,manager,before,tmp_path)['engine']
        finally:release.set();await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_durable_cancel_waits_for_worker_and_discards_only_unpublished_new_account(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    entered,release=Event(),Event();original=ContinuousRepairPublication.publish
    def held(self,*args,**kwargs):
        entered.set();assert release.wait(15);return original(self,*args,**kwargs)
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,plan=await revised(owner,manager,now)
            monkeypatch.setattr(ContinuousRepairPublication,'publish',held)
            record=await confirm(owner,before,plan)
            assert await asyncio.to_thread(entered.wait,10)
            cancelling=asyncio.create_task(owner.cancel_repair('repair-1',expected=plan['expected']))
            await until(lambda: owner.store.epochs.describe(record['id'])['phase']=='CANCELLED')
            assert not cancelling.done() and not owner.store.closed
            assert owner.store.load(before['run']['id'])==before
            release.set();result=await cancelling
            assert result['phase']=='CANCELLED' and result['progress']['resources_released']
            assert owner.store.load(before['run']['id'])==before
            assert manager.bars.prefixes.inspect(plan['source']['owner']) is not None
            assert manager.bars.prefixes.inspect(record['source_owner']) is None
            assert not (tmp_path/'continuous-strategy-repairs'/record['id']).exists()
            assert owner.store.db.execute('SELECT count(*) FROM epoch_result_items').fetchone()[0]==0
            assert owner.store.db.execute('SELECT 1 FROM checkpoints WHERE revision=? AND run_id=?',(record['target_revision'],record['run_id'])).fetchone() is None
        finally:release.set();await owner.close();await manager.event_bus.close()
        assert not active
    asyncio.run(scenario())


def test_repair_disk_budget_failure_preserves_old_account_and_releases_only_new_source(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now,repair_options={'max_total_bytes':8192,'max_stage_bytes':4096})
        try:
            _,before,plan=await revised(owner,manager,now)
            accepted=await confirm(owner,before,plan);record=await finished(owner)
            assert record['phase']=='FAILED' and record['error']['code']=='BUDGET_EXCEEDED'
            assert owner.store.load(before['run']['id'])==before
            assert manager.bars.prefixes.inspect(accepted['source_owner']) is None
            assert manager.bars.prefixes.inspect(plan['source']['owner']) is not None
        finally:await owner.close();await manager.event_bus.close()
        assert not active
    asyncio.run(scenario())


def test_repair_waits_for_real_source_completion_without_periodic_queries(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,_=await revised(owner,manager,now)
            klines_repo.delete_klines(KEY.symbol,KEY.interval,start_ms=START+12*STEP,end_ms=START+12*STEP)
            plan=await owner.repair_preview(before['run']['id'],expected=owner.store.results.identity(before['run']),resume_after=False)
            calls=[];original=manager.bars.query
            def counted(*args,**kwargs):calls.append(kwargs);return original(*args,**kwargs)
            monkeypatch.setattr(manager.bars,'query',counted)
            await confirm(owner,before,plan)
            await until(lambda: (owner.store.epochs.request('repair-1')['progress'] or {}).get('waiting')=='SOURCE_GAP')
            count=len(calls);assert count==1
            await asyncio.sleep(.03)
            assert len(calls)==count and owner.store.load(before['run']['id'])==before
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+12*STEP,220)],source=SOURCE)
            await manager.event_bus.emit(DataEvent(DataEventType.BACKFILL_COMPLETED,KEY))
            assert (await finished(owner))['phase']=='COMMITTED'
        finally:await owner.close();await manager.event_bus.close()
        assert not active
    asyncio.run(scenario())


def test_missing_original_source_watch_requires_disclosed_full_reinitialization(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,plan=await revised(owner,manager,now)
            old=PrefixReceipt.from_dict(plan['source']);observed=manager.bars.prefixes.inspect(old.owner)
            manager.bars.prefixes.release(replace(old,acquisition=observed['acquisition']))
            plan=await owner.repair_preview(before['run']['id'],expected=plan['expected'],resume_after=False)
            assert plan['full_reinitialization'] and plan['expanded_range_reason']=='SOURCE_CONTINUITY_UNAVAILABLE'
            await confirm(owner,before,plan)
            assert (await finished(owner))['phase']=='COMMITTED'
            assert owner.store.load(before['run']['id'])['checkpoint']['engine']==reference(owner,manager,before,tmp_path)['engine']
        finally:await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_resume_intent_starts_same_corrected_account_and_catches_only_later_closed_bars(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,_=await revised(owner,manager,now)
            plan=await owner.repair_preview(before['run']['id'],expected=owner.store.results.identity(before['run']),resume_after=True)
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(25,30)],source=SOURCE)
            now[0]=START+30*STEP
            await confirm(owner,before,plan)
            record=await finished(owner)
            assert record['phase']=='COMMITTED' and record['plan']['through_ms']==START+25*STEP-1
            row=await wait_row(owner.store,before['run']['id'],lambda row: row['phase']=='LIVE' and row['sequence']==30)
            assert owner.store.load(row['id'])['checkpoint']['provider']['lastSequence']==30
            assert active=={'strategy:continuous:'+row['id']}
        finally:await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('kind',['unmarked','symlink'])
def test_foreign_staging_is_preserved_and_artifact_cleanup_failure_does_not_hold_application_lease(storage,tmp_path,monkeypatch,kind):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,plan=await revised(owner,manager,now)
            foreign=tmp_path/'continuous-strategy-repairs'
            target=tmp_path/'user-data' if kind=='symlink' else foreign
            target.mkdir();document=target/'notes.txt';document.write_text('local-only user data')
            if kind=='symlink':
                try:foreign.symlink_to(target,target_is_directory=True)
                except OSError:pytest.skip('Host cannot create a directory symlink')
            await confirm(owner,before,plan)
            await until(lambda: not owner.repairs.busy)
            record=owner.store.epochs.request('repair-1')
            assert record['phase']=='FAILED' and record['error']['code']=='CONTINUOUS_INPUT_OWNERSHIP'
            assert record['progress']['physical_resources_released'] and not record['progress']['resources_released']
            assert document.read_text()=='local-only user data' and owner.store.load(before['run']['id'])==before
            assert manager.bars.prefixes.inspect(record['source_owner']) is None
            await owner.close();assert owner.resources_closed and not active
            owner=await open_owner(tmp_path,manager,now)
            restored=await owner.restore()
            assert 'repair:repair-1' in restored['not_admitted']
            assert document.read_text()=='local-only user data'
        finally:await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_pause_cannot_remove_repair_required_financial_fence(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            accepted,before,_=await revised(owner,manager,now)
            await owner.control('request','pause',revision=accepted['revision'] if accepted['phase']=='COMMITTED' else owner.store.creations.describe('request')['revision'])
            assert owner.store.load(before['run']['id'])==before
            with pytest.raises(BacktestError,match='repair resolution'):
                await owner.control('request','resume',revision=owner.store.creations.describe('request')['revision'])
        finally:await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_new_backend_process_restores_accepted_python_repair_from_real_private_account(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    entered,release=Event(),Event();original=ContinuousRepairPublication.stage
    def held(self,*args,**kwargs):
        entered.set();assert release.wait(15);return original(self,*args,**kwargs)
    async def first():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,plan=await revised(owner,manager,now,python=True)
            expected=reference(owner,manager,before,tmp_path)
            monkeypatch.setattr(ContinuousRepairPublication,'stage',held)
            accepted=await confirm(owner,before,plan)
            assert await asyncio.to_thread(entered.wait,10)
            closing=asyncio.create_task(owner.close());await asyncio.sleep(0)
            release.set();await closing
            return before,accepted,expected
        finally:release.set();await owner.close();await manager.event_bus.close()
    before,accepted,expected=asyncio.run(first())
    assert not active
    child=textwrap.dedent('''
        import asyncio,json,os,sys
        from pathlib import Path
        from app.core import config
        from app.data_engine.storage import klines_repo
        from app.data_engine.data_manager import DataManager
        from app.backtest.continuous_controller import ContinuousStrategyController
        from app.backtest.continuous_provider import ContinuousProviderFactory
        from tests.test_continuous_repairs import finished
        config.RUNTIME_MODE='LIVE'
        config.KLINES_DB_PATH=klines_repo.KLINES_DB_PATH=Path(sys.argv[1])
        async def main():
            manager=DataManager();manager.set_storage(klines_repo.KlinesRepoAdapter());active=set()
            async def acquire(*args,**kwargs):active.add(kwargs['consumer_id'])
            async def release(*args,**kwargs):active.discard(kwargs['consumer_id'])
            manager.bars.ensure_stream=acquire;manager.release_stream=release
            owner=await ContinuousStrategyController.open(Path(sys.argv[2]),manager,clock_ms=lambda:int(sys.argv[3]),
                provider_factory=ContinuousProviderFactory(scratch_root=Path(sys.argv[2]).parent))
            try:
                restored=await owner.restore();record=await finished(owner)
                assert record['phase']=='COMMITTED',record
                state=owner.store.load(record['run_id'])
            finally:await owner.close();await manager.event_bus.close()
            assert not active and owner.resources_closed
            print(json.dumps({'pid':os.getpid(),'restored':restored,'record':record,'state':state}))
        asyncio.run(main())
    ''')
    result=subprocess.run([sys.executable,'-B','-c',child,str(klines_repo.KLINES_DB_PATH),str(tmp_path/'continuous.db'),str(START+30*STEP)],
        text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    fresh=json.loads(result.stdout.strip().splitlines()[-1])
    assert fresh['pid']!=os.getpid() and fresh['restored']['repairing']==[before['run']['id']]
    assert fresh['record']['id']==accepted['id'] and fresh['state']['run']['sequence']==25
    assert fresh['state']['run']['phase']=='PAUSED'
    assert fresh['state']['checkpoint']['engine']==expected['engine']
    # Host restore increments the process/session fencing generation once;
    # strategy state and consumed sequence must remain exact across that fence.
    assert fresh['state']['checkpoint']['provider']=={**expected['provider'],'generation':expected['provider']['generation']+1}
    assert not list(tmp_path.glob('candlescope-continuous-*'))


def test_failed_physical_repair_lease_release_keeps_profile_owned_until_retry(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    original=manager.release_stream;broken=[True]
    async def release(*args,**kwargs):
        if broken[0] and kwargs['consumer_id'].startswith('strategy:repair:'):raise OSError('repair physical release failed')
        return await original(*args,**kwargs)
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,plan=await revised(owner,manager,now)
            monkeypatch.setattr(manager,'release_stream',release)
            await confirm(owner,before,plan)
            job=owner.repairs.job;assert job is not None
            with pytest.raises(OSError,match='physical release failed'):await job.task
            assert owner.store.epochs.request('repair-1')['phase']=='COMMITTED'
            with pytest.raises(OSError,match='physical release failed'):await owner.close()
            assert not owner.store.closed and not owner.resources_closed and active and owner.repairs.busy
            with pytest.raises(BacktestError,match='owner holds'):await open_owner(tmp_path,manager,now)
            broken[0]=False;await owner.close()
            assert owner.resources_closed and not active and owner.executor.snapshot()['active']==0
        finally:broken[0]=False;await owner.close();await manager.event_bus.close()
    asyncio.run(scenario())


def test_large_repair_uses_bounded_batches_and_keeps_old_results_until_complete(storage,tmp_path,monkeypatch):
    manager,active,_=market(storage,monkeypatch);now=[START+10*STEP]
    async def scenario():
        owner=await open_owner(tmp_path,manager,now)
        try:
            _,before,_=await revised(owner,manager,now)
            klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(25,1030)],source=SOURCE)
            now[0]=START+1030*STEP
            plan=await owner.repair_preview(before['run']['id'],expected=owner.store.results.identity(before['run']),resume_after=False)
            original=ContinuousBarHost.apply_batch;batches=[]
            def counted(host,events,**kwargs):
                if 'continuous-strategy-repairs' in host.store.path.parts:
                    batches.append(len(events))
                    assert owner.store.load(before['run']['id'])==before
                return original(host,events,**kwargs)
            monkeypatch.setattr(ContinuousBarHost,'apply_batch',counted)
            await confirm(owner,before,plan)
            record=await finished(owner)
            assert record['phase']=='COMMITTED',record
            assert batches==[1000,20]
            after=owner.store.load(before['run']['id'])
            assert after['run']['sequence']==1030 and after['run']['phase']=='PAUSED'
            assert after['checkpoint']['engine']==reference(owner,manager,before,tmp_path,count=1030)['engine']
        finally:await owner.close();await manager.event_bus.close()
        assert not active
    asyncio.run(scenario())
