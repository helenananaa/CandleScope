"""Same ledger/view work: three old read projections versus one state read.

No HTTP, renderer, exchange or matcher performance claim. All files are owned
by a TemporaryDirectory; the source application functions and SQLite are real.
"""
from pathlib import Path
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'backend'))
from app.trading_accounts.store import TradingStore
from app.trading_accounts.service import TradingAccountService
results=[]
for count in (100,1000,5000):
 with tempfile.TemporaryDirectory(prefix='candlescope-ledger-measure-') as temporary:
  root=Path(temporary);store=TradingStore(root/'ledger.db')
  service=TradingAccountService(store,snapshot_dir=root/'images')
  account=service.create_account({'kind':'practice','name':'Controlled benchmark','settings':{'initialBalance':'1000'}})['id']
  rows=[]
  for index in range(count):
   for leg,(side,price) in enumerate((('buy','100'),('sell','101'))):
    rows.append((f'fil_{index*2+leg:020x}',account,'binance','futures','BTCUSDT',side,'0.1234567890123456789',price,'0.0001','USDT','taker',1700000000000+index*120000+leg*60000,'practice',1700000000000))
  with store.transaction() as db:
   db.executemany('INSERT INTO fills(id,account_id,exchange,market_type,symbol,side,qty,price,fee,fee_currency,liquidity,ts_ms,source,created_at_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',rows)
  original=store.fills;reads=[0]
  def observed(a):reads[0]+=1;return original(a)
  store.fills=observed
  def old():return {'summary':service.account_summary(account),'trades':service.list_trades(account)['trades'],'entries':service.list_entries(account)['entries']}
  def new():
   state=service.account_state(account)
   return {key:state[key] for key in ('summary','trades','entries')}
  assert old()==new()
  elapsed={'old':[],'new':[]};calls={'old':[],'new':[]}
  for trial in range(5):
   for label,fn in ([('old',old),('new',new)] if trial%2==0 else [('new',new),('old',old)]):
    reads[0]=0;start=time.perf_counter_ns();view=fn();elapsed[label].append((time.perf_counter_ns()-start)/1e6);calls[label].append(reads[0])
  assert calls['old']==[3]*5 and calls['new']==[1]*5
  results.append({'closed_trades':count,'fills':count*2,'trials_ms':elapsed,'p50_ms':{key:statistics.median(value) for key,value in elapsed.items()},'fills_reads_per_state':calls,'same_views':True})
  store.close()
print(json.dumps({'scope':__doc__,'source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'python':sys.version,'platform':platform.platform(),'measurements':results},indent=2))
