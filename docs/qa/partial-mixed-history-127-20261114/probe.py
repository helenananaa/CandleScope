"""Read a retained stopped-profile SQLite snapshot through the real DataManager.

Usage: python probe.py --root CHECKOUT --database STOPPED_DB --output NEW_DIR
No network work is admitted; the original database is never opened for writing.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--database', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
source = args.database.resolve()
args.output.mkdir(parents=True, exist_ok=False)
target = args.output / 'source-copy.sqlite'
before = hashlib.sha256(source.read_bytes()).hexdigest()
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as reader, sqlite3.connect(target) as writer:
    reader.backup(writer)
sys.path.insert(0, str(root / 'backend'))
from app.core import config as core_config
from app.data_engine.storage import klines_repo
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.interval_policy import parse_interval_spec

klines_repo.KLINES_DB_PATH = core_config.KLINES_DB_PATH = target
results, values = [], []
for method in ['query', 'query_materialized']:
    config = DataManagerConfig()
    config.query.auto_backfill = False
    manager = DataManager(config)
    manager.set_storage(klines_repo.KlinesRepoAdapter())
    try:
        spec = parse_interval_spec('89m')
        end, count = 1794624480000, 221
        start = end - (count - 1) * spec.nominal_ms
        floor = manager.query_engine.storage.revision_store.head()
        options = {'auto_backfill': False, 'min_revision': floor} if method == 'query' else {}
        result = getattr(manager, method)('BTCUSDT', '89m', start_ms=start, end_ms=end,
            limit=count, exchange='binance', market_type='futures', **options)
        canonical = [dict(bar.to_aggregation_dict(), source=bar.source,
                          trusted_final=bar.trusted_final) for bar in result.bars]
        values.append(canonical)
        results.append(dict(method=method, bars=len(canonical), complete=result.complete,
            retryable=result.retryable, history_state=result.history_state,
            canonical_sha256=hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest(),
            metadata=result.metadata, missing=[item.to_dict() for item in result.missing_ranges]))
    finally:
        asyncio.run(manager.shutdown())
after = hashlib.sha256(source.read_bytes()).hexdigest()
assert before == after, 'original database changed'
payload = dict(source_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
        text=True).strip(), source_diff=subprocess.check_output(['git', 'diff', '--',
        'backend/app/data_engine/data_manager/custom_query.py',
        'backend/app/data_engine/data_manager/mixed_query.py'], cwd=root, text=True),
    original_database_sha256=before, original_unchanged=True,
    canonical_values_equal=values[0] == values[1], results=results)
(args.output / 'results.json').write_text(json.dumps(payload, indent=2, default=str) + '\n')
(args.output / 'canonical-values.json').write_text(json.dumps(values, indent=2) + '\n')
print(json.dumps(dict(original_unchanged=True, canonical_values_equal=values[0] == values[1],
    results=[dict(method=item['method'], bars=item['bars'], complete=item['complete'],
                  history_state=item['history_state']) for item in results])))
