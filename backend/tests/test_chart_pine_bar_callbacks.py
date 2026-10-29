"""Installed Pine on the actual historical chart BAR matcher and lifecycle."""
import json
from copy import deepcopy
from decimal import Decimal

import pytest

from app.backtest.strategy.pine_engine import PineEngineProvider
from tests.test_chart_pine_callbacks import service as service, pytestmark as pytestmark
from tests.test_pine_cost_sensitivity import bars
from tests.test_native_backtests import runtime as runtime

SOURCE = '''//@version=6
strategy("Historical callbacks",calc_on_order_fills=true%s)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0 and barstate.ishistory and barstate.isconfirmed and barstate.isnew
    strategy.exit("X","L",limit=strategy.position_avg_price+0.5,stop=strategy.position_avg_price-0.5)
plot(barstate.ishistory ? 1 : 0)
plot(barstate.isconfirmed ? 1 : 0)
plot(ta.sma(close,2))
'''


class RecordingProvider(PineEngineProvider):
    def __init__(self):
        super().__init__()
        self.frames = []

    def step(self, frame):
        self.frames.append(deepcopy(frame))
        return super().step(frame)


def config(service, *, source=None, closing=False, spot=False, **overrides):
    revision = service.create_strategy_revision({"language": "PINE_ENGINE", "name": "Historical",
        "source_text": source or SOURCE % (",process_orders_on_close=true" if closing else "")})
    value = {"strategy_revision_id": revision["revision_id"], "dataset_id": "local-pine", "data_epoch": "epoch-bar",
        "snapshot_hash": "sha256:snapshot", "fidelity_mode": "BAR_APPROX", "source_event_kind": "BAR",
        "start_time_ms": 0, "end_time_ms": 300000, "symbol": "BTCUSDT", "interval": "1m", "exchange": "binance",
        "market_type": "spot" if spot else "usdm", "account_model": "SPOT_CASH_V1" if spot else "LINEAR_PERP_ONE_WAY_V1",
        "output_mode": "ORDER_INTENT", "parameters": {}, "initial_balance": "10000", "slippage_bps": "0",
        "taker_fee_bps": "0", "price_tick": ".1", "checkpoint_policy": "INTERVAL", "checkpoint_interval": 1}
    value.update(overrides)
    service.smoke_strategy_revision(revision["revision_id"], value, now_ms=2)
    return value


def execute(service, value, key, provider=None, run=None):
    record = run or service.create_run(value, idempotency_key=key, now_ms=3)
    return service.execute_bar_run(record["run_id"], events=bars(), provider=provider or PineEngineProvider(), now_ms=4,
        observation_market={"venue": "binance", "symbol": "BTCUSDT"})


@pytest.mark.parametrize("closing,spot,inline", [(False, False, True), (True, False, True), (False, True, True), (False, False, False)])
def test_chart_bar_callbacks_observe_actual_fills_full_ohlcv_and_historical_state(service, closing, spot, inline):
    service._colocated_worker = inline
    provider = RecordingProvider()
    result = execute(service, config(service, closing=closing, spot=spot), "historical", provider)
    report = result["report"]
    assert report["fill_model"]["name"] == "PINE_OHLC_PATH_V1"
    assert report["fill_model"]["physical_tape"] is False
    assert [Decimal(row["price"]) for row in report["fills"]] == [Decimal(10), Decimal("9.5")]
    assert report["fills"][0]["event_time_ms"] == (59999 if closing else 60000)
    assert report["strategy"]["pineExecution"]["profile"] == "EXPLICIT_HOST_EXECUTION_SCHEDULE"
    assert report["strategy"]["pineExecution"]["fillCallbackCount"] == 2
    assert report["pine_orders"]["open_entries"] == []
    frames = provider.frames
    assert [frame.sequence for frame in frames] == list(range(1, len(frames) + 1))
    fills = [frame for frame in frames if frame.features["pineExecutionContext"]["trigger"] != "bar_close"]
    assert [frame.account_view["position_size"] for frame in fills] == [2, 0]
    assert all(float(frame.bar["high"]) == 11 and float(frame.bar["low"]) == 9 for frame in fills)
    assert all(frame.features["pineExecutionContext"]["bar_state"] == "historical" for frame in frames)
    saved = provider.snapshot()
    assert all(row["evaluation"]["bar"]["close"] == 10 for group in saved["execution_schedule"] for row in group)
    matrix = report["cost_sensitivity"]
    assert matrix["baseline_reexecution_verified"] is True
    assert matrix["scenarios"][-1]["status"] == "NOT_APPLICABLE_OHLC_PATH_NO_TAPE_CAPACITY"


@pytest.mark.parametrize("middle", [False, True])
def test_chart_bar_recovery_preserves_account_path_and_provider_clocks(service, middle):
    value = config(service)
    baseline = execute(service, value, "baseline")
    run = service.create_run(value, idempotency_key="interrupted", now_ms=3)
    if middle:
        class Interrupted(PineEngineProvider):
            def step(self, frame):
                if frame.features["pineExecutionContext"]["trigger"] == "order_fill":
                    raise KeyboardInterrupt("interrupt after Host fill, before durable close")
                return super().step(frame)
        provider = Interrupted()
    else:
        provider = PineEngineProvider()
        original = service.repository.save_checkpoint
        def save(value):
            result = original(value)
            if value["sequence"] == 1:
                raise KeyboardInterrupt("interrupt after durable complete bar")
            return result
        service.repository.save_checkpoint = save
    try:
        with pytest.raises(KeyboardInterrupt):
            execute(service, value, "interrupted", provider, run)
    finally:
        if not middle:
            service.repository.save_checkpoint = original
    checkpoint = service.repository.latest_checkpoint(run["run_id"])
    state = json.loads(checkpoint["payload_json"])
    assert state["sequence"] == 1 and state["engine"]["pine_chart_bar"]["bar_count"] == 1
    assert state["engine"]["fills"] == []
    assert service.requeue_interrupted_run(run["run_id"], expected_generation=1, now_ms=8)
    recovered = execute(service, value, "interrupted", run=run)
    for name in ("fills", "orders", "pine_orders", "cost_sensitivity"):
        assert recovered["report"][name] == baseline["report"][name]
    for name in ("decision_hash", "fill_hash", "ledger_hash", "report_hash"):
        assert recovered["result"][name] == baseline["result"][name]


