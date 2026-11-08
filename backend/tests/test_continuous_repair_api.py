"""HTTP/WS repair through the production Manager/controller and real providers."""
import asyncio
import json
import sqlite3
from threading import Event, Thread
from urllib.parse import quote

import pytest

from app.backtest.continuous_publication import ContinuousRepairPublication
from app.backtest.continuous_epochs import ContinuousEpochs
from app.core import config
from app.core.operator_origin import trusted_operator_origins
from app.data_engine.data_manager.core import DataManagerCore
from app.data_engine.data_manager.models import DataEvent, DataEventType
from app.data_engine.storage import klines_repo
from tests.test_continuous_api import api as api, BASE, create, payload, full_initial, assert_values, apply
from tests.test_kline_revision_contract import storage as storage
from tests.test_continuous_strategy_runtime import wait_row
from tests.test_continuous_repairs import reference
from tests.test_query_cache_fencing import START, STEP, KEY, SOURCE, _row


ORIGIN=next(iter(trusted_operator_origins()))


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():await asyncio.sleep(.001)


def revised(api, *, python=False, index=12):
    api.now[0]=START+10*STEP
    accepted=create(api,payload(python=python));run_id=accepted['run_id'];controller=api.gate.continuous
    full_initial(api,run_id)
    api.client.portal.call(until,lambda:not controller.jobs)
    api.now[0]=START+25*STEP
    api.client.portal.call(api.manager.event_bus.emit,DataEvent(DataEventType.BAR_CLOSED,KEY))
    api.client.portal.call(wait_row,controller.store,run_id,lambda row:row['sequence']==25)
    klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+index*STEP,220)],source=SOURCE)
    api.client.portal.call(api.manager.event_bus.emit,DataEvent(DataEventType.BAR_AMENDED,KEY))
    api.client.portal.call(wait_row,controller.store,run_id,lambda row:row['phase']=='REPAIR_REQUIRED')
    before=controller.store.load(run_id)
    identity=controller.store.results.identity(before['run'])
    response=api.client.post(f'{BASE}/runs/{run_id}/repair/preview',json={'expected':identity,'resume_after':False})
    assert response.status_code==200,response.text
    return run_id,before,response.json()['plan']


def confirm(api,run_id,plan,*,key='repair/http'):
    return api.client.post(f'{BASE}/runs/{run_id}/repairs',json={
        'expected':plan['expected'],'plan_id':plan['plan_id'],'resume_after':plan['resume_after'],'confirmed':True},
        headers={'Idempotency-Key':key,'Origin':ORIGIN})


def complete(api, key='repair/http'):
    def done():
        record=api.gate.continuous.store.epochs.request(key)
        return record and record['phase'] in {'COMMITTED','FAILED','CANCELLED'} and (record['progress'] or {}).get('resources_released')
    api.client.portal.call(until,done)
    api.client.portal.call(until,lambda:not api.gate.continuous.repairs.busy)
    return api.client.get(BASE+'/repairs/'+quote(key,safe='')).json()['repair']


@pytest.mark.parametrize('python',[False,True])
@pytest.mark.parametrize('index',[5,12])
def test_preview_confirm_http_and_resumable_ws_replace_only_complete_account(api,python,index):
    run_id,before,plan=revised(api,python=python,index=index)
    controller=api.gate.continuous
    assert plan['full_reinitialization'] is (index==5)
    assert plan['anchor_sequence']==(0 if index==5 else 10)
    assert plan['recompute_bars']==(25 if index==5 else 15)
    assert api.client.get(BASE+'/capabilities').json()['repair_available']
    assert not {'source','observed_source','source_owner','initial_snapshot','provider'} & plan.keys()
    accepted=confirm(api,run_id,plan);assert accepted.status_code==202,accepted.text
    record=complete(api);assert record['phase']=='COMMITTED',record
    status=api.client.get(f'{BASE}/runs/{run_id}').json()
    assert status['run']['phase']=='PAUSED' and status['run']['sequence']==25
    assert status['identity']['data_revision']!=plan['expected']['data_revision']
    assert status['repair']['id']==record['id']
    assert api.client.get(f'{BASE}/runs/{run_id}/repairs/latest').json()['repair']==status['repair']
    latest,_,values=full_initial(api,run_id);assert not latest['result']['stale']
    assert_values(controller,run_id,values)
    old_cursor=quote(json.dumps(plan['expected']),safe='')
    values={kind:{} for kind in values}
    with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1&after={old_cursor}') as ws:
        while True:
            packet=ws.receive_json();assert packet['type']!='error',packet
            apply(packet,values)
            if packet.get('complete'):
                assert packet['repair']['id']==record['id']
                assert packet['repair']['phase']=='COMMITTED'
                assert packet['identity']['data_revision']==status['identity']['data_revision']
                break
    assert_values(controller,run_id,values)
    current=controller.store.load(run_id)
    assert confirm(api,run_id,plan).json()['repair']['id']==record['id']
    assert controller.store.load(run_id)==current
    private=controller.store.epochs.describe(record['id'])
    for value in (plan,record,api.client.get(BASE+'/runs').json(),status):
        wire=json.dumps(value)
        assert private['source_owner'] not in wire and 'initial_snapshot' not in wire and 'source_text' not in wire
    corrected=reference(controller,api.manager,before,api.tmp)
    assert current['checkpoint']['engine']==corrected['engine']
    assert current['checkpoint']['provider']==corrected['provider']
    assert not api.active


