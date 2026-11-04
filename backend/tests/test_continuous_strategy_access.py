"""Production Manager/bootstrap and real events/Provider/SQLite; no public feed."""
import asyncio
from threading import Event
from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.backtest.continuous_results import KINDS
from app.core import config
from app.data_engine.data_manager.core import DataManagerCore
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import DataEvent,DataEventType
from app.data_engine.data_manager import continuous_strategy as module
from tests.test_backtest_control_plane import _settings
from tests.test_continuous_controller import market
from tests.test_continuous_provider import spec
from tests.test_continuous_strategy_runtime import wait_row
from tests.test_continuous_strategy_runtime import leases
from tests.test_kline_revision_contract import storage as storage
from tests.test_query_cache_fencing import START,STEP,KEY


def access_setup(storage,tmp_path,monkeypatch,*,count=25):
    manager,active,calls=market(storage,monkeypatch,count=count)
    service=BacktestService.start(_settings(tmp_path),now_ms=1)
    gate=manager.bind_strategy(service)
    now=[START+20*STEP]
    monkeypatch.setattr(module,'utc_ms',lambda:now[0])
    return manager,service,gate,active,calls,now


async def create(access,*,history=True,python=False,key='request'):
    return await access.create(key,provider=spec(python=python),execution={'account_model':'SPOT_CASH_V1'},series=KEY,
        mode='HISTORY_LIVE' if history else 'LIVE_ONLY',**({'from_ms':START} if history else {}))


def empty():return {kind:{} for kind in KINDS}


def apply(packet,values):
    if packet['type']=='reset':
        values.clear();values.update(empty())
    for item in packet.get('items',[]):values[item['kind']][item['index']]=item['value']


async def until(stream,values,predicate):
    async with asyncio.timeout(10):
        while True:
            packet=await anext(stream)
            assert packet['type']!='error',packet
            apply(packet,values)
            if predicate(packet):return packet


def assert_results(controller,run_id,values):
    state=controller.store.load(run_id)['checkpoint']['engine']
    for kind in KINDS:
        expected=state['account']['journal'] if kind=='ledger' else state.get(kind,[])
        assert [row for _,row in sorted(values[kind].items())]==expected,kind


