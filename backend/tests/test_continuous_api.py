"""Real ASGI HTTP/WS -> Manager -> source/account; public leases only replaced."""
import asyncio
from concurrent.futures import CancelledError as FutureCancelled
from contextlib import asynccontextmanager
from dataclasses import asdict
import json
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.backtests import router
from app.api.v1.continuous_strategies import MAX_BYTES
from app.backtest.service import BacktestService
from app.core import config
from app.core.operator_origin import trusted_operator_origins
from app.data_engine.data_manager.core import DataManagerCore
from app.data_engine.data_manager.models import DataEvent,DataEventType
from app.data_engine.data_manager import continuous_strategy as access_module
from app.data_engine.storage import klines_repo
from tests.test_backtest_control_plane import _settings
from tests.test_continuous_controller import market
from tests.test_continuous_provider import spec
from tests.test_continuous_results import KINDS
from tests.test_continuous_strategy_runtime import wait_row
from tests.test_kline_revision_contract import storage as storage
from tests.test_query_cache_fencing import START,STEP,KEY,SOURCE,_row

BASE='/api/v1/backtests/continuous'


@pytest.fixture
def api(storage,tmp_path,monkeypatch):
    manager,active,calls=market(storage,monkeypatch,count=25)
    now=[START+20*STEP];monkeypatch.setattr(access_module,'utc_ms',lambda:now[0])
    service=BacktestService.start(_settings(tmp_path),now_ms=1)
    gate=manager.bind_strategy(service)
    def forbidden(*_args,**_kwargs):raise AssertionError('Live creation cannot create a user revision or fake smoke')
    monkeypatch.setattr(service,'create_strategy_revision',forbidden)
    monkeypatch.setattr(service,'smoke_strategy_revision',forbidden)
    @asynccontextmanager
    async def lifespan(app):
        await gate.start_continuous()
        try:yield
        finally:
            await app.state.data_manager_core.shutdown_strategy()
            await gate.shutdown();await manager.event_bus.close()
    app=FastAPI(lifespan=lifespan);app.include_router(router,prefix='/api/v1');app.state.data_manager_core=manager
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(client=client,app=app,manager=manager,gate=gate,service=service,now=now,active=active,calls=calls,tmp=tmp_path)
    finally:service.shutdown()


def payload(*,history=True,python=False):
    return {'mode':'HISTORY_LIVE' if history else 'LIVE_ONLY',
        'provider':spec(python=python),'execution':{'account_model':'SPOT_CASH_V1'},
        'series':{'exchange':KEY.exchange,'market_type':KEY.market_type,'symbol':KEY.symbol,'interval':KEY.interval,
            'identity':asdict(KEY.identity)},**({'from_ms':START} if history else {})}


def create(api,body=None,key='request/test'):
    response=api.client.post(BASE+'/runs',json=payload() if body is None else body,
        headers={'Idempotency-Key':key,'Origin':next(iter(trusted_operator_origins()))})
    assert response.status_code==202,response.text
    return response.json()['creation']


def apply(packet,values):
    if packet.get('type')=='reset' or (packet.get('type')=='snapshot' and packet.get('begin')):
        for collection in values.values():collection.clear()
    for item in packet.get('items',[]):values[item['kind']][item['index']]=item['value']


def full_initial(api,run_id):
    response=api.client.get(f'{BASE}/runs/{run_id}/initial')
    assert response.status_code==200,response.text
    initial=response.json();assert initial['initial_result_ready'],initial
    page=initial['result'];values={kind:{} for kind in KINDS};apply(page,values)
    while page['more']:
        response=api.client.post(f'{BASE}/runs/{run_id}/results/query',json={
            'since_revision':0,'change_cursor':page['next_cursor'],'expected':page['identity']})
        assert response.status_code==200,response.text
        page=response.json();apply(page,values)
    return initial,page,values


def assert_values(controller,run_id,values):
    engine=controller.store.load(run_id)['checkpoint']['engine']
    for kind in KINDS:
        expected=engine['account']['journal'] if kind=='ledger' else engine.get(kind,[])
        assert [value for _,value in sorted(values[kind].items())]==expected,kind


