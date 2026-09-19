import json
import random
from types import SimpleNamespace

import pytest

from app.backtest.strategy import qualified_json
from app.backtest.strategy.direct_observation import small_text, encode_output
from app.backtest.strategy.python_provider import _to_host_output, _target_state_hash
from app.backtest.strategy.protocol import canonical_hash, ProviderCapabilities
from app.backtest.colocated import _GuardedProvider


@pytest.mark.parametrize("native", [False, True])
def test_qualified_native_bytes_match_stdlib_for_ascii_and_integer_trees(monkeypatch, native):
    monkeypatch.setattr(qualified_json, "_ENABLED", native)
    rng = random.Random(20260912)
    values = [None, True, False, 0, -(2**63), 2**64-1, 2**100, "".join(map(chr, range(127)))]
    for _ in range(1000):
        text = "".join(chr(rng.randrange(127)) for _ in range(rng.randrange(20)))
        value = {"z": [rng.choice(values), text], text: {"sequence": rng.randrange(2**53)}}
        expected = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        assert qualified_json.encode_ascii_tree(value) == expected
    assert not small_text("\x7f")
    assert not small_text("中")


def test_missing_native_module_uses_identical_reference_bytes(monkeypatch):
    monkeypatch.setattr(qualified_json, "orjson", None)
    value = {"a": [None, 10, "quoted\"\n"]}
    assert qualified_json.encode_ascii_tree(value) == json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_native_sdk_output_matches_sdk_encoder():
    from candlescope_backtest_sdk import TargetPosition, Signal, OrderIntent
    from candlescope_backtest_sdk.models import encode_output as reference
    for output in (TargetPosition("1.000"), TargetPosition("-0.01"), Signal("LONG"),
                   OrderIntent("BUY", "MARKET", "1")):
        for sequence in (1, 100000, 2**53-1):
            assert encode_output(sequence, output)[0] == reference(sequence, output)


def test_target_hash_reuse_keeps_detached_payload_and_extra_fields():
    _target_state_hash.cache_clear()
    wire = {"kind":"TARGET_POSITION", "payload":{"quantity":"1"}, "outputHash":"sdk-hash"}
    first = _to_host_output(1, wire)
    first.payload["quantity"] = "poison"
    second = _to_host_output(2, wire)
    assert second.payload == {"quantity":"1", "targetExposure":"1"}
    assert second.state_hash == canonical_hash(second.payload)
    assert _target_state_hash.cache_info().hits == 1
    extra = _to_host_output(3, {**wire, "payload":{"quantity":"1", "reason":"x"}})
    assert extra.state_hash == canonical_hash(extra.payload)
    assert extra.state_hash != second.state_hash


def test_owned_capability_cache_invalidates_at_prepare_and_restore():
    class Provider:
        count = 0
        features = ("close",)
        def describe(self):
            self.count += 1
            return ProviderCapabilities(required_features=self.features)
        def prepare(self, _):
            self.features = ("open",)
        def restore(self, _):
            self.features = ("volume",)
        def step(self, _):
            assert deadline.value > 0
            return 1
    provider = Provider()
    deadline = SimpleNamespace(value=0)
    guarded = _GuardedProvider(provider, deadline, 1, 1)
    for _ in range(100):
        assert guarded.describe().required_features == ("close",)
    assert provider.count == 1
    guarded.prepare({})
    assert guarded.describe().required_features == ("open",)
    guarded.restore({})
    assert guarded.describe().required_features == ("volume",)
    assert provider.count == 3
    step = guarded.step
    assert guarded.step is step and step(None) == 1
    assert deadline.value == 0


def test_empty_decision_codec_preserves_exact_legacy_chain_bytes():
    from app.simulation.kernel import _empty_decision_hash
    from app.market_dataset.snapshot import sha256_hex
    rng = random.Random(1024)
    prior = "sha256:GENESIS"
    for i in range(1000):
        sequence = rng.randrange(-2**100, 2**100)
        stamp = rng.randrange(-2**60, 2**60)
        if i % 25 == 0:
            prior = "legacy-中-\x7f-\n-\""
        expected = "sha256:" + sha256_hex({"previous":prior,
            "decision":{"sequence":sequence, "watermark_ms":stamp, "intents":[]}})
        assert _empty_decision_hash(prior, sequence, stamp) == expected
        prior = expected


def test_bar_input_native_hash_is_exact_and_rejects_incompatible_values(monkeypatch):
    monkeypatch.setattr(qualified_json, "_ENABLED", True)
    bar = {"open":"100.1", "high":"102", "close":"101", "flag":True, "time":123}
    for features in (None, {}, {"close":"101"}):
        encoded = qualified_json.try_bar_input_bytes(1, 123, bar, None, features)
        if qualified_json.orjson is not None:
            assert encoded == json.dumps({"sequence":1,"watermark":123,"bar":bar,
                "trade":None,"features":features},sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    for invalid in (1e-7, float("nan"), {"nested":1}, "中", "\x7f", 2**100):
        assert qualified_json.try_bar_input_bytes(1, 123, {"close":invalid}, None, {}) is None
    assert qualified_json.try_bar_input_bytes(1, 123, bar, {}, {}) is None


def test_benchmark_sources_are_unchanged_without_test_imports():
    import ast
    from pathlib import Path
    from scripts.strategy_benchmark_sources import SMA, RSI
    from tests.test_backtest_chart_pyne import SMA as original_sma, RSI as original_rsi
    assert (SMA, RSI) == (original_sma, original_rsi)
    source = Path(__file__).resolve().parents[1]/"scripts/benchmark_strategy_bar_audit.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tests") for node in ast.walk(tree))
