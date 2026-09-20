"""Sequential installed-wheel comparison on checksum-verified archive data."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'packages/candlescope-plugin-sdk/src')]
from app.backtest.native import invoke, digest, encoded, PROTOCOL
from app.backtest.external import run_external_host, host_identity


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--bars',type=int,default=1440)
    parser.add_argument('--candidate-only',action='store_true')
    args=parser.parse_args()
    import pyarrow.parquet as pq
    import pandas as pd
    import psutil
    archive=ROOT/'backend/data/raw_agg_trades/exchange=binance/market_type=futures/symbol=BTCUSDT/date=2026-06-01'
    metadata=json.loads((archive/'_verified_import.json').read_text())
    chunks=[]
    for item in metadata['objects']:
        path=archive/Path(item['object_id']).name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['parquet_sha256']
        chunks.append(pq.ParquetFile(path).read(columns=['agg_trade_id','trade_time_ms','price','quantity']).to_pandas())
    data=pd.concat(chunks,ignore_index=True)
    assert data.trade_time_ms.is_monotonic_increasing and (data.agg_trade_id.diff().dropna()==1).all()
    frame=data.groupby(data.trade_time_ms//60000,sort=True).agg(open=('price','first'),high=('price','max'),low=('price','min'),close=('price','last'),volume=('quantity','sum'))
    bars=[dict(time=int(k)*60,**v) for k,v in zip(frame.index,frame.to_dict('records'))]
    if not 1 <= args.bars <= len(bars): parser.error('bars outside available archive')
    bars=bars[:args.bars]
    source='''def init(ctx):
    ctx.strategy.configure()
def on_bar(ctx, bar):
    if ctx.bar_index % 120 == 0:
        ctx.strategy.entry("L", qty=0.01)
    if ctx.bar_index % 120 == 119:
        ctx.strategy.close("L")
    ctx.plot("Equity", ctx.strategy.equity)
'''
    report={'archive':metadata['metadata'],'verified_objects':len(chunks),'bars':len(bars),'runs':[],
        'scope':'sequential installed evaluators, full host BAR matching and JSON report encoding; excludes production scheduling and UI',
        'comparison':'complete report except runtime identity; engine code hashes must differ'}
    hashes=[]
    runs=[('candidate-1',args.candidate),('candidate-2',args.candidate)]
    if not args.candidate_only: runs.insert(0,('baseline',args.baseline))
    for label,registry_path in runs:
        registry=json.loads(registry_path.read_text())
        row=next(p for p in registry['plugins'] if p['id']=='candlescope.pyne')
        plugin={'command':[row['launch']['executable'],'-I','-m','candlescope_plugin_pyne.external_strategy']}
        identity=invoke(plugin,{'operation':'describe'})['identity']
        wire={'protocol':PROTOCOL,'identity':identity,'host_runtime_identity':host_identity(),'source':source,'parameters':{},
            'context':{'symbol':'BINANCE:BTCUSDT','timeframe':'1'},'bars':bars,'contexts':[],'context_intervals':[],
            'interval':'1m','execution_fidelity':'BAR_APPROX','host_settings':{'initial_balance':10000,'slippage_bps':1,'taker_fee_bps':1}}
        item={'label':label,'identity':identity,'input_hash':digest(wire),'bundle':row['managed']['installationId']}
        sampled_cpu={}
        stop=threading.Event()
        def sample():
            while not stop.wait(.2):
                for child in psutil.Process().children(recursive=True):
                    try:
                        cpu=child.cpu_times()
                        sampled_cpu[(child.pid,child.create_time())]=cpu.user+cpu.system
                    except psutil.Error:
                        pass
        sampler=threading.Thread(target=sample,daemon=True);sampler.start()
        host_cpu=time.process_time()
        start=time.perf_counter()
        try:
            result=run_external_host(plugin,wire,invoke,threading.Event())
            item['execution_seconds']=time.perf_counter()-start
            stamp=time.perf_counter(); serialized=encoded(result)
            item.update(status='passed',encoding_seconds=time.perf_counter()-stamp,report_bytes=len(serialized.encode()),fills=len(result['trades']))
            result.pop('identity')
            item['semantic_report_hash']=digest(result);hashes.append(item['semantic_report_hash'])
        except Exception as exc:
            item.update(status='failed',execution_seconds=time.perf_counter()-start,error=str(exc))
        finally:
            stop.set();sampler.join()
            item.update(host_cpu_seconds=time.process_time()-host_cpu,sampled_worker_cpu_seconds=sum(sampled_cpu.values()))
        report['runs'].append(item)
        args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(item),flush=True)
    report['all_passed_and_equal']=len(hashes)==len(runs) and len(set(hashes))==1
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    assert report['all_passed_and_equal'], 'benchmark failure or changed full report'


if __name__=='__main__': main()
