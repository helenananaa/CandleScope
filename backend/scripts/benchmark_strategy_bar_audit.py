"""Read-only product-path benchmark using disposable databases and synthetic OHLCV."""
import argparse
import json
import math
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from collections import defaultdict

import app.backtest.service as service_module
from app.backtest.service import BacktestService
from app.backtest.strategy.chart_pyne import CHART_PYNE_REVISION
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from app.backtest.reports import verify_report_hash
from app.core.config import load_backtest_settings
from app.market_dataset.snapshot import MarketEvent
from scripts.strategy_benchmark_sources import SMA, RSI


def measure(count, name, root, output, v2=False, dense=False, python_batch=False, python_case="SMA", checkpoint_policy=None):
    if python_batch and name != 'PYTHON':
        raise ValueError('--python-batch requires --strategy PYTHON')
    if python_case != "SMA" and (python_batch or name != "PYTHON"):
        raise ValueError('generic cases require scalar PYTHON execution')
    timings = defaultdict(float)
    calls = defaultdict(int)
    def wrap(owner, attr, label):
        original = getattr(owner, attr)
        def timed(*args, **kwargs):
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                timings[label] += time.perf_counter() - start
                calls[label] += 1
        setattr(owner, attr, timed)
        return original
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1", "BACKTEST_TRADE_EXPLANATION_ENABLED": "1", "BACKTEST_MAX_RUN_SECONDS": "180"}, data_dir=root, klines_db_path=root/'market.db', replay_db_path=root/'replay.db')
    service = BacktestService.start(settings, now_ms=1, enforce_registered_revisions=True)
    start = time.perf_counter()
    events = []
    for i in range(1, count+1):
        price = round(100 + 10*math.sin(i/(3 if dense else 40)), 5)
        events.append(MarketEvent(sequence=i, event_time_ms=i*60000, role='BARS', payload={'open':str(price), 'high':str(price+0.5), 'low':str(price-0.5), 'close':str(price), 'volume':'10000'}))
    events = tuple(events)
    data_seconds = time.perf_counter()-start
    if name == 'PYTHON':
        os.environ['BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED'] = '1'
        bundle_path = Path(__file__).resolve().parents[2] / 'packages/candlescope-backtest-sdk/templates/sma_cross'
        if python_batch:
            bundle_path = bundle_path.with_name('sma_cross_batch')
        if python_case != "SMA":
            from scripts.generic_strategy_sources import SOURCES
            template = bundle_path
            bundle_path = root / "generic-script"
            bundle_path.mkdir()
            manifest = json.loads((template / "strategy.json").read_text(encoding="utf-8"))
            manifest["name"] = "Generic " + python_case
            if python_case == "ORDERS":
                manifest["outputModes"] = ["ORDER_INTENT"]
            (bundle_path / "strategy.json").write_bytes(json.dumps(manifest, indent=2).encode())
            (bundle_path / "strategy.py").write_bytes(SOURCES[python_case].encode())
            (bundle_path / "requirements.lock").write_bytes((template / "requirements.lock").read_bytes())
        bundle = service.create_python_strategy_bundle(directory=str(bundle_path), now_ms=1)
        revision = service.create_python_strategy_revision(bundle['bundle_id'], now_ms=1)
    else:
        revision = service.create_strategy_revision({'name':name, 'language':'PYNE_CHART_V1','source_text':SMA if name=='SMA' else RSI,'parameter_schema':[]})
    payload = {'strategy_revision_id':revision['revision_id'],'dataset_id':'synthetic-audit','data_epoch':'epoch-audit','snapshot_hash':'sha256:audit','fidelity_mode':'BAR_APPROX','source_event_kind':'BAR','start_time_ms':0,'end_time_ms':(count+1)*60000,'symbol':'BTCUSDT','interval':'1m','output_mode':'TARGET_POSITION','initial_balance':'10000','slippage_bps':'1','taker_fee_bps':'4','maker_fee_bps':'4'}
    if v2:
        payload.update(execution_model_revision='EXECUTION_REALISM_V2')
    if checkpoint_policy is not None:
        payload["checkpoint_policy"] = checkpoint_policy
    if python_case == "ORDERS":
        payload["output_mode"] = "ORDER_INTENT"
    if name == 'PYTHON':
        payload.update(parameters={'fast':3, 'slow':5}, python_runtime_mode='TRUSTED_LOCAL', python_trusted_confirmed=True)
        if python_batch:
            payload['python_execution_protocol'] = 'MARKET_BATCH_V1'
    service.smoke_strategy_revision(revision['revision_id'], {**payload, 'end_time_ms': min(payload['end_time_ms'], 7*86400000)}, now_ms=2)
    created = service.create_run(payload, idempotency_key='audit',now_ms=3)
    provider = (service.build_python_host_provider(revision['revision_id'], parameters={'fast':3,'slow':5}, mode='TRUSTED_LOCAL', trusted_confirmed=True) if name == 'PYTHON' else IsolatedStrategyProvider(CHART_PYNE_REVISION, step_timeout_s=2))
    originals=[]
    for owner, attr, label in [(provider,'step','script_step'),(service,'_save_bar_checkpoint','checkpoint'),(service,'_persist_completed_run','report_and_persist'),(service_module,'build_cost_sensitivity_matrix','cost_sensitivity'),(service_module.SimulationKernel,'run','kernel_including_callbacks')]:
        originals.append((owner,attr,wrap(owner,attr,label)))
    start = time.perf_counter()
    result={'execution_model':'EXECUTION_REALISM_V2' if v2 else 'LEGACY_DEFAULT','strategy':name,'runtime_mode':'TRUSTED_LOCAL' if name=='PYTHON' else 'ISOLATED_PROVIDER','bars':count,'synthetic_data_seconds':data_seconds,'explanations_enabled':settings.trade_explanation_effective,'checkpoint_interval':settings.checkpoint_event_interval,'deadline_seconds':settings.max_run_seconds}
    if python_batch:
        result['python_execution_protocol'] = 'MARKET_BATCH_V1'
    result['compact_spawn_enabled'] = os.environ.get('BACKTEST_COMPACT_SPAWN_ENABLED', '1') == '1'
    result['host_hotpath_enabled'] = os.environ.get('BACKTEST_HOST_HOTPATH_ENABLED', '1') == '1'
    if name == "PYTHON":
        result["python_case"] = python_case
        result["generic_bar_enabled"] = os.environ.get("BACKTEST_GENERIC_BAR_ENABLED", "1") == "1"
        result["fused_output_enabled"] = os.environ.get("BACKTEST_FUSED_OUTPUT_ENABLED", "1") == "1"
        try:
            from app.backtest.strategy import _native_rows
            result["native_row_abi"] = _native_rows.ROW_PROTOCOL_ABI
            result["native_row_module"] = _native_rows.__file__
        except (ImportError, AttributeError):
            result["native_row_abi"] = None
    result["policy_flags"] = {name: os.environ.get(name, "1") == "1" for name in (
        "BACKTEST_DIRECT_FEEDBACK_ENABLED", "BACKTEST_OWNED_REPORT_ENABLED", "BACKTEST_CHUNKED_REPORT_ENABLED")}
    result["checkpoint_policy"] = checkpoint_policy or "INTERVAL"
    result["four_path_flags"] = {name: os.environ.get(name, "0" if name == "BACKTEST_SPECIALIZED_BAR_ENABLED" else "1") == "1" for name in (
        "BACKTEST_NATIVE_ENTRY_ENABLED", "BACKTEST_NATIVE_OUTPUT_FIELDS_ENABLED",
        "BACKTEST_SPECIALIZED_BAR_ENABLED", "BACKTEST_INCREMENTAL_CHECKPOINT_ENABLED")}
    try:
        completed=service.execute_bar_run(created['run_id'],events=events,provider=provider,now_ms=3)
        result['execution_seconds']=time.perf_counter()-start
        result['execution_lane']=completed.get('execution_lane', 'REFERENCE')
        summary_start = time.perf_counter()
        summary = service.get_report_view(created['run_id'])
        result['summary_read_seconds'] = time.perf_counter() - summary_start
        page_start = time.perf_counter()
        page = service.get_report_view(created['run_id'], section='fills', limit=100)
        result['page_read_seconds'] = time.perf_counter() - page_start
        result['page_rows'] = len(page['rows'])
        result['stored_report_bytes'] = service.repository.connection.execute(
            'SELECT length(CAST(report_json AS BLOB)) FROM backtest_reports WHERE run_id=?', (created['run_id'],)).fetchone()[0]
        result['stored_report_parts'] = service.repository.connection.execute(
            'SELECT COUNT(*) FROM backtest_report_parts WHERE run_id=?', (created['run_id'],)).fetchone()[0]
        read_start=time.perf_counter()
        report=service.get_report(created['run_id'])
        result['report_read_seconds']=time.perf_counter()-read_start
        encode_start=time.perf_counter()
        encoded=json.dumps(report,separators=(',',':')).encode()
        result.update(state=completed['state'],report_hash_valid=verify_report_hash(report),fills=len(report.get('fills') or []),equity_points=len(report.get('equity_curve') or []),report_bytes=len(encoded),report_json_seconds=time.perf_counter()-encode_start)
    except Exception as exc:
        result.update(state='FAILED',error=str(exc),execution_seconds=time.perf_counter()-start)
    finally:
        for owner,attr,original in reversed(originals):
            setattr(owner,attr,original)
        service.shutdown()
    result.update(timings_seconds=dict(timings),calls=dict(calls),processed_bars=count if result.get('state')=='COMPLETED' else calls.get('script_step'),timing_scope='parent only; child stages excluded for colocated lane')
    if os.environ.get('STRATEGY_AUDIT_MEMORY'):
        from scripts.strategy_worker_memory import peak_working_set
        result['parent_peak_working_set_bytes'] = peak_working_set()
        memory_path = Path(os.environ['STRATEGY_AUDIT_MEMORY'])
        if memory_path.exists():
            result.update(json.loads(memory_path.read_text(encoding='utf-8')))
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--bars',type=int,required=True)
    parser.add_argument('--strategy',choices=['SMA','RSI','PYTHON'],required=True)
    parser.add_argument('--v2',action='store_true')
    parser.add_argument('--dense',action='store_true')
    parser.add_argument('--checkpoint-policy', choices=['INTERVAL','FINAL_ONLY','NONE'])
    parser.add_argument('--python-batch',action='store_true')
    parser.add_argument('--python-case',choices=['SMA','EMPTY','STATE','FEEDBACK','ORDERS'],default='SMA')
    parser.add_argument('--profile-worker',type=Path)
    parser.add_argument('--worker-timings',type=Path)
    parser.add_argument('--worker-memory',type=Path)
    parser.add_argument('--spawn-timings',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.spawn_timings:
        from app.backtest import colocated
        from scripts.strategy_spawn_timings import install
        args.spawn_timings.parent.mkdir(parents=True, exist_ok=True)
        install(colocated, args.spawn_timings.resolve())
    if args.profile_worker:
        from app.backtest import colocated
        from scripts.strategy_worker_profile import profile_worker
        os.environ['STRATEGY_AUDIT_PROFILE'] = str(args.profile_worker.resolve())
        colocated._worker = profile_worker
    elif args.worker_timings:
        from app.backtest import colocated
        from scripts.strategy_worker_profile import timed_worker
        os.environ['STRATEGY_AUDIT_PROFILE'] = str(args.worker_timings.resolve())
        colocated._worker = timed_worker
    elif args.worker_memory:
        from app.backtest import colocated
        from scripts.strategy_worker_memory import memory_worker
        os.environ['STRATEGY_AUDIT_MEMORY'] = str(args.worker_memory.resolve())
        colocated._worker = memory_worker
    with TemporaryDirectory(prefix='strategy-audit-') as folder:
        measure(args.bars,args.strategy,Path(folder),args.output,args.v2,args.dense,args.python_batch,args.python_case,args.checkpoint_policy)
