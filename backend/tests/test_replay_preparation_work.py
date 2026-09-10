from dataclasses import asdict, replace
from hashlib import sha256
import json

import pytest

from app.replay.bars.builder import ReplayBarBuilder
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.dataset import validate_replay_repository_bar
from app.replay.errors import ReplayDomainError
from app.replay.source_chain import next_source_chain_hash, SOURCE_CHAIN_SCHEMA_VERSION


def validated_bar():
    return validate_replay_repository_bar(
        {
            "open_time": 0,
            "close_time": 59999,
            "open": "100.00",
            "high": "102.0",
            "low": "98",
            "close": "101",
            "volume": "2.00",
            "quote_volume": "200",
            "source": "fixture",
        },
        identity=ReplaySeriesIdentity(
            exchange="binance", market_type="futures", symbol="BTCUSDT"
        ),
        interval="1m",
        interval_ms=60000,
        expected_open_ms=0,
        now_ms=120000,
    )


def builder(start=0):
    return ReplayBarBuilder(
        base_interval="1m",
        display_interval="1m",
        replay_start_ms=start,
        warmup_bars=(),
        max_closed_bars=32,
    )


def test_repository_validation_is_reused_but_not_serialized(monkeypatch):
    from app.replay.bars import builder as module

    value = validated_bar()
    plain = replace(value)
    assert value == plain and asdict(value) == asdict(plain)
    assert value.to_dict() == plain.to_dict()
    slow = builder()
    slow.apply_bar(plain)

    def fail(*args, **kwargs):
        raise AssertionError("repeated numeric normalization")

    monkeypatch.setattr(module, "_normalized_decimal", fail)
    fast = builder()
    fast.apply_bar(value)
    assert fast.snapshot() == slow.snapshot()
    shifted = value.with_time_offset(60000)
    builder(60000).apply_bar(shifted)


@pytest.mark.parametrize(
    "changes", [{"high": "99"}, {"close": "NaN"}, {"volume": "-1"}]
)
def test_editing_a_validated_bar_requires_new_validation(changes):
    value = replace(validated_bar(), **changes)
    assert not getattr(value, "_normalized_values_validated", False)
    with pytest.raises(ReplayDomainError):
        builder().apply_bar(value)


def test_validation_receipt_does_not_skip_order_or_alignment_checks():
    value = validated_bar()
    with pytest.raises(ReplayDomainError):
        builder().apply_bar(value.with_time_offset(1))
    target = builder()
    target.apply_bar(value)
    with pytest.raises(ReplayDomainError):
        target.apply_bar(value)
    with pytest.raises(ReplayDomainError):
        target.apply_bar(value.with_time_offset(120000))


def test_decimal_normalization_preserves_original_spelling_rules():
    from decimal import Decimal
    import random
    from app.replay.models import normalize_decimal_string

    values = [
        "0",
        "-0",
        "+0",
        "0.00",
        "-.000",
        ".1",
        "1.",
        "+001.2300",
        "-0.00001",
        "１２.３００",
        "١٢.٣٠",
        "9" * 1000,
    ]
    randomizer = random.Random(32)
    for _ in range(2000):
        values.append(
            f"{randomizer.choice(['', '-', '+'])}{randomizer.randrange(100000):07d}.{randomizer.randrange(100000):05d}"
        )
    for value in values:
        number = Decimal(value)
        expected = format(number, "f") if number else "0"
        if "." in expected:
            expected = expected.rstrip("0").rstrip(".")
        assert normalize_decimal_string(value, field_name="test") == expected
    for value in ("NaN", "Infinity", "1e2", "1 2", "1_000", " 1", 1.0):
        with pytest.raises((TypeError, ValueError)):
            normalize_decimal_string(value, field_name="test")


