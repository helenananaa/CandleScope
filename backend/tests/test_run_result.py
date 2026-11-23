"""ADR-BACKTEST-015 P1: ``candlescope.run-result/1`` projections of host-kernel results.

Pine-path projections need the installed Pine runtime: ``test_run_result_pine.py``.
"""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.models import ENGINE_VERSION
from app.backtest.run_result import SCHEMA, BarAnchor, decimal_text, from_host_result, from_native_report
from tests import strategy_run_oracles as oracles
from tests.test_strategy_run_oracles import (  # noqa: F401 - service is a fixture
    BUILTIN_SMA_REVISION, DUAL_CLOCK, builtin_provider, fixed_run, service,
)

BAR_OPENS = {bar.payload["open_time_ms"] for bar in oracles.bars()}
# The dual clock executes on aggTrades, including the tape's last, incomplete minute.
TAPE_MINUTES = {minute * 60_000 for minute in range(oracles.MINUTES)}


@pytest.mark.parametrize("value,expected", [
    ("107.0107", "107.0107"), ("107.0", "107"), (107.0, "107"), (100, "100"), ("1E+2", "100"),
    ("-0.00", "0"), (106.83333333333333, "106.83333333333333"), (None, None), ("nan", None), (True, None),
])
def test_decimal_text_is_canonical(value, expected):
    assert decimal_text(value) == expected


def test_bar_anchor_floors_day_aligned_intervals_and_bisects_otherwise():
    assert BarAnchor("1m")(719_999) == 660_000
    assert BarAnchor("15m")(900_000) == 900_000
    assert BarAnchor("1m")(None) is None
    with pytest.raises(ValueError):
        BarAnchor("1w")  # week bars are not epoch-aligned: their open times are required
    weekly = BarAnchor("1w", [345_600_000, 950_400_000])
    assert weekly(400_000_000) == 345_600_000 and weekly(1) is None


def test_native_close_side_follows_the_running_position():
    report = {"bars": [{"time": 0}, {"time": 60}, {"time": 120}, {"time": 180}], "graphics": [],
              "orders": [{"direction": "strategy.short", "qty": 2.0, "price": 10.0, "time": 0, "id": "S"},
                         {"direction": "strategy.close", "qty": 2.0, "price": 9.0, "time": 60, "id": "Close S"},
                         {"direction": "strategy.long", "qty": 1.0, "price": 9.5, "time": 120, "id": "L"}],
              "trades": [{"qty": -2.0, "entryTime": 0, "exitTime": 60, "entryPrice": 10.0, "exitPrice": 9.0, "profit": 2.0}],
              "position": [{"size": 1.0, "avgPrice": 9.5}], "equity": [{"time": 0, "value": 100.0}, {"time": 180, "value": 102.0}]}
    projected = from_native_report(report, interval="1m")
    assert [fill["side"] for fill in projected["fills"]] == ["SELL", "BUY", "BUY"]
    assert projected["trades"][0]["side"] == "SHORT" and projected["trades"][0]["qty"] == "2"
    assert projected["open_position"] == {"side": "LONG", "qty": "1", "avg_price": "9.5"}
    assert projected["summary"]["net_profit"] == "2" and projected["authority"] == "SCRIPT"


def assert_projects_golden(projected, path, *, bar_opens=BAR_OPENS):
    """The projection keeps every fill and the final equity of the path's P0 golden."""
    golden = oracles.load_golden(path)["summary"]
    assert projected["schema"] == SCHEMA
    assert projected["summary"]["fill_count"] == golden["fills"] == len(golden["fill_rows"])
    assert Decimal(projected["summary"]["final_equity"]) == Decimal(str(golden["final_equity"]))
    times = [fill["time_ms"] for fill in projected["fills"]]
    assert times == sorted(times)
    assert {fill["bar_time_ms"] for fill in projected["fills"]} <= bar_opens
    assert {point["bar_time_ms"] for point in projected["equity"]} <= bar_opens
    for trade in projected["trades"]:
        assert trade["entry_bar_time_ms"] in bar_opens and trade["exit_bar_time_ms"] in bar_opens
        assert trade["entry_time_ms"] <= trade["exit_time_ms"]


