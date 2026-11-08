"""Finite alias-cost probe: sixteen compatible rules, eight new closed bars.

Legacy models the previous shared per-series rebuild, not sixteen independent
calculators. Public uses actual canonical SQLite inputs, bounded history process
and public result service. This is not whole-application/native latency evidence.
"""
from pathlib import Path
import argparse
import asyncio
import hashlib
import json
import os
import statistics
import subprocess
import time

if __name__ == '__main__':
    ROOT = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('legacy', 'public'))
    parser.add_argument('name')
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    OUT = ROOT / 'output/alert-builtin-service-20261101'
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ['CANDLE_DATA_DIR'] = str(OUT / ('cost-data-' + args.name + '-' + str(time.time_ns())))
    
    from legacy_indicator_oracle import compute_alert_indicator_values, merge_alert_bar_window
    from app.alerts.indicator_requests import ALIASES
    from app.data_engine.data_manager import DataManager, DataManagerConfig
    from app.data_engine.data_manager.indicator_inputs import IndicatorInputPort
    from app.data_engine.data_manager.models import BarData, SeriesKey
    from app.data_engine.storage import klines_repo
    from app.indicator.query_contracts import IndicatorQuery
    from app.indicator.numeric_queries import NumericIndicatorService
    from app.indicator.range_result_service import IndicatorRangeResultService
    from app.indicator.history_worker import history_executor_snapshot, shutdown_builtin_history
    
    KEY = SeriesKey('BTCUSDT', '1m')
    BASE = 1780000020
    bars = [BarData(time=BASE+i*60, open=100+i/100, high=130+i/100,
                    low=70+i/100, close=100+i/100+(i%17)/4,
                    volume=10+i%5, source='backfill') for i in range(258)]
    klines_repo.init_klines_storage()
    klines_repo.upsert_klines(KEY.symbol, KEY.interval, [dict(open_time=b.time_ms,
        close_time=b.time_ms+59999, open=b.open, high=b.high, low=b.low, close=b.close,
        volume=b.volume, quote_volume=0, trades=0, taker_buy_base=0, taker_buy_quote=0) for b in bars], source='backfill')
    cfg = DataManagerConfig();cfg.query.max_limit=500;cfg.query.auto_backfill=False
    manager=DataManager(cfg);manager.set_storage(klines_repo.KlinesRepoAdapter())
    results=IndicatorRangeResultService()
    service=NumericIndicatorService(IndicatorInputPort(manager), results)
    
    async def main():
        running, lags = True, []
        async def heartbeat():
            while running:
                start=time.perf_counter();await asyncio.sleep(.001)
                lags.append(max(0,(time.perf_counter()-start-.001)*1000))
        monitor=asyncio.create_task(heartbeat());await asyncio.sleep(0)
        windows=[list(bars[:250]) for _ in range(16)]
        samples=[]
        profiler=None
        try:
            for index in range(250,258):
                if args.profile and index==251:
                    import cProfile
                    profiler=cProfile.Profile();profiler.enable()
                cpu=time.process_time();started=time.perf_counter();lag_start=len(lags)
                if args.mode=='legacy':
                    cached=None;fingerprint=None;outputs=[]
                    for i in range(16):
                        windows[i]=merge_alert_bar_window(windows[i], bars[index])
                        key=tuple((b.time,b.close) for b in windows[i])
                        if key!=fingerprint:
                            cached=compute_alert_indicator_values(windows[i]);fingerprint=key
                        outputs.append(dict(cached))
                else:
                    request=IndicatorQuery(KEY,tuple(ALIASES.values()),through_ms=bars[index].time_ms)
                    snapshots=await asyncio.gather(*(service.query(request) for _ in range(16)))
                    assert all(s.status=='ready' for s in snapshots), snapshots[0]
                    outputs=[{name:dict(s.values)[definition] for name,definition in ALIASES.items()} for s in snapshots]
                elapsed=(time.perf_counter()-started)*1000;parent_cpu=(time.process_time()-cpu)*1000
                if profiler is not None and index==257:
                    profiler.disable();profiler.dump_stats(str(OUT/(args.name+'.pstats')))
                await asyncio.sleep(.002)
                measured_lag=max(lags[lag_start:],default=0)
                oracle=compute_alert_indicator_values(bars[index-249:index+1])
                assert all(value==oracle for value in outputs)
                await asyncio.sleep(.002)
                samples.append(dict(bar=index,wall_ms=elapsed,parent_cpu_ms=parent_cpu,
                    max_loop_lag_ms=measured_lag,
                    values_sha256=hashlib.sha256(json.dumps(outputs,sort_keys=True).encode()).hexdigest()))
            return dict(schema='candlescope.alert-numeric-cost/1',mode=args.mode,
                source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                numeric_source_sha256=hashlib.sha256((ROOT/'backend/app/indicator/numeric_queries.py').read_bytes()).hexdigest(),
                inputs_source_sha256=hashlib.sha256((ROOT/'backend/app/data_engine/data_manager/indicator_inputs.py').read_bytes()).hexdigest(),
                worker_source_sha256=hashlib.sha256((ROOT/'backend/app/indicator/history_worker.py').read_bytes()).hexdigest(),
                rules=16,source_slots=250,ticks=8,oracle_equal=True,samples=samples,
                steady_median_wall_ms=statistics.median(s['wall_ms'] for s in samples[1:]),
                parent_cpu_ms=sum(s['parent_cpu_ms'] for s in samples),
                history_process=history_executor_snapshot(),numeric=service.snapshot(),cache=results.snapshot(),
                limits=['Component probe, not native notification latency or an SLA.',
                        'Legacy shares one rebuild per series, as the prior runtime did.',
                        'First public request includes process startup; parent and child CPU reported separately.',
                        'Shared host activity may interfere; retain both run orders and adverse samples.'])
        finally:
            running=False;await monitor;await service.close();await shutdown_builtin_history();await manager.shutdown()
    
    result=asyncio.run(main())
    target=OUT/(args.name+'.json');target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(file=str(target),mode=args.mode,median=result['steady_median_wall_ms'],
        parent_cpu_ms=result['parent_cpu_ms'],max_loop_lag_ms=max(s['max_loop_lag_ms'] for s in result['samples']))))
