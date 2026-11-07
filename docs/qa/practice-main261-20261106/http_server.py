"""Real local-account API with explicit controlled candles; no LIVE startup."""
from pathlib import Path
from contextlib import asynccontextmanager
from decimal import Decimal
import asyncio
import json
import os
import socket
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'packages/candlescope-plugin-sdk/src'),str(ROOT/'packages/candlescope-backtest-sdk/src')]
from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware
import uvicorn
from app.api.v1.trading_accounts import router
from app.core.executors import run_storage
from app.data_engine.data_manager.core import DataManagerCore
from app.local_data.network_guard import OfflineNetworkGuard
from app.trading_accounts.store import TradingStore
from app.trading_accounts.service import TradingAccountService
QA=Path(os.environ['CANDLESCOPE_QA_STATE_ROOT']).resolve();QA.mkdir(parents=True,exist_ok=True)
store=TradingStore(QA/'accounts.sqlite3')
T0=1760000040000
persisted=store.one('SELECT MAX(observed_ms) AS latest FROM practice_cursors')
clock=[max(T0,int(persisted['latest'] or T0))]
def candle(at,o,h,l,c):return {'time':at,'open':Decimal(o),'high':Decimal(h),'low':Decimal(l),'close':Decimal(c),'volume':Decimal('1'),'is_closed':False}
class ControlledMarket:
 def latest_bar(self,*_):
  return candle(clock[0]//60000*60,'100','100.5','99.8','100') if clock[0]==T0 else candle(clock[0]//60000*60,'100.2','103.5','100.1','103.2')
service=TradingAccountService(store,snapshot_dir=QA/'images',market=ControlledMarket(),clock=lambda:clock[0])
core=DataManagerCore();manager=core.bind_trading(service)
network=OfflineNetworkGuard();network.install()
requests=[]
shutdown_complete=False
@asynccontextmanager
async def lifespan(app):
 global shutdown_complete
 try:
  yield
 finally:
  await core.shutdown_trading();store.close()
  shutdown_complete=True
  print(json.dumps({'shutdown_complete':True,'manager':manager.diagnostics(),'network':network.snapshot()}),flush=True)
  network.uninstall()
app=FastAPI(lifespan=lifespan);app.state.trading_accounts=service;app.state.data_manager_core=core
app.include_router(router,prefix='/api/v1');app.add_middleware(GZipMiddleware,minimum_size=500)
class Audit:
 def __init__(self,app):self.app=app
 async def __call__(self,scope,receive,send):
  if scope['type']=='http':requests.append({'path':scope['path'],'method':scope['method']})
  await self.app(scope,receive,send)
app.add_middleware(Audit)
@app.get('/qa/diagnostics')
async def diagnostics():return {'scope':__doc__,'manager':manager.diagnostics(),'network':network.snapshot(),'requests':requests}
@app.post('/qa/advance')
async def advance():
 clock[0]=T0+70000
 bars=[candle(T0//1000,'100','100.5','99.8','100.2'),candle(T0//1000+60,'100.2','103.5','100.1','103.2')]
 fills=await run_storage(service.apply_market_bars,('binance','futures','BTCUSDT'),bars,observed_ms=clock[0])
 return {'controlled':True,'fills':fills,'cursor':store.state_cursor()}
sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
print(json.dumps({'ready':True,'port':sock.getsockname()[1]}),flush=True)
try:
 asyncio.run(uvicorn.Server(uvicorn.Config(app,log_level='warning')).serve(sockets=[sock]))
except KeyboardInterrupt:
 # Uvicorn0.34 re-raises SIGINT after graceful cleanup. Only translate it to
 # a normal fixture exit when the full owned shutdown actually completed.
 if not shutdown_complete:
  raise