def test_invalid_confirmation_origin_identity_and_changed_source_are_rejected_before_job(api):
    run_id,before,plan=revised(api)
    endpoint=f'{BASE}/runs/{run_id}/repairs'
    body={'expected':plan['expected'],'plan_id':plan['plan_id'],'resume_after':False,'confirmed':True}
    headers={'Idempotency-Key':'repair/invalid','Origin':ORIGIN}
    for change in [{'confirmed':False},{'confirmed':1},{'resume_after':1},{'source_owner':'foreign'},
                   {'provider':{'source_text':'DO_NOT_EXPOSE_EDITOR'}},{'plan_id':'short'}]:
        response=api.client.post(endpoint,json={**body,**change},headers=headers)
        assert response.status_code==422,response.text
        assert 'DO_NOT_EXPOSE' not in response.text
    assert api.client.post(endpoint,json=body,headers={'Origin':ORIGIN}).status_code==422
    assert api.client.post(endpoint,json=body,headers=[('Idempotency-Key','a'),('Idempotency-Key','b'),('Origin',ORIGIN)]).status_code==422
    assert api.client.post(endpoint,json=body,headers={'Idempotency-Key':'missing-origin'}).status_code==403
    assert api.client.post(endpoint,json=body,headers={'Idempotency-Key':'remote','Origin':'https://foreign.invalid'}).status_code==403
    response=api.client.post(endpoint,json={**body,'expected':{**body['expected'],'sequence':0}},headers=headers)
    assert response.status_code==409,response.text
    klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+5*STEP,230)],source=SOURCE)
    assert api.client.post(endpoint,json=body,headers=headers).status_code==409
    assert api.gate.continuous.store.epochs.pending()==[] and not api.gate.continuous.repairs.busy
    assert api.gate.continuous.store.load(run_id)==before


def test_progress_without_financial_commit_is_delivered_on_existing_socket_and_cancel_preserves_old_account(api,monkeypatch):
    run_id,before,plan=revised(api)
    entered,release=Event(),Event();original=ContinuousRepairPublication.publish
    def held(self,*args,**kwargs):
        entered.set();assert release.wait(10);return original(self,*args,**kwargs)
    monkeypatch.setattr(ContinuousRepairPublication,'publish',held)
    cursor=quote(json.dumps(plan['expected']),safe='');responses=[];thread=None
    try:
        with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1&after={cursor}') as ws:
            assert confirm(api,run_id,plan).status_code==202
            assert entered.wait(10)
            while True:
                packet=ws.receive_json();assert packet['type']!='error',packet
                if (packet.get('repair') or {}).get('phase')=='READY':break
            assert packet['identity']==plan['expected'] and packet['items']==[] and packet['stale']
            assert api.gate.continuous.store.load(run_id)==before
            def cancel():responses.append(api.client.post(BASE+'/repairs/repair%2Fhttp/cancel',json={'expected':plan['expected']}))
            thread=Thread(target=cancel);thread.start()
            api.client.portal.call(until,lambda:api.gate.continuous.store.epochs.request('repair/http')['phase']=='CANCELLED')
            assert thread.is_alive()
            release.set();thread.join(10);assert not thread.is_alive()
            assert responses[0].status_code==200,responses[0].text
            record=responses[0].json()['repair'];assert record['phase']=='CANCELLED'
            assert record['progress']['resources_released']
            while True:
                packet=ws.receive_json();assert packet['type']!='error',packet
                repair=packet.get('repair') or {}
                if repair.get('phase')=='CANCELLED' and (repair.get('progress') or {}).get('resources_released'):break
            assert packet['identity']==plan['expected'] and not packet['terminal']
        assert api.gate.continuous.store.load(run_id)==before and not api.active
    finally:
        release.set()
        if thread is not None:thread.join(10)


