from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.backtests import router as backtests_router
from app.api.v1.local_data import router as local_router
from app.local_data.service import LocalDatasetError, LocalDatasetService
from app.local_data.user_market_trades import UserMarketTradeOptions
from tests.asgi_peer import PeerASGIApp
from tests.test_backtest_chart_context import _runtime
from tests.test_local_data_api import _TRUSTED_HEADERS
from tests.test_python_editor import compile_editor


START = 1704067200000
END = START + 10 * 60_000
HEADER = "time,sequence,price,quantity,is_buyer_maker\n"
IMPORT_ROUTE = "/api/v1/local/imports/market-trades/csv"
RUNS = "/api/v1/backtests/runs"


def fixture(last_price=1000):
    rows = []
    for minute in range(10):
        stamp = START + minute * 60_000
        rows.extend([(stamp + 1000, 200 + minute * 2, 100 + minute, 20, "true"),
                     (stamp + 1000, 201 + minute * 2, 101 + minute if minute < 9 else last_price, 20, "false")])
    return HEADER + "".join(",".join(map(str, row)) + "\n" for row in rows)


def app_client(runtime):
    app = FastAPI()
    app.include_router(local_router, prefix="/api/v1")
    app.include_router(backtests_router, prefix="/api/v1")
    app.state.local_data_service = runtime.local_data
    app.state.backtest_runtime = runtime
    app.state.backtest_service = runtime.service
    return TestClient(PeerASGIApp(app, "127.0.0.1"), headers=_TRUSTED_HEADERS)


@pytest.mark.parametrize(("source", "unit", "code"), [
    (fixture(), "s", "trade_time_outside_coverage"),
    (fixture().replace(",201,", ",200,", 1), "ms", "trade_order_invalid"),
    (fixture().replace(",201,", ",203,", 1), "ms", "trade_sequence_gap"),
    (fixture().replace(f"{START + 61_000},202,", f"{START + 500},202,", 1), "ms", "trade_order_invalid"),
    (fixture().replace(f"{START + 61_000},", f"{START + 121_000},"), "ms", "trade_coverage_gap"),
    ("time,order_id,price,quantity,is_buyer_maker\n" + fixture().split("\n", 1)[1], "ms", "trade_columns_invalid"),
])
def test_rejects_invalid_source_without_publishing(tmp_path, source, unit, code):
    service = LocalDatasetService(tmp_path / "library")
    path = tmp_path / "market.csv"
    path.write_text(source)
    with pytest.raises(LocalDatasetError) as error:
        service.import_user_market_trades(path, UserMarketTradeOptions(
            "Market file", "ETHUSDT", "ETH", "USDT", unit, START, END, "MARKET_AGG_TRADE",
        ))
    assert error.value.code == code
    assert service.list_datasets() == []
    assert list((service.root / ".staging").iterdir()) == []


def test_user_trade_http_run_uses_pinned_original_after_reimport_and_restart(tmp_path):
    params = {
        "name": "User market fixture", "symbol": "ETHUSDT", "base_asset": "ETH", "quote_asset": "USDT",
        "timestamp_unit": "ms", "coverage_start_ms": START, "coverage_end_ms": END, "trade_kind": "MARKET_AGG_TRADE",
    }
    runtime = _runtime(tmp_path)
    client = app_client(runtime)
    try:
        imported = client.post(IMPORT_ROUTE, params=params, content=fixture())
        assert imported.status_code == 201, imported.text
        manifest = imported.json()
        assert manifest["source"] == "user_market_trades"
        assert manifest["market_trade_input"]["row_count"] == 20
        assert manifest["market_trade_input"]["coverage_end_ms_exclusive"] == END
        assert runtime.trade_archive is None
        snapshot_request = {
            "dataset_id": manifest["dataset_id"], "data_epoch": manifest["data_epoch"],
            "start_time_ms": START, "end_time_ms": END - 1, "interval": "1m",
            "exchange": "local", "market_type": "spot", "fidelity_mode": "AGG_TRADE_EXECUTION",
            "account_model": "SPOT_CASH_V1",
        }
        snapshot_path = "/api/v1/backtests/datasets/snapshot"
        snap = client.post(snapshot_path, json=snapshot_request)
        assert snap.status_code == 200, snap.text
        preview = snap.json()
        assert preview["quality"]["source_quality"] == "user_market_trades"
        assert preview["quality"]["completeness"] == "user_declared_coverage"
        assert preview["row_count"] == 20
        assert preview["coverage_end_ms"] == END - 1

        revision = compile_editor(runtime.service)
        body = {**snapshot_request, "snapshot_hash": preview["snapshot_hash"],
                "source_event_kind": "AGG_TRADE", "strategy_revision_id": revision["revision_id"],
                "python_runtime_mode": "TRUSTED_LOCAL", "python_trusted_confirmed": True,
                "output_mode": "SIGNAL", "equity_percent": "10", "sizing_policy": "EQUITY_PERCENT_V1",
                "symbol": "ETHUSDT"}
        smoke = client.post("/api/v1/backtests/strategy-revisions/" + revision["revision_id"] + "/smoke", json={
            key: body[key] for key in ("dataset_id", "snapshot_hash", "start_time_ms", "end_time_ms",
                                      "python_runtime_mode", "python_trusted_confirmed")
        })
        assert smoke.status_code == 200, smoke.text
        replacement = client.post(IMPORT_ROUTE, params={**params, "dataset_id": manifest["dataset_id"]}, content=fixture(1200))
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["data_epoch"] != manifest["data_epoch"]
        assert client.post(snapshot_path, json=snapshot_request).json()["snapshot_hash"] == preview["snapshot_hash"]
        creation = client.post(RUNS, json=body, headers={"Idempotency-Key": "user-market-test"})
        assert creation.status_code == 200, creation.text
        run_id = creation.json()["run_id"]
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            run = client.get(RUNS + "/" + run_id).json()
            if run["state"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.05)
        assert run["state"] == "COMPLETED", run
        assert run["snapshot_hash"] == preview["snapshot_hash"]
        chart = client.get(RUNS + "/" + run_id + "/chart")
        assert chart.status_code == 200, chart.text
        chart_body = chart.json()
        assert len(chart_body["bars"]) == 9
        assert chart_body["bars"][0]["close"] == 101
        assert max(bar["high"] for bar in chart_body["bars"]) < 1000
        assert chart_body["fills"]
    finally:
        runtime.shutdown()

    cold = _runtime(tmp_path)
    try:
        reopened = app_client(cold).get(RUNS + "/" + run_id + "/chart")
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["chart_hash"] == chart_body["chart_hash"]
    finally:
        cold.shutdown()
