"""Compare direct, cold-block and reused-block reduction on identical inputs.

No IO, provider, base-cache or UI latency is measured. Inputs include the
prevalidated decoder representation used by the real storage path. Memory is
sampled separately from CPU timing. Output parity is checked on every run.
"""
from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.experimental_aggregate_blocks import AggregateBlockCache
from app.data_engine.data_manager.custom_query import _aggregate_fixed_bars_to_interval
from app.data_engine.data_manager.models import BarData, SeriesKey
from app.data_engine.interval_policy import parse_interval_ms


def source_rows(count: int, width: int, decoded: bool) -> list[BarData]:
    bars = [BarData(time=i * width, open=100 + i % 31 / 7, high=110, low=90,
                    close=100 + i % 13 / 7, volume=1 + i % 17 / 13,
                    quote_volume=100 + i % 17 / 13, trades=i % 23,
                    taker_buy_base=0.2, taker_buy_quote=20, source="backfill")
            for i in range(count)]
    if decoded:
        for index, bar in enumerate(bars):
            bars[index] = BarData.from_storage_components((bar.time_ms, bar.open, bar.high,
                bar.low, bar.close, bar.volume, bar.quote_volume, bar.trades,
                bar.taker_buy_base, bar.taker_buy_quote, bar.source),
                exchange="binance", market_type="futures")
    return bars


def measure(source, width, source_width, key, mode, *, memory=False, seed_factors=()):
    direct = lambda rows, on_bucket=None: _aggregate_fixed_bars_to_interval(
        rows, width, source_interval_seconds=source_width, on_bucket=on_bucket)
    expected = direct(source)
    cache = AggregateBlockCache()
    for factor in seed_factors:
        cache.aggregate(source, key, factor * source_width, source_width,
                        lambda rows, on_bucket=None: _aggregate_fixed_bars_to_interval(
                            rows, factor * source_width, source_interval_seconds=source_width, on_bucket=on_bucket))
    if mode == "warm":
        cache.aggregate(source, key, width, source_width, direct)
    gc.collect()
    if memory:
        tracemalloc.start()
    start = time.process_time()
    result = direct(source) if mode == "direct" else cache.aggregate(source, key, width, source_width, direct)
    cpu_ms = (time.process_time() - start) * 1000
    peak_bytes = tracemalloc.get_traced_memory()[1] if memory else None
    if memory:
        tracemalloc.stop()
    assert result == expected
    return dict(cpu_ms=cpu_ms, peak_bytes=peak_bytes, cache=cache.snapshot())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    report = dict(scope=__doc__, repeats=args.repeats, cases=[])
    for interval, source_interval in [("45m", "15m"), ("90m", "30m"),
                                      ("2d", "1d"), ("4d", "1d"), ("5d", "1d")]:
        width = parse_interval_ms(interval) // 1000
        source_width = parse_interval_ms(source_interval) // 1000
        for decoded in [False, True]:
            for targets in [128, 1500]:
                source = source_rows(targets * width // source_width, source_width, decoded)
                key = SeriesKey("SYNTHETIC127", source_interval)
                modes = ["direct", "cold", "warm"]
                measurements = {mode: [] for mode in modes}
                for repeat in range(args.repeats):
                    for mode in modes if repeat % 2 == 0 else reversed(modes):
                        measurements[mode].append(measure(source, width, source_width, key, mode))
                case = dict(interval=interval, source=source_interval, decoded=decoded,
                            targets=targets, exact_parity=True)
                for mode in modes:
                    case[mode] = {
                        **measure(source, width, source_width, key, mode, memory=True),
                        "cpu_ms": statistics.median(run["cpu_ms"] for run in measurements[mode]),
                        "cpu_samples_ms": [run["cpu_ms"] for run in measurements[mode]],
                    }
                report["cases"].append(case)
    # Same 7,500-day window: 2d seeds aligned children; 4d and 5d share them.
    source = source_rows(7500, 86400, True)
    key = SeriesKey("SYNTHETIC127", "1d")
    report["cross_period"] = {}
    for factor, seed_factors in [(4, (2,)), (5, (2, 4))]:
        modes = {"direct": (), "cold": (), "shared": seed_factors}
        measurements = {mode: [measure(source, factor * 86400, 86400, key, mode, seed_factors=seeds)
                               for _ in range(args.repeats)] for mode, seeds in modes.items()}
        report["cross_period"][f"{factor}d"] = {mode: {
            "cpu_ms": statistics.median(run["cpu_ms"] for run in runs), "cache": runs[-1]["cache"],
        } for mode, runs in measurements.items()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Exact parity verified; saved {len(report['cases'])} cases to {args.out}")


if __name__ == "__main__":
    main()
