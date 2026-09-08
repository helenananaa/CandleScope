import pytest
from app.data_engine.data_manager.models import BarData
from app.indicator.indicators.ma import MAIndicator


@pytest.mark.parametrize('period', [1, 2, 20, 500])
def test_ma_first_window_preview_does_not_drop_oldest_before_window_is_full(period):
    bars = [BarData(time=1700000000+i*60, open=100+i, high=100+i,
                    low=100+i, close=100+i, volume=1) for i in range(period+1)]
    indicator = MAIndicator({'period': period})
    indicator.init(bars[:period-1])
    expected = 100 + (period-1)/2
    for _ in range(3):
        indicator.update_partial(bars[period-1])
        assert indicator.get_preview()['ma'] == pytest.approx(expected)
        assert indicator.get_latest()['ma'] is None
    indicator.update_closed(bars[period-1])
    assert indicator.get_latest()['ma'] == pytest.approx(expected)
    indicator.update_partial(bars[period])
    assert indicator.get_preview()['ma'] == pytest.approx(expected+1)
    indicator.update_closed(bars[period])
    assert indicator.get_latest()['ma'] == pytest.approx(expected+1)
