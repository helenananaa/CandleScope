"""Controlled real SQLite/manager/executor race at the subscription limit.

No external market, HTTP, UI, matcher throughput, Windows or production SLO
claim. Reports this process's RSS, bounded view adoption and one queued write.
"""
from pathlib import Path
import asyncio
import json
import hashlib
import os
import platform
import resource
import sys
import tempfile
import threading
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'backend'))
from app.core.executors import run_storage
from app.data_engine.data_manager.trading import TradingAccountDataManager
from app.trading_accounts.store import TradingStore
from app.trading_accounts.service import TradingAccountService

async def main():
 with tempfile.TemporaryDirectory(prefix='candlescope-state-pressure-') as temporary:
  root=Path(temporary);store=TradingStore(root/'ledger.db');service=TradingAccountService(store,snapshot_dir=root/'images')
  aid=service.create_account({'kind':'practice','name':'Pressure fixture','settings':{'initialBalance':'1000'}})['id']
  rows=[]
  for index in range(1000):
   for leg,(side,price) in enumerate((('buy','100'),('sell','101'))):
    rows.append((f'fil_{index*2+leg:020x}',aid,'binance','futures','BTCUSDT',side,'0.1234567890123456789',price,'0.0001','USDT','taker',1700000000000+index*120000+leg*60000,'practice',1700000000000))
  with store.transaction() as db:db.executemany('INSERT INTO fills(id,account_id,exchange,market_type,symbol,side,qty,price,fee,fee_currency,liquidity,ts_ms,source,created_at_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',rows)
  manager=TradingAccountDataManager(service)
  coalesced=os.environ.get('CANDLESCOPE_PRESSURE_COALESCED','1')=='1'
  if not coalesced:
   # Same current service/state output; restore only the old per-reader path.
   async def unshared(account):return await run_storage(service.account_state,account)
   manager.read_state=unshared
  calls=[0];lock=threading.Lock();original=service.account_state
  def counted(account):
   with lock:calls[0]+=1
   return original(account)
  service.account_state=counted
  rss_start=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
  started=time.perf_counter();cpu_started=time.process_time()
  subscribers=await asyncio.gather(*(manager.subscribe_state(aid) for _ in range(16)))
  events=[s.events() for s in subscribers]
  first=await asyncio.gather(*(anext(e) for e in events))
  initial_ms=(time.perf_counter()-started)*1000
  try:
   await manager.subscribe_state(aid)
  except Exception as error:
   assert getattr(error,'code',None)=='TRADING_SUBSCRIPTION_CAPACITY'
  else:raise AssertionError('subscription capacity was not enforced')
  await asyncio.sleep(1.05)
  pending=[asyncio.create_task(anext(e)) for e in events]
  # Unchanged matcher observation starts reads. A real committed write then
  # races them; clear-before-read must retain that wakeup for the next view.
  store.updates.notify('state');await asyncio.sleep(.01)
  writer_started=time.perf_counter()
  def write():
   with store.transaction() as db:db.execute("UPDATE cash_flows SET amount='1001' WHERE account_id=?",(aid,))
   return store.state_cursor()
  cursor=await run_storage(write)
  writer_ms=(time.perf_counter()-writer_started)*1000
  updated=await asyncio.wait_for(asyncio.gather(*pending),30)
  adopted_ms=(time.perf_counter()-writer_started)*1000
  expected=service.account_summary(aid)
  assert all(frame['state']['cursor']==cursor and frame['state']['summary']==expected for frame in updated)
  assert all(frame['state']['summary']['account']['id']==aid for frame in first)
  await asyncio.gather(*(e.aclose() for e in events));manager.close()
  assert not manager._subscriptions and store.updates.diagnostics()['subscriptions']==0
  result={'scope':__doc__,'coalesced':coalesced,'managerSourceSha256':hashlib.sha256((ROOT/'backend/app/data_engine/data_manager/trading.py').read_bytes()).hexdigest(),'python':sys.version,'platform':platform.platform(),'subscriptions':16,'closed_trades':1000,'fills':2000,
   'initial_all_ready_ms':initial_ms,'queued_writer_commit_ms':writer_ms,'all_latest_views_after_write_ms':adopted_ms,
   'state_reads':calls[0],'cpu_seconds':time.process_time()-cpu_started,'rss_highwater_before':rss_start,'rss_highwater_after':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
   'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB','all_latest_views_equal':True,'remaining_subscriptions':0}
  store.close();print(json.dumps(result,indent=2))
asyncio.run(main())
