"""Installed external evaluators against checksum-verified local trade archives.

Measures archive admission, matching/evaluation and report encoding separately.
No network, registry mutation, production run DB, or invented order book data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'packages/candlescope-plugin-sdk/src')]
from app.backtest.native import invoke, digest, encoded, PROTOCOL
from app.backtest.external import run_external_host, host_identity
from app.backtest.external_market import validate_execution
from app.market_dataset.snapshot import MarketEvent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--registry',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    import pyarrow.parquet as pq
    import pandas as pd
    started=time.perf_counter()
    archive=ROOT/'backend/data/raw_agg_trades/exchange=binance/market_type=futures/symbol=BTCUSDT/date=2026-06-01'
    metadata=json.loads((archive/'_verified_import.json').read_text(encoding='utf-8'))
    chunks=[]
    for item in metadata['objects']:
        path=archive/Path(item['object_id']).name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['parquet_sha256']
        chunks.append(pq.ParquetFile(path).read(columns=['agg_trade_id','trade_time_ms','price','quantity','is_buyer_maker']).to_pandas())
    data=pd.concat(chunks,ignore_index=True)
    assert (data.agg_trade_id.diff().dropna()==1).all()
    assert data.trade_time_ms.is_monotonic_increasing
    grouped=data.groupby(data.trade_time_ms//60000,sort=True)
    frame=grouped.agg(open=('price','first'),high=('price','max'),low=('price','min'),close=('price','last'),volume=('quantity','sum'))
    bars=[dict(time=int(key)*60,**row) for key,row in zip(frame.index,frame.to_dict('records'))]
    assert len(bars)==1440
    report={'source':metadata['metadata'],'parquet_objects_verified':len(chunks),'archive_seconds':time.perf_counter()-started,
        'scope':'archive verification, fixed input, real external plugin IPC, kernel/account/report; excludes UI paint and production DB scheduling',
        'runs':[]}
    registry=json.loads(args.registry.read_text(encoding='utf-8'))
    plugins={language:{'command':[row['launch']['executable'],'-I','-m',module]} for language,module,row in [
        ('pine','candlescope_plugin_pine_compat.external_strategy',registry['plugins'][0]),
        ('pyne','candlescope_plugin_pyne.external_strategy',registry['plugins'][1])]}
    sources={'pine':'''//@version=6
strategy("Archive qualification")
if bar_index % 120 == 0
    strategy.entry("L", strategy.long, qty=0.01)
if bar_index % 120 == 119
    strategy.close("L")
plot(strategy.equity)
''','pyne':'''def init(ctx):
    ctx.strategy.configure()
def on_bar(ctx, bar):
    if ctx.bar_index % 120 == 0:
        ctx.strategy.entry("L", qty=0.01)
    if ctx.bar_index % 120 == 119:
        ctx.strategy.close("L")
    ctx.plot("Equity", ctx.strategy.equity)
'''}
    def save():
        args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    for language,plugin in plugins.items():
        identity=invoke(plugin,{'operation':'describe'})['identity']
        comparisons=[]
        for mode,count,worker,callbacks in [('BAR_APPROX',60,False,False),('BAR_APPROX',60,True,False),('BAR_APPROX',1440,True,False),('TRADE_TAPE',120,True,False),('TRADE_TAPE',120,True,True)]:
            selected=bars[:count]
            wire={'protocol':PROTOCOL,'identity':identity,'host_runtime_identity':host_identity(),
                'source':sources[language],'parameters':{},'context':{'symbol':'BINANCE:BTCUSDT','timeframe':'1'},
                'bars':selected,'contexts':[],'context_intervals':[],'interval':'1m','execution_fidelity':mode,
                'host_settings':{'initial_balance':10000,'slippage_bps':1,'taker_fee_bps':1}}
            if callbacks:
                wire['fill_recalculation']=True
                if language=='pine':
                    wire['source']=sources[language].replace('strategy("Archive qualification")','strategy("Archive qualification", calc_on_order_fills=true)').replace('if bar_index % 120 == 0','if bar_index % 120 == 0 and barstate.isconfirmed').replace('if bar_index % 120 == 119','if strategy.position_size > 0 and not barstate.isconfirmed')
                else:
                    wire['source']=sources[language].replace('ctx.strategy.configure()','ctx.strategy.configure(calc_on_order_fills=True)')+'\ndef on_fill(ctx, bar):\n    if ctx.strategy.position_size > 0:\n        ctx.strategy.close("L")\n'
            admission=time.perf_counter()
            if mode=='TRADE_TAPE':
                section=data[data.trade_time_ms < (selected[-1]['time']+60)*1000]
                events=[MarketEvent(i+1,int(row.trade_time_ms),'TRADES',{'source_event_kind':'AGG_TRADE',
                    'source_sequence':int(row.agg_trade_id),'price':str(row.price),'qty':str(row.quantity)})
                    for i,row in enumerate(section.itertuples())]
                validate_execution(events,selected,'1m',mode)
                wire['execution_events']=[dict(sequence=e.sequence,event_time_ms=e.event_time_ms,role=e.role,payload=e.payload) for e in events]
            admitted=time.perf_counter()-admission
            start=time.perf_counter()
            item={'language':language,'mode':mode,'bars':count,'events':len(wire.get('execution_events',[])),
                'persistent_worker':worker,'fill_recalculation':callbacks,'admission_seconds':admitted,'input_hash':digest(wire)}
            try:
                result=run_external_host(plugin,wire,invoke if worker else lambda *a,**k:invoke(*a,**k),threading.Event())
                item['execution_seconds']=time.perf_counter()-start
                stamp=time.perf_counter(); encoded_result=encoded(result)
                item.update(status='passed',encoding_seconds=time.perf_counter()-stamp,report_bytes=len(encoded_result.encode()),
                    fills=len(result['trades']),report_hash=digest(result))
                if count==60: comparisons.append(item['report_hash'])
            except Exception as exc:
                item.update(status='failed',execution_seconds=time.perf_counter()-start,error=str(exc))
            report['runs'].append(item); save(); print(json.dumps(item),flush=True)
        assert len(comparisons)==2 and comparisons[0]==comparisons[1], 'worker/single-shot report mismatch'
    save()


if __name__=='__main__': main()
