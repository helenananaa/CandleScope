"""Controlled target churn/replay costs, no network/DB/native acceptance.

Run once per fresh process with PYTHONPATH pointing to the full selected backend.
"""
import asyncio
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

isolated=tempfile.TemporaryDirectory()
os.environ['CANDLE_DATA_DIR']=isolated.name
from app.data_engine.bar_aggregator import BarAggregator,BarAggregatorConfig
from app.data_engine.memory_budget import retained_size

ROWS=[dict(open_time=i*60000,close_time=(i+1)*60000-1,open=100.,high=102.,low=99.,
    close=101.,volume=1.,quote_volume=2.,trades=1,taker_buy_base=.4,taker_buy_quote=.8)
    for i in range(89)]
SYMBOLS=[f'CHURN{i}USDT' for i in range(16)]


def digest(values):
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


def measured(agg):
    gc.collect()
    return dict(usage=agg.memory_usage(),heap=retained_size(agg._memory_roots())[0])


async def main():
    cfg=BarAggregatorConfig(emit_created_events=False,emit_updated_events=False,
        emit_expired_events=False,finalize_timeout_ms=10**15,update_throttle_ms=0)
    agg=BarAggregator(cfg)
    rows=[]
    for symbol in SYMBOLS:
        agg.add_target(symbol,'89m')
        await agg.on_backfill_bars(symbol,'1m',ROWS)
        bars=agg.get_recent_bars(symbol,'89m')
        assert len(bars)==1
        rows.append(bars[0].to_storage_dict())
    # Keep detached output rows, not BarStates or component graphs.
    del bars
    before=measured(agg)
    started=time.perf_counter_ns(); cpu=time.process_time_ns()
    for symbol in SYMBOLS:
        agg.remove_target(symbol,'89m')
    detach=dict(wall_us=(time.perf_counter_ns()-started)/1000,
                cpu_us=(time.process_time_ns()-cpu)/1000)
    after=measured(agg)
    assert agg.get_targets()==[]
    # Existing explicit replay reconstructs the target; no new persistent owner.
    symbol=SYMBOLS[0]
    started=time.perf_counter_ns(); cpu=time.process_time_ns()
    agg.add_target(symbol,'89m')
    await agg.on_backfill_bars(symbol,'1m',ROWS)
    rebuilt=agg.get_recent_bars(symbol,'89m')[0].to_storage_dict()
    replay=dict(wall_us=(time.perf_counter_ns()-started)/1000,
                cpu_us=(time.process_time_ns()-cpu)/1000)
    assert rebuilt==rows[0]
    print(json.dumps(dict(python=sys.version,platform=platform.platform(),
        backend=str(Path(sys.modules[BarAggregator.__module__].__file__).resolve()),
        scope='16 detached symbols, one 89m closed target each; synthetic source replay, no I/O',
        input_hash=digest(ROWS),closed_hash=digest(rows),rebuilt_hash=digest(rebuilt),
        before=before,after=after,detach=detach,replay=replay,
        source_rows_per_target=len(ROWS),symbols=len(SYMBOLS)),indent=2))

if __name__=='__main__':
    asyncio.run(main())
