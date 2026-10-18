"""Actual candidate engine + host BAR/print matching; no broker test doubles."""
import pytest
from tests.test_native_backtests import runtime, terminal, pytestmark
from tests.test_external_strategy_v2 import tape


SOURCE = '''//@version=6
strategy("Renko real execution")
r = ticker.renko(syminfo.tickerid, "Traditional", 3)
brick = request.security(r, timeframe.period, close)
previous = request.security(r, timeframe.period, close[1])
plot(brick)
plot(previous)
if bar_index == 3 and brick > previous
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 5 and brick < previous
    strategy.close("L")
'''
PYNE_SOURCE = '''strategy("Renko real execution")
r = ticker.renko(syminfo.tickerid, "Traditional", 3)
brick = request.security(r, timeframe.period, "close")
previous = request.security(r, timeframe.period, "close[1]")
plot(brick, "Brick")
plot(previous, "Previous")
strategy.entry_when((bar_index == 3) & (brick > previous), "L", strategy.long, qty=1)
strategy.close_when((bar_index == 5) & (brick < previous), "L")
'''


def graphic_at(series, index):
    if "values" in series:
        return series["values"][index]
    return next(point["value"] for point in series["data"] if point["time"] == index * 60)


@pytest.mark.parametrize("fidelity", ["BAR_APPROX", "TRADE_TAPE"])
@pytest.mark.parametrize("language,source", [("pine", SOURCE), ("pyne", PYNE_SOURCE)])
def test_synthetic_decisions_execute_at_real_market_prices(runtime, fidelity, language, source):
    host, payload = runtime
    config = {**payload, "language":language, "source":source, "execution_mode":"CANDLESCOPE",
        "execution_fidelity":fidelity,
        "host_settings":{"initial_balance":10000,"slippage_bps":0,"taker_fee_bps":0}}
    if fidelity == "TRADE_TAPE":
        config["execution_data"] = tape()
    record = terminal(host.native, host.native.create(config, "renko-real")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    result = record["result"]
    assert graphic_at(result["graphics"][0], 3) == 19
    assert graphic_at(result["graphics"][1], 3) == 16
    assert len(result["trades"]) == 2
    assert [float(row["price"]) for row in result["trades"]] == [20,5]
    assert float(result["trades"][0]["price"]) != graphic_at(result["graphics"][0], 3)
    assert [item["bar_index"] for item in result["raw_output"]["intent_history"]] == [3,5]
    assert result["account_authority"] == "candlescope"
    assert not result["raw_output"]["strategy_output"].get("strategy")
    assert float(result["closed_trades"][0]["profit"]) == -15
    if fidelity == "TRADE_TAPE":
        fills = result["trades"]
        assert [row["event_time_ms"] for row in fills] == [240000,360000]
        events = config["execution_data"]["events"]
        assert all(any(event["time_ms"] == row["event_time_ms"] and
                       float(event["payload"]["price"]) == float(row["price"])
                       for event in events) for row in fills)
