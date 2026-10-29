"""Risk stops through installed Pine workers and the real chart Host matcher."""
import json
from decimal import Decimal

import pytest

from app.backtest.errors import BacktestError
from app.backtest.strategy.pine_engine import PineEngineProvider
from app.market_dataset.snapshot import MarketEvent
from tests.test_chart_pine_callbacks import service as service, pytestmark as pytestmark
from tests.test_chart_pine_orders import run_chart
from tests.test_native_backtests import runtime as runtime
from tests.test_backtest_dual_clock import _trade

DAY = 86_400_000


def source(rule, body, *, callbacks=False, closing=False):
    return ('//@version=6\nstrategy("Risk stops",pyramiding=4'
        + (',calc_on_order_fills=true' if callbacks else '')
        + (',process_orders_on_close=true' if closing else '')
        + ')\nif false\n    strategy.risk.' + rule + '\n' + body)


def config(host, text, *, tape=False, **overrides):
    revision = host.create_strategy_revision({"language": "PINE_ENGINE", "name": "Risk stops", "source_text": text})
    value = {"strategy_revision_id": revision["revision_id"], "dataset_id": "local-pine", "data_epoch": "epoch-20261019",
        "snapshot_hash": "sha256:snapshot", "fidelity_mode": "AGG_TRADE_EXECUTION" if tape else "BAR_APPROX",
        "source_event_kind": "AGG_TRADE" if tape else "BAR", "start_time_ms": 0, "end_time_ms": 300000,
        "symbol": "BTCUSDT", "exchange": "binance", "market_type": "usdm", "interval": "1m",
        "output_mode": "ORDER_INTENT", "parameters": {}, "initial_balance": "1000", "slippage_bps": "0", "taker_fee_bps": "0",
        "checkpoint_policy": "INTERVAL", "checkpoint_interval": 1}
    if tape:
        value.update(signal_clock="DERIVED_BAR_CLOSE", signal_interval="1m", execution_clock="NEXT_AGG_TRADE",
            bar_builder="TRADE_DERIVED_COMPLETE_BUCKETS_V1", timezone="UTC")
    value.update(overrides)
    host.smoke_strategy_revision(revision["revision_id"], value, now_ms=2)
    return value


def bars(prices):
    return tuple(MarketEvent(i+1,(i+1)*60000-1,"BARS", {"open_time_ms": i*60000,
        "close_time_ms": (i+1)*60000-1, **{key:str(p) for key in ("open","high","low","close")}, "volume":"100"})
        for i,p in enumerate(prices))


def execute(host, value, rows, *, key="risk"):
    run = host.create_run(value, idempotency_key=key, now_ms=3)
    fn = host.execute_dual_clock_run if value["fidelity_mode"] == "AGG_TRADE_EXECUTION" else host.execute_bar_run
    return fn(run["run_id"], events=rows, provider=PineEngineProvider(), now_ms=4,
        observation_market={"venue": "binance", "symbol": "BTCUSDT"})


def risk(result):
    return result["report"]["pine_risk_stops"]


def test_queued_chart_drawdown_cancels_script_orders_and_closes_actual_position(runtime):
    host, main = runtime
    body = '''if false
    strategy.risk.max_drawdown(10,strategy.cash)
if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if bar_index==4
    strategy.entry("pending",strategy.long,qty=2,limit=1)
if bar_index>=5
    strategy.order("halted",strategy.long,qty=2)
'''
    report = run_chart(host, main, body)
    assert [fill["sequence"] for fill in report["fills"]] == [2,7]
    assert [float(fill["qty"]) for fill in report["fills"]] == [2,2]
    stop = report["pine_risk_stops"]
    assert stop["blocked"] and not stop["flatten_requested"]
    assert stop["trips"][0]["function"] == "strategy.risk.max_drawdown"
    assert report["pine_orders"]["open_entries"] == []


@pytest.mark.parametrize("rule", ['max_drawdown(100,strategy.cash)', 'max_intraday_loss(100,strategy.cash)'])
def test_bar_market_updates_trip_stops_without_pending_orders_or_fill_recalculation(service, rule):
    text = source(rule, '''if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if bar_index==2
    strategy.entry("pending",strategy.long,qty=2,limit=1)
if bar_index>=3
    strategy.order("ignored",strategy.long,qty=2)
''')
    result = execute(service, config(service,text), bars((100,100,150,90,80)))
    assert [fill["sequence"] for fill in result["report"]["fills"]] == [2,5]
    assert Decimal(risk(result)["trips"][0]["peak"]) == 1100
    assert Decimal(risk(result)["residual_position"]) == 0


