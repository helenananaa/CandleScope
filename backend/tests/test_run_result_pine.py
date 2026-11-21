"""ADR-BACKTEST-015 P1: Pine-path projections, and the cross-path comparison they enable.

Needs the qualified Pine runtime (runs in the "Pine host contracts" workflow).
"""
from __future__ import annotations

from decimal import Decimal

from app.backtest.run_result import from_external_report, from_host_result, from_native_report
from app.backtest.service import BacktestService
from app.backtest.strategy.pine_engine import PineEngineProvider
from app.backtest.strategy.registry import build_default_strategy_registry
from app.core.config import load_backtest_settings
from tests import strategy_run_oracles as oracles
from tests.test_run_result import assert_projects_golden
from tests.test_strategy_run_oracles import BUILTIN_SMA_REVISION, BAR, builtin_provider
from tests.test_strategy_run_oracles_pine import (  # noqa: F401 - native_runtime is a fixture
    _complete, _settings, native_runtime, pytestmark,
)

EXTERNAL = {"execution_mode": "CANDLESCOPE", "execution_fidelity": "BAR_APPROX", "fill_recalculation": False,
            "host_settings": {"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 10}}


def _host_pine_result(tmp_path):
    service = BacktestService.start(_settings(tmp_path), now_ms=1, enforce_registered_revisions=True)
    provider = PineEngineProvider()
    try:
        revision = service.create_strategy_revision(
            {"language": "PINE_ENGINE", "name": "Oracle SMA", "source_text": oracles.PINE_SMA_SOURCE})
        payload = {**BAR, "strategy_revision_id": revision["revision_id"], "parameters": {}, "symbol": "BTCUSDT",
                   "initial_balance": "10000", "account_model": "LINEAR_PERP_ONE_WAY_V1", "exchange": "binance",
                   "market_type": "usdm"}
        payload.pop("warmup_bars")
        service.smoke_strategy_revision(str(revision["revision_id"]), payload, now_ms=2)
        row = service.create_run(payload, idempotency_key="result-host-pine", now_ms=3)
        return service.execute_bar_run(str(row["run_id"]), events=oracles.bars(), provider=provider, now_ms=4,
                                       observation_market={"venue": "binance", "symbol": "BTCUSDT"})["result"]
    finally:
        provider.close()
        service.shutdown()


def _host_builtin_result(tmp_path):
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"}, data_dir=tmp_path / "builtin",
                                      klines_db_path=tmp_path / "builtin.db", replay_db_path=tmp_path / "replay.db")
    service = BacktestService.start(settings, strategy_registry=build_default_strategy_registry(),
                                    enforce_registered_revisions=True, now_ms=1)
    try:
        row = service.create_run({**BAR, "strategy_revision_id": BUILTIN_SMA_REVISION}, idempotency_key="b", now_ms=2)
        return service.execute_bar_run(str(row["run_id"]), events=oracles.bars(), provider=builtin_provider(),
                                       now_ms=3)["result"]
    finally:
        service.shutdown()


def test_pine_paths_project_without_loss_and_agree_on_bars(tmp_path, native_runtime):
    runtime, request = native_runtime
    native = from_native_report(_complete(runtime, request, "result-native"), interval="1m")
    external = from_external_report(_complete(runtime, {**request, **EXTERNAL}, "result-external"), interval="1m")
    host_pine = from_host_result(_host_pine_result(tmp_path), interval="1m", fidelity="BAR_APPROX")
    builtin = from_host_result(_host_builtin_result(tmp_path), interval="1m", fidelity="BAR_APPROX")

    assert_projects_golden(external, "external-pine-feedback")
    assert_projects_golden(host_pine, "host-pine-engine")
    native_golden = oracles.load_golden("native-pine")["summary"]
    assert native["summary"]["fill_count"] == native_golden["orders"]
    assert native["summary"]["trade_count"] == native_golden["trades"]
    assert Decimal(native["summary"]["final_equity"]) == Decimal(str(native_golden["final_equity"]))
    oracles.assert_frontend_fixture("native-pine", native)
    assert native["authority"] == "SCRIPT" and external["authority"] == host_pine["authority"] == "HOST"
    assert len(native["plots"]) == len(external["plots"]) == 2
    assert all(len(plot["points"]) == len(oracles.bars()) for plot in native["plots"])

    # Once projected, the four SMA paths fill on the same bars, in the same direction and size,
    # and close the same round trips. Prices and money differ only by each path's costs.
    def fills(result):
        return [(fill["bar_time_ms"], fill["side"], fill["qty"]) for fill in result["fills"]]

    def trips(result):
        return [(t["side"], t["entry_bar_time_ms"], t["exit_bar_time_ms"], t["qty"]) for t in result["trades"]]

    assert fills(native) == fills(external) == fills(host_pine) == fills(builtin)
    assert trips(native) == trips(external) == trips(host_pine) == trips(builtin)
    assert native["open_position"]["qty"] == external["open_position"]["qty"] == builtin["open_position"]["qty"]
    # Native Pine uses the script's zero costs; the host paths charge configured fees and slippage.
    assert [f["price"] for f in native["fills"]] == [f["price"] for f in external["fills"]]
    assert all(f["fee"] is None for f in native["fills"]) and all(f["fee"] for f in host_pine["fills"])


def test_native_and_external_routes_serve_their_projections(native_runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.backtests import router
    from tests.test_native_backtests import terminal

    runtime, request = native_runtime
    native_id = terminal(runtime.native, runtime.native.create(request, "route-native")["run_id"], timeout=90)["run_id"]
    external_id = terminal(runtime.native, runtime.native.create({**request, **EXTERNAL}, "route-external")["run_id"],
                           timeout=90)["run_id"]
    app = FastAPI()
    app.state.backtest_runtime = runtime
    app.include_router(router)
    with TestClient(app) as client:
        native = client.get(f"/backtests/native/runs/{native_id}/run-result")
        external = client.get(f"/backtests/external/runs/{external_id}/run-result")
        unknown = client.get("/backtests/native/runs/no-such-run/run-result")
    assert native.status_code == external.status_code == 200
    assert native.json() == from_native_report(runtime.native.get(native_id)["result"], interval="1m")
    assert external.json() == from_external_report(runtime.native.get(external_id)["result"], interval="1m")
    assert native.json()["authority"] == "SCRIPT" and external.json()["authority"] == "HOST"
    assert unknown.status_code >= 400
