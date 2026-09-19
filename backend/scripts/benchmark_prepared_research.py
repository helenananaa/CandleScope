"""Paired cold+warm research batch, with identical run identities and real Parquet."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from app.backtest.runtime import BacktestWorker
from app.backtest.service import BacktestService
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from app.local_data.service import LocalDatasetService
from app.data_engine.storage.raw_trade_archive import ParquetRawAggTradeArchive
from scripts.benchmark_strategy_research import archive_fixture, request_for
from scripts.benchmark_trade_strategy import settings


def run(count, trials, pairs, flag="BACKTEST_TRADE_SNAPSHOT_CACHE_ENABLED"):
    samples = []
    with tempfile.TemporaryDirectory(prefix="paired-research-") as tmp:
        root = Path(tmp)
        start, end = archive_fixture(root / "archive", count)
        archive = ParquetRawAggTradeArchive(root / "archive", read_only=True, max_scan_rows=count)
        bounds = dict(exchange="binance", market_type="usdm", symbol="BTCUSDT", start_time_ms=start, end_time_ms=end)
        dataset = archive.freeze_dataset(**bounds)
        config = settings(root)
        seed = BacktestService.start(config, now_ms=1)
        requests = [request_for(index, start, end, dataset) for index in range(trials + 1)]
        runs = [seed.create_run(request, idempotency_key=f"trial-{index}", now_ms=2)
                for index, request in enumerate(requests)]
        seed.shutdown()
        for pair in range(pairs):
            comparisons = []
            for enabled in (0, 1) if pair % 2 == 0 else (1, 0):
                os.environ["BACKTEST_TRADE_SNAPSHOT_CACHE_ENABLED"] = "1"
                os.environ[flag] = str(enabled)
                db = root / f"{pair}-{enabled}.db"
                shutil.copy2(config.db_path, db)
                lane_config = replace(config, db_path=db)
                worker = BacktestWorker(settings=lane_config, local_data=LocalDatasetService(root / "local"),
                                        trade_archive_dir=root / "archive")
                service = BacktestService.start(lane_config, now_ms=1)
                outcomes, jobs = [], []
                batch_start = time.perf_counter()
                try:
                    for index, (record, request) in enumerate(zip(runs, requests, strict=True)):
                        started = time.perf_counter()
                        frozen = worker.trade_archive.freeze_dataset(**bounds)
                        assert frozen == dataset
                        freeze_seconds = time.perf_counter() - started
                        started = time.perf_counter()
                        events = worker._load_trade_events(frozen)
                        prepare_seconds = time.perf_counter() - started
                        started = time.perf_counter()
                        completed = service.execute_dual_clock_run(record["run_id"], events=events,
                            provider=IsolatedStrategyProvider(request["strategy_revision_id"], step_timeout_s=10), now_ms=3)
                        execute_seconds = time.perf_counter() - started
                        outcomes.append((completed["result"], completed["report"], service.repository.get_chart_cache(record["run_id"])))
                        if index == 0:
                            assert float(completed["result"]["ledger"]["position_qty"]) == 1
                            assert completed["result"]["ledger"]["open_order_count"] == 2
                        jobs.append(dict(index=index, freeze_seconds=freeze_seconds, prepare_seconds=prepare_seconds,
                                         execute_seconds=execute_seconds, fills=len(completed["result"]["fills"])))
                    sample = dict(pair=pair, enabled=enabled, seconds=time.perf_counter()-batch_start,
                                  jobs=jobs, cache=worker._trade_snapshots.stats)
                    samples.append(sample)
                    print(json.dumps(sample), flush=True)
                    comparisons.append(outcomes)
                finally:
                    worker.shutdown()
                    service.shutdown()
            assert comparisons[0] == comparisons[1], "complete result/report/chart mismatch"
    return dict(samples=samples, full_result_report_chart_equal=True, events=count, parameter_trials=trials, flag=flag,
                scope="synthetic real-Parquet fixture; batch includes cold held+resting task then parameter trials; freeze/checks retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=100000)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--flag", choices=("BACKTEST_TRADE_SNAPSHOT_CACHE_ENABLED", "BACKTEST_TRADE_RESTING_FILTER_ENABLED"),
                        default="BACKTEST_TRADE_SNAPSHOT_CACHE_ENABLED")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = run(args.events, args.trials, args.pairs, args.flag)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
