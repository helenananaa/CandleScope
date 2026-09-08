import math
import pytest
from app.data_engine.data_manager.models import BarData
from app.indicator.indicators.boll import BOLLIndicator


@pytest.mark.parametrize('period', [2, 20, 100])
@pytest.mark.parametrize('mult', [1.5, 3])
def test_boll_first_window_preview_matches_population_variance(period, mult):
    bars = [BarData(time=1700000000+i*60, open=100+i, high=100+i,
                    low=100+i, close=100+i, volume=1) for i in range(period+1)]
    mean = 100+(period-1)/2
    spread = mult*math.sqrt((period**2-1)/12)
    expected = {'middle': mean, 'upper': mean+spread, 'lower': mean-spread}
    indicator = BOLLIndicator({'period': period, 'mult': mult})
    indicator.init(bars[:period-1])
    for _ in range(3):
        indicator.update_partial(bars[period-1])
        assert indicator.get_preview() == pytest.approx(expected)
        assert all(value is None for value in indicator.get_latest().values())
    indicator.update_closed(bars[period-1])
    assert indicator.get_latest() == pytest.approx(expected)
    shifted = {key: value+1 for key, value in expected.items()}
    indicator.update_partial(bars[period])
    assert indicator.get_preview() == pytest.approx(shifted)
    indicator.update_closed(bars[period])
    assert indicator.get_latest() == pytest.approx(shifted)
