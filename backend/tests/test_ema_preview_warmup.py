import pytest

from app.data_engine.data_manager.models import BarData
from app.indicator.indicators.ema import EMAIndicator


@pytest.mark.parametrize('period', [1, 2, 20, 500])
def test_ema_preview_initial_seed_and_following_bar(period):
    values = [100 + (i * 7 % 13) for i in range(period + 1)]
    bars = [BarData(time=1700000000+i*60, open=v, high=v, low=v, close=v, volume=1)
            for i, v in enumerate(values)]
    indicator = EMAIndicator({'period': period})
    indicator.init(bars[:period-1])
    expected = sum(values[:period]) / period
    for _ in range(3):
        indicator.update_partial(bars[period-1])
        assert indicator.get_preview()['ema'] == pytest.approx(expected)
        assert indicator.get_latest()['ema'] is None
    indicator.update_closed(bars[period-1])
    assert indicator.get_latest()['ema'] == pytest.approx(expected)
    alpha = 2 / (period+1)
    next_expected = alpha * values[period] + (1-alpha) * expected
    indicator.update_partial(bars[period])
    assert indicator.get_preview()['ema'] == pytest.approx(next_expected)
    indicator.update_closed(bars[period])
    assert indicator.get_latest()['ema'] == pytest.approx(next_expected)
    batch = EMAIndicator({'period': period})
    batch.init(bars)
    assert batch.get_latest() == indicator.get_latest()
