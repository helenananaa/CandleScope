from decimal import Decimal as D
from copy import deepcopy
import json
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.backtests import router
from app.backtest.errors import BacktestError
from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_pine_bar_workbench import config as base_config
from tests.test_native_replay import settle
from tests.test_backtest_account_v2_m4 import rules


def config(main, *, model="LINEAR_PERP_ONE_WAY_V2", closing=False):
    value = base_config(main, closing)
    value.update(account_model=model, execution_model_revision="EXECUTION_REALISM_V2", participation_rate=.05)
    value["source"] = '''//@version=6
strategy("Workbench V2",calc_on_order_fills=true%s)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=7)
if strategy.position_size>0
    strategy.exit("X","L",stop=9.5,limit=10.5)
plot(strategy.position_size)
''' % (",process_orders_on_close=true" if closing else "")
    if model == "SPOT_CASH_V1":
        value["market_type"] = "spot"
    if model == "LINEAR_PERP_ONE_WAY_V2":
        value["context"] = {**value["context"], "metadata": {"priceTickSize": "1/10"}}
        value.update(leverage=10, account_data={"symbol": "BTCUSDT", "events": [
            {"time_ms": -2, "role": "INSTRUMENT_RULES", "payload": dict(rules(-2).payload)},
            {"time_ms": -1, "role": "MARK_INDEX", "payload": {"mark_price": "10", "index_price": "10"}}],
            "provenance": {"fixture": "frozen-account"}})
    return value


