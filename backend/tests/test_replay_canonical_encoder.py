"""The accelerated hash encoder must emit the exact frozen JSON byte contract."""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import random
from types import MappingProxyType

import pytest

from app.replay import canonical


class Side(str, Enum):
    BUY = "买"


@dataclass
class Value:
    amount: Decimal
    side: Side


@pytest.mark.parametrize("value", [
    None, True, 0, -1, 2**64 - 1, 2**80, -(2**80),
    {"z": "\x00\n\r\t\\\"/", "中": "😀\u2028\u2029", "a": [1, None, False]},
    MappingProxyType({"decimal": Decimal("-0.5000"), "tuple": (Side.BUY, 1)}),
    Value(Decimal("12.3400"), Side.BUY),
])
def test_fast_bytes_match_reference_and_optional_fallback(value, monkeypatch):
    reference = canonical.canonical_json(value).encode("utf-8")
    assert canonical.canonical_json_bytes(value) == reference
    monkeypatch.setattr(canonical, "orjson", None)
    assert canonical.canonical_json_bytes(value) == reference


def test_random_native_state_trees_are_byte_identical():
    randomizer = random.Random(1729)
    def tree(depth):
        if depth == 0:
            return randomizer.choice([None, False, True, randomizer.randrange(-10**20, 10**20), "汉字 😀 \n\"", ""])
        if randomizer.randrange(2):
            return [tree(depth - 1) for _ in range(randomizer.randrange(5))]
        return {str(key): tree(depth - 1) for key in randomizer.sample(range(20), randomizer.randrange(6))}
    for _ in range(200):
        value = tree(4)
        assert canonical.canonical_json_bytes(value) == canonical.canonical_json(value).encode("utf-8")


@pytest.mark.parametrize("value", [1.25, float("nan"), float("inf"), {1: "bad key"}, object()])
def test_fast_path_does_not_weaken_canonical_validation(value):
    with pytest.raises((TypeError, ValueError)):
        canonical.canonical_json_bytes({"nested": [value]})