@pytest.mark.parametrize('history',[False,True])
@pytest.mark.parametrize('python',[False,True])
def test_initial_http_to_ws_handoff_catches_injected_tail_without_reexecution(api,history,python):
    accepted=create(api,payload(history=history,python=python));run_id=accepted['run_id'];controller=api.gate.continuous
    initial,page,values=full_initial(api,run_id)
    assert initial['creation']['cutoff_ms']==START+20*STEP-1
    api.now[0]=START+25*STEP
    api.client.portal.call(api.manager.event_bus.emit,DataEvent(DataEventType.BAR_CLOSED,KEY))
    api.client.portal.call(wait_row,controller.store,run_id,lambda row:row['phase']=='LIVE' and row['sequence']==(25 if history else 5))
    before=controller.store.load(run_id)
    after=quote(json.dumps(page['identity'],separators=(',',':')),safe='')
    with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1&after={after}') as ws:
        while True:
            packet=ws.receive_json();assert packet['protocol']=='continuous.v1' and packet['type']!='error',packet
            apply(packet,values)
            if packet.get('complete'):break
        assert packet['run']['sequence']==(25 if history else 5)
        assert_values(controller,run_id,values)
    assert controller.store.load(run_id)==before and api.active
    assert create(api,payload(history=history,python=python))['run_id']==run_id
    assert controller.store.load(run_id)==before
    control=api.client.post(BASE+'/requests/request%2Ftest/control',json={
        'action':'pause','revision':initial['creation']['revision'],'expected':packet['identity']})
    assert control.status_code==200,control.text
    assert control.json()['run']['phase']=='PAUSED'
    assert not api.active


@pytest.mark.parametrize('action',['pause','cancel','resume','retry'])
def test_http_control_cannot_act_on_generation_changed_after_manager_precheck(api,monkeypatch,action):
    accepted=create(api,payload(python=True));run_id=accepted['run_id'];controller=api.gate.continuous
    initial,page,_values=full_initial(api,run_id)
    original=controller.control;restored=[]
    async def interleave(key,command,**kwargs):
        await original(key,'pause',revision=initial['creation']['revision'])
        await original(key,'resume',revision=initial['creation']['revision'])
        await wait_row(controller.store,run_id,lambda row:row['phase']=='LIVE')
        restored.append(controller.store.load(run_id))
        return await original(key,command,**kwargs)
    monkeypatch.setattr(controller,'control',interleave)
    response=api.client.post(BASE+'/requests/request%2Ftest/control',json={
        'action':action,'revision':initial['creation']['revision'],'expected':page['identity']})
    assert response.status_code==409,response.text
    assert response.json()['error']['code']=='CONTINUOUS_COMMIT_CONFLICT'
    assert len(restored)==1 and restored[0]['run']['generation']>page['identity']['generation']
    assert controller.store.load(run_id)==restored[0] and api.active
    assert not controller.runtime.actors[run_id].stopping


def test_http_preflight_validation_rejects_legacy_and_ambiguous_inputs_before_reserving(api):
    cases=[]
    for field,value in [('strategy_revision_id','fake'),('snapshot_hash','fake'),('skip_smoke',True),('cutoff_ms',0)]:
        cases.append({**payload(),field:value})
    cases.extend([{**payload(),'from_ms':True},{**payload(),'mode':'HISTORY'},
        {**payload(),'provider':{'language':'pyne'}},
        {**payload(),'series':{**payload()['series'],'interval':'1s'}}])
    for body in cases:
        response=api.client.post(BASE+'/runs',json=body,headers={'Idempotency-Key':'invalid'})
        assert response.status_code in {400,422},response.text
    assert api.gate.continuous.store.creations.list_pending()==[]
    assert api.gate.continuous.store.list_summaries()==[] and not api.calls
    response=api.client.post(BASE+'/runs',content=b'{"mode":"LIVE_ONLY","mode":"HISTORY_LIVE"}',headers={'Idempotency-Key':'dup'})
    assert response.status_code==400
    response=api.client.post(BASE+'/runs',content=b'{"parameters":{"value":NaN}}',headers={'Idempotency-Key':'nan'})
    assert response.status_code==400
    response=api.client.post(BASE+'/runs',content=b'x'*(MAX_BYTES+1),headers={'Idempotency-Key':'large'})
    assert response.status_code==413


def test_python_origin_gate_and_validation_never_echo_editor_source(api):
    body=payload(python=True)
    for headers in [{'Idempotency-Key':'missing'},{'Idempotency-Key':'untrusted','Origin':'https://not-an-operator.invalid'}]:
        response=api.client.post(BASE+'/runs',json=body,headers=headers)
        assert response.status_code==403,response.text
    body['provider']['unknown']='DO_NOT_ECHO_PRIVATE_EDITOR_TEXT'
    response=api.client.post(BASE+'/runs',json=body,headers={'Idempotency-Key':'invalid'})
    assert response.status_code==422 and 'DO_NOT_ECHO' not in response.text
    assert not api.calls and api.gate.continuous.store.creations.list_pending()==[]


