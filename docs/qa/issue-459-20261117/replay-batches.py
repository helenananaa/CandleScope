"""Replay recorded public inputs through scheduler -> engine -> real SQLite.

No external communication. This is source/integration evidence, not a native
cold-load pass. Each scenario has a fresh disposable database and real reducer.
"""
import argparse
import asyncio
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

from app.core import config as core_config
from app.data_engine.backfill import BackfillEngine
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.models import FetchResult, FetchedBar
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.backfill_contracts import RepairRequest, RepairOutcome
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
from app.data_engine.data_manager import backfill_scheduler as scheduler_module
from app.data_engine.storage import klines_repo

parser=argparse.ArgumentParser()
parser.add_argument('fixture',type=Path)
parser.add_argument('output',type=Path)
args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=False)
fixture=json.loads(gzip.decompress(args.fixture.read_bytes()))
fields=['open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote']
enhanced=frozenset(fields[5:])
receipt={'scope':'recorded actual public Binance inputs; controlled fetch replay; not live exchange qualification',
         'product':subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(scheduler_module.__file__).resolve().parents[4],text=True).strip(),
         'scheduler_sha256':hashlib.sha256(Path(scheduler_module.__file__).read_bytes()).hexdigest(),
         'fixture_sha256':hashlib.sha256(args.fixture.read_bytes()).hexdigest(),'cases':[]}

async def scenario(case,local):
    period=case['period'];width=period*60000;first=case['start_ms'];last=first+31*width
    path=args.output/f'{period}-{local}.sqlite'
    klines_repo.KLINES_DB_PATH=core_config.KLINES_DB_PATH=path
    klines_repo.init_klines_storage()
    dm=DataManager(DataManagerConfig());storage=klines_repo.KlinesRepoAdapter();dm.set_storage(storage)
    by_time={row['open_time']:row for row in case['rows']}
    if local:
        storage.upsert_bars('BTCUSDT','1m',case['rows'],market_type='futures',source='backfill')
    upstream_calls=[]; executions=[]
    class Replay:
        async def close(self):
            pass
        async def fetch(self,tasks,**_):
            results=[]
            for task in tasks:
                assert task.interval=='1m', 'optional batch forced mixed/coarse source'
                values=[by_time[at] for at in range(task.start_ms,task.end_ms+1,60000)]
                assert all(first<=r['open_time']<last+width for r in values)
                upstream_calls.append({'start_ms':task.start_ms,'end_ms':task.end_ms,'rows':len(values),
                    'ledger_range':task.metadata.get('ledger_range')})
                results.append(FetchResult(task,[FetchedBar(symbol='BTCUSDT',interval='1m',
                    exchange='binance',market_type='futures',**value,enhanced_fields=enhanced) for value in values]))
            return results
    engine=BackfillEngine(BackfillConfig(history_archive_enabled=False),storage=klines_repo.AsyncKlinesRepoAdapter())
    engine.memory_budget=dm.memory_budget;engine._fetcher=Replay()
    futures={}
    def future_for(r):
        return futures.setdefault(r.request_id,asyncio.get_running_loop().create_future())
    def complete(r,outcome):
        f=future_for(r)
        if not f.done():f.set_result(outcome)
    async def finalize(*_):pass
    async def execute(r):
        began=time.monotonic();before=len(upstream_calls)
        report=await engine.run('BTCUSDT',intervals=[r.interval],range_start_ms=r.start_ms,
            range_end_ms=r.end_ms,exchange='binance',market_type='futures',
            metadata={**r.metadata,'reason':r.reason,'priority':r.priority,'requester':r.requester,'request_id':r.request_id})
        expected=(r.end_ms-r.start_ms)//width+1
        actual=storage.count_final_bars('BTCUSDT',r.interval,r.start_ms,r.end_ms,
                                        exchange='binance',market_type='futures')
        assert actual==expected and not report.errors,(actual,expected,report.errors)
        for call in upstream_calls[before:]:
            assert r.start_ms<=call['start_ms']<=call['end_ms']<r.end_ms+width, 'C child range amplification'
        executions.append({'start_ms':r.start_ms,'end_ms':r.end_ms,'actual_total_ms':round((time.monotonic()-began)*1000,3),
            'target_count':expected,'work_plan':r.metadata['interval_work_plan'],
            'fetch_calls':len(upstream_calls)-before,'report_elapsed_ms':report.elapsed_ms,
            'reconcile_elapsed_ms':report.reconcile_result.elapsed_ms if report.reconcile_result else None})
        return RepairOutcome(r,'completed',report=BackfillCoordinator._summarize_report(report),verified_contiguous=True)
    scheduler=BackfillScheduler(execute=execute,future_for=future_for,complete=complete,finalize=finalize,
        on_queued=lambda _:None,max_concurrency=1,chunk_bars=1000)
    contract=scheduler._interval_resolver.history_composition_routes(exchange='binance',market_type='futures',interval=f'{period}m')[0].contract_id
    req=RepairRequest('BTCUSDT',f'{period}m',first,last,market_type='futures',reason='initial_history',requester='klines_range',
        metadata={'bounded_history_batch_contract':contract,'history_calendar_id':'crypto.24x7.utc',
            'history_fetch_ranges':[{'start_ms':first,'end_ms':first+15*width},
                {'start_ms':first+8*width,'end_ms':first+23*width},{'start_ms':first+24*width,'end_ms':last}]})
    try:
        began=time.monotonic();_,done=scheduler.submit(req);outcome=await asyncio.wait_for(done,30)
        total=(time.monotonic()-began)*1000
        targets=storage.query_bars('BTCUSDT',f'{period}m',first,last,market_type='futures')
        assert len(targets)==32 and outcome.verified_contiguous
        mismatches=[]
        for row in targets:
            group=[by_time[at] for at in range(row['open_time'],row['open_time']+width,60000)]
            expected={'open':group[0]['open'],'close':group[-1]['close'],
                'high':max(v['high'] for v in group),'low':min(v['low'] for v in group)}
            expected.update({f:math.fsum(v[f] for v in group) for f in fields[4:]})
            for f,value in expected.items():
                if row[f] is None or not math.isclose(row[f],value,rel_tol=1e-12,abs_tol=1e-9):
                    mismatches.append({'open_time':row['open_time'],'field':f,'expected':value,'actual':row[f]})
        assert not mismatches,mismatches
        counts=Counter(at for e in executions for at in range(e['start_ms'],e['end_ms']+1,width))
        return {'period':period,'base_inputs_local':local,'actual_total_ms':round(total,3),'target_count':len(targets),
            'execution_count':len(executions),'repeated_target_opens':sum(v-1 for v in counts.values()),
            'controlled_fetch_calls':len(upstream_calls),'controlled_fetch_rows':sum(c['rows'] for c in upstream_calls),
            'executions':executions,'fetch_ranges':upstream_calls,'numeric_mismatches':mismatches,
            'scheduler':scheduler.snapshot()}
    finally:
        await scheduler.shutdown();await engine.close();await dm.shutdown()
        assert dm.memory_budget.snapshot()['reserved_bytes']==0

for case in fixture['cases']:
    for local in [False,True]:
        receipt['cases'].append(asyncio.run(scenario(case,local)))
receipt['passed']=all(not c['numeric_mismatches'] for c in receipt['cases'])
(args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'passed':receipt['passed'],'cases':[{k:c[k] for k in ['period','base_inputs_local','target_count','execution_count','repeated_target_opens','controlled_fetch_calls','controlled_fetch_rows','actual_total_ms']} for c in receipt['cases']]}))
