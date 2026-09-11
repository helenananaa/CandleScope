from copy import deepcopy

import pytest

from app.replay import canonical
from app.replay.immutable_json import freeze
from tests.test_replay_hotpath_history import _seed_live_book, _history_broker
from tests.fixtures.replay.broker_fakes import bar, request
from app.replay.broker.models import OrderSide


@pytest.mark.parametrize("fallback", [False, True])
def test_readonly_json_preserves_canonical_bytes_and_blocks_nested_mutations(monkeypatch, fallback):
    if fallback:
        monkeypatch.setattr(canonical, "orjson", None)
    original = {"items": [{"text": "中😀", "n": 2**100}], "flags": [True, None]}
    value = freeze(original)
    assert canonical.canonical_json_bytes(value) == canonical.canonical_json_bytes(original)
    for change in (
        lambda: value.update({"items": []}), lambda: value["items"].append({}),
        lambda: value["items"][0].update({"n": 0}), lambda: value.__init__({}),
        lambda: value["items"].__init__([]),
    ):
        with pytest.raises(TypeError):
            change()
    assert canonical.canonical_json_bytes(value) == canonical.canonical_json_bytes(original)


def test_streamed_canonical_hash_matches_flat_encoding():
    child = {"a": [1, "中", None]}
    parts = tuple(canonical._canonical_object_parts(child, encoded_fields={}))
    value = {"schema": "test", "state": child}
    assert canonical._canonical_object_sha256(value, encoded_fields={"state": parts}) == canonical.canonical_sha256(value)


def test_mark_only_work_shares_history_but_new_fill_detaches():
    broker, index = _seed_live_book(25)
    first, wire = broker._owned_snapshot_with_encoding()
    old = (broker._orders, broker._fills, broker._closed_trades, broker._warnings)
    broker.apply_bar(bar(index, 101))
    second, _ = broker._owned_snapshot_with_encoding()
    assert all(a is b for a, b in zip(old, (broker._orders, broker._fills, broker._closed_trades, broker._warnings)))
    for key in ("orders", "fills", "closed_trades", "warnings", "ledger", "client_order_ids"):
        assert first[key] is second[key]
    assert canonical.canonical_json_bytes(first) == wire
    with pytest.raises(TypeError):
        second["fills"].clear()
    public = broker.snapshot()
    detached = deepcopy(public)
    public["orders"][0]["status_history"].append("INVALID")
    assert broker.snapshot() == detached
    broker.place_order(request(client_order_id="exit", side=OrderSide.SELL), command_id="exit")
    broker.apply_bar(bar(index + 1, 101))
    assert broker._fills is not old[1]
    assert canonical.canonical_json_bytes(first) == wire
    restored = _history_broker()
    restored.restore(first)
    assert restored.snapshot() == first


def test_native_clone_preserves_oversized_integers():
    broker = _history_broker()
    value, wire = broker._snapshot_component("fills", lambda: [{"large": 2**100}])
    copied = broker._copy_snapshot_component(value, wire, "fills")
    assert type(copied[0]["large"]) is int
    assert copied[0]["large"] == 2**100


def test_fresh_checkpoint_receipt_avoids_decode_but_imported_bytes_are_verified(monkeypatch):
    from app.replay.checkpoints import CheckpointCodec
    from app.replay.storage import checkpoint_delta as delta
    source = {"items": [{"amount": "12"}]}
    wire = CheckpointCodec().encode(source)
    source["items"][0]["amount"] = "99"
    assert wire.payload["items"][0]["amount"] == "12"
    with pytest.raises(TypeError):
        wire.payload["items"][0]["amount"] = "0"
    with pytest.raises(TypeError):
        wire.payload = {}
    def forbidden(*args):
        raise ValueError("import path invoked")
    monkeypatch.setattr(CheckpointCodec, "decode", forbidden)
    assert delta._logical(wire)["items"][0]["amount"] == "12"
    with pytest.raises(ValueError, match="import path"):
        delta._logical(bytes(wire))


def test_base_cache_budget_uses_raw_size_not_compressed_size(monkeypatch):
    from collections import OrderedDict
    from app.replay.checkpoints import CheckpointCodec
    from app.replay.storage import checkpoint_delta as delta
    monkeypatch.setattr(delta, "_base_cache", OrderedDict())
    wire = CheckpointCodec().encode({"text": "a" * (4 * 1024 * 1024 + 1)})
    assert len(wire) < 100_000
    delta._remember_base(wire, wire.payload)
    assert not delta._base_cache


def test_constant_held_tape_batch_revalues_once_and_matches_scalar(monkeypatch):
    from tests.test_replay_execution_tape import _broker, _trade
    fast, slow = _broker(), _broker()
    for broker in (fast, slow):
        broker.place_order(request(client_order_id="entry"), command_id="entry")
        broker.apply_trade(_trade(0, price="100", quantity="1"))
    events = tuple(_trade(i, price="100", quantity="1") for i in range(1, 101))
    calls = []
    original = fast._account_from
    def account(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(fast, "_account_from", account)
    fast.apply_source_events_final_state(events)
    for event in events:
        slow.apply_trade(event)
    assert len(calls) == 1
    assert fast.snapshot() == slow.snapshot()
