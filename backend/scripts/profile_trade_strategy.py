"""Diagnostic spawned-worker profile, deliberately separate from latency samples."""

import argparse
import os
from pathlib import Path
import tempfile

from app.backtest import colocated
from app.backtest.service import BacktestService
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from scripts.benchmark_trade_strategy import events, payload, settings
from scripts.strategy_worker_profile import profile_worker


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=100000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["STRATEGY_AUDIT_PROFILE"] = str(args.output.resolve())
    colocated._worker = profile_worker
    with tempfile.TemporaryDirectory(prefix="trade-profile-") as tmp:
        service = BacktestService.start(settings(Path(tmp)), now_ms=1)
        try:
            run = service.create_run(payload(), idempotency_key="profile", now_ms=2)
            completed = service.execute_dual_clock_run(
                run["run_id"],
                events=events(args.events),
                provider=IsolatedStrategyProvider(
                    "builtin-sma-cross-v1", step_timeout_s=10
                ),
                now_ms=3,
            )
            print(completed["execution_lane"])
        finally:
            service.shutdown()
