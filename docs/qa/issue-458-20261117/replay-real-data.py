"""Same-input SQLite query comparison using retained public Binance data.

This is source/replay evidence, not native cold-load or external-feed qualification.
Each case uses a fresh disposable database; the retained original is read-only.
"""
import argparse
import asyncio
from collections import defaultdict
from contextlib import nullcontext
import hashlib
import inspect
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import time
from unittest.mock import patch

from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager import query as query_module
from app.data_engine.storage import klines_repo

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--allow-contract-failure', action='store_true')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
source = sqlite3.connect(args.source.resolve().as_uri()+'?mode=ro', uri=True)
source.row_factory = sqlite3.Row
where = "exchange='binance' AND market_type='futures' AND symbol='BTCUSDT' AND provider_id='binance' AND venue='binance' AND asset_class='crypto' AND series_variant='native' AND price_adjustment='raw' AND session_variant='continuous' AND volume_semantics='base_asset'"
minutes = [dict(r) for r in source.execute('SELECT * FROM klines WHERE '+where+" AND interval='1m' ORDER BY open_time")]
by_time = {r['open_time']: r for r in minutes}
additive = ['volume','quote_volume','trades','taker_buy_base','taker_buy_quote']
fields = ['open','high','low','close',*additive]
result = {'scope':'retained actual public data replay; isolated databases; no network; not native cold qualification',
          'product':subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(query_module.__file__).resolve().parents[4],text=True).strip(),
          'query_module_sha256':hashlib.sha256(Path(query_module.__file__).read_bytes()).hexdigest(),
          'source_database_sha256':hashlib.sha256(args.source.read_bytes()).hexdigest(), 'cases':[]}

def insert(adapter, interval, rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['source']].append(row)
    for label, values in groups.items():
        adapter.upsert_bars('BTCUSDT', interval, values, market_type='futures', source=label)

for period in [89,97,101]:
    width = period*60_000
    targets = [dict(r) for r in source.execute('SELECT * FROM klines WHERE '+where+' AND interval=? ORDER BY open_time',(f'{period}m',))]
    qualified = []
    for row in targets:
        group = [by_time.get(at) for at in range(row['open_time'],row['open_time']+width,60_000)]
        if all(r is not None and all(r[f] is not None for f in fields) for r in group):
            if not qualified or row['open_time'] == qualified[-1]['open_time']+width:
                qualified.append(row)
            if len(qualified) == 32:
                break
    assert len(qualified) == 32, (period,len(qualified))
    for scenario in ['materialized','sparse','base_history','empty_storage','latest_without_preview']:
        selected = qualified[:16] if scenario == 'base_history' else qualified
        start, end = selected[0]['open_time'], selected[-1]['open_time']
        path = args.output/f'{period}-{scenario}.sqlite'
        klines_repo.KLINES_DB_PATH = core_config.KLINES_DB_PATH = path
        klines_repo.init_klines_storage()
        config = DataManagerConfig()
        config.query.auto_backfill = False
        dm = DataManager(config)
        adapter = klines_repo.KlinesRepoAdapter()
        dm.set_storage(adapter)
        query = dm.query_engine
        if scenario in {'sparse','base_history','latest_without_preview'}:
            insert(adapter,'1m',[by_time[at] for at in range(start,end+width,60_000)])
        if scenario in {'materialized','sparse','latest_without_preview'}:
            insert(adapter, f'{period}m', [r for i,r in enumerate(selected) if scenario != 'sparse' or i not in {10,24}])
        calls = []
        for method in ['query_bars','query_bar_components','fetch_before','fetch_before_bar_components']:
            original = getattr(adapter,method,None)
            if not callable(original):
                continue
            def measured(*a,_method=method,_original=original,**kw):
                began = time.monotonic()
                value = _original(*a,**kw)
                bound = inspect.signature(_original).bind(*a,**kw).arguments
                calls.append({'method':_method,**{name:bound.get(name) for name in ['interval','start_ms','end_ms','before_ms','limit']},
                              'rows':len(value),'elapsed_ms':round((time.monotonic()-began)*1000,3)})
                return value
            setattr(adapter,method,measured)
        submitted = []
        query.set_backfill_trigger(lambda *a:submitted.append(a))
        replay_now = end+width+60_000
        began = time.monotonic()
        with patch('time.time',lambda:replay_now/1000) if scenario == 'latest_without_preview' else nullcontext():
            response = (query.query_latest('BTCUSDT',f'{period}m',limit=33,market_type='futures',auto_backfill=False)
                        if scenario == 'latest_without_preview' else query.query('BTCUSDT',f'{period}m',start_ms=start,
                            end_ms=end+width-1,limit=len(selected),market_type='futures',auto_backfill=scenario=='empty_storage'))
        elapsed = (time.monotonic()-began)*1000
        mismatches = []
        for bar in response.bars:
            if not bar.is_closed:
                continue
            group = [by_time[at] for at in range(bar.time_ms,bar.time_ms+width,60_000)]
            expected = {'open':group[0]['open'],'close':group[-1]['close'],
                        'high':max(r['high'] for r in group),'low':min(r['low'] for r in group)}
            expected.update({f:math.fsum(r[f] for r in group) for f in additive})
            for field,value in expected.items():
                actual = getattr(bar,field)
                if actual is None or not math.isclose(actual,value,rel_tol=1e-12,abs_tol=1e-9):
                    mismatches.append({'time':bar.time_ms,'field':field,'expected':value,'actual':actual})
        source_calls = [c for c in calls if c['interval'] != f'{period}m']
        record = {'period':period,'scenario':scenario,'target_start_ms':start,'target_end_ms':end,
                  'actual_total_ms':round(elapsed,3),'bars':len(response.bars),'complete':response.complete,
                  'retryable':response.retryable,'metadata':response.metadata,'submitted':submitted,
                  'calls':calls,'source_read_calls':len(source_calls),'source_rows':sum(c['rows'] for c in source_calls),
                  'numeric_mismatches':mismatches}
        result['cases'].append(record)
        checks = {'numeric':not mismatches}
        if scenario == 'materialized':
            checks['valid_target_reused'] = response.complete and len(response.bars)==32 and not source_calls and not submitted
        elif scenario == 'base_history':
            checks['base_history_materialized'] = response.complete and len(response.bars)==16 and not submitted
        elif scenario == 'sparse':
            checks['only_local_holes'] = (response.complete and len(response.bars)==32 and not submitted
                and response.metadata.get('canonical_local_repair_source_budget',999999) <= 2048
                and sum(c['rows'] for c in source_calls) <= 2048)
        elif scenario == 'empty_storage':
            checks['cold_pending_preserves_demand'] = not response.complete and not response.bars and response.retryable and not response.metadata.get('target_materialized')
        else:
            checks['current_only'] = (not response.complete and response.retryable and len(response.bars)==32
                and not submitted and all(c['start_ms'] is None or c['start_ms']>=end+width for c in source_calls))
        record['checks'] = checks
        if not args.allow_contract_failure:
            assert all(checks.values()), record
        asyncio.run(dm.shutdown())
        assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
result['passed'] = all(all(c['checks'].values()) for c in result['cases'])
(args.output/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'passed':result['passed'],'cases':[{k:c[k] for k in ['period','scenario','bars','complete','source_read_calls','source_rows','actual_total_ms']} for c in result['cases']]}))
