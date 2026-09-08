import pytest

from app.data_engine.data_manager.models import BarData
from app.indicator.indicators.atr import ATRIndicator


@pytest.mark.parametrize('period', [1, 2, 14, 100])
def test_atr_first_preview_includes_gaps_and_preserves_confirmed_state(period):
    bars = [BarData(time=1700000000+i*60, open=100+i*5, high=102+i*5,
                    low=99+i*5, close=101+i*5, volume=1) for i in range(period+1)]
    # First range is high-low=3; subsequent gap-up ranges are high-prevClose=6.
    expected = (3 + (period-1)*6) / period
    indicator = ATRIndicator({'period': period})
    indicator.init(bars[:period-1])
    for _ in range(3):
        indicator.update_partial(bars[period-1])
        assert indicator.get_preview()['atr'] == pytest.approx(expected)
        assert indicator.get_latest()['atr'] is None
    indicator.update_closed(bars[period-1])
    assert indicator.get_latest()['atr'] == pytest.approx(expected)
    following = (expected*(period-1)+6)/period
    indicator.update_partial(bars[period])
    assert indicator.get_preview()['atr'] == pytest.approx(following)
    indicator.update_closed(bars[period])
    assert indicator.get_latest()['atr'] == pytest.approx(following)
