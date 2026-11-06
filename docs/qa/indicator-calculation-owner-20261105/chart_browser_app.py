"""Private renderer qualification: real DataManager/SQLite/ASGI/runtime, controlled BAR feed.

Run with the qualified core launcher and repository SDK+backend PYTHONPATH.
Owns only the explicit scratch directory; never opens a user profile or exchange.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.api.v1 import indicators
from app.api.v1.stream_indicators import stream_indicators
from app.core import config
from app.data_engine.data_manager import query as query_module
from app.data_engine.data_manager.models import DataEvent, DataEventType, SeriesKey
from app.data_engine.storage import klines_repo
from app.indicator.range_result_service import IndicatorRangeResultService
from app.indicator.runtime_routes import IndicatorRuntimeRoute, IndicatorRuntimeRoutes
from app.indicator.runtime_service import IndicatorRuntimeService
from app.plugin_runtime.registry import RuntimeRegistry
from app.plugin_runtime.service import RuntimeHostService
from tests.test_chart_calculation_transports import Source, bars
from tests.test_runtime_owned_output import owner, SOURCE

scratch = Path(sys.argv[1]).absolute()
scratch.mkdir(parents=True,exist_ok=True)
config.KLINES_DB_PATH = klines_repo.KLINES_DB_PATH = scratch/'source.sqlite'
klines_repo.init_klines_storage()
source = Source(klines_repo.KlinesRepoAdapter())
query_module.time = SimpleNamespace(time=lambda:source.now_ms/1000,monotonic=time.monotonic)
ranges = IndicatorRangeResultService(server_epoch='chart-browser')
spec = owner(scratch/'pine.sqlite').spec
host = RuntimeHostService(RuntimeRegistry(plugins=(spec,)),host_name='CandleScope',host_version='0.3.0')
service = IndicatorRuntimeService(IndicatorRuntimeRoutes((IndicatorRuntimeRoute('pine','sidecar',spec.runtime_id),)),host=host)
engine = SimpleNamespace(indicator_range_service=ranges,add_listener=lambda callback:None,remove_listener=lambda callback:None)


@asynccontextmanager
async def lifespan(_app):
    yield
    processes = [item._process for item in host._supervisors.values() if item._process is not None]
    await service.stop();await host.stop();await source.shutdown()
    receipts=[]
    for process in processes:
        try:os.kill(process.pid,0);absent=False
        except ProcessLookupError:absent=True
        receipts.append({'pid':process.pid,'returncode':process.returncode,'absent':absent})
    with klines_repo._connect() as conn:
        watches=conn.execute("SELECT count(*) FROM kline_prefix_watches WHERE owner LIKE 'indicator:%'").fetchone()[0]
    receipt={'workers':receipts,'sourceWatches':watches,'callbacks':len(source.callbacks),'leases':len(source.leases),
        'registry':service.calculations.snapshot(),'queries':source.query_windows}
    (scratch/'shutdown.json').write_text(json.dumps(receipt,indent=2)+'\n')
    assert all(p['returncode']==0 and p['absent'] for p in receipts),receipt
    assert not watches and not source.callbacks and not source.leases and not receipt['registry']['entries'],receipt


app=FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
app.state.data_manager,app.state.indicator_runtime_service,app.state.indicator_range_service=source,service,ranges
app.include_router(indicators.router,prefix='/api/v1')


@app.websocket('/api/v1/stream/indicators')
async def stream(socket:WebSocket):
    await socket.accept();await stream_indicators(socket,source,engine,runtime_service=service)


@app.get('/api/v1/fixture/bars')
async def current_bars():
    return {'rows':[{key:getattr(bar,key) for key in ('time','open','high','low','close','volume','is_closed')} for bar in source.rows],
        'script':SOURCE}


@app.post('/api/v1/fixture/tick/{count}')
async def tick(count:int,close:float=102):
    rows=list(bars(count,forming=True));rows[-1]=replace(rows[-1],close=close,high=max(rows[-1].high,close))
    source.rows=rows
    await source.emit(DataEvent(DataEventType.BAR_UPDATED,SeriesKey('BTCUSDT','1m'),bar=rows[-1]))
    return {'ok':True}


@app.post('/api/v1/fixture/amend')
async def amend():
    old=source.rows[10];source.replace_bar(10,replace(old,close=101))
    await source.emit(DataEvent(DataEventType.BAR_AMENDED,SeriesKey('BTCUSDT','1m'),bar=source.rows[10],previous_bar=old))
    return {'ok':True}


@app.post('/api/v1/fixture/seed-left')
async def seed_left():
    initial = list(source.rows)
    first = initial[0]
    source.rows = [replace(first, time=first.time-(1000-index)*60) for index in range(1000)] + initial
    return {'ok': True}


@app.post('/api/v1/fixture/append')
async def append():
    latest = source.rows[-1]
    source.rows = [*source.rows, replace(latest, time=latest.time+60, is_closed=False)]
    await source.emit(DataEvent(DataEventType.BAR_UPDATED, SeriesKey('BTCUSDT', '1m'), bar=source.rows[-1]))
    return {'ok': True}


@app.get('/api/v1/fixture/state')
async def state():
    return {'registry':service.calculations.snapshot(),'callbacks':len(source.callbacks),'leases':len(source.leases),
        'runtimes':host.diagnostics()['runtimes'],'queries':source.query_windows}


@app.post('/api/v1/fixture/stop')
async def stop():
    asyncio.get_running_loop().call_later(.1,setattr,server,'should_exit',True)
    return {'ok':True}


server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=int(sys.argv[2]),log_level='info'))
if __name__=='__main__':server.run()