def test_cancelled_initial_view_leaves_backend_preparation_alive_and_then_http_returns_ready(api):
    api.now[0]=START+30*STEP
    accepted=create(api);run_id=accepted['run_id'];controller=api.gate.continuous
    future=api.client.portal.start_task_soon(api.gate.continuous_access().initial,run_id)
    async def waiting():
        async with asyncio.timeout(5):
            while not controller.initial_waiters:await asyncio.sleep(0)
    api.client.portal.call(waiting)
    future.cancel()
    async def released():
        async with asyncio.timeout(5):
            while controller.initial_waiters or api.gate.continuous_access().initial_waiters:await asyncio.sleep(0)
    api.client.portal.call(released)
    assert controller.jobs and not controller.closed and api.active
    klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(25,30)],source=SOURCE)
    api.client.portal.call(api.manager.event_bus.emit,DataEvent(DataEventType.BACKFILL_COMPLETED,KEY))
    initial,_,values=full_initial(api,run_id)
    assert initial['result']['run']['sequence']==30
    assert_values(controller,run_id,values)


def test_source_repair_notification_marks_old_result_stale_without_replacing_it(api):
    accepted=create(api);run_id=accepted['run_id'];controller=api.gate.continuous
    _,page,values=full_initial(api,run_id)
    before=controller.store.load(run_id)['checkpoint']
    with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1') as ws:
        first=ws.receive_json();assert first['type']=='snapshot'
        klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START,230)],source=SOURCE)
        api.client.portal.call(api.manager.event_bus.emit,DataEvent(DataEventType.BAR_AMENDED,KEY))
        while True:
            packet=ws.receive_json();assert packet['type']!='error',packet
            if packet.get('stale') and packet.get('complete'):break
        assert packet['run']['phase']=='REPAIR_REQUIRED'
    current=api.client.get(f'{BASE}/runs/{run_id}/initial').json()
    assert current['result']['stale'] and current['result']['identity']['sequence']==page['identity']['sequence']
    assert controller.store.load(run_id)['checkpoint']==before
    assert_values(controller,run_id,values)


def test_unsupported_stream_protocol_and_unknown_run_release_subscribers(api):
    for protocol,code in [('wrong','PROTOCOL_UNSUPPORTED'),('continuous.v1','CONTINUOUS_RUN_NOT_FOUND')]:
        with api.client.websocket_connect(f'{BASE}/runs/missing/stream?protocol={protocol}') as ws:
            packet=ws.receive_json();assert packet['type']=='error' and packet['error']['code']==code,packet
    assert not api.gate.continuous_access().subscriptions


def test_offline_saved_result_http_ws_are_read_only_and_capabilities_do_not_adopt_market(api,monkeypatch):
    accepted=create(api);run_id=accepted['run_id'];_,_,_values=full_initial(api,run_id)
    before=api.gate.continuous.store.load(run_id)
    api.client.portal.call(api.gate.shutdown)
    monkeypatch.setattr(config,'RUNTIME_MODE','LOCAL_OFFLINE')
    core=DataManagerCore();gate=core.bind_strategy(api.service)
    async def bind():
        api.app.state.data_manager_core=core
        await gate.start_continuous()
    api.client.portal.call(bind)
    caps=api.client.get(BASE+'/capabilities').json()
    assert caps['available'] and not caps['execution_enabled'] and caps['runtime_mode']=='LOCAL_OFFLINE'
    assert api.client.post(BASE+'/runs',json=payload(),headers={'Idempotency-Key':'offline'}).status_code==503
    with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1') as ws:
        packet=ws.receive_json();assert packet['profile']['execution_enabled'] is False
    assert gate.continuous.store.load(run_id)==before and not gate.continuous.runtime.actors


def test_actual_http_disconnect_reclaims_waiter_without_cancelling_preparation(api):
    api.now[0]=START+30*STEP
    accepted=create(api);run_id=accepted['run_id'];controller=api.gate.continuous
    async def drive():
        disconnected=asyncio.Event();messages=[];first=True
        async def receive():
            nonlocal first
            if first:first=False;return {'type':'http.request','body':b'','more_body':False}
            await disconnected.wait();return {'type':'http.disconnect'}
        async def send(packet):messages.append(packet)
        scope={'type':'http','asgi':{'version':'3.0'},'method':'GET','path':f'{BASE}/runs/{run_id}/initial',
            'raw_path':f'{BASE}/runs/{run_id}/initial'.encode(),'query_string':b'','root_path':'',
            'headers':[],'scheme':'http','server':('testserver',80),'client':('127.0.0.1',1234),'http_version':'1.1'}
        task=asyncio.create_task(api.app(scope,receive,send))
        async with asyncio.timeout(5):
            while not controller.initial_waiters:await asyncio.sleep(0)
            disconnected.set();await task
        assert next(item['status'] for item in messages if item['type']=='http.response.start')==499
        assert not controller.initial_waiters and not api.gate.continuous_access().initial_waiters
    api.client.portal.call(drive)
    assert controller.jobs and api.active and not controller.closed