def test_repository_numeric_conversion_matches_decimal_reference():
    import random
    from decimal import Decimal
    from app.replay.dataset import _decimal_value
    from app.replay.models import normalize_decimal_string

    randomizer = random.Random(57)
    values = [0.0, -0.0, 1e-300, 1e300, 1.0000000000000002, Decimal("1.2300"), "001.2300"]
    values += [randomizer.random() * 10**randomizer.randrange(-20, 20) for _ in range(2000)]
    for value in values:
        expected = normalize_decimal_string(format(Decimal(str(value)), "f"), field_name="test")
        assert _decimal_value(value, field_name="test") == expected
    for value in (-1.0, float("nan"), float("inf"), Decimal("NaN"), True, None):
        with pytest.raises(ValueError):
            _decimal_value(value, field_name="test")
    with pytest.raises(ValueError):
        _decimal_value(-0.0, field_name="test", positive=True)


def test_preparation_reuses_evicted_prefix_hashes_and_bounds_cache(monkeypatch):
    original = ReplayBarBuilder._next_closed_chain_hash
    calls = 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    slow = builder()
    bars = [validated_bar().with_time_offset(i * 60000) for i in range(260)]
    for value in bars:
        slow.apply_bar(value)
    expected = slow.snapshot()
    fast = builder()
    fast._prepared_closed_hashes = {}
    monkeypatch.setattr(
        ReplayBarBuilder, "_next_closed_chain_hash", staticmethod(counted)
    )
    for value in bars:
        fast.apply_bars_final_state((value,))
        assert len(fast._prepared_closed_hashes) <= 32
    assert calls == len(bars)
    assert fast.snapshot() == expected


@pytest.mark.parametrize(
    "event",
    [
        {"price": "1.23", "text": '中文\n"\\'},
        {"large": 2**80, "small": -(2**80), "nested": [True, None, {"x": 3}]},
    ],
)
@pytest.mark.parametrize("native", [True, False])
def test_source_hash_matches_original_json_encoder(event, native, monkeypatch):
    from app.replay import canonical

    if not native:
        monkeypatch.setattr(canonical, "orjson", None)
    previous = "sha256:" + "1" * 64
    material = {
        "schema_version": SOURCE_CHAIN_SCHEMA_VERSION,
        "previous": previous,
        "source_sequence": 123,
        "event": event,
    }
    expected = (
        "sha256:"
        + sha256(
            json.dumps(
                material,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    assert next_source_chain_hash(previous, event, 123) == expected


@pytest.mark.parametrize("period", ["1h", "1d"])
@pytest.mark.parametrize("native", [True, False])
def test_compact_cache_retains_partial_buckets(tmp_path, monkeypatch, period, native):
    from app.replay.broker import prepared_cache
    from tests.test_replay_prepared_cache import Source
    from tests.fixtures.replay.broker_fakes import make_broker

    if not native:
        monkeypatch.setattr(prepared_cache, "orjson", None)
    fast = make_broker()
    fast._bar_builder = ReplayBarBuilder(
        base_interval="1m", display_interval=period,
        replay_start_ms=0, warmup_bars=(), max_closed_bars=32,
    )
    slow = ReplayBarBuilder(
        base_interval="1m", display_interval=period,
        replay_start_ms=0, warmup_bars=(), max_closed_bars=32,
    )
    first = validated_bar()
    fast.apply_bar(first)
    slow.apply_bar(first)
    bars = [first.with_time_offset(i * 60000) for i in range(1, 514)]
    path = tmp_path / "partial.zlib"
    index = prepared_cache.prepare(Source(bars), fast, "sha256:" + "0" * 64,
                                   next_source_chain_hash, path)
    index.apply(fast, 0, 131)
    loaded = prepared_cache.prepare(Source(bars, 131), fast, index.chains[131],
                                    next_source_chain_hash, path)
    assert loaded.loaded_from_cache
    loaded.apply(fast, 131, 512)
    slow.apply_bars_final_state(bars[:512])
    assert fast._bar_builder.snapshot() == slow.snapshot()
