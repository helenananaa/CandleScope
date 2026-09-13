"""Exact batch valuation versus the retained arbitrary-integer scanner."""

from dataclasses import replace
from decimal import Decimal
import random

import pytest

from app.replay.training.portfolio_prices import PortfolioPrices
from tests.test_replay_multi_interval import leg


@pytest.mark.parametrize("quantity", ["0.015", "0", "100000000000000000000"])
def test_batch_matches_integer_scanner_with_gaps_and_repeated_cohorts(quantity):
    rng = random.Random(9313)
    events = [
        (
            i // 7 * 3 + 100,
            30,
            str(rng.randrange(8)),
            i,
            Decimal(rng.randrange(-200000, 200001)) / 1000,
        )
        for i in range(12000)
    ]
    index = PortfolioPrices.build(events)
    scalar = replace(index, market_arrays=None)
    positions = [
        leg(str(i), "LONG" if i % 2 else "SHORT", quantity=quantity) for i in range(8)
    ]
    for start, end in ((99, 5300), (700, 2900), (2900, 2900), (4999, 6000)):
        prices = {str(i): Decimal("100.0001") for i in range(8)}
        for event in index.events:
            if event[0] <= start:
                prices[event[2]] = event[4]
        kwargs = dict(
            cash=Decimal("12345.00001"),
            legs=positions,
            initial_prices=prices,
            start=start,
            end=end,
            delta=77,
        )
        assert index.summary(**kwargs) == scalar.summary(**kwargs)
    arrays = index.market_arrays
    assert all(not a.flags.writeable for a in (*arrays[:4], *arrays[4]))


def test_batch_initial_prices_override_market_prefix_and_tied_minimum_is_first():
    # The account's pinned basis need not equal the preceding archive price.
    events = [(i, 30, "a", i, Decimal(90 if i % 2 else 110)) for i in range(1000)]
    index = PortfolioPrices.build(events)
    kwargs = dict(
        cash=Decimal(1000),
        legs=[leg("a")],
        initial_prices={"a": Decimal(105)},
        start=100,
        end=900,
    )
    actual = index.summary(**kwargs)
    assert actual == replace(index, market_arrays=None).summary(**kwargs)
    assert actual["trough_time_ms"] == 101


def test_int64_guard_falls_back_before_overflow(monkeypatch):
    index = PortfolioPrices.build(
        [(i, 30, "a", i, Decimal(10000000000 + i)) for i in range(1000)]
    )
    kwargs = dict(
        cash=Decimal(1000),
        legs=[leg("a", quantity="10000000000")],
        initial_prices={"a": Decimal(100)},
        start=0,
        end=999,
    )
    expected = replace(index, market_arrays=None).summary(**kwargs)
    original = PortfolioPrices._batch_summary
    results = []

    def checked(self, *args):
        result = original(self, *args)
        results.append(result)
        return result

    monkeypatch.setattr(PortfolioPrices, "_batch_summary", checked)
    assert index.summary(**kwargs) == expected
    assert results == [None]
