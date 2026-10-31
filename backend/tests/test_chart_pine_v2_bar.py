import json
from dataclasses import replace
from decimal import Decimal as D

import pytest

from app.backtest.errors import BacktestError
from app.backtest.strategy.pine_engine import PineEngineProvider
from app.market_dataset.snapshot import MarketEvent
from app.simulation.execution_realism import PINE_BAR_PATH_SCENARIO
from tests.test_backtest_account_v2_m4 import rules
from tests.test_chart_pine_bar_callbacks import service as service, pytestmark as pytestmark, config as base_config, RecordingProvider
from tests.test_native_backtests import runtime as runtime
from tests.test_pine_v2_bar_kernel import numbered, mark


SOURCE = '''//@version=6
strategy("V2 path",calc_on_order_fills=true%s)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=7)
if strategy.position_size>0 and barstate.ishistory and barstate.isconfirmed
    strategy.exit("X","L",stop=9.5,limit=10.5)
'''


def bars():
    return tuple(MarketEvent(index + 1, (index + 1) * 60000 - 1, "BARS", dict(open_time_ms=index * 60000,
        close_time_ms=(index + 1) * 60000 - 1, open="10", high="11", low="9", close="10", volume="10")) for index in range(5))


def config(service, *, account="LINEAR_PERP_ONE_WAY_V1", source=None, closing=False, **extra):
    options = dict(execution_model_revision="EXECUTION_REALISM_V2", participation_rate=".5",
        bar_path_scenario=PINE_BAR_PATH_SCENARIO, account_model=account)
    if account == "LINEAR_PERP_ONE_WAY_V2":
        options.update(contract_data_mode="HISTORICAL_CONTRACT_V1", funding_mode="OFF", leverage="10")
    if account == "SPOT_CASH_V1":
        options["market_type"] = "spot"
    options.update(extra)
    return base_config(service, source=source or SOURCE % (",process_orders_on_close=true" if closing else ""), **options)


def execute(service, value, key, rows=None, provider=None, run=None):
    run = run or service.create_run(value, idempotency_key=key, now_ms=3)
    return service.execute_bar_run(run["run_id"], events=rows or bars(), provider=provider or PineEngineProvider(),
        now_ms=4, observation_market={"venue": "binance", "symbol": "BTCUSDT"})


@pytest.mark.parametrize("account", ["LINEAR_PERP_ONE_WAY_V1", "SPOT_CASH_V1", "LINEAR_PERP_ONE_WAY_V2"])
def test_actual_pine_callbacks_share_bar_capacity_and_reexecute_all_scenarios(service, account):
    rows = bars()
    if account == "LINEAR_PERP_ONE_WAY_V2":
        rows = numbered(rules(-2), mark(-1, 10), *rows)
    provider = RecordingProvider()
    result = execute(service, config(service, account=account), "capacity", rows, provider)
    report = result["report"]
    assert report["fill_model"]["name"] == "PINE_OHLC_PATH_V2"
    assert [D(fill["qty"]) for fill in report["fills"]] == [5, 2, 3, 4]
    fills = [frame for frame in provider.frames if frame.features["pineExecutionContext"]["trigger"] != "bar_close"]
    assert [frame.account_view["position_size"] for frame in fills] == [5, 7, 4, 0]
    assert report["pine_orders"]["open_entries"] == []
    assert report["cost_sensitivity"]["baseline_reexecution_verified"] is True
    scenarios = {row["name"]: row for row in report["cost_sensitivity"]["scenarios"]}
    assert scenarios["PARTICIPATION_DOWN_ONE_TIER"]["status"] == "COMPLETED"
    assert scenarios["LATENCY_PLUS_ONE_TIER"]["status"] == "NOT_APPLICABLE_BAR_CLOCK"