@pytest.mark.parametrize("provider_name", ["builtin", "python"])
def test_host_bar_results_project_without_loss(service, provider_name):
    _, completed = fixed_run(service, provider_name)
    projected = from_host_result(completed["result"], interval="1m", fidelity="BAR_APPROX")
    assert_projects_golden(projected, f"host-bar-{provider_name}")
    if provider_name == "builtin":
        oracles.assert_frontend_fixture("host-bar-builtin", projected)
    assert projected["authority"] == "HOST" and projected["plots"] == []
    # Host round trips are exactly the report's own trade list.
    report_trades = completed["report"]["trades"]
    assert [(t["entry_price"], t["exit_price"], t["net_pnl"]) for t in projected["trades"]] == [
        (decimal_text(t["entry_price"]), decimal_text(t["exit_price"]), decimal_text(t["net_pnl"])) for t in report_trades]


def test_host_dual_clock_result_projects_without_loss(service):
    row = service.create_run({**DUAL_CLOCK, "strategy_revision_id": BUILTIN_SMA_REVISION},
                             idempotency_key="result-dual-clock", now_ms=4)
    completed = service.execute_dual_clock_run(str(row["run_id"]), events=oracles.trades(),
                                               provider=builtin_provider(), now_ms=5)
    projected = from_host_result(completed["result"], interval="1m", fidelity="AGG_TRADE_EXECUTION")
    assert_projects_golden(projected, "host-aggtrade-dual-clock", bar_opens=TAPE_MINUTES)
    assert projected["fills"][-1]["bar_time_ms"] not in BAR_OPENS  # filled inside the unclosed last minute


def test_forward_result_projects_like_fixed(service, tmp_path):
    """A continuous-kernel result and a fixed run of the same inputs project identically."""
    row, completed = fixed_run(service, "builtin")
    config = json.loads(str(row["config_json"]))
    definition = {"engine_version": ENGINE_VERSION, "configuration": config,
                  "input_plan": {"roles": ["BARS"], "parameters": config["parameters"]},
                  "market": {"venue": "local", "symbol": str(row["dataset_id"])}}
    store = ContinuousStrategyStore(tmp_path / "forward-result.db")
    factory = lambda _: builtin_provider()  # noqa: E731
    ContinuousBarHost.create_run(store, "result-forward", definition=definition, mode="HISTORY_LIVE",
                                 data_revision="r1", event_time_ms=0, provider_factory=factory)
    host = ContinuousBarHost.resume(store, "result-forward", factory)
    try:
        events = oracles.bars()
        host.apply_batch(events, data_revision="r1", revealed_through_ms=events[-1].event_time_ms,
                         coverage_complete=True, caught_up=True)
        forward = from_host_result(asdict(host.kernel.run((), host._observe, finalize=True)), interval="1m",
                                   fidelity="BAR_APPROX", clock_policy="FORWARD")
    finally:
        host.close(); store.close()
    fixed = from_host_result(completed["result"], interval="1m", fidelity="BAR_APPROX")
    assert {**forward, "clock_policy": "FIXED"} == fixed


