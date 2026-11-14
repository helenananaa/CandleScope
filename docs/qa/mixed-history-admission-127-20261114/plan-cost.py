"""Observe actual cold default planner proposals, without any network fetching."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--checkout', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--required-composition', action='store_true')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(args.checkout / 'backend'))
from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.storage import klines_repo
from app.data_engine.storage.revisions import ensure_acquisition
from app.data_engine.backfill import BackfillEngine
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.mixed_plan import build_mixed_backfill_plan
from app.data_engine.backfill.models import GapInfo, GapType

async def case(count):
    database = args.output / f'case-{count}.sqlite'
    klines_repo.KLINES_DB_PATH = core_config.KLINES_DB_PATH = database
    klines_repo.init_klines_storage()
    config = DataManagerConfig()
    config.query.auto_backfill = False
    manager = DataManager(config)
    manager.set_storage(klines_repo.KlinesRepoAdapter())
    backfill_config = BackfillConfig()
    backfill_config.history_archive_enabled = False
    engine = BackfillEngine(backfill_config, storage=klines_repo.AsyncKlinesRepoAdapter())
    engine.memory_budget = manager.memory_budget
    gap = GapInfo('BTCUSDT', '10007m', GapType.HEAD, 0, (count - 1) * 10007 * 60000,
                  count, market_type='futures')
    diagnostics = {}
    try:
        started = time.process_time()
        with ensure_acquisition(manager.query_engine.storage.revision_store.head()):
            metadata = ({'required_history_composition': 'binance.usdm.trade-klines/base-utc/1'}
                        if args.required_composition else {})
            plan = await build_mixed_backfill_plan(engine, [gap], metadata, diagnostics)
        return dict(count=count, adopted=plan is not None,
            estimated_requests=plan.estimated_requests if plan else None,
            tasks=len(plan.tasks) if plan else None,
            intervals=sorted({task.interval for task in plan.tasks}) if plan else [],
            diagnostics=diagnostics, process_cpu_ms=(time.process_time() - started) * 1000)
    finally:
        await engine.close()
        await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

results = [asyncio.run(case(count)) for count in (1, 8, 128, 406)]
runtime_files = subprocess.check_output(['git', 'ls-files', 'backend/app'], cwd=args.checkout, text=True).splitlines()
report = dict(source_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'],
    cwd=args.checkout, text=True).strip(),
    required_composition=args.required_composition,
    runtime_sha256={name: hashlib.sha256((args.checkout / name).read_bytes()).hexdigest() for name in runtime_files},
    runtime_diff=subprocess.check_output(['git', 'diff', 'HEAD', '--', 'backend/app'], cwd=args.checkout, text=True),
    driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    scope='actual default planner, empty real SQLite, no network; request counts are proposals; '
          'one unpaired CPU observation per size, not stable latency or native qualification', results=results)
(args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