def test_gap_margin_repricing_reexecutes_cost_accounts_and_recovers_exactly(service):
    source = '''//@version=6
strategy("Margin repricing",calc_on_order_fills=true)
if bar_index==0
    strategy.entry("L",strategy.long,qty=50)
'''
    values = tuple(replace(row, payload={**row.payload, **({"open": "20", "high": "21", "low": "19", "close": "20"} if index >= 3 else {})})
                   for index, row in enumerate(bars()))
    rows = numbered(rules(-2), mark(-1, 10), values[0], mark(60000, 8), *values[1:])
    value = config(service, account="LINEAR_PERP_ONE_WAY_V2", source=source, initial_balance="100", taker_fee_bps="1")
    baseline = execute(service, value, "gap-full", rows)
    report = baseline["report"]
    assert [D(fill["qty"]) for fill in report["fills"]] == [5, 5]
    account = report["ledger"]["account"]
    assert D(account["position_qty"]) == 10 and D(account["frozen_order_margin"]) == 0
    assert D(account["equity"]) == D("79.99") and account["liquidation_state"] == "ACTIVE"
    assert any(event.get("reason") == "ACCOUNT_MARGIN_REPRICE_REJECTED" for event in report["order_events"])
    matrix = report["cost_sensitivity"]
    assert matrix["baseline_reexecution_verified"]
    scenarios = {row["name"]: row for row in matrix["scenarios"]}
    assert scenarios["BASELINE"]["hashes"]["fill"] == baseline["result"]["fill_hash"]
    for name in ("COSTS_PLUS_25_PERCENT", "COSTS_PLUS_50_PERCENT", "PARTICIPATION_DOWN_ONE_TIER"):
        assert scenarios[name]["status"] == "COMPLETED"
    assert scenarios["COSTS_PLUS_50_PERCENT"]["hashes"]["fill"] != baseline["result"]["fill_hash"]
    record = service.create_run(value, idempotency_key="gap-recovery", now_ms=3)
    save = service.repository.save_checkpoint
    def interrupt(checkpoint):
        result = save(checkpoint)
        if checkpoint["sequence"] == 3:
            raise KeyboardInterrupt("before gap cancellation")
        return result
    service.repository.save_checkpoint = interrupt
    try:
        with pytest.raises(KeyboardInterrupt):
            execute(service, value, "gap-recovery", rows, run=record)
    finally:
        service.repository.save_checkpoint = save
    assert service.requeue_interrupted_run(record["run_id"], expected_generation=1, now_ms=8)
    restored = execute(service, value, "gap-recovery", rows, run=record)
    for name in ("fills", "orders", "pine_orders", "ledger", "cost_sensitivity"):
        assert restored["report"][name] == report[name]
    for name in ("decision_hash", "fill_hash", "ledger_hash", "report_hash"):
        assert restored["result"][name] == baseline["result"][name]


@pytest.mark.parametrize("stamp,trigger", [(60000, "FILL"), (70000, "MARK_INDEX")])
def test_real_pine_observes_actual_v2_liquidation_after_distinct_primary_fill(service, stamp, trigger):
    source = '''//@version=6
strategy("Liquidation on path",calc_on_order_fills=true)
if bar_index==0
    strategy.entry("L",strategy.long,qty=50)
'''
    values = tuple(replace(row, payload={**row.payload, "open": "100", "high": "110", "low": "90", "close": "100", "volume": "100"}) for row in bars()[:3])
    rows = numbered(rules(-2), mark(-1, 100), values[0], mark(stamp, 80), *values[1:])
    provider = RecordingProvider()
    result = execute(service, config(service, account="LINEAR_PERP_ONE_WAY_V2", source=source, initial_balance="1000"), "settlement", rows, provider)
    report = result["report"]
    assert [D(fill["position_after"]) for fill in report["fills"]] == [50, 0]
    assert report["fills"][-1]["account_liquidation"]["trigger"] == trigger
    assert report["fills"][-1]["event_time_ms"] == stamp
    frames = [frame for frame in provider.frames if frame.features["pineExecutionContext"]["trigger"] == "order_fill"]
    assert [frame.account_view["position_size"] for frame in frames] == [50, 0]
    assert report["pine_orders"]["open_entries"] == []
    assert report["cost_sensitivity"]["baseline_reexecution_verified"] is True


def test_account_mark_and_funding_do_not_leak_backward_into_actual_pine_fill(service):
    source = '''//@version=6
strategy("As of mark",calc_on_order_fills=true)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=2)
if bar_index==1 and strategy.position_size>0 and strategy.openprofit!=0
    strategy.close("L")
'''
    rows = numbered(rules(-2), mark(-1, 10), bars()[0], mark(70000, 20),
        MarketEvent(1, 80000, "FUNDING", {"funding_rate": ".01", "period_id": "actual"}), *bars()[1:])
    provider = RecordingProvider()
    result = execute(service, config(service, account="LINEAR_PERP_ONE_WAY_V2", source=source, funding_mode="HISTORICAL_REQUIRED"), "asof", rows, provider)
    frames = [frame for frame in provider.frames if frame.features["pineExecutionContext"]["trigger"] == "order_fill"]
    assert frames[0].event_time_ms == 60000 and frames[0].account_view["openprofit"] == 0
    assert result["report"]["fills"][1]["event_time_ms"] >= 120000
    assert D(result["report"]["ledger"]["account"]["cumulative_funding"]) == D("-.4")


