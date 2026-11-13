"""Per-process publisher-policy costs, not network/reducer/native performance."""
import argparse
import asyncio
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path
from types import SimpleNamespace

from app.data_engine.bar_aggregator import publisher as publisher_module
from app.data_engine.bar_aggregator.models import BarState
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import DataEventType
from app.data_engine.storage import klines_repo


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('case', choices=['regular', 'preserve', 'unrelated'])
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    publisher_module.time = SimpleNamespace(time=lambda: 2000000)
    klines_repo.init_klines_storage()
    dm = DataManager()
    dm.set_storage(klines_repo.KlinesRepoAdapter())
    pub = dm.bar_aggregator.publisher
    pub.set_update_throttle_ms(1000)
    async def ignore(event):
        pass
    dm.subscribe(ignore, symbol='BTCUSDT', interval='7m',
        event_types={DataEventType.BAR_UPDATED}, preserve_updates=args.case == 'preserve')
    if args.case == 'unrelated':
        for index in range(64):
            dm.subscribe(ignore, symbol='OTHER'+str(index), interval='7m', preserve_updates=True)
    observed = []
    async def record(event):
        observed.append(event.bar.volume)
    pub.on_bar_updated(record)
    state = BarState('BTCUSDT', '7m', 0, 420000, 100, 104, 99, 100, 1)
    samples = []
    try:
        for repeat in range(9):
            observed.clear()
            pub._update_throttle.clear()  # fresh independent policy window
            stamp = time.process_time_ns()
            for index in range(512):
                state.volume = index+1
                await pub.emit_updated(state)
            if repeat >= 2:
                samples.append((time.process_time_ns()-stamp)/1000/512)
        args.output.write_text(json.dumps({'case': args.case, 'backend': publisher_module.__file__,
            'platform': platform.platform(), 'cpu_us_per_attempt': samples,
            'cpu_median_us_per_attempt': statistics.median(samples), 'attempts_per_sample': 512,
            'emitted_per_sample': len(observed), 'observed': observed,
            'observed_hash': hashlib.sha256(json.dumps(observed).encode()).hexdigest(),
            'publisher': pub.snapshot(),
            'scope': 'default DataManager registration, not started; bridge inactive; one simple BarState; 2 warm+7 timed windows; no reducer/source/network/native/RSS qualification'}, indent=2)+'\n')
    finally:
        await dm.event_bus.close()
        await dm.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
