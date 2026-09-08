"""Compare streaming MACD previews with an independent weighted-sum EMA."""
import pytest

from app.data_engine.data_manager.models import BarData
from app.indicator.indicators.macd import MACDIndicator


def reference_ema(values, period):
    if len(values) < period:
        return None
    decay = 1 - 2 / (period + 1)
    tail = len(values) - period
    return (sum(values[:period]) / period * decay ** tail
            + sum(value * (1 - decay) * decay ** (len(values) - i - 1)
                  for i, value in enumerate(values) if i >= period))


@pytest.mark.parametrize('length', [1, 2, 3, 4, 5, 6, 7, 8, 12])
def test_macd_preview_matches_independent_seed_and_signal_boundaries(length):
    prices = [100, 102, 101, 105, 103, 106, 108, 104, 110, 109, 111, 107][:length]
    bars = [BarData(time=1700000000+i*60, open=v, high=v, low=v, close=v, volume=1)
            for i, v in enumerate(prices)]
    difs = [reference_ema(prices[:end], 3) - reference_ema(prices[:end], 5)
            for end in range(5, len(prices)+1)]
    dif = difs[-1] if difs else None
    dea = reference_ema(difs, 3)
    expected = {'dif': dif, 'dea': dea, 'hist': None if dea is None else 2*(dif-dea)}
    indicator = MACDIndicator({'fast': 3, 'slow': 5, 'signal': 3})
    indicator.init(bars[:-1])
    committed = indicator.get_latest()
    for _ in range(3):
        indicator.update_partial(bars[-1])
        assert indicator.get_preview() == pytest.approx(expected)
        assert indicator.get_latest() == committed
    indicator.update_closed(bars[-1])
    assert indicator.get_latest() == pytest.approx(expected)
    batch = MACDIndicator({'fast': 3, 'slow': 5, 'signal': 3})
    batch.init(bars)
    assert batch.get_latest() == pytest.approx(expected)
