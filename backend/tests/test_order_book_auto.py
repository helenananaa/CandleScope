from decimal import Decimal

import pytest

from app.api.v1.order_book_auto import AutoGroupingState, step_scores
from app.api.v1.order_book_projection import project_order_book_levels
from app.api.v1.stream_full_order_book import _display_options


def book(count=200, gap=1):
    return {
        "bids": [[100000 - i * gap, 1] for i in range(count)],
        "asks": [[100001 + i * gap, 1] for i in range(count)],
    }


def best(data, rows=10):
    scores = step_scores(data, Decimal(1), rows)
    return min(scores, key=lambda step: (scores[step], step))


def test_density_and_viewport_drive_step_without_coalescing_thin_side():
    assert best(book(), 5) > best(book(), 20)
    assert best(book(count=3, gap=40)) == 1
    asymmetric = book()
    asymmetric["asks"] = [[100001, 1]]
    assert best(asymmetric) > 1
    assert best({"bids": [], "asks": []}) == 1


def test_price_threshold_does_not_cause_tenfold_step_jump():
    original = book()
    shifted = {side: [[price + 1, qty] for price, qty in levels] for side, levels in original.items()}
    assert best(original) == best(shifted)


def test_hysteresis_requires_sustained_improvement_cooldown_and_unfrozen_view():
    state = AutoGroupingState()
    fine = {Decimal(1): 0.0, Decimal(2): 1.0}
    coarse = {Decimal(1): 1.0, Decimal(2): 0.0}
    assert state.choose(fine, 0) == 1
    assert state.choose(coarse, 1) == 1
    assert state.choose(coarse, 3) == 1  # cooldown
    assert state.choose(fine, 4) == 1  # pending cancelled
    assert state.choose(coarse, 5) == 1
    assert state.choose(coarse, 7) == 2
    assert state.choose(fine, 20, frozen=True) == 2
    assert state.choose(fine, 30) == 2
    assert state.choose(fine, 32) == 1
    assert state.choose({Decimal(1): 0.2, Decimal(2): 0.0}, 50) == 1


def test_output_limit_and_explicit_range_are_independent_and_preserve_gaps():
    data = book(count=10, gap=20)
    options = dict(price_grouping="raw", price_tick_size=Decimal(1))
    uncapped = project_order_book_levels(data, limit=5, **options)
    narrow = project_order_book_levels(data, limit=5, range_bps=5, **options)
    larger_limit = project_order_book_levels(data, limit=10, range_bps=5, **options)
    assert len(uncapped.bids) == 5
    assert uncapped.bids[0][0] - uncapped.bids[1][0] == 20
    assert len(narrow.bids) == len(larger_limit.bids) == 3
    assert narrow.price_window_bid_truncated


def test_grouping_keeps_quantity_and_side_rounding_for_two_and_five_ticks():
    for grouping in ("2", "5"):
        data = book(count=40)
        result = project_order_book_levels(data, price_grouping=grouping, price_tick_size=Decimal(1))
        assert sum(qty for _, qty in result.bids) == 40
        assert sum(qty for _, qty in result.asks) == 40
        assert result.bids[0][0] <= data["bids"][0][0]
        assert result.asks[0][0] >= data["asks"][0][0]


@pytest.mark.parametrize("options", [
    {"target_rows": True}, {"target_rows": 101}, {"target_rows": 2.5},
    {"range_bps": 3}, {"auto_frozen": "false"},
])
def test_invalid_display_options_fail_closed(options):
    with pytest.raises((TypeError, ValueError)):
        _display_options(options)


def test_wide_btc_buckets_keep_all_known_quantity_and_mark_partial_coverage():
    data = {"bids": [[60000, 1], [59999.9, 2]], "asks": [[60000.1, 3], [60000.2, 4]],
            "coverage_bid_min": 59999.9, "coverage_ask_max": 60000.2,
            "exchange_full_depth_exhaustive": False}
    result = project_order_book_levels(data, price_grouping="100000", price_tick_size=Decimal("0.1"))
    assert result.price_step == 10000
    assert result.bids == [[60000, 1], [50000, 2]]
    assert result.asks == [[70000, 7]]
    assert result.incomplete_bid_prices == [50000]
    assert result.incomplete_ask_prices == [70000]
    assert not result.incomplete_outer_ask_bucket_omitted
    assert sum(q for _, q in result.bids) == 3


def test_huge_grouping_handles_zero_lower_price_and_unknown_coverage():
    result = project_order_book_levels(book(count=3), price_grouping="1000000000", price_tick_size=Decimal("0.01"))
    assert result.bids == [[0, 3]]
    assert result.asks == [[10000000, 3]]
    assert result.incomplete_bid_prices == [0]
    assert result.incomplete_ask_prices == [10000000]


def test_sparse_outer_updates_cannot_expand_trusted_interval():
    data = {"bids": [[60000, 1], [59000, 2], [10000, 5]],
            "asks": [[60001, 1], [61000, 2], [90000, 5]],
            "coverage_bid_min": 58900, "coverage_ask_max": 61100}
    result = project_order_book_levels(data, price_grouping="1000", price_tick_size=Decimal(1))
    assert result.incomplete_bid_prices == [10000]
    assert result.incomplete_ask_prices == [90000]
    assert result.coverage_bid_min == 58900
    assert result.coverage_ask_max == 61100


def test_exhaustive_flag_does_not_hide_projection_truncation():
    data = {"bids": [[60000, 1], [59999, 2]], "asks": [[60001, 3], [60002, 4]],
            "exchange_full_depth_exhaustive": True, "book_bid_levels": 100, "book_ask_levels": 100}
    result = project_order_book_levels(data, price_grouping="10000", price_tick_size=Decimal(1))
    assert result.incomplete_bid_prices == [50000]
    assert result.incomplete_ask_prices == [70000]
