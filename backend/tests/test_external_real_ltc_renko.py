"""Original native-acceptance tape, replayed through actual installed engines."""
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.local_data.service import LocalImportOptions
from tests.test_native_backtests import runtime, terminal, pytestmark


FIXTURE = Path(__file__).with_name("fixtures") / "real_ltc_agg_trade_20261010_6m.json"


def source(language, synthetic):
    begin, end = (3, 4) if synthetic else (1, 3)
    if language == "pine":
        observe = '''r = ticker.renko(syminfo.tickerid, "Traditional", 0.005)
brick = request.security(r, timeframe.period, close)
previous = request.security(r, timeframe.period, close[1])
plot(brick)
plot(previous)
''' if synthetic else "plot(close)\n"
        return ('//@version=6\nstrategy("Real LTC input audit")\n' + observe
                + f'if bar_index == {begin}' + (' and brick > previous' if synthetic else '')
                + '\n    strategy.entry("R", strategy.long, qty=1)\n'
                + f'if bar_index == {end}' + (' and brick < previous' if synthetic else '')
                + '\n    strategy.close("R")\n')
    observe = '''r = ticker.renko(syminfo.tickerid, "Traditional", 0.005)
brick = request.security(r, timeframe.period, "close")
previous = request.security(r, timeframe.period, "close[1]")
plot(brick, "Brick")
plot(previous, "Previous")
''' if synthetic else 'plot(close, "Close")\n'
    return ('strategy("Real LTC input audit")\n' + observe
            + f'strategy.entry_when((bar_index == {begin})' + (' & (brick > previous)' if synthetic else '')
            + ', "R", strategy.long, qty=1)\n'
            + f'strategy.close_when((bar_index == {end})' + (' & (brick < previous)' if synthetic else '')
            + ', "R")\n')


@pytest.mark.parametrize("language", ["pine", "pyne"])
@pytest.mark.parametrize("synthetic", [False, True])
def test_original_real_tape_prices_and_closed_trade_statistics(runtime, tmp_path, language, synthetic):
    host, _ = runtime
    fixture = json.loads(FIXTURE.read_text())
    bars, execution = fixture["bars"], fixture["execution_data"]
    ids = [event["payload"]["source_sequence"] for event in execution["events"]]
    assert ids == list(range(428090935, 428091290))
    csv = tmp_path / "real-ltc.csv"
    columns = ["time", "open", "high", "low", "close", "volume"]
    csv.write_text(",".join(columns) + "\n" + "\n".join(
        ",".join(str(bar[key]) for key in columns) for bar in bars))
    manifest = host.local_data.import_csv(csv, LocalImportOptions(
        name="Real LTC Renko control", symbol="LTCUSDT", interval="1m", timestamp_unit="ms"))
    data = dict(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"],
                start_time_ms=bars[0]["time"], end_time_ms=bars[-1]["time"] + 59999, interval="1m")
    snapshot = host.preview_snapshot(**data)
    payload = {**data, "snapshot_hash": snapshot["snapshot_hash"], "language": language,
               "source": source(language, synthetic), "context": {"symbol": "LTCUSDT", "timeframe": "1"},
               "execution_mode": "CANDLESCOPE", "execution_fidelity": "TRADE_TAPE",
               "execution_data": execution,
               "host_settings": {"initial_balance": 10000, "slippage_bps": 1, "taker_fee_bps": 0}}
    record = terminal(host.native, host.native.create(payload, f"{language}-{synthetic}")["run_id"])
    assert record["state"] == "COMPLETED", record.get("error")
    result = record["result"]
    assert result["fidelity"] == "AGG_TRADE_TAPE"
    assert len(result["trades"]) == 2
    assert len(result["closed_trades"]) == 1
    begin, end = (3, 4) if synthetic else (1, 3)
    expected_prices = []
    for fill, decision, multiplier in zip(result["trades"], (begin, end),
                                          (Decimal("1.0001"), Decimal("0.9999")), strict=True):
        confirmed_at = bars[decision]["time"] + 60000
        real_event = next(event for event in execution["events"] if event["time_ms"] >= confirmed_at)
        assert fill["event_time_ms"] == real_event["time_ms"]
        expected = Decimal(real_event["payload"]["price"]) * multiplier
        assert Decimal(fill["price"]) == expected
        expected_prices.append(expected)
    expected_profit = expected_prices[1] - expected_prices[0]
    assert expected_profit == (Decimal("-0.052686") if synthetic else Decimal("0.007312"))
    assert Decimal(result["closed_trades"][0]["profit"]) == expected_profit
    assert Decimal(result["position"]["quote_balance"]) == Decimal(10000) + expected_profit
    assert Decimal(result["position"]["position_qty"]) == 0
    assert [item["bar_index"] for item in result["raw_output"]["intent_history"]] == [begin, end]
    assert not result["raw_output"]["strategy_output"].get("strategy")
    if synthetic:
        def values(line):
            if "values" in line:
                return line["values"]
            return [next((point["value"] for point in line["data"]
                          if point["time"] == bar["time"] / 1000), None) for bar in bars]
        assert values(result["graphics"][0]) == pytest.approx([None, None, None, 63.45, 63.41, 63.42])
        assert values(result["graphics"][1]) == pytest.approx([None, None, None, 63.445, 63.415, 63.41])
        assert expected_prices[0] != Decimal("63.45")
