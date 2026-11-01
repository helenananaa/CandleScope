"""Real SQLite warmup/live/correction pair; no network or native-UI claim."""
import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import tempfile
import time

from app.core import config
from app.api.v1.stream_utils import normalize_exchange
from app.data_engine.bar_aggregator.models import BarInput, BarInputSource, MergeMode
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.interval_resolution import IntervalPurpose
from app.data_engine.storage import klines_repo

ROOT = Path(__file__).resolve().parents[3]


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, int((len(values) - 1) * fraction))]


def row(index, *, volume=None):
    price = 100 + index / 100
    volume = (10 + index % 7) if volume is None else volume
    return dict(open_time=index * 60000, close_time=(index + 1) * 60000 - 1,
                open=price, high=price + .5, low=price - .5, close=price + .1,
                volume=volume, quote_volume=volume * price, trades=2,
                taker_buy_base=volume / 2, taker_buy_quote=volume * price / 2)


def incoming(value, *, closed=False, sequence=None):
    return BarInput(symbol='BTCUSDT', source_interval='1m', exchange='binance', market_type='spot',
                    open_time_ms=value['open_time'], close_time_ms=value['close_time'],
                    **{name: value[name] for name in ('open', 'high', 'low', 'close', 'volume',
                       'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote')},
                    enhanced_fields=frozenset(('quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote')),
                    source=BarInputSource.CORRECTION if closed else BarInputSource.REALTIME,
                    is_closed=closed, sequence=sequence, merge_mode=MergeMode.COMPONENT)


async def case(root, count, events):
    klines_repo.KLINES_DB_PATH = root / f'bars-{count}.sqlite'
    config.KLINES_DB_PATH = klines_repo.KLINES_DB_PATH
    klines_repo.init_klines_storage()
    source = [row(index) for index in range(count)]
    klines_repo.upsert_klines('BTCUSDT', '1m', source, source='backfill')
    cfg = DataManagerConfig()
    cfg.query.auto_backfill = False
    manager = DataManager(cfg)
    manager.set_storage(klines_repo.KlinesRepoAdapter())
    agg = manager.bar_aggregator
    agg.config.update_throttle_ms = 0  # explicit every-publication workload
    # These targets do not divide by a coarser Binance native interval.
    interval = f'{count + 3}m'
    route = manager.interval_resolver.resolve(exchange='binance', market_type='spot',
        interval=interval, purpose=IntervalPurpose.REALTIME)
    assert route.base_interval == '1m', route
    agg.add_target('BTCUSDT', interval)
    real_clock = time.time
    time.time = lambda: count * 60 + 30
    manager._started = True  # real bridge/cache path; no background provider I/O
    published = []
    async def observe(event):
        published.append((event.event_type.value, event.bar.close, event.bar.volume))
    agg.publisher.on_bar_event(observe)
    lag = []
    running = True
    async def heartbeat():
        while running:
            target = time.perf_counter() + .005
            await asyncio.sleep(.005)
            lag.append(max(0, time.perf_counter() - target) * 1000)
    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(.01)
    cpu = time.process_time()
    started = time.perf_counter()
    try:
        await manager.warm_start.seed_if_needed('BTCUSDT', interval, exchange='binance',
                                               market_type='spot', had_stream=True)
        warm_ms = (time.perf_counter() - started) * 1000
        initial = agg.get_bucket_state('BTCUSDT', interval, 0)
        assert initial is not None
        initial_shape = dict(components=len(initial.source_snapshots), compact=initial._history_prefix is not None)
        timings = []
        for index in range(events):
            tail = row(count, volume=20 + index)
            started = time.perf_counter()
            await agg.ingest_bar_input('binance', 'spot', 'BTCUSDT', interval, incoming(tail, sequence=index))
            timings.append((time.perf_counter() - started) * 1000)
            await asyncio.sleep(.002)
        # Source revision is genuinely committed in SQLite, then delivered as
        # a canonical correction to the same active target.
        corrected = dict(source[count // 3], volume=2)
        corrected['quote_volume'] = 2 * corrected['open']
        corrected['taker_buy_base'] = 1
        corrected['taker_buy_quote'] = corrected['open']
        klines_repo.upsert_klines('BTCUSDT', '1m', [corrected], source='repair_binance_rest_verified')
        started = time.perf_counter()
        await agg.ingest_bar_input('binance', 'spot', 'BTCUSDT', interval, incoming(corrected, closed=True))
        correction_ms = (time.perf_counter() - started) * 1000
        source[count // 3] = corrected
        expected = dict(open=source[0]['open'], high=max(r['high'] for r in [*source, tail]),
                        low=min(r['low'] for r in [*source, tail]), close=tail['close'],
                        volume=math.fsum(r['volume'] for r in [*source, tail]))
        final = agg.get_bucket_state('BTCUSDT', interval, 0)
        values = {name: getattr(final, name) for name in expected}
        assert all(abs(values[name] - value) < 1e-8 for name, value in expected.items()), (values, expected)
        snapshot = manager.history_prefix_runtime.snapshot() if manager.history_prefix_runtime else None
        return dict(history_rows=count, target_interval=interval, source_interval=route.base_interval,
                    live_events=events, warm_ms=warm_ms,
                    update_ms=dict(p50=percentile(timings, .5), p95=percentile(timings, .95), max=max(timings)),
                    correction_ms=correction_ms, cpu_ms=(time.process_time() - cpu) * 1000,
                    loop_lag_ms=dict(p95=percentile(lag, .95), max=max(lag)),
                    initial_shape=initial_shape, memory=agg.memory_usage(), prefix_runtime=snapshot,
                    history_blocks=manager.query_engine.history_blocks.snapshot(),
                    observed_publications=len(published), oracle_equal=True,
                    final_values=values,
                    final_sha256=hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest())
    finally:
        running = False
        await beat
        manager._started = False
        await manager.shutdown()
        time.time = real_clock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--events', type=int, default=64)
    args = parser.parse_args()
    normalize_exchange('binance')  # keep cold provider-registry bootstrap out of timing
    with tempfile.TemporaryDirectory(prefix='h127-r129-bench-') as directory:
        async def run():
            return [await case(Path(directory), count, args.events) for count in (64, 1000, 4000)]
        cases = asyncio.run(run())
    report = dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  benchmark_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  prefix_enabled=config.HISTORY_PREFIX_ENABLED, cases=cases,
                  process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  limits='Isolated real SQLite and actual DataManager warm/bridge/cache path, controlled canonical rows, no network/native UI. Every-update publication throttle explicitly disabled in both modes;64 updates paced2ms. Source correction invalidates shared source blocks. Busy shared host, not an SLA. CPU includes preparation after the timer starts, not fixture creation. No background provider or revision poll tasks.')
    Path(args.out).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
