from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from app.replay import canonical
import app.replay.bars.builder as builder_module
from app.replay.bars.builder import BAR_BUILDER_STATE_HASH_SCHEMA_VERSION
from app.replay.broker.execution import BROKER_STATE_HASH_SCHEMA_VERSION
from tests.test_replay_bar_builder import _builder
from tests.fixtures.replay.bar_builder_fakes import make_replay_bar, REPLAY_START_MS, INTERVAL_MS
from tests.test_replay_v2_training_phase6 import _bar_broker


@pytest.mark.parametrize("fallback", [False, True])
def test_composed_canonical_fields_are_exact(fallback, monkeypatch):
    if fallback:
        monkeypatch.setattr(canonical, "orjson", None)
    value = {"z": [None, True, 2**90], "a": {"x": Decimal("1.2500")}, "中": "😀\n"}
    fields = {"z": canonical.canonical_json_bytes(value["z"])}
    assert canonical._canonical_object_bytes(value, encoded_fields=fields) == canonical.canonical_json(value).encode("utf-8")
    with pytest.raises(TypeError):
        canonical._canonical_object_bytes({"bad": 1.25, **value}, encoded_fields=fields)
    with pytest.raises(ValueError):
        canonical._canonical_object_bytes(value, encoded_fields={"missing": b"null"})


@pytest.mark.parametrize("fallback", [False, True])
def test_cached_bars_remain_byte_exact_bounded_and_detached(fallback, monkeypatch):
    if fallback:
        monkeypatch.setattr(canonical, "orjson", None)
    builder = _builder(display_interval="1m", max_closed_bars=3)
    calls = 0
    original = builder_module.canonical_json_bytes
    def counted(value):
        nonlocal calls
        if isinstance(value, dict) and "open_time_ms" in value:
            calls += 1
        return original(value)
    monkeypatch.setattr(builder_module, "canonical_json_bytes", counted)
    prior = None
    for i in range(8):
        builder.apply_bar(make_replay_bar(REPLAY_START_MS + i * INTERVAL_MS, i + 10))
        snapshot, encoded = builder._snapshot_with_encoding()
        assert encoded == canonical.canonical_json_bytes(snapshot)
        unhashed = dict(snapshot)
        state_hash = unhashed.pop("state_hash")
        assert state_hash == canonical.canonical_sha256({"schema_version": BAR_BUILDER_STATE_HASH_SCHEMA_VERSION, "state": unhashed})
        assert calls == i + 1
        assert len(builder._closed_encoding_cache) <= 3
        assert builder.snapshot() == snapshot
        prior = deepcopy(snapshot)
        snapshot["closed_bars"][0]["close"] = "caller mutation"
        assert builder.snapshot() == prior
    restored = _builder(display_interval="1m", max_closed_bars=3)
    restored.restore(prior)
    assert restored.snapshot() == prior
    builder.restore(prior)
    assert builder._closed_encoding_cache == {}
    assert builder.snapshot() == prior


@pytest.mark.parametrize("v2", [False, True])
def test_broker_nested_hash_keeps_reference_contract(v2):
    broker = _bar_broker(v2=v2)
    state = broker.snapshot()
    original = deepcopy(state)
    digest = state.pop("state_hash")
    assert digest == canonical.canonical_sha256({"schema_version": BROKER_STATE_HASH_SCHEMA_VERSION, "state": state})
    state["bar_builder"]["closed_bars"].append({"invalid": True})
    assert broker.snapshot() == original
    broker.restore(original)
    assert broker.snapshot() == original


def test_mark_only_snapshot_reuses_fill_and_ledger_encodings():
    from tests.fixtures.replay.broker_fakes import bar, make_broker, request

    broker = make_broker()
    broker.place_order(request(client_order_id="entry"), command_id="cmd-entry")
    broker.apply_bar(bar(0, 100))
    broker.snapshot()
    fills = broker._snapshot_component_encodes["fills"]
    ledger = broker._snapshot_component_encodes["ledger"]
    encoded_entries = broker._ledger.entry_encodes
    broker.apply_bar(bar(1, 101))
    after = broker.snapshot()
    assert broker._snapshot_component_encodes["fills"] == fills
    assert broker._snapshot_component_encodes["ledger"] == ledger
    assert broker._ledger.entry_encodes == encoded_entries
    restored = make_broker()
    restored.restore(after)
    assert restored.account.cash_balance == broker.account.cash_balance
    assert restored.position.to_dict() == broker.position.to_dict()
    assert restored.fills == broker.fills
    assert restored._ledger.tail_hash == broker._ledger.tail_hash
    broker.close_position(command_id="cmd-close")
    broker.apply_bar(bar(2, 102))
    broker.snapshot()
    assert broker._snapshot_component_encodes["fills"] == fills + 1
    assert broker._snapshot_component_encodes["ledger"] == ledger + 1
