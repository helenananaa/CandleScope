"""Independent close-source examples; these run without a language engine."""
from copy import deepcopy

import pytest

from candlescope_plugin_sdk.synthetic_ohlcv import renko_rows


def bars(closes):
    return [dict(time=i * 60, open=c, high=c + 1, low=c - 1,
                 close=c, volume=(i + 1) * 10) for i, c in enumerate(closes)]


def test_fixed_bricks_keep_same_time_ordinals_and_two_brick_reversal():
    source = bars([100, 106, 101, 108])
    original = deepcopy(source)
    result = renko_rows(source, "Traditional", 2)
    assert source == original
    assert [row["close"] for row in result] == [102, 104, 106, 102, 106, 108]
    assert [row["open"] for row in result] == [100, 102, 104, 104, 104, 106]
    assert [row["source_index"] for row in result] == [1, 1, 1, 2, 3, 3]
    assert [row["time"] for row in result] == [60, 60, 60, 120, 180, 180]
    assert [row["ordinal"] for row in result] == list(range(6))
    assert [row["volume"] for row in result] == [10, 10, 10, 30, 20, 20]


def test_atr_uses_only_the_source_prefix_and_keeps_confirmed_bricks():
    # True ranges2,5,47 give Wilder ATR(2)3.5 then25.25.
    source = bars([100, 104, 150])
    before = renko_rows(source[:2], "ATR", 2)
    after = renko_rows(source, "ATR", 2)
    assert [row["close"] for row in before] == [103.5]
    assert [row["close"] for row in after] == [103.5, 128.75]
    assert after[:len(before)] == before


@pytest.mark.parametrize("style,size", [("Traditional", 2), ("ATR", 2)])
def test_every_prefix_and_forming_tail_match_confirmed_history(style, size):
    source = bars([100, 106, 101, 108, 150, 90, 110])
    full = renko_rows(source, style, size)
    for count in range(len(source) + 1):
        assert renko_rows(source[:count], style, size) == [
            row for row in full if row["source_index"] < count]
        if count:
            forming = [*source[:count - 1], {**source[count - 1], "is_closed": False}]
            assert renko_rows(forming, style, size) == renko_rows(source[:count - 1], style, size)


@pytest.mark.parametrize("style,size", [
    ("Traditional", 0), ("Traditional", -1), ("Traditional", True),
    ("Traditional", "NaN"), ("Traditional", "Infinity"),
    ("ATR", 1.5), ("ATR", 5001), ("Other", 1),
])
def test_invalid_profiles_fail_instead_of_falling_back(style, size):
    with pytest.raises(ValueError, match="SYNTHETIC_INPUT_INVALID"):
        renko_rows(bars([100, 102]), style, size)


def test_one_source_cannot_create_unbounded_synthetic_history():
    with pytest.raises(ValueError, match="SYNTHETIC_INPUT_BUDGET"):
        renko_rows(bars([100, 20102]), "Traditional", 1)