@pytest.mark.parametrize("auxiliary", [False, True])
def test_v2_path_durable_recovery_reconstructs_capacity_and_account_without_duplicate_fills(service, auxiliary):
    value = config(service, account="LINEAR_PERP_ONE_WAY_V2")
    rows = numbered(rules(-2), mark(-1, 10), bars()[0], mark(70000, 10), *bars()[1:])
    baseline = execute(service, value, "baseline", rows)
    record = service.create_run(value, idempotency_key="interrupted", now_ms=3)
    original = service.repository.save_checkpoint
    def save(checkpoint):
        result = original(checkpoint)
        if checkpoint["sequence"] == 3:
            raise KeyboardInterrupt("durable preceding bar")
        return result
    class Interrupted(PineEngineProvider):
        def step(self, frame):
            if frame.features["pineExecutionContext"]["trigger"] == "order_fill":
                raise KeyboardInterrupt("after partial fill, before complete bar")
            return super().step(frame)
    if not auxiliary:
        service.repository.save_checkpoint = save
    try:
        with pytest.raises(KeyboardInterrupt):
            execute(service, value, "interrupted", rows, Interrupted() if auxiliary else None, record)
    finally:
        service.repository.save_checkpoint = original
    state = json.loads(service.repository.latest_checkpoint(record["run_id"])["payload_json"])
    assert state["sequence"] == 3 and state["observed"] == 1
    assert state["engine"]["fills"] == []
    assert service.requeue_interrupted_run(record["run_id"], expected_generation=1, now_ms=8)
    result = execute(service, value, "interrupted", rows, run=record)
    for key in ("fills", "orders", "pine_orders", "cost_sensitivity"):
        assert result["report"][key] == baseline["report"][key]
    for key in ("decision_hash", "fill_hash", "ledger_hash", "report_hash"):
        assert result["result"][key] == baseline["result"][key]


def test_new_path_cannot_silently_relabel_an_explicit_worst_case_scenario(service):
    value = config(service, bar_path_scenario="OHLC_WORST_CASE_STOP_FIRST_V1")
    with pytest.raises(BacktestError, match="bar_path_scenario"):
        service.create_run(value, idempotency_key="wrong-scenario", now_ms=3)


def test_v2_margin_account_can_use_full_fills_without_a_participation_proxy(service):
    rows = numbered(rules(-2), mark(-1, 10), *bars())
    result = execute(service, config(service, account="LINEAR_PERP_ONE_WAY_V2", execution_model_revision=None,
        bar_path_scenario=None), "margin-only", rows)
    assert [D(row["qty"]) for row in result["report"]["fills"]] == [7, 7]
    assert result["report"]["fill_model"]["mark_authority"] == "HISTORICAL_MARK_INDEX"
    assert result["report"]["fill_model"]["capacity_policy"] == "UNCAPPED"


def test_actual_queued_chart_selects_new_v2_model_and_freezes_its_scenario(runtime):
    from tests.test_chart_pine_orders import run_chart
    host, main = runtime
    report = run_chart(host, main, '''varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=7)
if strategy.position_size>0
    strategy.exit("X","L",stop=9.5,limit=10.5)
''', calc_on_order_fills=True, execution_model_revision="EXECUTION_REALISM_V2", participation_rate=".05",
        bar_path_scenario=PINE_BAR_PATH_SCENARIO)
    assert report["fill_model"]["name"] == "PINE_OHLC_PATH_V2"
    assert report["fill_model"]["bar_path_scenario"] == PINE_BAR_PATH_SCENARIO
    assert [D(row["qty"]) for row in report["fills"]] == [5, 2, 3, 4]
    assert report["cost_sensitivity"]["baseline_reexecution_verified"] is True


@pytest.mark.parametrize("materialized", [False, True])
def test_resumed_row_ceiling_counts_bars_instead_of_account_source_ordinals(service, materialized):
    service.settings = replace(service.settings, max_bar_rows=2)
    value = config(service, account="LINEAR_PERP_ONE_WAY_V2")
    rows = numbered(rules(-2), mark(-1, 10), bars()[0], mark(70000, 10), bars()[1])
    def events():
        return rows if materialized else iter(rows)
    def execute_run(record):
        return service.execute_bar_run(record["run_id"], events=events(), provider=PineEngineProvider(), now_ms=4,
            observation_market={"venue": "binance", "symbol": "BTCUSDT"})
    baseline = execute_run(service.create_run(value, idempotency_key="budget-baseline", now_ms=3))
    record = service.create_run(value, idempotency_key="budget-interrupted", now_ms=3)
    original = service.repository.save_checkpoint
    def save(checkpoint):
        result = original(checkpoint)
        if checkpoint["sequence"] == 3:
            raise KeyboardInterrupt("first bar with three source events")
        return result
    service.repository.save_checkpoint = save
    try:
        with pytest.raises(KeyboardInterrupt):
            execute_run(record)
    finally:
        service.repository.save_checkpoint = original
    state = json.loads(service.repository.latest_checkpoint(record["run_id"])["payload_json"])
    assert state["sequence"] == 3 and state["observed"] == 1
    assert service.requeue_interrupted_run(record["run_id"], expected_generation=1, now_ms=8)
    result = execute_run(record)
    for key in ("fills", "orders", "pine_orders", "cost_sensitivity"):
        assert result["report"][key] == baseline["report"][key]
    for key in ("decision_hash", "fill_hash", "ledger_hash", "report_hash"):
        assert result["result"][key] == baseline["result"][key]
