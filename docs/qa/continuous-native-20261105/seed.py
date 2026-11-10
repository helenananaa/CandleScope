"""Seed a fresh synthetic saved account through packaged production owners.

This is fixture preparation, not a live-feed or native execution qualification.
The subsequently launched application must use LOCAL_OFFLINE, without patches.
"""
from pathlib import Path
import argparse
import asyncio
import hashlib
import json
import os

parser=argparse.ArgumentParser();parser.add_argument('--profile',required=True);args=parser.parse_args()
profile=Path(args.profile).resolve();assert not profile.exists(),'Preserve existing profile evidence'
profile.mkdir(parents=True);data=profile/'data';data.mkdir()
os.environ.update(CANDLE_DATA_DIR=str(data),KLINES_DB_PATH=str(data/'candlescope.db'),
    BACKTEST_DB_PATH=str(data/'backtest.db'),REPLAY_DB_PATH=str(data/'replay.db'),
    CANDLESCOPE_RUNTIME_MODE='LIVE',BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED='1')

from app.core import config
from app.backtest.service import BacktestService
from app.data_engine.data_manager import DataManager,continuous_strategy
from app.data_engine.data_manager.models import SeriesKey,DataEvent,DataEventType
from app.data_engine.storage import klines_repo
from tests.test_continuous_provider import spec
from tests.test_continuous_strategy_runtime import wait_row
from tests.test_query_cache_fencing import START,STEP,SOURCE,_row

key=SeriesKey.create('BTCUSDT','1m',exchange='binance',market_type='spot')
klines_repo.init_klines_storage()
def write(rows):klines_repo.upsert_klines(key.symbol,key.interval,rows,source=SOURCE,
    exchange=key.exchange,market_type=key.market_type,series_identity=key.identity)
write([_row(START+i*STEP,100+i%7) for i in range(25)])
clock=[START+10*STEP];continuous_strategy.utc_ms=lambda:clock[0]
service=BacktestService.start(config.BACKTEST_SETTINGS)
manager=DataManager();manager.set_storage(klines_repo.KlinesRepoAdapter());leases=set()
async def acquire(*_args,**options):leases.add(options['consumer_id'])
async def release(*_args,**options):leases.discard(options['consumer_id'])
manager.bars.ensure_stream=acquire;manager.release_stream=release
gate=manager.bind_strategy(service);editor=spec(python=True)
request='native/continuous-synthetic';repair_key='native/repair-synthetic'
receipt={'scope':'Synthetic canonical BARs with packaged production Manager/SDK/account; public demand replaced by tracked leases during fixture creation only. Native application is unmodified LOCAL_OFFLINE.',
    'profile':str(profile),'data':str(data),'requestKey':request,'repairKey':repair_key,
    'source':editor['source_text'],'parameters':editor['parameters'],'fromMs':START}
async def quiet(controller):
    async with asyncio.timeout(15):
        while controller.jobs or controller.repairs.busy:await asyncio.sleep(.005)
async def scenario():
    try:
        await gate.start_continuous();controller=gate.continuous;access=gate.continuous_access()
        receipt['packagedModule']=__import__('app.backtest.continuous_controller',fromlist=['x']).__file__
        assert '/Installed App/CandleScope.app/Contents/Resources/backend/' in receipt['packagedModule']
        created=await access.create(request,provider=editor,
            execution={'account_model':'SPOT_CASH_V1','initial_balance':'10000','sizing_policy':'EQUITY_PERCENT_V1',
                'equity_percent':'10','slippage_bps':'0'},series=key,mode='HISTORY_LIVE',from_ms=START)
        run_id=created['run_id'];receipt['runId']=run_id
        await controller.wait_initial(request);await quiet(controller)
        clock[0]=START+25*STEP;await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED,key))
        await wait_row(controller.store,run_id,lambda row:row['phase']=='LIVE' and row['sequence']==25)
        write([_row(START+12*STEP,220)]);await manager.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED,key))
        await wait_row(controller.store,run_id,lambda row:row['phase']=='REPAIR_REQUIRED')
        expected=controller.store.results.identity(controller.store.summary(run_id))
        preview=await access.repair_preview(run_id,expected=expected,resume_after=False)
        assert preview['anchor_sequence']==10 and preview['recompute_bars']==15
        await access.repair(run_id,repair_key,expected=expected,plan_id=preview['plan_id'],resume_after=False,confirmed=True)
        await quiet(controller)
        assert controller.store.epochs.summary(repair_key)['phase']=='COMMITTED'
        assert controller.store.summary(run_id)['phase']=='PAUSED'
        write([_row(START+5*STEP,230)])
        await controller.runtime.start_existing(run_id)
        await wait_row(controller.store,run_id,lambda row:row['phase']=='REPAIR_REQUIRED')
        await quiet(controller)
        receipt.update(saved=controller.store.load(run_id),view=controller.store.results.read(run_id),
            repair=controller.store.epochs.summary(repair_key),preview=preview)
    finally:
        await gate.shutdown();await manager.event_bus.close();service.shutdown()
    receipt['exit']={'allLeasesReleased':not leases,'controllerClosed':gate.continuous.resources_closed,
        'storeClosed':gate.continuous.store.closed}
    assert all(receipt['exit'].values())
asyncio.run(scenario())
receipt['savedSha256']=hashlib.sha256(json.dumps(receipt['saved'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
draft={'schemaVersion':1,'id':'draft-continuous-native-qa','revision':1,'displayName':'QA Saved Continuous SMA',
    'language':'python','source':editor['source_text'],'cursor':{'line':1,'column':1},'createdAt':START,'updatedAt':START}
(profile/'strategy-storage-v1.json').write_text(json.dumps({'schemaVersion':1,'values':{
    'candlescope-strategy-drafts-v1':json.dumps({'schemaVersion':1,'drafts':{draft['id']:draft}})}})+'\n')
(profile/'seed-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'profile':str(profile),'runId':receipt['runId'],'savedSha256':receipt['savedSha256'],'exit':receipt['exit']}))
