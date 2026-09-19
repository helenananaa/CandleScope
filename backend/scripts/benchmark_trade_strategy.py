"""Paired, real-service dual-clock benchmark; synthetic aggregate prints, no network."""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from app.backtest.service import BacktestService
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from app.core.config import load_backtest_settings
from app.market_dataset.snapshot import MarketEvent

FLAGS = (
    "BACKTEST_TRADE_ACTIVE_INDEX_ENABLED",
    "BACKTEST_COLOCATED_DUAL_CLOCK_ENABLED",
    "BACKTEST_TRADE_INCREMENTAL_CHECKPOINT_ENABLED",
)


def events(count, prints_per_bar=10):
    return tuple(
        MarketEvent(
            i + 1,
            (i // prints_per_bar) * 60000
            + (i % prints_per_bar) * (60000 // prints_per_bar),
            "TRADES",
            {
                "source_event_kind": "AGG_TRADE",
                "source_sequence": i + 1,
                "tie_break": f"AGG_TRADE:{i + 1}",
                "price": str(100 + (i // prints_per_bar) % 9),
                "qty": "10",
            },
        )
        for i in range(count)
    )


def payload():
    return {
        "strategy_revision_id": "builtin-sma-cross-v1",
        "dataset_id": "synthetic-agg",
        "data_epoch": "sha256:" + "ab" * 32,
        "snapshot_hash": "sha256:" + "cd" * 32,
        "fidelity_mode": "AGG_TRADE_EXECUTION",
        "source_event_kind": "AGG_TRADE",
        "signal_clock": "DERIVED_BAR_CLOSE",
        "signal_interval": "1m",
        "execution_clock": "NEXT_AGG_TRADE",
        "bar_builder": "TRADE_DERIVED_COMPLETE_BUCKETS_V1",
        "timezone": "UTC",
        "start_time_ms": 0,
        "end_time_ms": 600000,
        "parameters": {"fast": 3, "slow": 5},
        "execution_model_revision": "EXECUTION_REALISM_V2",
        "warmup_bars": 5,
    }


def settings(path, interval=1000):
    return load_backtest_settings(
        {
            "BACKTEST_ENABLED": "1",
            "BACKTEST_BAR_ENABLED": "1",
            "BACKTEST_TRADE_TAPE_ENABLED": "1",
            "BACKTEST_CHECKPOINT_EVENT_INTERVAL": str(interval),
        },
        data_dir=path,
        klines_db_path=path / "candles.db",
        replay_db_path=path / "replay.db",
    )


def run(count, pairs, prints_per_bar, flags=FLAGS):
    tape = events(count, prints_per_bar)
    samples = []
    with tempfile.TemporaryDirectory(prefix="trade-strategy-") as directory:
        root = Path(directory)
        config = settings(root)
        seed = BacktestService.start(config, now_ms=1)
        request = payload()
        request["end_time_ms"] = tape[-1].event_time_ms + 1
        created = seed.create_run(request, idempotency_key="paired", now_ms=2)
        seed.shutdown()
        for pair in range(pairs):
            outputs = []
            for enabled in (0, 1) if pair % 2 == 0 else (1, 0):
                for flag in flags:
                    os.environ[flag] = str(enabled)
                db = root / f"pair-{pair}-{enabled}.db"
                shutil.copy2(config.db_path, db)
                service = BacktestService.start(replace(config, db_path=db), now_ms=1)
                provider = IsolatedStrategyProvider(
                    "builtin-sma-cross-v1", step_timeout_s=5
                )
                try:
                    start = time.perf_counter()
                    completed = service.execute_dual_clock_run(
                        created["run_id"], events=tape, provider=provider, now_ms=3
                    )
                    elapsed = time.perf_counter() - start
                    outputs.append(completed)
                    sample = {
                        "pair": pair,
                        "enabled": enabled,
                        "seconds": elapsed,
                        "events": count,
                        "prints_per_bar": prints_per_bar,
                        "fills": len(completed["result"]["fills"]),
                        "fill_hash": completed["result"]["fill_hash"],
                        "lane": completed.get("execution_lane", "REFERENCE"),
                    }
                    samples.append(sample)
                    print(json.dumps(sample), flush=True)
                finally:
                    service.shutdown()
            assert outputs[0]["result"] == outputs[1]["result"], "result mismatch"
            assert outputs[0]["report"] == outputs[1]["report"], "report mismatch"
    return {
        "samples": samples,
        "full_result_and_report_equal": True,
        "scope": "synthetic aggregate prints; service incl worker/checkpoints/report; excludes import, HTTP, browser",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=10000)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--prints-per-bar", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--round2",
        action="store_true",
        help="Keep round 1 enabled; compare shared sensitivity and sampled curve construction",
    )
    parser.add_argument(
        "--round3",
        action="store_true",
        help="Compare incremental SMA hash and extended history, keeping rounds 1/2 on",
    )
    parser.add_argument("--round5", action="store_true",
                        help="Compare idle sensitivity pruning, keeping earlier optimizations enabled")
    parser.add_argument("--round6", action="store_true",
                        help="Compare direct dual result construction with earlier optimizations enabled")
    parser.add_argument("--round7", action="store_true",
                        help="Compare checkpoint history encoding reuse")
    parser.add_argument("--round8", action="store_true",
                        help="Compare flat trade records; round7 candidate stays disabled")
    parser.add_argument("--round9", action="store_true",
                        help="Compare reusing completed chart bars; round7 stays disabled")
    args = parser.parse_args()
    round2_flags = (
        "BACKTEST_FUSED_DUAL_SENSITIVITY_ENABLED",
        "BACKTEST_LAZY_DUAL_CURVE_ENABLED",
    )
    round3_flags = (
        "BACKTEST_INCREMENTAL_SMA_HASH_ENABLED",
        "BACKTEST_EXTENDED_TRADE_HISTORY_ENABLED",
    )
    round5_flags = ("BACKTEST_PRUNED_DUAL_SENSITIVITY_ENABLED",)
    round6_flags = ("BACKTEST_DIRECT_DUAL_RESULT_ENABLED",)
    round7_flags = ("BACKTEST_REUSE_HISTORY_JSON_ENABLED",)
    round8_flags = ("BACKTEST_FLAT_TRADE_RECORDS_ENABLED",)
    round9_flags = ("BACKTEST_REUSE_DUAL_CHART_BARS_ENABLED",)
    groups = [FLAGS, round2_flags, round3_flags, round5_flags, round6_flags, round7_flags, round8_flags, round9_flags]
    selected = 7 if args.round9 else 6 if args.round8 else 5 if args.round7 else 4 if args.round6 else 3 if args.round5 else 2 if args.round3 else 1 if args.round2 else 0
    flags = groups[selected]
    for index, group in enumerate(groups):
        if index != selected:
            for flag in group:
                os.environ[flag] = "1" if index < selected and not ((args.round8 or args.round9) and group == round7_flags) else "0"
    result = run(args.events, args.pairs, args.prints_per_bar, flags)
    result["varied_flags"] = list(flags)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