def test_saved_repair_metadata_remains_read_only_in_offline_profile(api,monkeypatch):
    run_id,_before,plan=revised(api)
    assert confirm(api,run_id,plan).status_code==202
    record=complete(api);before=api.gate.continuous.store.load(run_id)
    api.client.portal.call(api.gate.shutdown)
    monkeypatch.setattr(config,'RUNTIME_MODE','LOCAL_OFFLINE')
    core=DataManagerCore();gate=core.bind_strategy(api.service)
    async def bind():
        api.app.state.data_manager_core=core
        await gate.start_continuous()
    api.client.portal.call(bind)
    assert not api.client.get(BASE+'/capabilities').json()['repair_available']
    assert api.client.get(f'{BASE}/runs/{run_id}/repairs/latest').json()['repair']['id']==record['id']
    assert api.client.post(f'{BASE}/runs/{run_id}/repair/preview',json={'expected':plan['expected'],'resume_after':False}).status_code==503
    assert confirm(api,run_id,plan).status_code==503
    assert api.client.post(BASE+'/repairs/repair%2Fhttp/cancel',json={'expected':plan['expected']}).status_code==503
    with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1') as ws:
        packet=ws.receive_json();assert packet['repair']['id']==record['id']
        assert not packet['profile']['execution_enabled']
    assert gate.continuous.store.load(run_id)==before


def test_cancelled_asgi_request_does_not_cancel_durably_accepted_repair(api,monkeypatch):
    run_id,_before,plan=revised(api)
    entered,release=Event(),Event();original=ContinuousEpochs.reserve
    def held(self,*args,**kwargs):
        result=original(self,*args,**kwargs);entered.set();assert release.wait(10);return result
    monkeypatch.setattr(ContinuousEpochs,'reserve',held)
    async def drive():
        body=json.dumps({'expected':plan['expected'],'plan_id':plan['plan_id'],'resume_after':False,'confirmed':True}).encode()
        first=True;disconnected=asyncio.Event();messages=[]
        async def receive():
            nonlocal first
            if first:first=False;return {'type':'http.request','body':body,'more_body':False}
            await disconnected.wait();return {'type':'http.disconnect'}
        async def send(packet):messages.append(packet)
        path=f'{BASE}/runs/{run_id}/repairs'
        scope={'type':'http','asgi':{'version':'3.0'},'method':'POST','path':path,'raw_path':path.encode(),
            'query_string':b'','root_path':'','scheme':'http','server':('testserver',80),'client':('127.0.0.1',1234),
            'http_version':'1.1','headers':[(b'content-type',b'application/json'),(b'origin',ORIGIN.encode()),
                (b'idempotency-key',b'repair/disconnected')]}
        task=asyncio.create_task(api.app(scope,receive,send))
        try:
            assert await asyncio.to_thread(entered.wait,5)
            disconnected.set();task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            assert api.gate.continuous.store.epochs.request('repair/disconnected')['phase']=='REQUESTED'
            assert api.gate.continuous.repairs.busy
        finally:release.set()
    try:api.client.portal.call(drive)
    finally:release.set()
    assert complete(api,'repair/disconnected')['phase']=='COMMITTED'


def test_repair_views_do_not_decode_checkpoints_definitions_or_private_source_receipts(api):
    run_id,_before,plan=revised(api)
    assert confirm(api,run_id,plan).status_code==202
    record=complete(api);store=api.gate.continuous.store
    def authorize(action,table,column,*_args):
        if action==sqlite3.SQLITE_READ and (table=='checkpoints' or column=='definition_json'
                or (table=='continuous_epochs' and column in {'source_json','initial_snapshot_json'})):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    store.db.set_authorizer(authorize)
    try:
        for path in [f'/runs/{run_id}',f'/runs/{run_id}/repairs/latest','/repairs/repair%2Fhttp','/runs']:
            response=api.client.get(BASE+path);assert response.status_code==200,response.text
            assert record['id'] in response.text and 'source_owner' not in response.text
        with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1') as ws:
            packet=ws.receive_json();assert packet['repair']['id']==record['id'] and packet['type']!='error'
    finally:store.db.set_authorizer(None)


