"""Exercise the actual installed Pine/Pyne plugins through the host HTTP contract."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root/'backend'),str(root/'packages/candlescope-plugin-sdk/src'),str(root/'packages/candlescope-backtest-sdk/src')]
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.backtests import router
from app.backtest.runtime import BacktestRuntime
from app.core.config import load_backtest_settings
from app.local_data.service import LocalDatasetService, LocalImportOptions


def qualify(directory):
    execution = json.loads((directory/'execution.json').read_text())
    manifest = json.loads((directory/'manifest.json').read_text())
    for filename, key in [('execution.json','execution_sha256'),('bars.csv','bars_sha256')]:
        assert hashlib.sha256((directory/filename).read_bytes()).hexdigest() == manifest[key]
    results = []
    with tempfile.TemporaryDirectory(prefix='okx-sampled-') as temporary:
        base = Path(temporary)
        local = LocalDatasetService(base/'local')
        data = local.import_csv(directory/'bars.csv', LocalImportOptions(name='OKX sampled qualification',symbol='BTCUSDT',interval='1m',timestamp_unit='ms'))
        settings = load_backtest_settings({'BACKTEST_ENABLED':'1','BACKTEST_BAR_ENABLED':'1'},data_dir=base,klines_db_path=base/'klines.db',replay_db_path=base/'replay.db')
        host = BacktestRuntime.start(settings,local_data_dir=base/'local')
        try:
            app=FastAPI(); app.state.backtest_runtime=host; app.include_router(router)
            begin,end=manifest['start_time_ms'],manifest['end_time_ms_exclusive']-1
            snapshot=host.preview_snapshot(dataset_id=data['dataset_id'],data_epoch=data['data_epoch'],start_time_ms=begin,end_time_ms=end,interval='1m')
            with TestClient(app) as client:
                for language in ('pine','pyne'):
                    for callbacks in (False,True):
                        pine = f'''//@version=6
strategy("OKX sampled", calc_on_order_fills={str(callbacks).lower()})
if bar_index == 0 and barstate.isconfirmed
    strategy.entry("L", strategy.long, qty=0.001)
if bar_index == 5 and barstate.isconfirmed
    strategy.close("L")
plot(close)
'''
                        pyne = f'''def init(ctx):
    ctx.strategy.configure(calc_on_order_fills={callbacks})
def on_bar(ctx, bar):
    if ctx.bar_index == 0:
        ctx.strategy.entry("L", ctx.strategy.long, qty=0.001)
    if ctx.bar_index == 5:
        ctx.strategy.close("L")
def on_fill(ctx, bar):
    pass
'''
                        payload=dict(language=language,source=pine if language=='pine' else pyne,
                            dataset_id=data['dataset_id'],data_epoch=data['data_epoch'],snapshot_hash=snapshot['snapshot_hash'],
                            start_time_ms=begin,end_time_ms=end,interval='1m',exchange='okx',market_type='spot',
                            context={'symbol':'OKX:BTCUSDT','timeframe':'1'}, execution_fidelity='BOOK_SAMPLED',
                            fill_recalculation=callbacks,execution_data=execution,
                            host_settings={'initial_balance':10000,'slippage_bps':0,'taker_fee_bps':0})
                        started=time.monotonic()
                        response=client.post('/backtests/external/runs',json=payload,headers={'Idempotency-Key':f'{language}-{callbacks}'})
                        assert response.status_code==200,response.text
                        run_id=response.json()['run_id']
                        while time.monotonic()-started < 140:
                            record=host.native.get(run_id)
                            if record['state'] in {'COMPLETED','FAILED','CANCELLED'}: break
                            time.sleep(.05)
                        assert record['state']=='COMPLETED',record.get('error')
                        report=record['result']
                        assert report['fidelity']=='BOOK_SAMPLED'
                        assert report['account_authority']=='candlescope'
                        assert report['fill_model']=='SAMPLED_L2_VISIBLE_TAKER_ONLY_V1'
                        assert report['raw_output']['execution_provenance']==execution['provenance']
                        assert len(report['trades'])>=2 and float(report['trades'][-1]['position_after'])==0
                        assert report['raw_output']['depth_model']['passive_policy']=='NO_INFERRED_PASSIVE_FILLS'
                        assert client.get(f'/backtests/external/runs/{run_id}/export').json()['result']==report
                        # Same ordered input and source must reproduce the whole report.
                        response=client.post('/backtests/external/runs',json=payload,headers={'Idempotency-Key':f'{language}-{callbacks}-repeat'})
                        assert response.status_code==200,response.text
                        repeat=response.json()
                        until=time.monotonic()+140
                        while time.monotonic()<until:
                            repeated=host.native.get(repeat['run_id'])
                            if repeated['state'] in {'COMPLETED','FAILED','CANCELLED'}: break
                            time.sleep(.05)
                        assert repeated['state']=='COMPLETED',repeated.get('error')
                        assert repeated['result']==report
                        results.append({'language':language,'fill_callbacks':callbacks,'repeat_equal':True,
                            'seconds_including_repeat':time.monotonic()-started,'identity':record['runtime_identity'],
                            'report_hash':report['report_hash'],'trades':report['trades'],
                            'position':report['position'],'depth_model':report['raw_output']['depth_model']})
                        print(json.dumps({'language':language,'callbacks':callbacks,'fills':len(report['trades']),'repeat_equal':True}),flush=True)
        finally:
            host.shutdown()
    # Both language runtimes must receive the same host-account fills.
    for row in results[1:]:
        assert row['trades']==results[0]['trades'] and row['position']==results[0]['position']
    return {'schema':'candlescope.okx-sampled-qualification/1','manifest':manifest,'runs':results,
            'all_passed':True,'same_host_ledger_across_languages_and_callbacks':True,
            'scope':'actual installed engines, isolated host HTTP and export; 10-minute public archive window; no exact queue claims'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps(qualify(args.directory),ensure_ascii=False,indent=2),encoding='utf-8')