@pytest.mark.parametrize('history',[False,True])
@pytest.mark.parametrize('python',[False,True])
def test_application_bootstrap_binds_actual_controller_and_streams_both_modes_without_view_ownership(storage,tmp_path,monkeypatch,history,python):
    from app import main
    manager,service,gate,active,calls,now=access_setup(storage,tmp_path,monkeypatch)
    state=SimpleNamespace(data_manager_core=manager,data_manager=manager)
    monkeypatch.setattr(main,'app',SimpleNamespace(state=state))
    async def scenario():
        try:
            await main._init_continuous_strategies()
            assert state.continuous_strategy_status['execution_enabled'] and not active
            access=gate.continuous_access();controller=gate.continuous
            assert (await gate.start_continuous())==state.continuous_strategy_status
            accepted=await create(access,history=history,python=python)
            assert 'definition' not in accepted and 'dataset_id' not in accepted
            await controller.wait_initial('request')
            await wait_row(controller.store,accepted['run_id'],lambda row:row['phase']=='LIVE')
            subscription=await access.subscribe(accepted['run_id']);stream=subscription.events();values=empty()
            first=await until(stream,values,lambda packet:packet.get('complete') and packet.get('initial_result_ready'))
            assert first['profile']['execution_enabled'] and first['run']['sequence']==(20 if history else 0)
            assert_results(controller,accepted['run_id'],values)
            now[0]=START+25*STEP
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
            packet=await until(stream,values,lambda packet:packet.get('complete') and packet.get('run',{}).get('sequence')==(25 if history else 5))
            assert packet['type']=='update' and packet['after_checkpoint']>=1
            assert_results(controller,accepted['run_id'],values)
            before=controller.store.load(accepted['run_id'])
            subscription.close();await stream.aclose()
            assert active and not controller.closed and controller.store.load(accepted['run_id'])==before
            catalog=await access.catalog()
            assert catalog['runs'][0]['id']==accepted['run_id'] and catalog['preparations']==[]
            assert (await access.read(accepted['run_id']))['identity']==packet['identity']
        finally:await gate.shutdown();await manager.event_bus.close()
        assert not active and gate._closed
        assert gate.continuous.store.closed
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_offline_bootstrap_reads_saved_account_without_resuming_or_changing_intent(storage,tmp_path,monkeypatch):
    from app import main
    manager,service,gate,active,calls,now=access_setup(storage,tmp_path,monkeypatch)
    async def scenario():
        offline=None
        try:
            await gate.start_continuous();access=gate.continuous_access()
            accepted=await create(access)
            await gate.continuous.wait_initial('request')
            await wait_row(gate.continuous.store,accepted['run_id'],lambda row:row['phase']=='LIVE')
            before=gate.continuous.store.load(accepted['run_id'])
            await gate.shutdown()
            assert not active
            count=len(calls)
            monkeypatch.setattr(config,'RUNTIME_MODE','LOCAL_OFFLINE')
            core=DataManagerCore();offline=core.bind_strategy(service)
            state=SimpleNamespace(data_manager_core=core)
            monkeypatch.setattr(main,'app',SimpleNamespace(state=state))
            await main._init_continuous_strategies()
            assert state.continuous_strategy_status['available'] and not state.continuous_strategy_status['execution_enabled']
            assert offline.continuous.manager is None and offline.continuous.runtime_mode=='LOCAL_OFFLINE'
            saved=offline.continuous_access()
            assert (await saved.read(accepted['run_id']))['run']==before['run']
            sub=await saved.subscribe(accepted['run_id']);stream=sub.events();values=empty()
            packet=await until(stream,values,lambda packet:packet.get('complete'))
            assert packet['profile']=={'runtime_mode':'LOCAL_OFFLINE','execution_enabled':False}
            assert_results(offline.continuous,accepted['run_id'],values)
            sub.close();await stream.aclose()
            with pytest.raises(BacktestError,match='LIVE profile'):await create(saved,key='offline')
            with pytest.raises(BacktestError,match='read-only'):
                await saved.control('request','pause',revision=packet['creation']['revision'])
            assert offline.continuous.store.load(accepted['run_id'])==before
            assert len(calls)==count and not offline.continuous.runtime.actors
        finally:
            if offline is not None:await offline.shutdown()
            await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_chunked_initial_result_restarts_after_concurrent_commit_and_cancelled_archive_drains_all_rows(storage,tmp_path,monkeypatch):
    manager,service,gate,active,_calls,now=access_setup(storage,tmp_path,monkeypatch,count=801)
    now[0]=START+300*STEP
    async def scenario():
        try:
            await gate.start_continuous();access=gate.continuous_access();controller=gate.continuous
            accepted=await create(access)
            await controller.wait_initial('request')
            await wait_row(controller.store,accepted['run_id'],lambda row:row['phase']=='LIVE')
            sub=await access.subscribe(accepted['run_id']);stream=sub.events();values=empty()
            packet=await anext(stream);apply(packet,values)
            assert packet['begin'] and not packet['complete']
            now[0]=START+301*STEP
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
            await wait_row(controller.store,accepted['run_id'],lambda row:row['sequence']==301)
            reset=await anext(stream);apply(reset,values)
            assert reset['type']=='reset' and not values['equity_curve']
            packet=await until(stream,values,lambda packet:packet.get('complete'))
            assert packet['run']['sequence']==301
            assert_results(controller,accepted['run_id'],values)
            baseline=packet['identity']['checkpoint_revision']
            now[0]=START+801*STEP
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
            await wait_row(controller.store,accepted['run_id'],lambda row:row['sequence']==801)
            chunks=[]
            async with asyncio.timeout(10):
                while True:
                    packet=await anext(stream);chunks.append(packet);apply(packet,values)
                    if packet.get('complete'):break
            assert len(chunks)>1 and all(item['type']=='update' and item['after_checkpoint']==baseline for item in chunks)
            assert chunks[0]['begin'] and not chunks[-1]['begin']
            assert_results(controller,accepted['run_id'],values)
            sub.close();await stream.aclose()
            creation=controller.store.creations.describe('request')
            await access.control('request','cancel',revision=creation['revision'],expected=packet['identity'])
            assert not active
            sub=await access.subscribe(accepted['run_id']);stream=sub.events();values=empty();packets=[]
            async with asyncio.timeout(10):
                async for packet in stream:packets.append(packet);apply(packet,values)
            assert len(packets)>1 and not packets[0]['terminal'] and packets[-1]['terminal'] and packets[-1]['complete']
            assert_results(controller,accepted['run_id'],values)
        finally:await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_heartbeats_do_not_poll_results_and_shared_subscription_capacity_is_reclaimed(storage,tmp_path,monkeypatch):
    manager,service,gate,_active,_calls,_now=access_setup(storage,tmp_path,monkeypatch)
    gate.heartbeat_seconds=0.02;gate.max_subscriptions=1
    async def scenario():
        try:
            await gate.start_continuous();access=gate.continuous_access();controller=gate.continuous
            accepted=await create(access)
            await controller.wait_initial('request')
            await wait_row(controller.store,accepted['run_id'],lambda row:row['phase']=='LIVE')
            sub=await access.subscribe(accepted['run_id']);stream=sub.events();values=empty()
            await until(stream,values,lambda packet:packet.get('complete'))
            queries=[];controller.store.db.set_trace_callback(queries.append)
            for _ in range(2):assert (await asyncio.wait_for(anext(stream),1))['type']=='heartbeat'
            assert not queries
            with pytest.raises(BacktestError,match='capacity'):await access.subscribe(accepted['run_id'])
            with pytest.raises(BacktestError,match='capacity'):await gate.subscribe_run('unread')
            sub.close();await stream.aclose()
            assert not access.subscriptions and controller.store.updates.diagnostics()['subscriptions']==0
        finally:await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_shutdown_drains_cancelled_view_read_before_store_and_market_dependencies(storage,tmp_path,monkeypatch):
    manager,service,gate,active,_calls,_now=access_setup(storage,tmp_path,monkeypatch)
    entered,release=Event(),Event()
    async def scenario():
        try:
            await gate.start_continuous();access=gate.continuous_access();controller=gate.continuous
            accepted=await create(access)
            await controller.wait_initial('request')
            await wait_row(controller.store,accepted['run_id'],lambda row:row['phase']=='LIVE')
            original=controller.store.results.read
            def held(*args,**kwargs):
                entered.set();assert release.wait(10)
                return original(*args,**kwargs)
            monkeypatch.setattr(controller.store.results,'read',held)
            read=asyncio.create_task(access.read(accepted['run_id']))
            assert await asyncio.to_thread(entered.wait,10)
            read.cancel()
            with pytest.raises(asyncio.CancelledError):await read
            closing=asyncio.create_task(manager.shutdown());await asyncio.sleep(0)
            closing.cancel();await asyncio.sleep(0);closing.cancel();await asyncio.sleep(0)
            assert not closing.done() and not controller.store.closed and access.pending
            release.set()
            with pytest.raises(asyncio.CancelledError):await closing
            assert controller.resources_closed and not active and not access.pending
            assert access.executor.snapshot()['active']==0
        finally:release.set();await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_start_cancelled_before_binding_releases_profile_and_does_not_open_market(storage,tmp_path,monkeypatch):
    from app.backtest.continuous_inputs import ContinuousInputs,ProfileLease
    manager,service,gate,active,calls,_now=access_setup(storage,tmp_path,monkeypatch)
    entered,release=Event(),Event();original=ContinuousInputs._own_directory
    def held(inputs):
        entered.set();assert release.wait(10)
        return original(inputs)
    monkeypatch.setattr(ContinuousInputs,'_own_directory',held)
    async def scenario():
        try:
            starting=asyncio.create_task(gate.start_continuous())
            assert await asyncio.to_thread(entered.wait,10)
            closing=asyncio.create_task(gate.shutdown());await asyncio.sleep(0)
            assert not closing.done() and gate.continuous is None
            release.set();await closing
            with pytest.raises(asyncio.CancelledError):await starting
            ProfileLease(tmp_path/'continuous-execution.lock').close()
            assert not active and not calls and gate.continuous is None
        finally:release.set();await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


