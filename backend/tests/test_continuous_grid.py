"""The bar grid forward runs advance on (ADR-BACKTEST-015 B-333)."""
import pytest

from app.backtest.continuous_grid import bar_grid, supports
from app.backtest.errors import BacktestError

MONDAY = 1_795_392_000_000  # 2026-11-23 00:00 UTC


@pytest.mark.parametrize("interval, step", [("1m", 60_000), ("5m", 300_000), ("1h", 3_600_000),
                                             ("4h", 14_400_000), ("1d", 86_400_000), ("1w", 604_800_000)])
def test_fixed_length_intervals_have_a_grid(interval, step):
    grid = bar_grid(interval)
    assert grid.step_ms == step and grid.aligned(MONDAY) and grid.closes_bar(MONDAY - 1)
    assert grid.count(MONDAY, MONDAY + 3 * step - 1) == 3
    assert grid.closed_through(MONDAY + step + 1) == MONDAY + step - 1


@pytest.mark.parametrize("interval", ["1M", "60m", "90s", "1s", "", "x", None])
def test_calendar_sub_minute_and_alias_intervals_are_refused(interval):
    assert not supports(interval)
    with pytest.raises(BacktestError) as refused:
        bar_grid(interval)
    assert refused.value.code == "FIDELITY_UNSUPPORTED"


def test_weeks_open_on_monday():
    week = bar_grid("1w")
    assert week.aligned(MONDAY) and not week.aligned(MONDAY - 86_400_000)
    assert week.closed_through(MONDAY + 3 * 86_400_000) == MONDAY - 1


def test_boundaries_inside_a_bar_are_not_bar_boundaries():
    five = bar_grid("5m")
    assert not five.aligned(MONDAY + 60_000) and not five.closes_bar(MONDAY + 60_000 - 1)
    assert not five.aligned("0") and not five.closes_bar(None)
