"""Isolated D126 primitive/query benchmark, compatible with the pre-D126 backend.

Select backend code with PYTHONPATH and pass baseline/candidate. Set an isolated
CANDLE_DATA_DIR. Each process creates and removes its own temporary SQLite DB.
This measures controlled backend work, not desktop/network acceptance or RSS
attributable solely to a cache. Compare runs on the same otherwise idle host.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import platform
import resource
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from app.data_engine.bar_aggregator.config import BarAggregatorConfig
from app.data_engine.bar_aggregator.models import BarEvent, BarEventType, BarState
from app.data_engine.bar_aggregator.publisher import BarAggregatorPublisher
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, SeriesKey
from app.data_engine.data_manager.query import QueryEngine
from app.data_engine.storage import klines_repo

START = 1_700_000_040
KEY = SeriesKey("BTCUSDT", "1m")
SOURCE = "backfill_rest_verified"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def percentiles(samples):
    samples.sort()
    count = len(samples)
    return {"p50_us": statistics.median(samples), "p95_us": samples[int(.95 * count)],
            "p99_us": samples[int(.99 * count)], "samples": count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=("baseline", "candidate"))
    args = parser.parse_args()
    if "CANDLE_DATA_DIR" not in os.environ:
        parser.error("Set CANDLE_DATA_DIR to an isolated scratch directory")
    data_dir = Path(os.environ["CANDLE_DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    out = {"variant": args.variant, "python": sys.version.split()[0],
           "platform": platform.platform(), "backend": str(Path(klines_repo.__file__).resolve()),
           "scenarios": {}}

    def measure(name, fn, count=200):
        for _ in range(5):
            fn()
        samples = []
        for _ in range(count):
            begin = time.perf_counter_ns()
            fn()
            samples.append((time.perf_counter_ns() - begin) / 1000)
        out["scenarios"][name] = percentiles(samples)

    tracemalloc.start()
    bars = [BarData(START + index * 60, 100., 200., 50., 150. + index / 10000,
                    10., source=SOURCE) for index in range(5000)]
    cache = BarCache()
    cache.bulk_load(KEY, bars)
    events = [copy.deepcopy(DataEvent(DataEventType.BAR_CLOSED, KEY, bar)) for bar in bars[-500:]]
    out["retained_python_bytes"], out["peak_python_bytes"] = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    out["shared_event_records"] = sum(event.bar is bar for event, bar in zip(events, bars[-500:]))
    out["input_hash"] = digest([(bar.time, bar.close, bar.volume) for bar in bars])
    measure("construct_record", lambda: BarData(START, 1., 2., 0., 1., 10., source=SOURCE), 1000)
    measure("tail_upsert", lambda: cache.upsert(KEY, bars[-1]), 2000)
    measure("event_snapshot", lambda: copy.deepcopy(DataEvent(DataEventType.BAR_CLOSED, KEY, bars[-1])), 1000)
    with tempfile.TemporaryDirectory(dir=data_dir) as temp:
        klines_repo.KLINES_DB_PATH = Path(temp) / "bench.sqlite"
        klines_repo.init_klines_storage()
        rows = [dict(open_time=bar.time * 1000, close_time=bar.time * 1000 + 59999,
                     open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume,
                     quote_volume=None, trades=None, taker_buy_base=None, taker_buy_quote=None)
                for bar in bars]
        klines_repo.upsert_klines(KEY.symbol, KEY.interval, rows, source=SOURCE)
        engine = QueryEngine(cache, klines_repo.KlinesRepoAdapter(), QueryConfig(auto_backfill=False))

        def query(count):
            result = engine.query(KEY.symbol, KEY.interval, start_ms=START * 1000,
                                  end_ms=(START + (count - 1) * 60) * 1000,
                                  limit=count, auto_backfill=False)
            assert len(result.bars) == count, (count, result.metadata)
            return result

        out["query_hashes"] = {}
        for count in (1, 1500, 5000):
            result = query(count)
            out["query_hashes"][count] = digest([
                [getattr(bar, name) for name in ("time", "open", "high", "low", "close", "volume",
                    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "is_closed", "source")]
                for bar in result.bars])
            measure(f"warm_{count}", lambda: query(count))

        def cold():
            cache.clear()
            query(1500)

        measure("cold_sqlite_1500", cold, 40)
        counter = 0

        def write(count):
            nonlocal counter
            counter += 1
            changed = [{**row, "close": float(counter)} for row in rows[:count]]
            assert klines_repo.upsert_klines(KEY.symbol, KEY.interval, changed, source=SOURCE) == count

        measure("write_1", lambda: write(1), 50)
        measure("write_1000", lambda: write(1000), 20)
        fields = ("open_time", "close_time", "open", "high", "low", "close", "volume",
                  "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "source")
        canonical = klines_repo.query_klines(KEY.symbol, KEY.interval, limit=5000)
        assert len(canonical) == 5000
        out["canonical_hash"] = digest([[row[name] for name in fields] for row in canonical])

    async def publish():
        publisher = BarAggregatorPublisher(BarAggregatorConfig(update_throttle_ms=0))

        async def consume(event):
            assert event.bar.close == 1.

        publisher.on_bar_event(consume)
        for components in (0, 1000):
            state = BarState("BTCUSDT", "1000m", 0, 60000000, 1., 2., 0., 1., 10.)
            state.source_snapshots = {
                str(index): {"time": index, "open": 1., "high": 2., "low": 0., "close": 1.,
                             "volume": 10., "is_closed": True, "source": "realtime"}
                for index in range(components)}
            if args.variant == "candidate":
                from app.data_engine.readonly import ReadonlyFields
                state.source_snapshots = {key: ReadonlyFields(value) for key, value in state.source_snapshots.items()}
            samples = []
            for _ in range(100):
                begin = time.perf_counter_ns()
                await publisher.emit(BarEvent(BarEventType.UPDATED, state))
                samples.append((time.perf_counter_ns() - begin) / 1000)
            out["scenarios"][f"publisher_{components}"] = percentiles(samples)

    asyncio.run(publish())
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    out["process_peak_rss_bytes"] = peak_rss if sys.platform == "darwin" else peak_rss * 1024
    out["rss_scope"] = "whole interpreter maximum; includes imports, SQLite and all sequential scenarios"
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
