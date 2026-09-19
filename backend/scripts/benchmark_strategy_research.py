"""Structural workloads using synthetic trades, real Parquet and supervised service."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time

from app.backtest import colocated
from app.backtest.runtime import BacktestWorker
from app.local_data.service import LocalDatasetService
from app.backtest.service import BacktestService
from app.backtest.strategy.builtin import BUILTIN_ORDER_COMMAND_REVISION
from app.backtest.strategy.isolated import IsolatedStrategyProvider
from app.data_engine.storage.raw_trade_archive import ParquetRawAggTradeArchive, VerifiedRawAggTradeDay
from scripts.benchmark_trade_strategy import payload, settings
from scripts.strategy_worker_profile import timed_worker


def archive_fixture(root, count):
    start = 1735689600000  # synthetic 2025-01-01 UTC, all rows fit one day
    if not 1000 <= count <= 140000:
        raise ValueError("fixture supports 1000..140000 trades in one synthetic day")
    rows = [{"exchange": "binance", "market_type": "usdm", "symbol": "BTCUSDT",
             "agg_trade_id": i + 1000, "first_trade_id": i + 2000, "last_trade_id": i + 2000,
             "price": 100 + (i // 100) % 9, "quantity": 10,
             "trade_time_ms": start + i * 600, "event_time_ms": start + i * 600,
             "received_at_ms": start + i * 600 + 1, "is_buyer_maker": bool(i % 2),
             "source": "binance_public_archive"} for i in range(count)]
    writer = ParquetRawAggTradeArchive(root, max_rows_per_file=25000)
    writer.import_verified_day(rows, VerifiedRawAggTradeDay(
        exchange="binance", market_type="usdm", symbol="BTCUSDT", date="2025-01-01",
        source_url="https://data.binance.vision/synthetic-test-fixture.zip",
        source_file="synthetic-test-fixture.zip",
        source_checksum_sha256=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
        row_count=count, first_agg_trade_id=1000, last_agg_trade_id=999+count,
        first_trade_time_ms=start, last_trade_time_ms=start+(count-1)*600))
    return start, start + count * 600


def run(count, trials, output, profile=False, cache=False):
    import os
    os.environ["BACKTEST_TRADE_SNAPSHOT_CACHE_ENABLED"] = str(int(cache))
    samples = []
    with tempfile.TemporaryDirectory(prefix="strategy-research-") as tmp:
        root = Path(tmp)
        started = time.perf_counter()
        start, end = archive_fixture(root / "archive", count)
        import_seconds = time.perf_counter() - started
        archive = ParquetRawAggTradeArchive(root / "archive", read_only=True, max_scan_rows=count)
        config = settings(root)
        worker = BacktestWorker(settings=config, local_data=LocalDatasetService(root / "local"), trade_archive_dir=root / "archive")
        service = BacktestService.start(config, now_ms=1)
        if profile:
            colocated._worker = timed_worker
        try:
            for index in range(trials + 1):
                lane = "held_resting" if index == 0 else f"parameter_{index}"
                total_start = time.perf_counter()
                started = time.perf_counter()
                dataset = archive.freeze_dataset(exchange="binance", market_type="usdm", symbol="BTCUSDT",
                    start_time_ms=start, end_time_ms=end)
                freeze_seconds = time.perf_counter() - started
                started = time.perf_counter()
                tape = worker._load_trade_events(dataset)
                read_seconds = time.perf_counter() - started
                request = request_for(index, start, end, dataset)
                created = service.create_run(request, idempotency_key=lane, now_ms=2)
                if profile:
                    os.environ["STRATEGY_AUDIT_PROFILE"] = str(output.with_name(output.stem + "-" + lane + "-stages.json").resolve())
                started = time.perf_counter()
                completed = service.execute_dual_clock_run(created["run_id"], events=tape,
                    provider=IsolatedStrategyProvider(request["strategy_revision_id"], step_timeout_s=10), now_ms=3)
                elapsed = time.perf_counter() - started
                result = completed["result"]
                if index == 0:
                    assert result["ledger"]["position_qty"] == "1.0" or float(result["ledger"]["position_qty"]) == 1
                    assert result["ledger"]["open_order_count"] == 2
                    assert len(result["fills"]) == 1
                sample = dict(workload=lane, events=count, parameters=request["parameters"],
                    freeze_seconds=freeze_seconds, read_project_seconds=read_seconds,
                    execute_seconds=elapsed, total_seconds=time.perf_counter()-total_start,
                    fills=len(result["fills"]), open_orders=result["ledger"]["open_order_count"],
                    ending_position=result["ledger"]["position_qty"],
                    result_hash=hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest())
                samples.append(sample)
                print(json.dumps(sample), flush=True)
        finally:
            cache_stats = worker._trade_snapshots.stats
            worker.shutdown()
            service.shutdown()
    return dict(samples=samples, cache=cache, cache_stats=cache_stats, import_seconds=import_seconds, stage_timers=profile,
        scope="synthetic market data with real Parquet fixture; full supervised service; import excluded from each run")


def request_for(index, start, end, dataset):
    request = payload()
    request.update(start_time_ms=start, end_time_ms=end, data_epoch=dataset.data_epoch)
    if index == 0:
        request.update(strategy_revision_id=BUILTIN_ORDER_COMMAND_REVISION, parameters={},
            warmup_bars=0, output_mode="ORDER_INTENT", order_end_policy="KEEP_OPEN",
            strategy_source=json.dumps({"commands": [
                {"sequence": 1, "side": "BUY", "type": "MARKET", "qty": "1"},
                {"sequence": 2, "side": "BUY", "type": "LIMIT", "qty": "1", "limit_price": "50"},
                {"sequence": 2, "side": "SELL", "type": "LIMIT", "qty": "1", "limit_price": "200"}]}))
    else:
        request["parameters"] = {"fast": index + 1, "slow": index + 5}
    return request


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=100000)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--cache", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = run(args.events, args.trials, args.output, args.profile, args.cache)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
