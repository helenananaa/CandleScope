"""Same retained public-data SQLite snapshot, fresh process and isolated copy."""
import argparse
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--checkout', type=Path, required=True)
parser.add_argument('--database', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--load-context', default='local full integration running concurrently')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
os.environ['CANDLE_DATA_DIR'] = os.environ['DATA_DIR'] = str(args.output / 'data')
sys.path.insert(0, str(args.checkout / 'backend'))
from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.storage import klines_repo

original_hash = hashlib.sha256(args.database.read_bytes()).hexdigest()
database = args.output / 'market.sqlite'
with closing(sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True)) as source:
    with closing(sqlite3.connect(database)) as target:
        source.backup(target)
klines_repo.KLINES_DB_PATH = core_config.KLINES_DB_PATH = database
config = DataManagerConfig()
config.query.auto_backfill = False
manager = DataManager(config)
manager.set_storage(klines_repo.KlinesRepoAdapter())
start, stop = 1717201200000, 1793454540000
head = manager.query_engine.storage.revision_store.head()
assert manager.query_engine._interval_resolver.history_composition_routes(
    exchange='binance',market_type='futures',interval='10007m') is not None
def values(bar):
    return dict(time_ms=bar.time_ms, open=bar.open, high=bar.high, low=bar.low, close=bar.close,
        volume=bar.volume, quote_volume=bar.quote_volume, trades=bar.trades,
        taker_buy_base=bar.taker_buy_base, taker_buy_quote=bar.taker_buy_quote,
        source=bar.source, trusted_final=bar.trusted_final)
try:
    began, cpu = time.perf_counter(), time.process_time()
    result = manager.query_composed('BTCUSDT','10007m',start_ms=start,end_ms=stop,limit=128,
        exchange='binance',market_type='futures',auto_backfill=False,min_revision=head,
        composition_contract='binance.usdm.trade-klines/base-utc/1')
    elapsed, cpu_ms = (time.perf_counter()-began)*1000, (time.process_time()-cpu)*1000
    materialized = manager.query_materialized('BTCUSDT','10007m',start_ms=start,end_ms=stop,
        limit=128,exchange='binance',market_type='futures')
    actual, expected = [values(bar) for bar in result.bars], [values(bar) for bar in materialized.bars]
    assert actual == expected and actual and not result.complete and result.retryable
    assert result.metadata['target_materialized_written'] == 0
    assert manager.query_engine.storage.revision_store.head() == head
    report = dict(source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.checkout,text=True).strip(),
        source_diff=subprocess.check_output(['git','diff','HEAD','--','backend/app'],cwd=args.checkout,text=True),
        input_sha256=original_hash, driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        elapsed_ms=elapsed, process_cpu_ms=cpu_ms, values=actual, metadata=result.metadata,
        pending=True, materialized_values_equal=True, target_writes=0,
        load_context=args.load_context,
        scope='one fresh-process first data read after provider declaration bootstrap on an isolated exact public-data database copy; no network; not native latency or whole-product resource qualification')
    files=subprocess.check_output(['git','ls-files','backend/app'],cwd=args.checkout,text=True).splitlines()
    report['runtime_sha256']={name:hashlib.sha256((args.checkout/name).read_bytes()).hexdigest() for name in files}
    (args.output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('source_head','elapsed_ms','process_cpu_ms','materialized_values_equal')}))
finally:
    asyncio.run(manager.shutdown())
    assert manager.memory_budget.snapshot()['reserved_bytes'] == 0
    assert hashlib.sha256(args.database.read_bytes()).hexdigest() == original_hash
