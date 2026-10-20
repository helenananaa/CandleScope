from decimal import Decimal

import pytest

from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_external_replay import payload
from tests.test_native_replay import settle


def config(main, closing=False):
    value = payload(main, "BAR_APPROX", True)
    value["host_settings"].update(taker_fee_bps=0)
    value["source"] = '''//@version=6
strategy("BAR callbacks", calc_on_order_fills=true%s)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0
    strategy.exit("X","L",limit=strategy.position_avg_price+0.5,stop=strategy.position_avg_price-0.5)
plot(strategy.position_size)
plot(barstate.ishistory ? 1 : 0)
plot(barstate.isconfirmed ? 1 : 0)
''' % (",process_orders_on_close=true" if closing else "")
    return value


@pytest.mark.parametrize("closing", [False, True])
def test_actual_bar_fills_drive_historical_schedule_and_account(runtime, closing):
    host, main = runtime
    record = terminal(host.native, host.native.create(config(main, closing), "bar-callback") ["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    report = record["result"]
    assert report["fill_model"] == "PINE_OHLC_PATH_V1"
    trades = report["trades"]
    assert [row["script_order_id"] for row in trades] == ["L", "X"]
    assert trades[0]["event_time_ms"] == (59999 if closing else 60000)
    assert trades[1]["event_time_ms"] > trades[0]["event_time_ms"]
    assert Decimal(trades[1]["price"]) == Decimal("9.5")
    raw = report["raw_output"]
    assert raw["pine_bar_path"]["physical_tape"] is False
    groups = raw["execution_schedule"]
    assert all(row["context"]["bar_state"] == "historical" for group in groups for row in group)
    assert all(row["context"]["is_new"] for group in groups for row in group)
    fills = [row for group in groups for row in group if row["context"]["trigger"] in {"order_fill", "closing_fill"}]
    assert [row["evaluation"]["account"]["position_size"] for row in fills] == [2, 0]
    assert all(row["evaluation"]["bar"]["high"] == 11 for row in fills)
    assert all(value == 1 for value in report["graphics"][1]["values"])
    assert all(value == 1 for value in report["graphics"][2]["values"])
    if closing:
        assert [row["context"]["trigger"] for row in groups[0]] == ["bar_close", "closing_fill"]


def test_bar_path_snapshot_restore_reproduces_actual_endpoint(runtime):
    host, main = runtime
    origin = terminal(host.native, host.native.create(config(main), "bar-replay")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    replay = host.native.replay
    created = replay.create(origin["run_id"])
    key = created["replay_id"]
    def seek(target):
        replay.command(key, replay.get(key)["revision"], "seek", target)
        value = settle(replay, key)
        assert value.get("error") is None, value
        return value
    first = seek(1)
    snapshot = replay.snapshot(key, first["revision"])["snapshots"][0]["snapshot_id"]
    second = seek(3)
    replay.restore(key, second["revision"], snapshot)
    assert seek(3)["result"] == second["result"]
    assert seek(created["total"])["result"] == origin["result"]


def test_bar_trailing_stop_uses_activation_then_actual_intrabar_watermark(runtime):
    host, main = runtime
    value = config(main)
    value["host_settings"]["price_tick"] = ".1"
    value["source"] = '''//@version=6
strategy("BAR trailing",calc_on_order_fills=true)
if bar_index==0
    strategy.entry("L",strategy.long,qty=2)
if strategy.position_size>0
    strategy.exit("T","L",trail_points=5,trail_offset=2)
'''
    record = terminal(host.native, host.native.create(value, "bar-trailing")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    assert [Decimal(row["price"]) for row in record["result"]["trades"]] == [Decimal(10), Decimal("10.8")]


@pytest.mark.parametrize("market", ["spot", "usdm"])
def test_bar_callbacks_keep_fees_and_actual_account_authority(runtime, market):
    host, main = runtime
    value = config(main)
    value["market_type"] = market
    value["host_settings"].update(taker_fee_bps=10)
    record = terminal(host.native, host.native.create(value, "bar-fees")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    report = record["result"]
    assert [Decimal(row["fee"]) for row in report["trades"]] == [Decimal(".02"), Decimal(".019")]
    assert Decimal(report["position"]["position_qty"]) == 0
    assert report["account_model"] == ("SPOT_CASH_V1" if market == "spot" else "LINEAR_PERP_ONE_WAY_V1")


def test_historical_fill_requests_use_final_bar_visibility_not_synthetic_watermark(runtime):
    from tests.test_native_additional_inputs import additional
    host, main = runtime
    value = config(main)
    value["contexts"] = [{**additional(host, "bar-foreign", "ETHUSDT", "2m", 120000, [100, 200, 300, 400, 500]),
        "symbol": "BINANCE:ETHUSDT", "timeframe": "2", "metadata": {"priceTickSize": ".25"}}]
    value["source"] += '\nplot(request.security("BINANCE:ETHUSDT","2",close))\n'
    record = terminal(host.native, host.native.create(value, "bar-foreign")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    group = record["result"]["raw_output"]["execution_schedule"][1]
    assert group[0]["context"]["trigger"] == "order_fill"
    assert group[0]["evaluation"]["event_time_ms"] == 60000
    assert all([row["time"] for row in item["evaluation"]["request_data"][0]["bars"]] == [0] for item in group)
    assert record["result"]["graphics"][3]["values"][1] == 100
