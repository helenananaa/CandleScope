"""Actual isolated Pine + real matching + resumable special-chart event clocks."""

import pytest
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_external_replay import payload
from tests.test_native_replay import settle


def source(ticks, fills):
    return f"""//@version=6
strategy("Special events",calc_on_every_tick={str(ticks).lower()},calc_on_order_fills={str(fills).lower()})
varip bool entered=false
varip bool exited=false
if not entered
    strategy.entry("L",strategy.long,qty=1)
    entered:=true
if strategy.position_size>0 and not exited
    strategy.close("L")
    exited:=true
plot(close)
plot(bar_index)
plot(time)
plot(strategy.position_size)
"""


@pytest.mark.parametrize(
    "transform", ["heikin-ashi", "renko", "point-and-figure", "kagi", "line-break"]
)
@pytest.mark.parametrize(
    "mode,ticks,fills",
    [
        ("BAR_APPROX", False, True),
        ("TRADE_TAPE", False, True),
        ("TRADE_TAPE", True, False),
        ("TRADE_TAPE", True, True),
    ],
)
def test_native_event_runs_real_prices_replay_and_checkpoint(
    runtime, transform, mode, ticks, fills
):
    host, main = runtime
    value = payload(main, mode, fills)
    value.update(
        source=source(ticks, fills),
        signal_chart={"transform": transform, "box_size": 2, "min_tick": 1, "reversal_amount": 2},
    )
    origin = terminal(host.native, host.native.create(value, "chart-events")["run_id"])
    assert origin["state"] == "COMPLETED", origin
    result = origin["result"]
    assert result["account_authority"] == "candlescope"
    assert result["evaluation_contract"] == "candlescope.chart-signal-events/1"
    assert result["trades"], result
    if mode == "TRADE_TAPE":
        real_prices = {
            float(row["payload"]["price"])
            for row in value["execution_data"]["events"]
            if row["role"] == "TRADES"
        }
        assert all(float(row["price"]) in real_prices for row in result["trades"])
    replay = host.native.replay
    record = replay.create(origin["run_id"])
    replay.command(record["replay_id"], record["revision"], "seek", 5)
    record = settle(replay, record["replay_id"])
    checkpoint = replay.snapshot(record["replay_id"], record["revision"])
    replay.command(record["replay_id"], checkpoint["revision"], "step")
    advanced = settle(replay, record["replay_id"])
    restored = replay.restore(
        record["replay_id"], advanced["revision"], checkpoint["snapshots"][0]["snapshot_id"]
    )
    assert restored["result"] == record["result"]
    replay.command(record["replay_id"], restored["revision"], "seek", record["total"])
    final = settle(replay, record["replay_id"])
    assert final["result"] == result


@pytest.mark.parametrize("mode", ["TRADE_TAPE", "BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"])
def test_real_account_mark_and_book_owners_survive_chart_event_replay(runtime, mode):
    from tests.test_pine_workbench_v2_print import config

    host, main = runtime
    value = config(main, mode, True)
    value.update(
        source=source(True, True), signal_chart={"transform": "renko", "box_size": 2, "min_tick": 1}
    )
    origin = terminal(host.native, host.native.create(value, "chart-v2")["run_id"])
    assert origin["state"] == "COMPLETED", origin
    assert origin["result"]["position"]["mark_price"] == "13"
    assert origin["result"]["position"]["funding_event_count"] == 1
    replay = host.native.replay
    record = replay.create(origin["run_id"])
    replay.command(record["replay_id"], record["revision"], "seek", 2)
    record = settle(replay, record["replay_id"])
    checkpoint = replay.snapshot(record["replay_id"], record["revision"])
    replay.command(record["replay_id"], checkpoint["revision"], "seek", record["total"])
    record = settle(replay, record["replay_id"])
    assert record["result"] == origin["result"]


def test_source_fill_setting_is_enabled_by_default_for_special_charts(runtime):
    host, main = runtime
    value = payload(main, "TRADE_TAPE", False)
    value.update(
        source=source(False, True),
        signal_chart={"transform": "renko", "box_size": 2, "min_tick": 1},
    )
    record = terminal(host.native, host.native.create(value, "auto-fill")["run_id"])
    assert record["state"] == "COMPLETED", record
    assert record["result"]["evaluation_contract"] == "candlescope.chart-signal-events/1"


@pytest.mark.parametrize("mode", ["BAR_APPROX", "TRADE_TAPE"])
@pytest.mark.parametrize("transform", ["heikin-ashi", "renko", "kagi"])
def test_closing_fills_keep_real_closing_owner_and_callback_order(runtime, mode, transform):
    host, main = runtime
    value = payload(main, mode, True)
    value.update(
        source=source(mode != "BAR_APPROX", True).replace(
            'strategy("Special events",', 'strategy("Special events",process_orders_on_close=true,'
        ),
        signal_chart={"transform": transform, "box_size": 2, "min_tick": 1},
    )
    result = terminal(host.native, host.native.create(value, "chart-close")["run_id"])
    assert result["state"] == "COMPLETED", result.get("error")
    assert result["result"]["trades"]


def test_historical_account_bar_capacity_and_event_replay_remain_shared(runtime):
    from tests.test_pine_workbench_v2_bar import config

    host, main = runtime
    value = config(main)
    value.update(
        source=source(False, True),
        signal_chart={"transform": "renko", "box_size": 2, "min_tick": 1},
    )
    result = terminal(host.native, host.native.create(value, "chart-bar-v2")["run_id"])
    assert result["state"] == "COMPLETED", result.get("error")
    assert result["result"]["fill_model"] == "PINE_OHLC_PATH_V2"
    replay = host.native.replay
    record = replay.create(result["run_id"])
    replay.command(record["replay_id"], record["revision"], "seek", 2)
    record = settle(replay, record["replay_id"])
    replay.command(record["replay_id"], record["revision"], "seek", record["total"])
    record = settle(replay, record["replay_id"])
    assert record["result"] == result["result"]


