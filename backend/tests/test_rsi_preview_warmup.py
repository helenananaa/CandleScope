"""Boundary previews must use the same first Wilder seed as a closed bar."""
import pytest

from app.data_engine.data_manager.models import BarData
from app.indicator.indicators.rsi import RSIIndicator


def bars_for(values):
    return [BarData(time=1700000000 + i * 60, open=v, high=v, low=v,
                    close=v, volume=1) for i, v in enumerate(values)]


@pytest.mark.parametrize('period', [2, 14, 100])
@pytest.mark.parametrize('direction', ['up', 'down', 'mixed'])
def test_first_valid_rsi_preview_uses_all_period_changes_without_committing(period, direction):
    changes = [(1 if direction == 'up' else -1 if direction == 'down'
                else (3 if i % 2 else -2)) for i in range(period)]
    values = [500.0]
    for change in changes:
        values.append(values[-1] + change)
    bars = bars_for(values)
    gains = sum(max(change, 0) for change in changes)
    losses = sum(max(-change, 0) for change in changes)
    expected = 100.0 if losses == 0 else 100 * gains / (gains + losses)
    indicator = RSIIndicator({'period': period})
    indicator.init(bars[:-2])
    indicator.update_partial(bars[-2])
    assert indicator.get_preview()['rsi'] is None
    indicator.update_closed(bars[-2])
    for _ in range(3):
        indicator.update_partial(bars[-1])
        assert indicator.get_preview()['rsi'] == pytest.approx(expected)
        assert indicator.get_latest()['rsi'] is None
    indicator.update_closed(bars[-1])
    assert indicator.get_latest()['rsi'] == pytest.approx(expected)
    batch = RSIIndicator({'period': period})
    batch.init(bars)
    assert batch.get_latest() == indicator.get_latest()
