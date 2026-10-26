import json

import pytest

from app.backtest.checkpoint_codec import checkpoint_json, checkpoint_session
from app.backtest.identity import canonical_json, sha256_hex
from app.backtest.strategy.protocol import StrategyProviderSession, StrategyProviderError


@pytest.mark.parametrize("state", [
    {"unicode": "中文\x7f\ud800", "float": 1e-7, "big": 2**100, "list": [False, None, "x"]},
    {}, [], False, None, "", {"tuple": (1, 2, 3)},
])
def test_checkpoint_fragments_equal_original_bytes_and_hashes(state):
    class Provider:
        def snapshot(self):
            return state
    current = StrategyProviderSession(Provider(), run_id="test")
    expected = current.snapshot()
    snapshot, encoded, size = checkpoint_session(current)
    assert snapshot == expected
    assert encoded == canonical_json(expected)
    assert size == len(canonical_json(state or {}).encode("utf-8"))
    payload = {"provider": snapshot, "engine": {"a": [1, "中文"]}, "sequence": 9}
    actual = checkpoint_json(payload, encoded)
    assert actual == canonical_json(payload)
    assert sha256_hex(actual) == sha256_hex(payload)


def test_provider_payload_is_captured_and_encoded_once(monkeypatch):
    state = {"big": ["a"] * 10000}
    captures = []
    class Provider:
        def snapshot(self):
            captures.append(1)
            return state
    dumps, encodings = json.dumps, []
    def tracked(value, *args, **kwargs):
        if value is state:
            encodings.append(1)
        return dumps(value, *args, **kwargs)
    monkeypatch.setattr(json, "dumps", tracked)
    snapshot, encoded, _ = checkpoint_session(StrategyProviderSession(Provider(), run_id="test"))
    checkpoint_json({"provider": snapshot}, encoded)
    assert len(captures) == len(encodings) == 1


@pytest.mark.parametrize("state", [{"bad": float("nan")}, {"bad": object()}])
def test_encoding_keeps_strict_provider_errors(state):
    class Provider:
        def snapshot(self):
            return state
    current = StrategyProviderSession(Provider(), run_id="test")
    with pytest.raises((TypeError, ValueError)) as original:
        current.snapshot()
    with pytest.raises(type(original.value)):
        checkpoint_session(current)