@pytest.mark.parametrize('python',[False,True])
def test_default_new_manager_restores_original_account_then_respects_explicit_pause(storage,tmp_path,monkeypatch,python):
    from app import main
    manager,service,gate,active,_calls,now=access_setup(storage,tmp_path,monkeypatch)
    async def scenario():
        restored=None;other=None
        try:
            await gate.start_continuous();access=gate.continuous_access()
            accepted=await create(access,python=python)
            await gate.continuous.wait_initial('request')
            await wait_row(gate.continuous.store,accepted['run_id'],lambda row:row['phase']=='LIVE')
            before=gate.continuous.store.load(accepted['run_id'])
            await gate.shutdown();assert not active
            other=DataManager();other.set_storage(storage);new_active,_=leases(monkeypatch,other)
            restored=other.bind_strategy(service);now[0]=START+25*STEP
            state=SimpleNamespace(data_manager_core=other,data_manager=other)
            monkeypatch.setattr(main,'app',SimpleNamespace(state=state))
            await main._init_continuous_strategies()
            assert state.continuous_strategy_status['restoration']['started']==[accepted['run_id']]
            await wait_row(restored.continuous.store,accepted['run_id'],lambda row:row['sequence']==25 and row['phase']=='LIVE')
            after=restored.continuous.store.load(accepted['run_id'])
            assert after['run']['generation']==before['run']['generation']+1
            fills=before['checkpoint']['engine']['fills']
            assert fills and after['checkpoint']['engine']['fills'][:len(fills)]==fills
            view=await restored.continuous_access().read(accepted['run_id'])
            creation=restored.continuous.store.creations.summary('request')
            paused=await restored.continuous_access().control('request','pause',revision=creation['revision'],expected=view['identity'])
            assert paused['run']['phase']=='PAUSED' and not new_active
            saved=restored.continuous.store.load(accepted['run_id'])
            await restored.start_continuous()
            assert restored.continuous.store.load(accepted['run_id'])==saved and not new_active
        finally:
            if restored is not None:await restored.shutdown()
            if other is not None:await other.event_bus.close()
            await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_stale_account_control_is_rejected_before_stopping_actor(storage,tmp_path,monkeypatch):
    manager,service,gate,active,_calls,now=access_setup(storage,tmp_path,monkeypatch)
    async def scenario():
        try:
            await gate.start_continuous();access=gate.continuous_access();controller=gate.continuous
            accepted=await create(access)
            await controller.wait_initial('request')
            await wait_row(controller.store,accepted['run_id'],lambda row:row['phase']=='LIVE')
            old=await access.read(accepted['run_id']);creation=controller.store.creations.summary('request')
            now[0]=START+25*STEP;await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
            await wait_row(controller.store,accepted['run_id'],lambda row:row['sequence']==25)
            before=controller.store.load(accepted['run_id'])
            with pytest.raises(BacktestError,match='changed before control'):
                await access.control('request','pause',revision=creation['revision'],expected=old['identity'])
            assert active and controller.store.load(accepted['run_id'])==before
            assert not controller.runtime.actors[accepted['run_id']].stopping
            with pytest.raises(BacktestError,match='full committed identity'):
                await access.control('request','cancel',revision=creation['revision'])
        finally:await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_partial_initialization_streams_progress_then_pause_resume_preserve_financial_prefix(storage,tmp_path,monkeypatch):
    from app.backtest.continuous_runtime import _Actor
    manager,service,gate,active,_calls,now=access_setup(storage,tmp_path,monkeypatch,count=1500)
    now[0]=START+1500*STEP;entered,release=Event(),Event();original=_Actor.step
    def held(actor,*args,**kwargs):
        if actor.host is not None and actor.host.row['sequence']==1000:
            entered.set();assert release.wait(10)
        return original(actor,*args,**kwargs)
    monkeypatch.setattr(_Actor,'step',held)
    async def scenario():
        stream=None
        try:
            await gate.start_continuous();access=gate.continuous_access();controller=gate.continuous
            accepted=await create(access)
            assert await asyncio.to_thread(entered.wait,10)
            sub=await access.subscribe(accepted['run_id']);stream=sub.events()
            progress=await anext(stream)
            assert progress['type']=='initializing' and not progress['initial_result_ready'] and progress['items']==[]
            assert progress['run']['sequence']==1000 and progress['counts']['equity_curve']>0
            saved=controller.store.load(accepted['run_id'])
            creation=controller.store.creations.summary('request')
            pausing=asyncio.create_task(access.control('request','pause',revision=creation['revision'],expected=progress['identity']))
            async with asyncio.timeout(10):
                while not controller.runtime.actors[accepted['run_id']].stopping:await asyncio.sleep(0)
            release.set();paused=await pausing
            assert paused['run']['phase']=='PAUSED' and paused['run']['sequence']==1000 and not active
            assert controller.store.load(accepted['run_id'])['checkpoint']==saved['checkpoint']
            view=await access.read(accepted['run_id'])
            await access.control('request','resume',revision=creation['revision'],expected=view['identity'])
            values=empty()
            final=await until(stream,values,lambda packet:packet.get('complete') and packet.get('initial_result_ready'))
            assert final['run']['sequence']==1500
            assert_results(controller,accepted['run_id'],values)
            assert controller.store.load(accepted['run_id'])['checkpoint']['engine']['fills'][:len(saved['checkpoint']['engine']['fills'])]==saved['checkpoint']['engine']['fills']
        finally:
            release.set()
            if stream is not None:await stream.aclose()
            await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_request_admission_is_finite_and_cancelled_callers_keep_physical_capacity(storage,tmp_path,monkeypatch):
    manager,service,gate,_active,_calls,_now=access_setup(storage,tmp_path,monkeypatch)
    release=Event();entered=Event();callers=[]
    async def scenario():
        try:
            await gate.start_continuous();access=gate.continuous_access();controller=gate.continuous
            accepted=await create(access);await controller.wait_initial('request')
            await wait_row(controller.store,accepted['run_id'],lambda row:row['phase']=='LIVE')
            original=controller.store.results.read
            def held(*args,**kwargs):
                entered.set();assert release.wait(10)
                return original(*args,**kwargs)
            monkeypatch.setattr(controller.store.results,'read',held)
            callers.extend(asyncio.create_task(access.read(accepted['run_id'])) for _ in range(module.MAX_REQUESTS))
            assert await asyncio.to_thread(entered.wait,10)
            async with asyncio.timeout(10):
                while len(access.operations)<module.MAX_REQUESTS:await asyncio.sleep(0)
            with pytest.raises(BacktestError,match='request capacity'):await access.read(accepted['run_id'])
            for caller in callers:caller.cancel()
            await asyncio.gather(*callers,return_exceptions=True)
            assert len(access.operations)==module.MAX_REQUESTS
            release.set()
            await asyncio.gather(*tuple(access.operations))
            assert not access.pending
        finally:release.set();await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_unmarked_private_data_degrades_feature_without_adopting_or_deleting_it(storage,tmp_path,monkeypatch):
    from app import main
    from app.backtest.continuous_inputs import ProfileLease
    manager,service,gate,active,calls,_now=access_setup(storage,tmp_path,monkeypatch)
    foreign=tmp_path/'continuous-strategy-inputs';foreign.mkdir();(foreign/'user-record.csv').write_text('preserve')
    state=SimpleNamespace(data_manager_core=manager,data_manager=manager)
    monkeypatch.setattr(main,'app',SimpleNamespace(state=state))
    async def scenario():
        try:
            await main._init_continuous_strategies()
            assert state.continuous_strategy_status['available'] is False
            assert state.continuous_strategy_status['error']['code']=='CONTINUOUS_INPUT_OWNERSHIP'
            assert gate.continuous is None and not active and not calls
            assert (foreign/'user-record.csv').read_text()=='preserve'
            ProfileLease(tmp_path/'continuous-execution.lock').close()
        finally:await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()


def test_bootstrap_does_not_adopt_failed_or_foreign_live_manager(storage,tmp_path,monkeypatch):
    from app import main
    manager,service,gate,active,calls,_now=access_setup(storage,tmp_path,monkeypatch)
    state=SimpleNamespace(data_manager_core=manager,data_manager=None)
    monkeypatch.setattr(main,'app',SimpleNamespace(state=state))
    async def scenario():
        try:
            await main._init_continuous_strategies()
            assert state.continuous_strategy_status=={'available':False,'execution_enabled':False,'reason':'MARKET_UNAVAILABLE'}
            assert gate.continuous is None and not active and not calls
            assert not (tmp_path/module.DATABASE_NAME).exists()
        finally:await gate.shutdown();await manager.event_bus.close()
    try:asyncio.run(scenario())
    finally:service.shutdown()
