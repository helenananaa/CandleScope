"""Controlled default-owner callback proof accounting costs; no network."""
import argparse
import asyncio
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

from app.core import config
from app.data_engine.bar_aggregator import BarInput, BarInputSource, MergeMode
from app.data_engine.data_manager import DataManager
from app.data_engine.storage import klines_repo


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('count', type=int)
    parser.add_argument('growth', type=int)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    klines_repo.init_klines_storage()
    dm = DataManager()
    dm.set_storage(klines_repo.KlinesRepoAdapter())
    agg = dm.bar_aggregator
    interval = str(args.count)+'m'
    agg.add_target('BTCUSDT', interval)
    async def no_siblings(*args):
        return []
    agg.set_source_component_reader(no_siblings)
    for index in range(args.count):
        value = BarInput(symbol='BTCUSDT', source_interval='1m', open_time_ms=index*60000,
            close_time_ms=(index+1)*60000-1, open=100., high=102., low=99., close=101., volume=1.,
            quote_volume=101., trades=1, taker_buy_base=.4, taker_buy_quote=40.,
            source=BarInputSource.BACKFILL, is_closed=True, merge_mode=MergeMode.COMPONENT,
            extra={'source_ref': {'series': 'controlled-source', 'revision': index+1,
                                  'proof': {'metadata': 'accepted'}}})
        await agg.ingest_bar_input('binance', 'spot', 'BTCUSDT', interval, value, emit_events=False)
    state = agg.get_pipeline(interval).bar_state.get_closed('binance', 'spot', 'BTCUSDT', 0)
    expected = state.to_storage_dict()
    times, held, observations = [], [], []
    async def callback(event):
        if args.growth:
            key = next(iter(event.bar.source_refs))
            event.bar.source_refs[key]['proof']['metadata'] = 'x' * args.growth
        stamp = time.process_time_ns()
        usage = agg.memory_usage()
        times.append((time.process_time_ns()-stamp)/1000)
        if not held:
            held.append(dm.memory_budget.snapshot(measure_heap=True)['owners']['realtime-state'])
        observations.append(event.bar.to_storage_dict())
    agg.publisher.on_bar_closed(callback)
    try:
        for _ in range(9):
            await agg.publisher.emit_closed(state)
        assert all({k:v for k,v in item.items() if k != 'source_refs'} ==
                   {k:v for k,v in expected.items() if k != 'source_refs'} for item in observations)
        assert state.to_storage_dict() == expected
        outside = []
        for _ in range(32):
            stamp = time.process_time_ns()
            agg.memory_usage()
            outside.append((time.process_time_ns()-stamp)/1000)
        agg.remove_target('BTCUSDT', interval)
        after = dm.memory_budget.snapshot(measure_heap=True)['owners']['realtime-state']
        result = {'backend': klines_repo.__file__, 'python': sys.version, 'platform': platform.platform(),
            'count': args.count, 'growth': args.growth, 'held': held[0], 'after': after,
            'callback_usage_cpu_us': times[2:], 'callback_usage_cpu_median_us': statistics.median(times[2:]),
            'outside_callback_cpu_us': outside,
            'outside_callback_cpu_median_us': statistics.median(outside),
            'payload_hash': hashlib.sha256(json.dumps(observations, sort_keys=True).encode()).hexdigest(),
            'scope': 'controlled accepted components; default DataManager not started; construction/copy/heap traversal outside usage timing; no network/native/RSS/endurance qualification'}
        args.output.write_text(json.dumps(result, indent=2)+'\n')
    finally:
        await dm.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
