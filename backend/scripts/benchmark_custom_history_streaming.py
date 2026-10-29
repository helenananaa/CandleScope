"""Compare bounded batch and streamed history using freshly allocated source pages.

No provider or production database is used. Timings cover the query service,
source-row creation and reduction; the shared QueryEngine base cache and disk
I/O are outside this microbenchmark. Memory is sampled in a separate run so
tracemalloc overhead does not contaminate the reported wall-clock timings.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.data_manager.custom_query import CustomIntervalQueryService
from app.data_engine.data_manager.models import BarData, QueryResult, QuerySource
from app.data_engine.interval_policy import parse_interval_ms


def measure(interval, source, target_count, enabled, *, memory=False):
    source_ms = parse_interval_ms(source)
    target_ms = parse_interval_ms(interval)
    assert source_ms and target_ms
    factor = target_ms // source_ms
    total_rows = (target_count + 2) * factor
    start_ms = (1_600_000_000_000 // target_ms) * target_ms
    calls = 0
    def read(symbol, base_interval, before_ms, limit, **kwargs):
        nonlocal calls
        calls += 1
        end = min(total_rows, (before_ms - start_ms + source_ms - 1) // source_ms)
        begin = max(0, end - limit)
        bars = [BarData(
            time=(start_ms + index * source_ms) // 1000,
            open=100 + index % 31 / 7, high=110, low=90,
            close=100 + index % 13 / 7, volume=1 + index % 17 / 13,
            quote_volume=100 + index % 17 / 13, trades=index % 23,
            taker_buy_base=0.2, taker_buy_quote=20, source="backfill",
        ) for index in range(begin, end)]
        return QueryResult(bars=bars, total=len(bars), symbol=symbol, interval=base_interval,
                           source=QuerySource.STORAGE, has_more=begin > 0, complete=True,
                           metadata={"all_rows_final": True, "storage_reads": 1,
                                     "storage_rows": len(bars)})
    service = CustomIntervalQueryService(
        cache=BarCache(), config=QueryConfig(stream_custom_history=enabled, share_custom_aggregate_blocks=False),
        base_query=lambda *a, **kw: QueryResult(), base_query_before=read,
    )
    gc.collect()
    if memory:
        tracemalloc.start()
    start = time.perf_counter()
    cpu_start = time.process_time()
    result = service.query_before("SYNTHETIC127", interval,
        before_ms=start_ms + total_rows * source_ms, limit=target_count, auto_backfill=False)
    elapsed_ms = (time.perf_counter() - start) * 1000
    cpu_ms = (time.process_time() - cpu_start) * 1000
    peak_bytes = tracemalloc.get_traced_memory()[1] if memory else None
    if memory:
        tracemalloc.stop()
    fingerprint = hashlib.sha256(json.dumps([
        (bar.to_kline_dict(), bar.source) for bar in result.bars
    ], sort_keys=True).encode()).hexdigest()
    return {
        "wall_ms": elapsed_ms, "cpu_ms": cpu_ms, "peak_bytes": peak_bytes, "returned": len(result.bars),
        "fingerprint": fingerprint, "source_reads": calls,
        "source_rows": result.metadata["base_rows_fetched"],
        "streamed": result.metadata.get("base_streaming", False),
        "peak_buffered_source_rows": result.metadata.get("base_stream_peak_buffered_rows"),
        "first_reduced_ms": result.metadata.get("base_first_reduced_ms"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--purpose", action="append", choices=["regular", "multi-page", "stress-only"])
    parser.add_argument("--skip-memory", action="store_true")
    args = parser.parse_args()
    report = {
        "scope": "Synthetic source pages; query execution memory and CPU only; no disk/provider/native UI or shared base cache",
        "page_limit": 10000, "page_budget": 32, "timing_repeats": args.repeats,
        "cases": [],
    }
    cases = [(name, source, 1500, "regular") for name, source in
             [("45m", "15m"), ("90m", "30m"), ("2d", "1d"), ("4d", "1d"), ("5d", "1d")]]
    cases += [("45m", "15m", 5000, "multi-page"), ("90m", "30m", 5000, "multi-page"),
              ("2d", "1d", 6000, "multi-page"), ("4d", "1d", 3000, "multi-page"),
              ("5d", "1d", 3000, "multi-page"), ("10007m", "1m", 24, "stress-only")]
    for interval, source, count, purpose in cases:
        if args.purpose and purpose not in args.purpose:
            continue
        measurements = {False: [], True: []}
        # Alternate mode order to avoid always giving one mode the warm CPU.
        for repeat in range(args.repeats):
            for enabled in ([False, True] if repeat % 2 == 0 else [True, False]):
                measurements[enabled].append(measure(interval, source, count, enabled))
        memory = {
            enabled: (measurements[enabled][-1] if args.skip_memory
                      else measure(interval, source, count, enabled, memory=True))
            for enabled in [False, True]
        }
        samples = [sample for runs in measurements.values() for sample in runs] + list(memory.values())
        assert len({sample["fingerprint"] for sample in samples}) == 1, (interval, count)
        assert all(sample["returned"] == count for sample in samples)
        assert len({sample["source_reads"] for sample in samples}) == 1
        case = {"interval": interval, "source": source, "targets": count, "purpose": purpose,
                "exact_parity": True}
        for enabled, label in [(False, "batch"), (True, "stream")]:
            case[label] = {**memory[enabled],
                "wall_ms": statistics.median(sample["wall_ms"] for sample in measurements[enabled]),
                "cpu_ms": statistics.median(sample["cpu_ms"] for sample in measurements[enabled]),
                "wall_samples_ms": [sample["wall_ms"] for sample in measurements[enabled]],
                "cpu_samples_ms": [sample["cpu_ms"] for sample in measurements[enabled]],
                "first_reduced_ms": measurements[enabled][0]["first_reduced_ms"],
            }
        case["peak_memory_reduction_percent"] = (None if args.skip_memory else
            100 * (1 - case["stream"]["peak_bytes"] / case["batch"]["peak_bytes"]))
        report["cases"].append(case)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"interval": interval, "targets": count,
                          "batch_ms": round(case["batch"]["wall_ms"], 2),
                          "stream_ms": round(case["stream"]["wall_ms"], 2),
                          "batch_cpu_ms": round(case["batch"]["cpu_ms"], 2),
                          "stream_cpu_ms": round(case["stream"]["cpu_ms"], 2),
                          "memory_reduction_pct": case["peak_memory_reduction_percent"]}), flush=True)


if __name__ == "__main__":
    main()
