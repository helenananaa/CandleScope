"""Run the packaged backend against an isolated deterministic SQLite fixture."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=False)
os.environ['CANDLE_DATA_DIR'] = str(out / 'data')

import app.data_engine.aggregation.blocks as blocks_module
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.storage import klines_repo
from app.data_engine.aggregation.blocks import BlockRevisionChanged

assert '.app/Contents/Resources/backend/' in str(Path(blocks_module.__file__).resolve())
klines_repo.init_klines_storage()
day = 86400000
inputs = [dict(open_time=i*day, close_time=(i+1)*day-1,
               open=2., high=4., low=1., close=3., volume=float(i+1),
               quote_volume=float((i+1)*3), trades=i+1,
               taker_buy_base=None, taker_buy_quote=None) for i in range(24)]
klines_repo.upsert_klines('BTCUSDT', '1d', inputs, source='backfill')
dm = DataManager()
dm.set_storage(klines_repo.KlinesRepoAdapter())
store = dm.query_engine.storage.revision_store
report = {'python': sys.executable, 'module': blocks_module.__file__,
          'module_sha256': hashlib.sha256(Path(blocks_module.__file__).read_bytes()).hexdigest(),
          'scope': 'Packaged Python/backend, isolated deterministic SQLite; no user or native profile database mutation',
          'phases': []}

def query(interval, count, revision=None):
    result = dm.query('BTCUSDT', interval, start_ms=0, end_ms=23*day, limit=count,
                      auto_backfill=False, min_revision=revision)
    return result

def record(name):
    state=dm.shared_blocks.snapshot()
    budget=dm.memory_budget.snapshot(measure_heap=True)
    assert budget['over_budget_bytes']==0
    assert state['leases']==state['views']==state['inflight']==0
    assert budget['owners']['aggregation-blocks']['reserved_bytes']==0
    report['phases'].append(dict(name=name,blocks=state,budget=budget))

first=query('2d',12)
assert first.complete and len(first.bars)==12, first.metadata
record('2d-built')
second=query('4d',6)
assert second.complete and len(second.bars)==6, second.metadata
assert second.bars[0].volume==10
assert dm.shared_blocks.snapshot()['hits']>0
record('4d-shared')
floor=store.head()
subprocess.run([sys.executable,'-c',
    "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\"UPDATE klines SET volume=1,quote_volume=3,high=21,close=20 WHERE interval='1d' AND open_time=?\",(2*86400000,)); c.commit()",
    str(klines_repo.KLINES_DB_PATH)],check=True)
dm.shared_blocks.poll()
assert dm.shared_blocks.snapshot()['entries']==0
corrected=query('4d',6,store.head())
assert corrected.complete and corrected.bars[0].volume==8 and corrected.bars[0].high==21, corrected.metadata
record('external-amendment-rebuilt')
dm.query_engine.storage.delete_bars('BTCUSDT','1d')
dm.shared_blocks.poll()
deleted=query('4d',6,store.head())
assert not deleted.bars
assert not dm.query_engine.storage.query_bars('BTCUSDT','4d')
assert dm.shared_blocks.snapshot()['entries']==0
try:
    with dm.shared_blocks.view((SeriesKey('BTCUSDT','1d'),),acquired_at=floor):
        raise AssertionError('pre-delete view was admitted')
except BlockRevisionChanged:
    pass
record('delete-and-old-view-rejection')
asyncio.run(dm.shutdown())
record('closed')
assert dm.shared_blocks.snapshot()['estimated_bytes']==0
report['passed']=True
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'passed':True,'phases':[p['name'] for p in report['phases']]}))
