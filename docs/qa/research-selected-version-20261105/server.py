"""Owned deterministic browser service; actual financial/runtime paths.

Only public stream leases are fixture inputs. No network, provider, financial
response, frozen-version response or continuous API is mocked.
"""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.api.v1.backtests import router
from app.backtest.continuous_controller import ContinuousStrategyController
from app.backtest.continuous_provider import ContinuousProviderFactory
from app.core import config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import DataEvent, DataEventType
from app.data_engine.data_manager.strategy import StrategyDataManager
from app.data_engine.storage import klines_repo
from tests.test_python_editor import service_at, compile_editor, SOURCE as EDITOR_SOURCE
from tests.test_research_selected_version import execute_selected_research
from tests.test_query_cache_fencing import START, STEP, SOURCE, KEY, _row

root = Path(os.environ['RESEARCH_RETURN_QA_PROFILE'])
root.mkdir(parents=True, exist_ok=False)
config.RUNTIME_MODE = 'LIVE'
config.KLINES_DB_PATH = klines_repo.KLINES_DB_PATH = root / 'market.sqlite'
klines_repo.init_klines_storage()
service = service_at(root)
run_id = execute_selected_research(service)
selected = service.selected_run_version(run_id)
compile_editor(service, EDITOR_SOURCE + '\n# newer mutable research draft; do not return this\n')
(root / 'selected.json').write_text(json.dumps(selected, indent=2))
research_before = service.repository.get_run_by_id(run_id)
manager = DataManager()
manager.set_storage(klines_repo.KlinesRepoAdapter())
klines_repo.upsert_klines(KEY.symbol, KEY.interval, [_row(START+i*STEP,100+i%7) for i in range(30)], source=SOURCE)
leases = set()
async def acquire(*args, **kwargs): leases.add(kwargs['consumer_id'])
async def release(*args, **kwargs): leases.discard(kwargs['consumer_id'])
manager.bars.ensure_stream = acquire
manager.release_stream = release
now = [START+20*STEP]
gate = StrategyDataManager(service, market_manager=manager)
controller = None

@asynccontextmanager
async def lifespan(app):
    global controller
    controller = await ContinuousStrategyController.open(service.settings.db_path.parent / 'continuous.db', manager,
        clock_ms=lambda: now[0], provider_factory=ContinuousProviderFactory(scratch_root=root))
    gate.bind_continuous(controller)
    await controller.create('qa/preexisting', provider={'language': 'python', 'source_text': EDITOR_SOURCE + '\n# preexisting chart version\n',
        'parameters': {'fast': 9, 'slow': 11}, 'output_mode': 'SIGNAL', 'runtime_mode': 'TRUSTED_LOCAL', 'trusted_confirmed': True},
        execution={'account_model': 'SPOT_CASH_V1', 'initial_balance': '10000'}, series=KEY, mode='HISTORY_LIVE', from_ms=START)
    await asyncio.wait_for(controller.wait_initial('qa/preexisting'), 20)
    app.state.data_manager_core = SimpleNamespace(strategy=gate)
    try: yield
    finally:
        await gate.shutdown()
        await manager.shutdown()
        assert not leases
        assert service.repository.get_run_by_id(run_id) == research_before
        (root / 'shutdown.json').write_text(json.dumps({'closed': controller.closed, 'leases': sorted(leases), 'research_unchanged': True}))
        service.shutdown()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:23183'],
    allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'Idempotency-Key'])
app.include_router(router, prefix='/api/v1')
@app.get('/api/v1/qa/selected')
async def metadata(): return {'run_id': run_id, 'source': EDITOR_SOURCE, 'selected': selected}
@app.post('/api/v1/qa/advance')
async def advance():
    now[0] += 5*STEP
    await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED, KEY))
    return {'through_ms': now[0]}
@app.get('/api/v1/qa/audit')
async def audit():
    rows = controller.store.list_summaries()
    return {'research_unchanged': service.repository.get_run_by_id(run_id) == research_before,
        'runs': [{'creation': controller.store.creations.summary_for_run(row['id']),
                  'stored': controller.store.load(row['id']), 'description': controller.store.describe(row['id'])}
            for row in rows], 'leases': sorted(leases)}

if __name__ == '__main__': uvicorn.run(app, host='127.0.0.1', port=23184, log_level='warning')
