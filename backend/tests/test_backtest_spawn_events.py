import pickle
from dataclasses import dataclass
from decimal import Decimal

import pytest

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


@pytest.mark.parametrize("value", [Decimal("1.2"), {"nested": 1}, [1, 2]])
def test_nonflat_values_keep_original_pickle(value):
    events = (MarketEvent(1, 1, "BARS", {"close": value}),)
    packed = pack_events(events)
    assert packed.__reduce__()[1][0] is events
    assert pickle.loads(pickle.dumps(packed)) == events


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
