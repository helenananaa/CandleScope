"""Real WS -> ingestion -> aggregator -> DM; real REST backfill -> SQLite.
Only fault/scheduling hooks are injected. Prices, times and finality are never
fabricated. Every REST-repaired closed candle is independently reread for parity.
"""
import asyncio, json, logging, os, time, traceback
from pathlib import Path
from app.data_engine.continuity_policy import ContinuityPolicy
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig,CoordinatorConfig
from app.data_engine.data_manager.models import DataEventType
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from app.data_engine.backfill import BackfillEngine,BackfillConfig
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.factory import ExchangeIngestionFactory
from app.data_engine.ingestion.models import StreamType,StreamDescriptor
from app.data_engine.storage import klines_repo
from app.exchanges.ccxt_ext.runtime import get_shared_ccxt_runtime_pool
OUT=Path(os.environ['LIVE_PROBE_OUTPUT']); OUT.mkdir(parents=True,exist_ok=True)
LOG=(OUT/'events.jsonl').open('w'); PHASE='startup'
SPECS=[('okx','futures','BTC-USDT-SWAP')]
REPORT={'started_ms':int(time.time()*1000),'method':'actual websocket outage across one complete 1m candle; real BackfillEngine/Coordinator/SQLite, with 3s repair scheduling delay to observe isolation','errors':[],'consumers':{},'source':{},'gaps':[],'repairs':[]}
def log(kind,**data):
 row={'at':time.time(),'phase':PHASE,'kind':kind,**data}; LOG.write(json.dumps(row,default=str)+'\n'); LOG.flush(); return row
def progress(message):
 print(json.dumps({'at':time.time(),'message':message}),flush=True)
 (OUT/'progress.json').write_text(json.dumps(REPORT,default=str,indent=2))
async def until(predicate,timeout,label):
 end=time.monotonic()+timeout
 while not predicate():
  if time.monotonic()>=end: raise TimeoutError(label)
  await asyncio.sleep(.1)
class Factory(ExchangeIngestionFactory):
 async def start(self,symbol,interval,on_market_event,exchange='binance',market_type='spot',on_gap=None,*,gap_repair_owner='inline'):
  async def source(event):
   row=log('source',exchange=exchange,event=event.to_dict())
   state=REPORT['source'].setdefault(exchange,{'count':0,'closed':0})
   state['count']+=1; state['last_open']=event.data['open_time']; state['last_at']=row['at']
   if event.data.get('is_closed'): state['closed']+=1
   await on_market_event(event)
  async def gap(marker):
   row=log('gap',exchange=exchange,gap=marker.to_dict()); REPORT['gaps'].append(row)
   if on_gap: await on_gap(marker)
  h=await super().start(symbol,interval,source,exchange,market_type,gap,gap_repair_owner=gap_repair_owner)
  async def health(state,reason): log('health',exchange=exchange,state=state.value,reason=reason)
  self._ingress.get_pipeline(h._stream_key).on_health_change(health)
  return h
class Engine(BackfillEngine):
 delay_repairs=False
 async def run(self,*args,**kwargs):
  entry={'started':time.time(),'kwargs':kwargs}; REPORT['repairs'].append(entry)
  log('repair_start',**entry)
  if self.delay_repairs: await asyncio.sleep(3)
  result=await super().run(*args,**kwargs)
  entry['finished']=time.time(); entry['report']=result.to_dict()
  log('repair_done',**entry)
  return result
