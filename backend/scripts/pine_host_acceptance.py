"""Isolated real Pine/Host API for production Workbench component acceptance.

Only market data is synthetic. Uses the configured production plugin resolver,
interpreter, preparation service, account and replay implementation.
"""
# ruff: noqa: E402 -- standalone command binds the repository before app imports.
import argparse
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from fastapi import FastAPI
import uvicorn
from app.api.v1.backtests import router as backtests
from app.api.v1.data_preparation import router as preparations
from app.backtest.runtime import BacktestRuntime
from app.core.config import load_backtest_settings
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.local_data.service import LocalImportOptions

parser = argparse.ArgumentParser()
parser.add_argument("--state", type=Path, required=True)
parser.add_argument("--port", type=int, default=0)
parser.add_argument("--runtime-registry", type=Path, required=True)
parser.add_argument("--resume", action="store_true", help="explicitly reuse this fixture's durable state")
args = parser.parse_args()
registry = args.runtime_registry.resolve(strict=True)
os.environ["CANDLESCOPE_NATIVE_RUNTIME_REGISTRY"] = str(registry)
state = args.state.resolve()
state.mkdir(parents=True, exist_ok=args.resume)
if args.resume and args.port == 0 and (state / "backend.json").exists():
    args.port = json.loads((state / "backend.json").read_text())["port"]
settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1",
    "BACKTEST_CHART_CONTEXT_ENABLED": "1"},
    data_dir=state, klines_db_path=state / "bars.db", replay_db_path=state / "replay.db")
host = BacktestRuntime.start(settings, local_data_dir=state / "local")
bootstrap_file = state / "bootstrap.json"
if bootstrap_file.exists():
    value = json.loads(bootstrap_file.read_text())
else:
    csv = state / "bars.csv"
    csv.write_text("time,open,high,low,close,volume\n" + "\n".join(
        f"{i*60000},10,11,9,10,100" for i in range(10)))
    manifest = host.local_data.import_csv(csv, LocalImportOptions(name="Pine acceptance", symbol="BTCUSDT",
        interval="1m", timestamp_unit="ms"))
    snapshot = host.preview_snapshot(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"],
        start_time_ms=0, end_time_ms=599999, interval="1m")
    value = {"dataset_id": manifest["dataset_id"], "data_epoch": manifest["data_epoch"],
        "snapshot_hash": snapshot["snapshot_hash"], "account_data": {"symbol": "BTCUSDT", "events": [
            {"time_ms": -2, "role": "INSTRUMENT_RULES", "payload": {
                "rule_version": "r1", "contract_multiplier": "1", "price_tick": "0.1",
                "quantity_step": "0.001", "min_notional": "5", "maintenance_tiers": [
                    {"notional_floor": "0", "notional_cap": "1000", "maintenance_rate": "0.005", "maintenance_deduction": "0"},
                    {"notional_floor": "1000", "notional_cap": "1000000", "maintenance_rate": "0.01", "maintenance_deduction": "5"}]}},
            {"time_ms": -1, "role": "MARK_INDEX", "payload": {"mark_price": "10", "index_price": "10"}}],
            "provenance": {"fixture": "controlled UI, synthetic OHLC and account rules"}},
        "source": '''//@version=6
strategy("Pine Host acceptance",calc_on_order_fills=true)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=7)
if strategy.position_size>0
    strategy.exit("X","L",stop=9.5,limit=10.5)
plot(strategy.position_size)
'''}
    bootstrap_file.write_text(json.dumps(value, indent=2))
(state / "account.json").write_text(json.dumps(value["account_data"], indent=2))


def query(symbol, interval, *args, **kwargs):
    assert symbol == "BTCUSDT" and interval in {"1m", "1d"}
    step = 60000 if interval == "1m" else 86400000
    start, end = kwargs["start_ms"], kwargs["end_ms"]
    if (end-start)//step > 10000:
        raise ValueError("acceptance fixture supports bounded synthetic windows only")
    return [{"open_time": t, "close_time": t+step-1, "open": 10, "high": 11, "low": 9,
             "close": 10, "volume": 100, "source": "backfill_rest_verified"}
            for t in range(max(0, start), end+1, step)]


class Coordinator:
    async def request_and_wait(self, repair):
        raise AssertionError("controlled complete data must not download market history")


adapter = BarPreparationAdapter(state / "chunks", coordinator=Coordinator(), local_data=host.local_data,
    backtest_runtime=host, query=query)
preparation = PreparationService(PreparationRepository(state / "preparation.db"), adapter)


@asynccontextmanager
async def lifespan(app):
    await preparation.start()
    try:
        yield
    finally:
        await preparation.shutdown()
        host.shutdown()


app = FastAPI(lifespan=lifespan)
app.state.backtest_runtime, app.state.backtest_service = host, host.service
app.state.data_preparation_service = preparation
app.include_router(backtests, prefix="/api/v1")
app.include_router(preparations, prefix="/api/v1")


@app.get("/api/harness/bootstrap")
def bootstrap():
    return value


@app.post("/api/harness/stop")
def stop():
    server.should_exit = True
    return {"stopping": True}


with socket.socket() as listener:
    listener.bind(("127.0.0.1", args.port))
    port = listener.getsockname()[1]
(state / "backend.json").write_text(json.dumps({"port": port}))
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port))
server.run()