def test_processed_correction_marks_committed_results_while_catchup_is_busy(api, monkeypatch):
    controller = api.gate.continuous
    api.now[0] = START + 10 * STEP
    run_id = create(api, payload(python=True))['run_id']
    full_initial(api, run_id)
    api.now[0] = START + 20 * STEP
    api.client.portal.call(api.manager.event_bus.emit, DataEvent(DataEventType.BAR_CLOSED, KEY))
    api.client.portal.call(wait_row, controller.store, run_id, lambda row: row['sequence'] == 20)
    api.client.portal.call(until, lambda: not controller.jobs)
    other_id = create(api, payload(history=False), key='request/other')['run_id']
    _, _, values = full_initial(api, run_id)
    full_initial(api, other_id)
    api.client.portal.call(wait_row, controller.store, run_id, lambda row: row['phase'] == 'LIVE')
    api.client.portal.call(wait_row, controller.store, other_id, lambda row: row['phase'] == 'LIVE')
    before = controller.store.load(run_id)
    identity = controller.store.results.identity(before['run'])
    cutoff = START + 25 * STEP - 1
    entered, release = Event(), Event()
    prepare = controller.store.prepare_checkpoint

    def block_checkpoint(checkpoint, *, event_time_ms, run_id=None, **kwargs):
        if run_id == identity['id'] and event_time_ms == cutoff and not entered.is_set():
            entered.set()
            assert release.wait(10)
        return prepare(checkpoint, event_time_ms=event_time_ms, run_id=run_id, **kwargs)

    monkeypatch.setattr(controller.store, 'prepare_checkpoint', block_checkpoint)
    cursor = quote(json.dumps(identity), safe='')
    try:
        with api.client.websocket_connect(f'{BASE}/runs/{run_id}/stream?protocol=continuous.v1&after={cursor}') as ws:
            api.now[0] = cutoff + 1
            api.client.portal.call(api.manager.event_bus.emit, DataEvent(DataEventType.BAR_CLOSED, KEY))
            assert entered.wait(5)
            changed = START + 12 * STEP
            klines_repo.upsert_klines(KEY.symbol, KEY.interval, [_row(changed, 220)], source=SOURCE)
            api.client.portal.call(api.manager.event_bus.emit, DataEvent(DataEventType.BAR_AMENDED, KEY))

            async def wait_stale():
                await asyncio.wait_for(wait_row(controller.store, run_id, lambda row: row['phase'] == 'REPAIR_REQUIRED'), 1)

            api.client.portal.call(wait_stale)
            assert not release.is_set()
            while True:
                stale = ws.receive_json()
                assert stale['type'] != 'error', stale
                if stale.get('complete') and stale.get('stale'):
                    break
            assert stale['identity']['sequence'] == identity['sequence']
            assert stale['identity']['checkpoint_revision'] == identity['checkpoint_revision']
            assert stale['items'] == []
            assert controller.store.load(run_id)['checkpoint'] == before['checkpoint']
            assert_values(controller, run_id, values)
            assert not controller.store.epochs.pending()
            other = api.client.portal.call(wait_row, controller.store, other_id, lambda row: row['event_time_ms'] == cutoff)
            assert other['phase'] == 'LIVE'

            release.set()
            api.client.portal.call(until, lambda: run_id not in controller.runtime.actors)
            response = api.client.post(f'{BASE}/runs/{run_id}/repair/preview',
                                       json={'expected':stale['identity'],'resume_after':False})
            assert response.status_code == 200, response.text
            plan = response.json()['plan']
            assert plan['anchor_sequence'] > 0
            assert confirm(api, run_id, plan).status_code == 202
            completed = complete(api)
            assert completed['phase'] == 'COMMITTED'
            replacement = []
            while True:
                packet = ws.receive_json()
                assert packet['type'] != 'error', packet
                if packet.get('type') == 'reset' or (packet.get('identity') and
                        packet['identity']['data_revision'] != identity['data_revision']):
                    replacement.append(packet)
                    apply(packet, values)
                    if packet.get('complete'):
                        break
            assert replacement[0]['type'] == 'reset'
            assert not replacement[-1]['stale']
            assert replacement[-1]['identity']['event_time_ms'] == cutoff
            assert_values(controller, run_id, values)
            outdated = api.client.post(f'{BASE}/runs/{run_id}/results/query',
                                       json={'since_revision':0,'expected':stale['identity']})
            assert outdated.status_code == 409
            oracle = reference(controller, api.manager, before, api.tmp)
            checkpoint = controller.store.load(run_id)['checkpoint']
            assert checkpoint['engine'] == oracle['engine'] and checkpoint['provider'] == oracle['provider']
            assert controller.store.summary(other_id) == other
    finally:
        release.set()