async def main():
 global PHASE
 klines_repo.KLINES_DB_PATH=OUT/'bars.sqlite'; klines_repo.init_klines_storage()
 store=klines_repo.KlinesRepoAdapter()
 config=IngestionConfig(ws_stale_timeout=180,ws_reconnect_delay_initial=.25,ws_reconnect_delay_max=3)
 factory=Factory(config)
 dm=DataManager(DataManagerConfig(coordinator=CoordinatorConfig(prewarm_symbols=[],prewarm_intervals={})))
 dm.set_storage(store); dm.set_ingestion_factory(factory)
 ingress=await factory._ensure_ingress()
 engine=Engine(BackfillConfig(history_archive_enabled=False),storage=klines_repo.AsyncKlinesRepoAdapter(),transport=ingress.transport,ingestion_config=config)
 dm.wire_backfill_reconciler(engine.reconciler)
 coordinator=BackfillCoordinator(storage=store,bars_backfilled=dm.on_bars_backfilled,emit_event=dm.emit_event,engine=engine,loop=asyncio.get_running_loop(),base_delay_seconds=.5)
 dm.set_backfill_trigger(coordinator.trigger)
 from app.data_engine.data_manager.bar_delivery import source_recovery_handler
 dm.aggregator_bridge.delivery.recover_source=source_recovery_handler(coordinator)
 restore=[]; handles=[]
 def attach(ex,mt,sym,mode,policy):
  label=ex+'.'+mode
  stats=REPORT['consumers'][label]={'events':[],'errors':[]}
  async def event(e):
   row=log('consumer',label=label,event=e.to_dict())
   stats['events'].append(row)
  async def recovery(error):
   stats['errors'].append(log('consumer_error',label=label,error=str(error)))
  handles.append(dm.subscribe(event,symbol=sym,interval='1m',exchange=ex,market_type=mt,
   event_types={DataEventType.BAR_CREATED,DataEventType.BAR_UPDATED,DataEventType.BAR_CLOSED,DataEventType.BAR_AMENDED},continuity=policy,on_recovery=recovery))
 try:
  await dm.start()
  for ex,mt,sym in SPECS:
   attach(ex,mt,sym,'strict',ContinuityPolicy('strict',10))
   attach(ex,mt,sym,'live','gap_aware')
  await asyncio.gather(*(dm.ensure_stream(sym,'1m',exchange=ex,market_type=mt) for ex,mt,sym in SPECS))
  await until(lambda: len(REPORT['source'])==len(SPECS) and all(s['closed']>0 for s in REPORT['source'].values()),100,'all exchanges have a real closed candle')
  PHASE='baseline'; progress('all selected exchanges delivered closed 1m bars through DataManager')
  for ex,mt,sym in SPECS: attach(ex,mt,sym,'short_strict',ContinuityPolicy('strict',.75))
  await asyncio.sleep(2)
  # Missing the entire following minute guarantees a true open-time hole.
  resume_at=(int(time.time())//60+2)*60+3
  REPORT['fault']={'started':time.time(),'resume_target':resume_at,'source_before':{k:dict(v) for k,v in REPORT['source'].items()}}
  pool=get_shared_ccxt_runtime_pool(); gate=asyncio.Event()
  for entry in list(pool._entries.values()):
   runtime=entry.runtime; old=runtime.watch
   async def gated(descriptor,symbol,original=old):
    await gate.wait(); return await original(descriptor,symbol)
   runtime.watch=gated; restore.append((runtime,old))
  engine.delay_repairs=True; PHASE='outage'
  REPORT['fault']['closed_clients']=await pool.recycle_all_websockets()
  progress('websockets closed until a complete minute candle has been missed')
  while time.time()<resume_at:
   await asyncio.sleep(min(10,max(0,resume_at-time.time())))
   progress('outage in progress')
  PHASE='recovering'; REPORT['fault']['reconnect_released']=time.time(); gate.set()
  progress('reconnecting; observing shared REST repair and independent subscribers')
  await until(lambda: {r['exchange'] for r in REPORT['gaps']}=={ex for ex,_,_ in SPECS},85,'a detected gap from every exchange')
  await until(lambda: all(any(r['event']['event_type']=='source.gap.resolved' for r in REPORT['consumers'][ex+'.live']['events']) for ex,_,_ in SPECS),60,'all source gaps resolved')
  recovered_at=time.time()
  await until(lambda: all(any(r['at']>recovered_at and r['event']['event_type']=='bar.closed' and not r['event'].get('detail',{}).get('continuity_replayed') for r in REPORT['consumers'][ex+'.strict']['events']) for ex,_,_ in SPECS),90,'a fresh natural close after repair for each strict subscriber')
  REPORT['natural_close_after_repair']=True
  PHASE='verified'
  REPORT['source_continuity']=dm.source_gaps.snapshot()
  REPORT['backfill']=coordinator.snapshot()
  REPORT['ingestion']=factory.snapshot()
  REPORT['parity']=[]
  for ex,mt,sym in SPECS:
   times=sorted({r['event']['bar']['time']*1000 for r in REPORT['consumers'][ex+'.strict']['events'] if r['event'].get('detail',{}).get('continuity_replayed') and r['event'].get('bar') and r['event']['event_type']=='bar.closed'})
   for opened in times:
    rows=await factory.fetch_market(StreamDescriptor(sym,StreamType.KLINE,interval='1m',exchange=ex,market_type=mt),start_ms=opened,end_ms=opened+59999,limit=3,history=True)
    remote=next((r for r in rows if r.data.get('open_time')==opened and r.data.get('is_closed')),None)
    stored=store.query_bars(symbol=sym,interval='1m',exchange=ex,market_type=mt,start_ms=opened,end_ms=opened)
    comparisons={f: bool(remote and stored and abs(float(remote.data[f])-float(stored[0][f]))<=max(1e-8,abs(float(remote.data[f]))*1e-10)) for f in ('open','high','low','close','volume')}
    REPORT['parity'].append({'exchange':ex,'open_time':opened,'match':all(comparisons.values()),'fields':comparisons,'rest':remote.to_dict() if remote else None,'storage':stored})
  REPORT['memory_budget']=dm.memory_budget.snapshot(measure_heap=True)
  REPORT['delivery']=dm.aggregator_bridge.delivery.snapshot()
  assert REPORT['parity'] and all(row['match'] for row in REPORT['parity'])
  assert all(not REPORT['consumers'][ex+'.strict']['errors'] and not REPORT['consumers'][ex+'.live']['errors'] for ex,_,_ in SPECS)
  assert all(len(REPORT['consumers'][ex+'.short_strict']['errors'])==1 for ex,_,_ in SPECS)
  progress('real REST parity checks completed')
 except Exception as e:
  REPORT['errors'].append({'stage':PHASE,'type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc()})
  REPORT['source_continuity']=dm.source_gaps.snapshot(); REPORT['backfill']=coordinator.snapshot(); REPORT['ingestion']=factory.snapshot()
  progress('failure retained in evidence')
 finally:
  PHASE='shutdown'
  for runtime,old in restore: runtime.watch=old
  if 'gate' in locals(): gate.set()
  for h in handles: dm.unsubscribe(h)
  for name,component in [('coordinator',coordinator),('dm',dm),('factory',factory)]:
   try: await asyncio.wait_for(component.shutdown(),30)
   except Exception as e: REPORT['errors'].append({'stage':'shutdown','component':name,'error':str(e)})
  REPORT['completed_ms']=int(time.time()*1000)
  (OUT/'report.json').write_text(json.dumps(REPORT,default=str,indent=2)); LOG.close()
  progress('report saved')
logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
