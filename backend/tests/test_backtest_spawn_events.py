import pickle
from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.backtest import spawn_events
from app.backtest.spawn_events import pack_events, _PackedEvents
from app.market_dataset.snapshot import MarketEvent


def test_compact_roundtrip_preserves_values_types_and_internal_aliases():
    payload = {"close": "1.000", "extra": "中文\x7f\ud800", "n": 2**100, "flag": True, "none": None, "float": 1e-12}
    first = MarketEvent(1, 60000, "BARS", payload)
    second = MarketEvent(2, 120000, "BARS", payload)
    events = (first, second, first)
    actual = pickle.loads(pickle.dumps(pack_events(events)))
    assert actual == events
    assert type(actual) is tuple and all(type(event) is MarketEvent for event in actual)
    assert actual[0] is actual[2]
    assert actual[0].payload is actual[1].payload
    assert actual[0].payload is not payload


@pytest.mark.parametrize("columnar", ["0", "1"])
def test_non_builtin_values_keep_original_pickle(monkeypatch, columnar):
    monkeypatch.setenv("BACKTEST_COLUMNAR_SPAWN_ENABLED", columnar)
    events = (MarketEvent(1, 1, "BARS", {"close": Decimal("1.2")}),)
    packed = pack_events(events)
    assert packed.__reduce__()[1][0] is events
    assert pickle.loads(pickle.dumps(packed)) == events


@pytest.mark.parametrize("value", [{"nested": 1}, [1, 2], (1, "2"), b"x", 1.5j])
def test_nested_builtin_values_round_trip_exactly(monkeypatch, value):
    monkeypatch.setenv("BACKTEST_COLUMNAR_SPAWN_ENABLED", "0")
    events = (MarketEvent(1, 1, "BARS", {"close": value}),)
    assert pack_events(events).__reduce__()[1][0] is events
    monkeypatch.setenv("BACKTEST_COLUMNAR_SPAWN_ENABLED", "1")
    restore, arguments = pack_events(events).__reduce__()
    assert restore is spawn_events._restore_columnar
    actual = pickle.loads(pickle.dumps(pack_events(events)))
    assert actual == events and type(actual[0].payload["close"]) is type(value)


def test_columnar_keeps_mixed_roles_order_types_and_aliases():
    shared = {"rate": "0.0001", "period_id": "p"}
    rules = MarketEvent(1, 0, "INSTRUMENT_RULES", {"tick": "0.1", "tiers": [{"max": "1"}]})
    events = (rules,) + tuple(
        MarketEvent(i, i * 1000, "TRADES", {"price": str(100 + i % 7), "qty": "1", "is_buyer_maker": bool(i % 2),
                                            "agg_trade_id": i, "first_trade_id": None, "f": i / 3})
        for i in range(2, 2000)
    ) + (MarketEvent(2000, 2_000_000, "FUNDING", shared), MarketEvent(2001, 2_000_001, "FUNDING", shared), rules)
    restore, arguments = pack_events(events).__reduce__()
    assert restore is spawn_events._restore_columnar
    actual = pickle.loads(pickle.dumps(pack_events(events)))
    assert actual == events
    assert [list(e.payload) for e in actual] == [list(e.payload) for e in events]
    assert [type(v) for e in actual for v in e.payload.values()] == [type(v) for e in events for v in e.payload.values()]
    assert actual[-3].payload is actual[-2].payload and actual[0] is actual[-1]


def test_columnar_buffer_is_verified_before_decoding():
    events = (MarketEvent(1, 1, "BARS", {"close": "1"}), MarketEvent(2, 2, "BARS", {"close": "2"}))
    restore, (buffer, digest, count) = pack_events(events).__reduce__()
    assert restore(buffer, digest, count) == events
    damaged = bytearray(buffer)
    damaged[-5] ^= 1
    with pytest.raises(ValueError, match="identity"):
        restore(bytes(damaged), digest, count)
    with pytest.raises(ValueError, match="count"):
        restore(buffer, digest, count + 1)


def test_cyclic_payload_falls_back_without_losing_graph():
    payload = {}
    event = MarketEvent(1, 1, "BARS", payload)
    payload["event"] = event
    actual = pickle.loads(pickle.dumps(pack_events((event,))))
    assert actual[0].payload["event"] is actual[0]


@dataclass(frozen=True, slots=True)
class ExtendedEvent(MarketEvent):
    extra: int = 1


def test_subclass_keeps_custom_state():
    events = (ExtendedEvent(1, 1, "BARS", {}),)
    actual = pickle.loads(pickle.dumps(pack_events(events)))
    assert actual == events and type(actual[0]) is ExtendedEvent


def test_disabled_or_altered_constructor_preserves_original_tuple(monkeypatch):
    events = (MarketEvent(1, 1, "BARS", {}),)
    monkeypatch.setenv("BACKTEST_COMPACT_SPAWN_ENABLED", "0")
    assert pack_events(events) is events
    monkeypatch.setenv("BACKTEST_COMPACT_SPAWN_ENABLED", "1")
    original = MarketEvent.__init__
    monkeypatch.setattr(MarketEvent, "__init__", lambda self, *args: original(self, *args))
    assert pack_events(events) is events


def test_empty_and_invalid_clock_values_are_not_rejected_early():
    assert pickle.loads(pickle.dumps(pack_events(()))) == ()
    for sequence in ("bad", True, -1, 2**100):
        events = (MarketEvent(sequence, 1, "BARS", {}),)
        assert pickle.loads(pickle.dumps(pack_events(events))) == events