def test_shutdown_cancels_initial_http_view_before_closing_store(api):
    api.now[0]=START+30*STEP
    accepted=create(api);controller=api.gate.continuous
    future=api.client.portal.start_task_soon(api.gate.continuous_access().initial,accepted['run_id'])
    async def waiting():
        async with asyncio.timeout(5):
            while not controller.initial_waiters:await asyncio.sleep(0)
    api.client.portal.call(waiting)
    api.client.portal.call(api.gate.shutdown)
    with pytest.raises((FutureCancelled,asyncio.CancelledError)):future.result(timeout=2)
    assert controller.resources_closed and not controller.initial_waiters and not api.active


def test_protocol_ping_and_rejected_socket_control_do_not_change_account(api):
    accepted=create(api);run_id=accepted['run_id'];full_initial(api,run_id)
    controller=api.gate.continuous;before=controller.store.load(run_id)
    with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1') as ws:
        packet=ws.receive_json();assert packet['type']=='snapshot'
        ws.send_text('ping');assert ws.receive_json()['type']=='pong'
        ws.send_text('{"action":"cancel"}')
        error=ws.receive_json();assert error['type']=='error' and error['terminal']
    assert controller.store.load(run_id)==before and api.active


def test_resume_cursor_expiration_rebuilds_view_and_ahead_cursor_cannot_skip_results(api):
    accepted=create(api);run_id=accepted['run_id'];controller=api.gate.continuous
    _,page,_values=full_initial(api,run_id)
    identity=page['identity']
    # Remove just this optional retained checkpoint; original and current
    # account recovery checkpoints remain. A new financial commit moves current.
    api.now[0]=START+25*STEP
    api.client.portal.call(api.manager.event_bus.emit,DataEvent(DataEventType.BAR_CLOSED,KEY))
    api.client.portal.call(wait_row,controller.store,run_id,lambda row:row['sequence']==25)
    assert identity['checkpoint_revision']!=1
    controller.store.db.execute('DELETE FROM checkpoints WHERE run_id=? AND revision=?',(run_id,identity['checkpoint_revision']))
    after=quote(json.dumps(identity),safe='')
    with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1&after={after}') as ws:
        packet=ws.receive_json()
        assert packet['type']=='snapshot' and packet['resume_reason']=='RESUME_CURSOR_EXPIRED',packet
    future={**identity,'checkpoint_revision':1000000}
    with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1&after={quote(json.dumps(future),safe="")}') as ws:
        packet=ws.receive_json();assert packet['type']=='error' and packet['error']['code']=='CONTINUOUS_COMMIT_CONFLICT'


def test_request_lookup_recovers_lost_create_response_and_unknown_reads_do_not_create_owner(api,tmp_path):
    accepted=create(api)
    lookup=api.client.get(BASE+'/requests/request%2Ftest')
    assert lookup.status_code==200 and lookup.json()['creation']['run_id']==accepted['run_id']
    assert api.client.get(BASE+'/requests/missing').status_code==404
    assert api.client.get(BASE+'/runs/missing/initial').status_code==404
    bare=FastAPI();bare.include_router(router,prefix='/api/v1')
    with TestClient(bare) as client:
        assert client.get(BASE+'/capabilities').status_code==503
    assert not hasattr(bare.state,'data_manager_core')


@pytest.mark.parametrize('body',[b'{"x":1e999}',b'{"x":"\\ud800"}',b'{"x":'+b'['*70+b'0'+b']'*70+b'}'])
def test_nonfinite_unpaired_unicode_and_excessive_structure_are_rejected_before_data_work(api,body):
    response=api.client.post(BASE+'/runs',content=body,headers={'Idempotency-Key':'invalid'})
    assert response.status_code==400,response.text
    assert not api.calls and api.gate.continuous.store.creations.list_pending()==[]


def test_current_frontend_sdk_signal_template_and_equity_policy_execute_through_continuous_api(api):
    frontend=Path(__file__).resolve().parents[2]/'frontend/src/features/backtest/chart-tester/chartStrategyTesterUiModel.ts'
    source=json.loads(re.search(r'export const PYTHON_SMA_SOURCE = ("(?:[^"\\]|\\.)*");',frontend.read_text()).group(1))
    body=payload(python=True);body['provider'].update(source_text=source,output_mode='SIGNAL')
    body['execution'].update(initial_balance='10000',sizing_policy='EQUITY_PERCENT_V1',equity_percent='10',taker_fee_bps='0',maker_fee_bps='0',slippage_bps='1')
    accepted=create(api,body,key='current-editor/signal')
    _initial,_page,values=full_initial(api,accepted['run_id'])
    assert_values(api.gate.continuous,accepted['run_id'],values)
    assert len(values['fills'])>0