def test_unconfirmed_ha_pine_state_rolls_back_while_varip_keeps_observations(runtime):
    host, main = runtime
    value = payload(main, "TRADE_TAPE", False)
    value.update(
        source="""//@version=6
strategy("Rollback",calc_on_every_tick=true)
var int ordinary=0
varip int persistent=0
ordinary+=1
persistent+=1
plot(ordinary)
plot(persistent)
""",
        signal_chart={"transform": "heikin-ashi"},
    )
    result = terminal(host.native, host.native.create(value, "chart-rollback")["run_id"])
    assert result["state"] == "COMPLETED", result.get("error")
    plots = result["result"]["raw_output"]["strategy_output"]["plots"]
    assert plots[0]["values"] == list(range(1, 11))
    assert plots[1]["values"][-1] > 10


def test_script_clock_uses_observed_milliseconds_without_fabricating_brick_timestamps(runtime):
    host, main = runtime
    value = payload(main, "TRADE_TAPE", False)
    value.update(
        source='//@version=6\nstrategy("ms",calc_on_every_tick=true)\nplot(time)',
        signal_chart={"transform": "renko", "box_size": 2, "min_tick": 1},
    )
    for i, row in enumerate(value["execution_data"]["events"]):
        if row["time_ms"] < 60000:
            row["time_ms"] = 1001 + i
    result = terminal(host.native, host.native.create(value, "native-milliseconds")["run_id"])
    assert result["state"] == "COMPLETED", result.get("error")
    assert result["result"]["raw_output"]["strategy_output"]["plots"][0]["values"][0] == 1001


def test_no_confirmed_column_checkpoint_does_not_invent_strategy_observations(runtime):
    host, main = runtime
    value = payload(main, "TRADE_TAPE", True)
    value.update(
        source=source(False, True),
        signal_chart={"transform": "renko", "box_size": 1000, "min_tick": 1},
    )
    result = terminal(host.native, host.native.create(value, "native-no-events")["run_id"])
    assert result["state"] == "COMPLETED", result.get("error")
    assert result["result"]["trades"] == []
    replay = host.native.replay
    record = replay.create(result["run_id"])
    replay.command(record["replay_id"], record["revision"], "seek", 5)
    record = settle(replay, record["replay_id"])
    saved = replay.snapshot(record["replay_id"], record["revision"])
    replay.command(record["replay_id"], saved["revision"], "seek", record["total"])
    record = settle(replay, record["replay_id"])
    assert record["result"] == result["result"]


def test_real_tick_mode_requires_trade_data_instead_of_ohlc_approximation(runtime):
    from app.backtest.errors import BacktestError

    host, main = runtime
    value = payload(main, "BAR_APPROX", True)
    value.update(source=source(True, True), signal_chart={"transform": "renko"})
    with pytest.raises(BacktestError, match="requires frozen trade data"):
        host.native.create(value, "needs-real-prints")


@pytest.mark.parametrize("mode", ["BAR_APPROX", "TRADE_TAPE"])
def test_standard_requested_symbol_keeps_real_dataset_and_observed_cutoff(runtime, mode):
    from tests.test_native_additional_inputs import additional

    host, main = runtime
    value = payload(main, mode, True)
    value.update(
        source=source(mode != "BAR_APPROX", True)
        + '\nremote=request.security("BINANCE:BTCUSDT","1",close)\nplot(remote)',
        signal_chart={"transform": "heikin-ashi"},
        contexts=[
            {
                **additional(host, "real-request", "BTCUSDT", "1m", 60000, list(range(100, 110))),
                "symbol": "BINANCE:BTCUSDT",
                "timeframe": "1",
            }
        ],
    )
    origin = terminal(host.native, host.native.create(value, "chart-real-request")["run_id"])
    assert origin["state"] == "COMPLETED", origin.get("error")
    plots = origin["result"]["raw_output"]["strategy_output"]["plots"]
    assert plots[-1]["values"] == list(range(100, 110))
    assert plots[0]["values"] != plots[-1]["values"]
    replay = host.native.replay
    record = replay.create(origin["run_id"])
    replay.command(record["replay_id"], record["revision"], "seek", 2)
    record = settle(replay, record["replay_id"])
    with host.native.lock:
        state = replay._host_state(record["replay_id"])
    clock = state["clock"]
    assert all(not item["bars"] for item in clock["stream"]["opening"]["contexts"])
    for group in clock["groups"]:
        for observation in group:
            evaluation = observation["evaluation"]
            assert all(
                update["available_at_ms"] <= evaluation["event_time_ms"] <= 119999
                for update in evaluation["request_updates"]
            )
    assert clock["request_feed"]["cursors"] == [2]
    saved = replay.snapshot(record["replay_id"], record["revision"])
    replay.command(record["replay_id"], saved["revision"], "seek", record["total"])
    record = settle(replay, record["replay_id"])
    restored = replay.restore(
        record["replay_id"], record["revision"], saved["snapshots"][0]["snapshot_id"]
    )
    replay.command(record["replay_id"], restored["revision"], "seek", record["total"])
    assert settle(replay, record["replay_id"])["result"] == origin["result"]
