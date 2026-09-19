"""Paired service benchmark: full analysis versus explicitly reduced research output."""

import argparse
import json
from pathlib import Path
import tempfile
import time

from app.backtest.service import BacktestService
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from scripts.benchmark_trade_strategy import events, payload, settings


def run(count, pairs):
    tape = events(count)
    samples = []
    with tempfile.TemporaryDirectory(prefix="trade-research-") as directory:
        service = BacktestService.start(settings(Path(directory)), now_ms=1)
        try:
            for pair in range(pairs):
                results = []
                for research in (False, True) if pair % 2 == 0 else (True, False):
                    request = payload()
                    request["end_time_ms"] = tape[-1].event_time_ms + 1
                    if research:
                        request.update(cost_sensitivity_mode="SKIP", checkpoint_policy="FINAL_ONLY")
                    record = service.create_run(request, idempotency_key=f"{pair}-{research}", now_ms=2)
                    start = time.perf_counter()
                    completed = service.execute_dual_clock_run(record["run_id"], events=tape,
                        provider=IsolatedStrategyProvider("builtin-sma-cross-v1", step_timeout_s=5), now_ms=3)
                    elapsed = time.perf_counter() - start
                    result = dict(completed["result"])
                    result.pop("cost_sensitivity")
                    result.pop("report_hash")
                    results.append(result)
                    sample = {"pair": pair, "research": research, "seconds": elapsed,
                              "events": count, "fills": len(result["fills"])}
                    samples.append(sample)
                    print(json.dumps(sample), flush=True)
                assert results[0] == results[1], "primary result mismatch"
        finally:
            service.shutdown()
    return {"samples": samples, "primary_results_equal": True,
            "scope": "synthetic dual-clock service; SKIP + FINAL_ONLY versus defaults; reports intentionally differ"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=100000)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.events, args.pairs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