def test_bar_cost_scenarios_reexecute_fee_dependent_callback_decisions(service):
    source = '''//@version=6
strategy("Fee branch",calc_on_order_fills=true)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0
    if strategy.netprofit < -0.0225
        strategy.close("L")
    else
        strategy.exit("X","L",stop=9.5,limit=10.5)
'''
    result = execute(service, config(service, source=source, taker_fee_bps="10"), "fee-dependent")
    matrix = result["report"]["cost_sensitivity"]
    assert matrix["decision_source"] == "INDEPENDENT_PINE_HOST_REEXECUTION"
    assert matrix["baseline_reexecution_verified"] is True
    scenarios = {row["name"]: row for row in matrix["scenarios"]}
    assert scenarios["BASELINE"]["hashes"]["decision"] != scenarios["COSTS_PLUS_50_PERCENT"]["hashes"]["decision"]
    # The higher fee changes the order, hence the actual exit price: the base
    # stop fills at 9.5, whereas the new market close waits for the low at 9.
    assert Decimal(scenarios["BASELINE"]["metrics"]["ending_equity"]) == Decimal("9998.961")
    assert Decimal(scenarios["COSTS_PLUS_50_PERCENT"]["metrics"]["ending_equity"]) == Decimal("9997.943")


def test_historical_chart_fill_uses_completed_foreign_bar_and_its_metadata(service, monkeypatch):
    monkeypatch.setattr("app.backtest.pine_requested_data.load_contexts", lambda *_: [
        {"symbol": "OKX:ETH-USDT", "timeframe": "2", "metadata": {"priceTickSize": ".25", "currency": "USDT"},
         "closes": [119999], "bars": [dict(time=0, open=100, high=100, low=100, close=100, volume=100)]}])
    source = (SOURCE % "").replace("varip bool sent=false",
        'remote=request.security("OKX:ETH-USDT","2",close+syminfo.mintick)\nvarip bool sent=false').replace(
        "if strategy.position_size>0", "if remote==100.25 and strategy.position_size>0")
    result = execute(service, config(service, source=source), "foreign-visibility")
    assert len(result["report"]["fills"]) == 2
    assert result["report"]["fills"][1]["event_time_ms"] < 120000


@pytest.mark.parametrize("closing", [False, True])
def test_bar_risk_halt_cancels_and_flattens_via_future_path_point(service, closing):
    source = (SOURCE % (",process_orders_on_close=true" if closing else "")).replace(
        "varip bool sent=false", "if false\n    strategy.risk.max_intraday_filled_orders(1)\nvarip bool sent=false")
    result = execute(service, config(service, source=source), "risk-path")
    report = result["report"]
    assert report["pine_risk_stops"]["blocked"]
    assert Decimal(report["pine_risk_stops"]["residual_position"]) == 0
    assert len(report["fills"]) == 2
    assert report["fills"][1]["event_time_ms"] > report["fills"][0]["event_time_ms"]
    assert report["pine_orders"]["open_entries"] == []


def test_queued_chart_uses_same_bar_callback_path_in_supervised_worker(runtime):
    from tests.test_chart_pine_orders import run_chart
    host, main = runtime
    report = run_chart(host, main, '''varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0 and barstate.ishistory and barstate.isconfirmed
    strategy.exit("X","L",stop=9.5,limit=10.5)
''', calc_on_order_fills=True)
    assert [Decimal(row["price"]) for row in report["fills"]] == [Decimal(10), Decimal("9.5")]
    assert report["fill_model"]["name"] == "PINE_OHLC_PATH_V1"
    assert report["strategy"]["pineExecution"]["fillCallbackCount"] == 2


def test_private_bar_path_flag_cannot_enable_a_source_without_fill_callbacks(service):
    value = config(service, source='//@version=6\nstrategy("Ordinary")\nplot(close)\n',
        pine_bar_path_contract="candlescope.pine-bar-path/1")
    record = service.create_run(value, idempotency_key="private-path", now_ms=3)
    frozen = json.loads(record["config_json"])
    assert "pine_bar_path_contract" not in frozen


def test_historical_bar_warmup_advances_script_state_without_submitting_orders(service):
    value = config(service, source=(SOURCE % "").replace("bar_index==0", "bar_index==2"))
    run = service.create_run(value, idempotency_key="bar-warmup", now_ms=3)
    provider = RecordingProvider()
    result = service.execute_bar_run(run["run_id"], events=bars(), provider=provider, now_ms=4, warmup_events=2,
        observation_market={"venue": "binance", "symbol": "BTCUSDT"})
    assert result["report"]["fills"][0]["event_time_ms"] == 180000
    assert result["report"]["strategy"]["pineExecution"]["barCount"] == 5
    assert provider.frames[0].sequence == 3
    assert result["report"]["cost_sensitivity"]["baseline_reexecution_verified"] is True
