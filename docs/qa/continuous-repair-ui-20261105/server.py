"""Controlled browser fixture: real production repair route/owner/SDK/account.

Use a new isolated --root and loopback ports. Only public transport demand is
replaced; local canonical observations and API responses are never substituted.
QA controls inject revisions and hold actual work at deterministic boundaries.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--port',type=int,default=23181)
args=parser.parse_args();root=Path(args.root).resolve()
if root.exists():raise RuntimeError('Preserve previous fixture data: use a fresh root')
root.mkdir(parents=True)
os.environ['CANDLE_DATA_DIR']=str(root/'data')
os.environ['BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED']='1'

from fastapi import FastAPI,Request
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.backtests import router
from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.continuous_epochs import ContinuousEpochs
from app.backtest.continuous_publication import ContinuousRepairPublication
from app.backtest.continuous_provider import ContinuousProviderFactory
from app.backtest.continuous_source_identity import new_source_owner
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.service import BacktestService
from app.core import config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.core import DataManagerCore
from app.data_engine.data_manager import continuous_strategy
from app.data_engine.data_manager.models import DataEvent,DataEventType
from app.data_engine.storage import klines_repo
from app.local_data.service import LocalDatasetService
from tests.test_backtest_control_plane import _settings
from tests.test_continuous_provider import spec
from tests.test_continuous_strategy_runtime import wait_row
from tests.test_query_cache_fencing import START,STEP,KEY,SOURCE,_row
import uvicorn

config.RUNTIME_MODE='LIVE'
config.KLINES_DB_PATH=klines_repo.KLINES_DB_PATH=root/'canonical.sqlite3'
klines_repo.init_klines_storage()
klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(25)],source=SOURCE)
clock=[START+10*STEP];continuous_strategy.utc_ms=lambda:clock[0]
service=BacktestService.start(_settings(root/'profile'),now_ms=1)
state={'run_id':None,'active':set(),'closing':False,'reservation_waiting':False,'processes':[]}
original_factory=ContinuousProviderFactory.__call__
def tracked_provider(self,definition):
    provider=original_factory(self,definition);prepare=provider.prepare
    def started(context):
        result=prepare(context)
        process=getattr(getattr(provider,'runner',None),'_process',None)
        if process is not None:state['processes'].append(process)
        return result
    provider.prepare=started
    return provider
ContinuousProviderFactory.__call__=tracked_provider
hold_reservation=threading.Event();hold_publish=threading.Event()
original_reserve=ContinuousEpochs.reserve;original_publish=ContinuousRepairPublication.publish
def reserve(self,*values,**options):
    while hold_reservation.is_set() and not state['closing']:
        state['reservation_waiting']=True;threading.Event().wait(.025)
    state['reservation_waiting']=False
    return original_reserve(self,*values,**options)
def publish(self,*values,**options):
    while hold_publish.is_set() and not state['closing']:
        options.get('check_stopping',lambda:None)();threading.Event().wait(.025)
    return original_publish(self,*values,**options)
ContinuousEpochs.reserve=reserve;ContinuousRepairPublication.publish=publish

def market():
    manager=DataManager();manager.set_storage(klines_repo.KlinesRepoAdapter())
    async def acquire(*_args,**options):state['active'].add(options['consumer_id'])
    async def release(*_args,**options):state['active'].discard(options['consumer_id'])
    manager.bars.ensure_stream=acquire;manager.release_stream=release
    return manager

async def quiet():
    owner=app.state.data_manager_core.strategy.continuous
    async with asyncio.timeout(15):
        while owner.jobs or owner.repairs.busy:await asyncio.sleep(.005)
    return owner

async def new_run():
    owner=await quiet()
    if state['run_id']:
        old=owner.store.summary(state['run_id'])
        if old['phase'] in {'LIVE','CATCHING_UP'}:await owner.runtime.pause(old['id'])
    clock[0]=START+10*STEP
    access=app.state.data_manager_core.strategy.continuous_access()
    created=await access.create('browser/'+uuid4().hex,provider=spec(python=True),
        execution={'account_model':'SPOT_CASH_V1','initial_balance':'10000','sizing_policy':'EQUITY_PERCENT_V1',
            'equity_percent':'10','slippage_bps':'0'},series=KEY,mode='HISTORY_LIVE',from_ms=START)
    await owner.wait_initial(created['request_key']);await wait_row(owner.store,created['run_id'],lambda row:row['phase']=='LIVE')
    await quiet();clock[0]=START+25*STEP
    await app.state.data_manager_core.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
    await wait_row(owner.store,created['run_id'],lambda row:row['sequence']==25)
    state['run_id']=created['run_id']
    return {'run_id':state['run_id']}

@asynccontextmanager
async def lifespan(app):
    manager=market();app.state.data_manager_core=manager
    await manager.bind_strategy(service).start_continuous();await new_run()
    try:yield
    finally:
        state['closing']=True;hold_publish.clear();hold_reservation.clear()
        await app.state.data_manager_core.shutdown_strategy()
        if hasattr(app.state.data_manager_core,'event_bus'):await app.state.data_manager_core.event_bus.close()
        service.shutdown()
        controller=app.state.data_manager_core.strategy.continuous
        (root/'exit.json').write_text(json.dumps({'all_transport_leases_released':not state['active'],
            'controller_resources_closed':controller.resources_closed,'store_closed':controller.store.closed,
            'sdk_processes':[{'pid':process.pid,'returncode':process.poll()} for process in state['processes']],
            'all_sdk_processes_exited':all(process.poll() is not None for process in state['processes']),
            'transport_scope':'Public stream demand replaced by controlled leases; no exchange-feed qualification'},indent=2)+'\n')

app=FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=config.CORS_ORIGINS,allow_methods=['*'],allow_headers=['*'])
app.include_router(router,prefix='/api/v1')
@app.get('/_qa/bootstrap')
async def bootstrap():return {'run_id':state['run_id']}
@app.post('/_qa/new')
async def create():return await new_run()
@app.post('/_qa/hold')
async def hold(request:Request):
    body=await request.json()
    (hold_publish.set if body.get('publish') else hold_publish.clear)()
    (hold_reservation.set if body.get('reservation') else hold_reservation.clear)()
    return {'ok':True}
@app.post('/_qa/amend')
async def amend(request:Request):
    body=await request.json();owner=await quiet();index=int(body['index'])
    klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+index*STEP,float(body.get('close',220)))],source=SOURCE)
    await app.state.data_manager_core.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED,KEY))
    if owner.store.summary(state['run_id'])['phase']=='PAUSED':await owner.runtime.start_existing(state['run_id'])
    await wait_row(owner.store,state['run_id'],lambda row:row['phase']=='REPAIR_REQUIRED')
    return {'ok':True}
@app.post('/_qa/append')
async def append():
    owner=await quiet()
    klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(25,30)],source=SOURCE)
    clock[0]=START+30*STEP
    await app.state.data_manager_core.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,KEY))
    await wait_row(owner.store,state['run_id'],lambda row:row['sequence']==30)
    return {'ok':True}
@app.get('/_qa/inspect')
async def inspect():
    owner=app.state.data_manager_core.strategy.continuous;value=owner.store.load(state['run_id'])
    wire=json.dumps(value,sort_keys=True,separators=(',',':'))
    return {'run':value['run'],'financial_sha256':hashlib.sha256(wire.encode()).hexdigest(),
        'epochs':len(owner.store.epochs.pending()),'reservation_waiting':state['reservation_waiting'],
        'active_leases':sorted(state['active']),'repair':owner.store.epochs.latest_summary(state['run_id'])}
@app.get('/_qa/proof')
async def proof():
    owner=await quiet();saved=owner.store.load(state['run_id']);run_id=state['run_id']
    def compare():
        definition={**saved['definition'],'source_owner':new_source_owner(run_id)};definition.pop('initial_snapshot',None)
        private=ContinuousStrategyStore(root/('proof-'+uuid4().hex+'.sqlite3'))
        source=ContinuousMarketBarSource(app.state.data_manager_core,LocalDatasetService(root/'reference-input'),KEY,clock_ms=lambda:clock[0])
        host=None
        try:
            point=source.register(run_id,from_ms=START,definition=definition)
            ContinuousBarHost.create_run(private,run_id,definition=definition,mode='HISTORY_LIVE',data_revision=point.incarnation,
                event_time_ms=START-1,provider_factory=owner.runtime.provider_factory,source_receipt=point)
            host=ContinuousBarHost.resume(private,run_id,owner.runtime.provider_factory)
            while True:
                batch=source.acquire(host,revealed_through_ms=clock[0]-1);batch.apply(host,app.state.data_manager_core)
                if batch.caught_up:break
            expected=private.load(run_id)['checkpoint'];actual=saved['checkpoint']
            return {'financial_equal':actual['engine']==expected['engine'],
                'provider_state_equal':{k:v for k,v in actual['provider'].items() if k!='generation'}=={k:v for k,v in expected['provider'].items() if k!='generation'},
                'actual_provider_generation':actual['provider']['generation'],'reference_provider_generation':expected['provider']['generation'],
                'sequence':saved['run']['sequence'],'run_id':run_id,'phase':saved['run']['phase']}
        finally:
            if host:
                host.close();app.state.data_manager_core.bars.prefixes.release(host.source_receipt)
            source.close();private.close()
    return await asyncio.to_thread(compare)
@app.post('/_qa/offline')
async def offline():
    await quiet();await app.state.data_manager_core.shutdown_strategy()
    await app.state.data_manager_core.event_bus.close()
    config.RUNTIME_MODE='LOCAL_OFFLINE';core=DataManagerCore();app.state.data_manager_core=core
    await core.bind_strategy(service).start_continuous()
    return {'offline':True}

if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