@pytest.mark.parametrize("model", ["LINEAR_PERP_ONE_WAY_V1", "SPOT_CASH_V1", "LINEAR_PERP_ONE_WAY_V2"])
def test_actual_workbench_v2_bar_shares_capacity_and_account_feedback(runtime, model):
    host, main = runtime
    record = terminal(host.native, host.native.create(config(main, model=model), "v2-capacity")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    result = record["result"]
    assert result["fill_model"] == "PINE_OHLC_PATH_V2"
    assert [D(row["qty"]) for row in result["trades"]] == [5, 2, 3, 4]
    groups = result["raw_output"]["execution_schedule"]
    frames = [row["evaluation"]["account"] for group in groups for row in group if row["context"]["trigger"] == "order_fill"]
    assert [row["position_size"] for row in frames] == [5, 7, 4, 0]
    assert result["account_model"] == model
    assert D(result["position"]["position_qty"]) == 0


@pytest.mark.parametrize("closing", [False, True])
def test_workbench_v2_snapshot_restore_matches_full_frozen_endpoint(runtime, closing):
    host, main = runtime
    record = terminal(host.native, host.native.create(config(main, closing=closing), "v2-recovery")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    replay = host.native.replay
    created = replay.create(record["run_id"])
    key = created["replay_id"]
    def seek(target):
        replay.command(key, replay.get(key)["revision"], "seek", target)
        value = settle(replay, key)
        assert value.get("error") is None, value
        return value
    first = seek(1)
    saved = replay.snapshot(key, first["revision"])["snapshots"][0]["snapshot_id"]
    third = seek(3)
    replay.restore(key, third["revision"], saved)
    assert seek(3)["result"] == third["result"]
    assert seek(created["total"])["result"] == record["result"]


@pytest.mark.parametrize("stamp,trigger", [(60000, "FILL"), (70000, "MARK_INDEX")])
def test_workbench_v2_publishes_distinct_actual_liquidation_callback(runtime, stamp, trigger):
    host, main = runtime
    value = config(main)
    value["host_settings"]["initial_balance"] = 100
    value["participation_rate"] = .5
    value["source"] = '''//@version=6
strategy("Workbench liquidation",calc_on_order_fills=true)
if bar_index==0
    strategy.entry("L",strategy.long,qty=50)
'''
    value["account_data"]["events"].append({"time_ms": stamp, "role": "MARK_INDEX",
        "payload": {"mark_price": "8", "index_price": "8"}})
    record = terminal(host.native, host.native.create(value, "v2-liquidation")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    fills = record["result"]["trades"]
    assert [D(row["position_after"]) for row in fills] == [50, 0]
    assert fills[-1]["account_liquidation"]["trigger"] == trigger
    assert fills[-1]["event_time_ms"] == stamp
    frames = [row for group in record["result"]["raw_output"]["execution_schedule"] for row in group
              if row["context"]["trigger"] == "order_fill"]
    assert [row["evaluation"]["account"]["position_size"] for row in frames] == [50, 0]


def test_workbench_v2_http_freezes_funding_and_provenance(runtime):
    host, main = runtime
    value = config(main)
    value["funding_mode"] = "HISTORICAL_REQUIRED"
    value["account_data"]["events"].append({"time_ms": 70000, "role": "FUNDING",
        "payload": {"funding_rate": ".01", "period_id": "fund-1"}})
    app = FastAPI()
    app.state.backtest_runtime = host
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/backtests/external/runs", json=value, headers={"Idempotency-Key": "http-v2"})
        assert response.status_code == 200, response.text
        record = terminal(host.native, response.json()["run_id"])
        assert record["state"] == "COMPLETED", record.get("error")
        account = record["result"]["position"]
        assert D(account["cumulative_funding"]) == D("-.5")
        assert record["result"]["raw_output"]["account_provenance"] == {"fixture": "frozen-account"}


def test_workbench_v2_source_checkpoint_and_future_tape_are_bound(runtime):
    from app.backtest.external import _run_external_host
    from app.backtest.external_replay import validate_state
    from app.backtest.native import digest
    host, main = runtime
    record = terminal(host.native, host.native.create(config(main), "source-cursor")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    wire = json.loads(host.native.db.execute("SELECT wire FROM native_inputs WHERE id=?", (record["run_id"],)).fetchone()[0])
    result, state = _run_external_host(record["runtime_launch"], wire, host.native.runner, threading.Event(), target=2)
    assert "account_events" not in state["last_request"]
    changed = deepcopy(state)
    changed["clock"]["source_sequence"] += 1
    changed["kernel"]["pine_chart_bar"]["sequence"] += 1
    changed["checksum"] = digest({k: v for k, v in changed.items() if k != "checksum"})
    with pytest.raises(BacktestError, match="source cursor"):
        validate_state(wire, changed)
    future = deepcopy(wire)
    future["account_events"].append({"time_ms": 500000, "role": "MARK_INDEX", "payload": {"mark_price": "20", "index_price": "20"}})
    prefix, _ = _run_external_host(record["runtime_launch"], future, host.native.runner, threading.Event(), target=2)
    assert prefix == result


def test_v2_trailing_prices_use_actual_account_rules_instead_of_generic_host_tick(runtime):
    host, main = runtime
    value = config(main)
    value["host_settings"]["price_tick"] = .001
    value["participation_rate"] = .5
    value["source"] = '''//@version=6
strategy("Historical tick",calc_on_order_fills=true)
if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0
    strategy.exit("T","L",trail_points=5,trail_offset=2)
'''
    record = terminal(host.native, host.native.create(value, "historical-account-tick")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    assert [D(row["price"]) for row in record["result"]["trades"]] == [D(10), D("10.8")]


@pytest.mark.parametrize("change", ["missing", "late", "symbol", "order", "multiplier", "tick", "profile"])
def test_workbench_v2_invalid_inputs_fail_before_matching(runtime, change):
    host, main = runtime
    value = config(main)
    if change == "missing":
        value.pop("account_data")
    elif change == "late":
        value["account_data"]["events"][1]["time_ms"] = 60000
    elif change == "symbol":
        value["account_data"]["symbol"] = "ETHUSDT"
    elif change == "order":
        value["account_data"]["events"].reverse()
    elif change == "multiplier":
        value["account_data"]["events"][0]["payload"]["contract_multiplier"] = "5"
    elif change == "tick":
        value["context"]["metadata"]["priceTickSize"] = "1/4"
    else:
        value["fill_recalculation"] = False
        value["source"] = '//@version=6\nstrategy("No callbacks")\nstrategy.entry("L",strategy.long,qty=1)'
    with pytest.raises(BacktestError):
        host.native.create(value, "invalid-v2")