@pytest.fixture
def runtime_run(tmp_path):
    """A builtin SMA run executed by the backtest runtime from a local dataset of the oracle bars."""
    import time
    from app.backtest.runtime import BacktestRuntime
    from app.core.config import load_backtest_settings
    from app.local_data.service import LocalDatasetService, LocalImportOptions
    from tests.test_strategy_run_oracles import COMMON

    csv = tmp_path / "oracle-bars.csv"
    csv.write_text(oracles.bars_csv(), encoding="utf-8")
    manifest = LocalDatasetService(tmp_path / "local").import_csv(
        csv, LocalImportOptions(name="oracle", symbol="BTCUSDT", interval="1m", timestamp_unit="ms"))
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"}, data_dir=tmp_path,
                                      klines_db_path=tmp_path / "candlescope.db", replay_db_path=tmp_path / "replay.db")
    runtime = BacktestRuntime.start(settings, local_data_dir=tmp_path / "local")
    try:
        end = len(oracles.bars()) * 60_000
        preview = runtime.preview_snapshot(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"],
                                           start_time_ms=0, end_time_ms=end, interval="1m")
        created = runtime.service.create_run({
            **COMMON, "strategy_revision_id": BUILTIN_SMA_REVISION, "fidelity_mode": "BAR_APPROX",
            "dataset_id": manifest["dataset_id"], "data_epoch": manifest["data_epoch"],
            "snapshot_hash": preview["snapshot_hash"], "end_time_ms": end,
        }, idempotency_key="result-runtime")
        deadline = time.monotonic() + 15
        while runtime.service.get_run(str(created["run_id"]))["state"] not in {"COMPLETED", "FAILED"}:
            assert time.monotonic() < deadline, "runtime run did not finish"
            time.sleep(0.05)
        assert runtime.service.get_run(str(created["run_id"]))["state"] == "COMPLETED"
        yield runtime, str(created["run_id"])
    finally:
        runtime.shutdown()


