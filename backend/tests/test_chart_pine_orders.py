import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.backtests import router
from tests.test_native_backtests import runtime as runtime, pytestmark as pytestmark


def run_chart(host, main, body, **settings):
    prepared = settings.pop("prepared", False)
    pyramiding = settings.pop("pyramiding",2)
    process_close = ",process_orders_on_close=true" if settings.pop("process_orders_on_close", False) else ""
    fill_callbacks = ",calc_on_order_fills=true" if settings.pop("calc_on_order_fills", False) else ""
    revision = host.service.create_strategy_revision({"language": "PINE_ENGINE", "name": "Chart orders",
        "source_text": f'//@version=6\nstrategy("Chart orders",pyramiding={pyramiding}{process_close}{fill_callbacks})\n' + body})
    payload = {key: main[key] for key in ("dataset_id", "data_epoch", "snapshot_hash", "interval", "start_time_ms", "end_time_ms")}
    payload.update(strategy_revision_id=revision["revision_id"], fidelity_mode="BAR_APPROX", source_event_kind="BAR",
        exchange="binance", market_type="usdm", symbol="BTCUSDT", output_mode="ORDER_INTENT",
        account_model="LINEAR_PERP_ONE_WAY_V1", initial_balance="10000", slippage_bps="0", taker_fee_bps="0")
    payload.update(settings)
    host.service.smoke_strategy_revision(revision["revision_id"], payload)
    app = FastAPI()
    app.state.backtest_runtime, app.state.backtest_service = host, host.service
    app.include_router(router)
    if prepared:
        from app.api.v1.data_preparation import StrategyLaunchPayload
        from app.backtest.quick_presets import quick_preset_for_market
        from app.data_preparation.strategy_launcher import launch
        preset = quick_preset_for_market("usdm")
        intent = StrategyLaunchPayload(strategy_revision_id=revision["revision_id"], parameters={}, output_mode="ORDER_INTENT").model_dump()
        resolution = {**main, "request": {"exchange": "binance", "market_type": "usdm", "symbol": "BTCUSDT", "interval": "1m", "range_mode": "CUSTOM"},
            "fidelity": {"mode": "BAR_APPROX"}, "coverage": {"requested_start_ms": 0, "requested_end_ms": 599999},
            "quick_preset_id": preset["id"], "account_execution_preset": preset,
            "cost_preset": {**preset, "preset_revision": preset["revision"]}}
        run_id = launch(host, intent, resolution, "chart-rich-prepared")["run_id"]
    else:
        with TestClient(app) as client:
            response = client.post("/backtests/runs", json=payload, headers={"Idempotency-Key": "chart-orders"})
            assert response.status_code == 200, response.text
            run_id = response.json()["run_id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = host.service.get_run(run_id)
        if result["state"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            break
        time.sleep(.03)
    assert result["state"] == "COMPLETED", result
    return host.service.get_report(run_id)


@pytest.mark.parametrize("kind,arguments", [("LIMIT", "limit=11"), ("STOP", "stop=11"), ("STOP_LIMIT", "limit=21,stop=11")])
def test_price_orders_reach_the_actual_queued_chart_matcher(runtime, kind, arguments):
    host, main = runtime
    report = run_chart(host, main, f'if bar_index == 0\n    strategy.entry("L",strategy.long,qty=4,{arguments})')
    assert report["orders"][0]["type"] == kind
    assert report["fills"]
    assert report["pine_orders"]["open_entries"][0]["entry_id"] == "L"


def test_replacement_partial_close_and_oco_bracket_use_the_real_chart_account(runtime):
    host, main = runtime
    report = run_chart(host, main, '''if bar_index == 0
    strategy.entry("L",strategy.long,qty=4,limit=1)
if bar_index == 1
    strategy.entry("L",strategy.long,qty=4)
if bar_index == 2
    strategy.close("L",qty_percent=50)
if bar_index == 3
    strategy.exit("X","L",limit=30,stop=8)
''')
    assert report["orders"][0]["status"] == "CANCELLED"
    assert [float(fill["qty"]) for fill in report["fills"]] == [4, 2, 2]
    assert any(order["status"] == "CANCELLED_OCO" for order in report["orders"])
    assert report["pine_orders"]["open_entries"] == []


def test_pyramiding_and_id_specific_close_keep_host_entry_ownership(runtime):
    host, main = runtime
    report = run_chart(host, main, '''if bar_index == 0
    strategy.entry("A",strategy.long,qty=2)
    strategy.entry("B",strategy.long,qty=3)
if bar_index == 2
    strategy.close("B",qty=1)
if bar_index == 3
    strategy.close("A")
''')
    assert [float(fill["qty"]) for fill in report["fills"]] == [2, 3, 1, 2]
    entries = report["pine_orders"]["open_entries"]
    assert len(entries) == 1 and entries[0]["entry_id"] == "B" and float(entries[0]["qty"]) == 2


@pytest.mark.parametrize("prepared", [False, True])
def test_bracket_can_be_submitted_before_its_entry_fills(runtime, prepared):
    host, main = runtime
    report = run_chart(host, main, '''if bar_index == 0
    strategy.entry("L",strategy.long,qty=4,limit=11)
    strategy.exit("X","L",limit=30,stop=8)
''', prepared=prepared)
    assert [float(fill["qty"]) for fill in report["fills"]] == [4, 4]
    assert report["pine_orders"]["open_entries"] == []


def test_rejected_first_order_cannot_steal_the_next_accepted_order_id(runtime):
    host, main = runtime
    report = run_chart(host, main, '''if bar_index == 0
    strategy.entry("too_large",strategy.long,qty=1000000)
    strategy.entry("B",strategy.long,qty=2)
if bar_index == 2
    strategy.close("B")
''', account_model="SPOT_CASH_V1", market_type="spot", initial_balance="100")
    assert report["rejected_orders"]
    assert [float(fill["qty"]) for fill in report["fills"]] == [2, 2]
    allocations = report["pine_orders"]["fill_allocations"]
    assert allocations[0]["opened"]["entry_id"] == "B"
    assert allocations[1]["closed"][0]["entry_id"] == "B"


def test_cancel_and_cancel_all_remove_pending_orders_before_a_new_entry(runtime):
    host, main = runtime
    report = run_chart(host, main, '''if bar_index == 0
    strategy.entry("A",strategy.long,qty=2,limit=1)
    strategy.entry("B",strategy.long,qty=3,limit=1)
if bar_index == 1
    strategy.cancel("A")
if bar_index == 2
    strategy.cancel_all()
if bar_index == 3
    strategy.entry("C",strategy.long,qty=2)
''')
    assert [row["status"] for row in report["orders"][:2]] == ["CANCELLED", "CANCELLED"]
    assert [float(fill["qty"]) for fill in report["fills"]] == [2]
    assert report["pine_orders"]["open_entries"][0]["entry_id"] == "C"


def test_tick_distance_bracket_uses_the_actual_entry_fill_basis(runtime):
    host, main = runtime
    report = run_chart(host, main, '''if bar_index == 0
    strategy.entry("L",strategy.long,qty=2)
if bar_index == 1
    strategy.exit("X","L",profit=2,loss=1)
''', price_tick=".5")
    assert [float(fill["qty"]) for fill in report["fills"]] == [2, 2]
    assert [float(fill["price"]) for fill in report["fills"]] == [10, 9.5]


@pytest.mark.parametrize("entry_risk", [False, True])
def test_checkpoint_recovery_preserves_pending_brackets_and_actual_entry_allocations(tmp_path, entry_risk):
    from app.backtest.strategy.pine_engine import PineEngineProvider
    from app.backtest.strategy.protocol import StrategyProviderError
    from app.market_dataset.snapshot import MarketEvent
    from tests.test_backtest_chart_pyne import _service
    service = _service(tmp_path)
    service._colocated_worker = True
    source = '''//@version=6
strategy("Recover orders",pyramiding=2)
if bar_index == 0
    strategy.entry("L",strategy.long,qty=4,limit=11)
    strategy.exit("X","L",limit=30,stop=8)
'''
    if entry_risk:
        source = source.replace('strategy("Recover orders",pyramiding=2)', 'strategy("Recover orders",pyramiding=2)\nif false\n    strategy.risk.max_position_size(2)')
    try:
        revision = service.create_strategy_revision({"language": "PINE_ENGINE", "name": "Recover", "source_text": source})
        payload = {"strategy_revision_id": revision["revision_id"], "dataset_id": "local-pine", "data_epoch": "epoch-20261019",
            "snapshot_hash": "sha256:snapshot", "fidelity_mode": "BAR_APPROX", "source_event_kind": "BAR", "start_time_ms": 0,
            "end_time_ms": 600000, "symbol": "BTCUSDT", "interval": "1m", "output_mode": "ORDER_INTENT", "parameters": {},
            "initial_balance": "10000", "slippage_bps": "0", "taker_fee_bps": "0", "checkpoint_policy": "INTERVAL", "checkpoint_interval": 1}
        service.smoke_strategy_revision(revision["revision_id"], payload, now_ms=2)
        events = tuple(MarketEvent(i+1,(i+1)*60000-1,"BARS", {"open_time_ms":i*60000,"close_time_ms":(i+1)*60000-1,
            **{key:str(value) for key in ("open","high","low","close")},"volume":"100"})
            for i,value in enumerate((10,10,10,20,20,5,5)))
        clean = service.create_run(payload, idempotency_key="clean", now_ms=3)
        baseline = service.execute_bar_run(clean["run_id"], events=events, provider=PineEngineProvider(), now_ms=4)
        interrupted = service.create_run(payload, idempotency_key="resume", now_ms=5)
        def fault(point, details):
            if point == "before_decision" and details["sequence"] == 4:
                raise StrategyProviderError("PROVIDER_TIMEOUT", "controlled recovery")
        service._fault_injector = fault
        with pytest.raises(StrategyProviderError, match="PROVIDER_TIMEOUT"):
            service.execute_bar_run(interrupted["run_id"], events=events, provider=PineEngineProvider(), now_ms=6)
        assert service.repository.latest_checkpoint(interrupted["run_id"])["sequence"] == 3
        service._fault_injector = None
        service.resume_failed_run(interrupted["run_id"], now_ms=7)
        resumed = service.execute_bar_run(interrupted["run_id"], events=events, provider=PineEngineProvider(), now_ms=8)
        for field in ("fills", "orders", "pine_orders"):
            assert resumed["report"][field] == baseline["report"][field]
        for field in ("fill_hash", "ledger_hash", "decision_hash"):
            assert resumed["result"][field] == baseline["result"][field]
    finally:
        service.shutdown()


def test_closed_bar_chart_orders_and_trailing_stops_execute_on_real_trade_clock(tmp_path):
    from app.backtest.service import BacktestService
    from app.backtest.strategy.pine_engine import PineEngineProvider
    from app.core.config import load_backtest_settings
    from tests.test_backtest_dual_clock import _trade
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1", "BACKTEST_TRADE_TAPE_ENABLED": "1"},
        data_dir=tmp_path, klines_db_path=tmp_path/"klines.db", replay_db_path=tmp_path/"replay.db")
    service = BacktestService.start(settings, enforce_registered_revisions=True, now_ms=1)
    try:
        source = '''//@version=6
strategy("Chart trade clock")
if bar_index == 0
    strategy.entry("L",strategy.long,qty=2,limit=11)
    strategy.exit("X","L",trail_points=2,trail_offset=1)
'''
        revision = service.create_strategy_revision({"language": "PINE_ENGINE", "name": "Print clock", "source_text": source})
        payload = {"strategy_revision_id": revision["revision_id"], "dataset_id": "local-pine", "data_epoch": "epoch-20261019",
            "snapshot_hash": "sha256:snapshot", "fidelity_mode": "AGG_TRADE_EXECUTION", "source_event_kind": "AGG_TRADE", "start_time_ms": 0,
            "end_time_ms": 240000, "symbol": "BTCUSDT", "interval": "1m", "output_mode": "ORDER_INTENT", "parameters": {},
            "initial_balance": "10000", "slippage_bps": "0", "taker_fee_bps": "0", "price_tick": ".5",
            "signal_clock": "DERIVED_BAR_CLOSE", "signal_interval": "1m", "execution_clock": "NEXT_AGG_TRADE",
            "bar_builder": "TRADE_DERIVED_COMPLETE_BUCKETS_V1", "timezone": "UTC"}
        service.smoke_strategy_revision(revision["revision_id"], payload, now_ms=2)
        run = service.create_run(payload, idempotency_key="chart-trailing", now_ms=3)
        trades = tuple(_trade(i+1, stamp, str(price), "100") for i,(stamp,price) in enumerate(
            ((1000,10),(60000,10),(90000,12),(120000,11),(130000,10),(180000,10))))
        completed = service.execute_dual_clock_run(run["run_id"], events=trades, provider=PineEngineProvider(), now_ms=4,
            observation_market={"venue": "binance", "symbol": "BTCUSDT"})
        report = completed["report"]
        assert [row["event_time_ms"] for row in report["fills"]] == [60000,120000]
        assert [float(row["qty"]) for row in report["fills"]] == [2,2]
        assert report["pine_orders"]["open_entries"] == []
        assert report["report_label"] == "AGGREGATED_TRADE_SEQUENCE"
    finally:
        service.shutdown()