def test_filled_order_stop_during_forming_callbacks_uses_actual_future_print_capacity_and_restores(service):
    text = source('max_intraday_filled_orders(1)', '''if barstate.isconfirmed and bar_index==0
    strategy.entry("A",strategy.long,qty=2)
    strategy.entry("B",strategy.long,qty=2)
if not barstate.isconfirmed
    strategy.order("callback_ignored",strategy.long,qty=2)
''', callbacks=True)
    value = config(service,text,tape=True)
    rows = tuple(_trade(i+1,stamp,"100",qty) for i,(stamp,qty) in enumerate(
        ((1000,"100"),(60000,".5"),(70000,".25"),(80000,".25"),(120000,"100"),(180000,"100"))))
    baseline = execute(service,value,rows,key="clean")
    assert [float(fill["qty"]) for fill in baseline["report"]["fills"]] == [.5,.25,.25]
    assert [fill["event_time_ms"] for fill in baseline["report"]["fills"]] == [60000,70000,80000]
    assert len(risk(baseline)["trips"]) == 1
    run = service.create_run(value,idempotency_key="recover",now_ms=3)
    save = service.repository.save_checkpoint
    def interrupt(checkpoint):
        saved = save(checkpoint)
        if checkpoint["sequence"] == 2:
            raise KeyboardInterrupt("durable partial risk close")
        return saved
    service.repository.save_checkpoint = interrupt
    try:
        with pytest.raises(KeyboardInterrupt):
            service.execute_dual_clock_run(run["run_id"],events=rows,provider=PineEngineProvider(),now_ms=4,
                observation_market={"venue":"binance","symbol":"BTCUSDT"})
    finally:
        service.repository.save_checkpoint = save
    saved = json.loads(service.repository.latest_checkpoint(run["run_id"])["payload_json"])
    assert saved["planner"]["pine_risk_stops"]["flatten_requested"]
    assert service.requeue_interrupted_run(run["run_id"],expected_generation=1,now_ms=8)
    restored = service.execute_dual_clock_run(run["run_id"],events=rows,provider=PineEngineProvider(),now_ms=9,
        observation_market={"venue":"binance","symbol":"BTCUSDT"})
    for field in ("fills","orders","pine_risk_stops","pine_orders"):
        assert restored["report"][field] == baseline["report"][field]
    for field in ("decision_hash","fill_hash","ledger_hash","report_hash"):
        assert restored["result"][field] == baseline["result"][field]


@pytest.mark.parametrize("override", [{"exchange":"unknown"},{"market_type":"stock"},{"interval":"1w"}])
def test_windowed_stop_admission_requires_known_sessions_and_observed_daily_pnl(service, override):
    text = source('max_cons_loss_days(1)', 'strategy.entry("L",strategy.long,qty=2)')
    value = config(service,text, **override)
    with pytest.raises(BacktestError,match="FIDELITY_UNSUPPORTED"):
        service.create_run(value,idempotency_key="unknown-window",now_ms=3)


def shifted_bars(prices, start):
    return tuple(MarketEvent(row.sequence,row.event_time_ms+start,row.role,{**row.payload,
        "open_time_ms":row.payload["open_time_ms"]+start,"close_time_ms":row.payload["close_time_ms"]+start})
        for row in bars(prices))


def test_actual_pine_realized_loss_day_halts_at_the_next_utc_session(service):
    text = source('max_cons_loss_days(1)', '''if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if bar_index==2
    strategy.close_all()
if bar_index>=3
    strategy.order("pending",strategy.long,qty=2,limit=1)
''')
    start = DAY-240000
    value = config(service,text,start_time_ms=start,end_time_ms=DAY+180000)
    result = execute(service,value,shifted_bars((100,100,90,90,90,90,90),start))
    assert [fill["sequence"] for fill in result["report"]["fills"]] == [2,4]
    assert risk(result)["trips"][0]["consecutive_loss_days"] == 1
    assert risk(result)["trips"][0]["time_ms"] == DAY+59999
    assert risk(result)["blocked"] and risk(result)["actions"] == []


def test_actual_pine_intraday_loss_reopens_only_after_the_new_session(service):
    text = source('max_intraday_loss(100,strategy.cash)', '''if strategy.position_size==0
    strategy.entry("L",strategy.long,qty=2)
''')
    start = DAY-240000
    value = config(service,text,start_time_ms=start,end_time_ms=DAY+180000)
    result = execute(service,value,shifted_bars((100,100,50,50,50,50,50),start))
    assert [fill["sequence"] for fill in result["report"]["fills"]] == [2,4,6]
    assert len(risk(result)["trips"]) == 1 and not risk(result)["blocked"]
    assert Decimal(risk(result)["residual_position"]) == 2


def test_risk_trips_and_closes_are_independently_reexecuted_for_each_cost_scenario(service):
    from tests.test_pine_cost_sensitivity import config as cost_config, execute as cost_execute, scenarios
    text = source('max_drawdown(0.0225,strategy.cash)', '''if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
''')
    result = cost_execute(service,cost_config(service,text))
    rows = scenarios(result)
    assert rows["BASELINE"]["metrics"]["fill_count"] == 1
    assert float(rows["BASELINE"]["metrics"]["ending_position"]) == 2
    for name in ("COSTS_PLUS_25_PERCENT","COSTS_PLUS_50_PERCENT"):
        assert rows[name]["metrics"]["fill_count"] == 2
        assert float(rows[name]["metrics"]["ending_position"]) == 0
        assert rows[name]["hashes"]["fill"] != rows["BASELINE"]["hashes"]["fill"]