def _client(runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.backtests import router

    app = FastAPI()
    app.state.backtest_runtime = runtime
    app.include_router(router)
    return TestClient(app)


def test_run_result_route_serves_the_projection_of_a_runtime_run(runtime_run):
    runtime, run_id = runtime_run
    with _client(runtime) as client:
        served = client.get(f"/backtests/runs/{run_id}/run-result")
        missing = client.get("/backtests/runs/no-such-run/run-result")
    assert served.status_code == 200
    body = served.json()
    assert body == from_host_result(runtime.service.get_report(run_id), interval="1m", fidelity="BAR_APPROX")
    # The production path over a local dataset trades exactly like the P0 oracle run.
    golden = oracles.load_golden("host-bar-builtin")["summary"]
    def golden_fill(row):  # "719999 BUY 1 @ 107.0107 fee 0.03210321"
        time_ms, side, qty, _, price, _, fee = row.split()
        return int(time_ms), side, Decimal(qty), Decimal(price), Decimal(fee)

    assert [(f["time_ms"], f["side"], Decimal(f["qty"]), Decimal(f["price"]), Decimal(f["fee"]))
            for f in body["fills"]] == [golden_fill(row) for row in golden["fill_rows"]]
    assert missing.status_code >= 400 and "error" in missing.json()


def test_calendar_intervals_anchor_to_the_runs_own_bars(runtime_run, monkeypatch):
    runtime, run_id = runtime_run
    opens = [0, 900_000, 1_800_000]  # pretend three uneven calendar bars
    monkeypatch.setattr(runtime, "_chart_interval", lambda record, config: "1w")
    monkeypatch.setattr(runtime, "chart_data", lambda _run_id: {"bars": [{"time": value // 1000} for value in opens]})
    projected = runtime.run_result(run_id)
    assert projected["interval"] == "1w"
    assert {fill["bar_time_ms"] for fill in projected["fills"]} <= set(opens)
    assert projected["fills"][0]["bar_time_ms"] == 0 and projected["fills"][-1]["bar_time_ms"] == 1_800_000


def test_host_rejections_and_explanations_pass_through():
    explanation = {"schema": "TRADE_EXPLANATION_V1", "evidenceHash": "sha256:" + "0" * 64}
    result = {
        "fills": [{"event_time_ms": 119_999, "side": "BUY", "qty": "1", "price": "10", "fee": "0",
                   "order_id": "ord-1", "sequence": 2, "explanation": explanation}],
        "orders": [], "ledger": {"account": {"position_qty": "1", "entry_price": "10"}},
        "equity_curve": [{"sequence": 4, "event_time_ms": 239_999, "equity": "100", "position_qty": "1"}],
        "rejected_orders": [
            {"reason": "MIN_NOTIONAL", "sequence": 3, "event_time_ms": 179_999, "intent": {"side": "sell"},
             "explanation": explanation},
            {"reason": "INSUFFICIENT_MARGIN", "sequence": 4, "intent": {}},
        ],
    }
    projected = from_host_result(result, interval="1m", fidelity="BAR_APPROX")
    assert projected["fills"][0]["explanation"] == explanation
    assert projected["rejections"] == [
        {"time_ms": 179_999, "bar_time_ms": 120_000, "side": "SELL", "reason": "MIN_NOTIONAL", "order_id": None,
         "explanation": explanation},
        # Report rows have no timestamp: the equity point of their sequence anchors them.
        {"time_ms": 239_999, "bar_time_ms": 180_000, "side": None, "reason": "INSUFFICIENT_MARGIN", "order_id": None,
         "explanation": None},
    ]
    # Kernel results name the same list "rejected".
    kernel = {**result, "rejected": result.pop("rejected_orders")}
    assert from_host_result(kernel, interval="1m", fidelity="BAR_APPROX")["rejections"] == projected["rejections"]



def test_rejected_runtime_orders_are_anchored_by_sequence(runtime_run, monkeypatch):
    """A real report: rejection rows carry only their sequence, yet every one gets a bar."""
    runtime, run_id = runtime_run
    report = runtime.service.get_report(run_id)
    first_fill = report["fills"][0]
    rejected = [{"accepted": False, "reason": "SPOT_INSUFFICIENT_CASH", "sequence": first_fill["sequence"],
                 "intent": {"side": "BUY", "type": "MARKET", "qty": "1"}}]
    projected = from_host_result({**report, "rejected_orders": rejected}, interval="1m", fidelity="BAR_APPROX")
    assert projected["rejections"][0]["bar_time_ms"] == projected["fills"][0]["bar_time_ms"]



def test_sampled_equity_still_anchors_rejections_only_across_gap_free_spans():
    """The runtime keeps every 100th equity point; rejections in between are placed exactly."""
    hour = 3_600_000
    equity = [{"sequence": seq, "event_time_ms": seq * hour - 1, "equity": "100", "position_qty": "0"} for seq in (1, 100)]
    equity.append({"sequence": 171, "event_time_ms": 175 * hour - 1, "equity": "100", "position_qty": "0"})  # 4 bars missing
    result = {"fills": [], "orders": [], "ledger": {"account": {}}, "equity_curve": equity,
              "rejected_orders": [{"reason": "SPOT_INSUFFICIENT_CASH", "sequence": seq, "intent": {"side": "BUY"}}
                                  for seq in (7, 100, 130)]}
    bar = from_host_result(result, interval="1h", fidelity="BAR_APPROX")["rejections"]
    assert [item["bar_time_ms"] for item in bar] == [6 * hour, 99 * hour, None]
    trades = from_host_result(result, interval="1h", fidelity="AGG_TRADE_EXECUTION")["rejections"]
    assert all(item["bar_time_ms"] is None for item in trades), "print sequences are not bar indexes"



def test_host_trade_evidence_comes_from_the_reports_own_trade_list(runtime_run):
    runtime, run_id = runtime_run
    report = runtime.service.get_report(run_id)
    entry = {"schema": "TRADE_EXPLANATION_V1", "side": "entry"}
    enriched = [{**row, "entry_explanation": entry, "exit_explanation": None} for row in report["trades"]]
    projected = from_host_result({**report, "trades": enriched}, interval="1m", fidelity="BAR_APPROX")
    assert projected["trades"] and all(t["entry_explanation"] == entry and t["exit_explanation"] is None
                                      for t in projected["trades"])
    mismatched = from_host_result({**report, "trades": enriched[:1]}, interval="1m", fidelity="BAR_APPROX")
    assert all(t["entry_explanation"] is None for t in mismatched["trades"]), "never pair evidence by guesswork"
