"""Alert rules on any builtin indicator output with explicit parameters."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.alerts.facade import AlertFacade
from app.alerts.indicator_requests import (
    ALIASES,
    builtin_output,
    indicator_field_key,
    parse_indicator_field,
    request_for,
)
from app.alerts.runtime import AlertRuntimeEngine
from app.alerts.validation import validate_alert_expression
from app.data_engine.data_manager.models import BarData
from app.indicator import create_engine, registry
from tests.test_alerts_runtime import FakeDataManager, _bar_event, _rule_payload

RSI7 = "ind:RSI:rsi:period=7,source=close"
TARGET = {"symbol": "BTCUSDT", "interval": "1m", "exchange": "binance", "marketType": "spot"}


def _leaf(left, right=None):
    return {"left": left, "comparator": ">", "right": right or {"type": "number", "value": 1}}


@pytest.mark.parametrize("name", ("MA", "EMA", "RSI", "ATR", "MACD", "BOLL", "VOL"))
def test_every_builtin_output_round_trips_through_its_canonical_key(name):
    spec = registry.get_spec(name)
    for output_id in spec.output_specs:
        output = builtin_output(name, {}, output_id)
        key = indicator_field_key(output)
        assert parse_indicator_field(key) == output
        validate_alert_expression(_leaf(key))


def test_aliases_are_the_default_parameter_keys():
    assert indicator_field_key(ALIASES["rsi"]) == "ind:RSI:rsi:period=14,source=close"
    assert indicator_field_key(ALIASES["macdHist"]) == "ind:MACD:hist:fast=12,signal=9,slow=26,source=close"
    assert indicator_field_key(ALIASES["ma20"]) == "ind:MA:ma:period=20,source=close"


def test_display_parameters_are_not_part_of_the_key():
    with pytest.raises(ValueError, match="Unsupported RSI parameter: color"):
        builtin_output("RSI", {"period": 7, "color": "#ffffff"}, "rsi")


@pytest.mark.parametrize("field, message", [
    ("ind:RSI:rsi:source=close,period=7", "not canonical"),
    ("ind:RSI:rsi:period=7", "not canonical"),
    ("ind:RSI:hist:period=7,source=close", "Unknown RSI output"),
    ("ind:RSI:rsi:period=1,source=close", "out of range"),
    ("ind:RSI:rsi:period=7.5,source=close", "must be an integer"),
    ("ind:RSI:rsi:period=7,source=vwap", "Unsupported RSI source"),
    ("ind:PINE:x:", "Unknown builtin indicator"),
    ("ind:RSI:rsi", "ind:<NAME>:<output>:<params>"),
])
def test_invalid_indicator_fields_are_rejected_with_the_reason(field, message):
    with pytest.raises(ValueError, match=message):
        validate_alert_expression(_leaf(field))
    with pytest.raises(ValueError, match=message):
        validate_alert_expression(_leaf("close", {"type": "indicator", "value": field}))


def test_a_rule_is_limited_to_one_numeric_query_of_three_outputs():
    four = [RSI7, "ind:EMA:ema:period=50,source=close", "ind:EMA:ema:period=200,source=close",
            "ind:ATR:atr:period=14"]
    with pytest.raises(ValueError, match="at most 3 indicator outputs"):
        validate_alert_expression({"op": "AND", "children": [_leaf(field) for field in four]})
    # An alias and its spelled-out key are one output, not two.
    validate_alert_expression({"op": "AND", "children": [
        _leaf("rsi"), _leaf("ind:RSI:rsi:period=14,source=close"), _leaf(RSI7), _leaf("ma20")]})
    request = request_for(TARGET, {"rsi", "ind:RSI:rsi:period=14,source=close", RSI7})
    assert len(request.outputs) == 2


def test_runtime_evaluates_a_parameterised_indicator_field(tmp_path: Path):
    closes = [100 + (index % 5) - (index % 3) for index in range(60)]
    seed = [BarData(time=index + 1, open=close, high=close, low=close, close=close, volume=1)
            for index, close in enumerate(closes)]
    engine = create_engine()
    try:
        expected = engine.compute("BTCUSDT", "1m", "spot", "RSI", {"period": 7, "source": "close"},
                                  [*seed, _bar_event(80, timestamp_ms=61_000).bar],
                                  exchange="binance").get_latest()["rsi"]
    finally:
        engine.stop()

    async def run():
        facade = AlertFacade(store_path=tmp_path / "alerts.json")
        payload = _rule_payload(maxTriggers=1)
        payload["expression"] = {"left": RSI7, "comparator": ">", "right": {"type": "number", "value": 0}}
        rule = facade.save_rule(payload)
        runtime = AlertRuntimeEngine(facade=facade, data_manager=FakeDataManager(seed))
        await runtime.start()
        try:
            return await runtime.evaluate_event(rule["id"], _bar_event(80, timestamp_ms=61_000))
        finally:
            await runtime.stop()

    emitted = asyncio.run(run())
    assert emitted is not None
    assert emitted["values"][RSI7] == pytest.approx(expected)
    # Trigger records keep the alias keys they always carried.
    assert {"rsi", "macdHist", "ma20"} <= set(emitted["values"])
