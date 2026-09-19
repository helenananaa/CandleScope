"""Paired supervised execution, with prepared synthetic data outside timing."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace

from app.backtest.service import BacktestService
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from scripts.benchmark_strategy_research import request_for
from scripts.benchmark_trade_strategy import events, settings


def run(count, pairs):
    tape = events(count, 100)
    samples = []
    with tempfile.TemporaryDirectory(prefix="resting-filter-") as tmp:
        root = Path(tmp)
        config = settings(root)
        seed = BacktestService.start(config, now_ms=1)
        requests = [request_for(index, 0, tape[-1].event_time_ms + 1,
                               SimpleNamespace(data_epoch="sha256:" + "ab" * 32)) for index in (0, 1)]
        records = [seed.create_run(request, idempotency_key=str(index), now_ms=2)
                   for index, request in enumerate(requests)]
        seed.shutdown()
        for pair in range(pairs):
            for index, (record, request) in enumerate(zip(records, requests, strict=True)):
                outputs = []
                for enabled in (0, 1) if pair % 2 == 0 else (1, 0):
                    os.environ["BACKTEST_TRADE_RESTING_FILTER_ENABLED"] = str(enabled)
                    db = root / f"{pair}-{index}-{enabled}.db"
                    shutil.copy2(config.db_path, db)
                    service = BacktestService.start(replace(config, db_path=db), now_ms=1)
                    try:
                        started = time.perf_counter()
                        result = service.execute_dual_clock_run(record["run_id"], events=tape,
                            provider=IsolatedStrategyProvider(request["strategy_revision_id"], step_timeout_s=10), now_ms=3)
                        elapsed = time.perf_counter() - started
                        outputs.append((result["result"], result["report"], service.repository.get_chart_cache(record["run_id"])))
                        sample = dict(pair=pair, workload="held_resting" if index == 0 else "sma",
                                      enabled=enabled, seconds=elapsed)
                        samples.append(sample)
                        print(json.dumps(sample), flush=True)
                    finally:
                        service.shutdown()
                assert outputs[0] == outputs[1], "result/report/chart mismatch"
    return dict(samples=samples, events=count, full_result_report_chart_equal=True,
                scope="synthetic prepared tape; supervised service execution; archive preparation excluded")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=100000)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.events, args.pairs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
