from copy import deepcopy
import json
import pytest
from app.data_engine.synthetic_series.events import ChartEventSeries
from app.data_engine.synthetic_series.core import SyntheticError


def visible(i, price):
    return dict(
        open_time_ms=0,
        close_time_ms=59999,
        open=100,
        high=max(100, price),
        low=min(100, price),
        close=price,
        volume=i,
    )


def test_renko_true_observed_path_multi_bricks_and_volume_survive_restore():
    series = ChartEventSeries(dict(transform="renko", box_size=2, min_tick=1))
    emitted = []
    for key, price, qty in [(1, 100, 1), (2, 101, 1), (3, 106, 3), (4, 107, 2), (5, 108, 4)]:
        series.update(visible(key, price), key * 1000, key, quantity=qty)
        rows = list(series.observations(key * 1000, preview=True))
        emitted.extend(row for row in rows if row["confirmed"])
        clone = ChartEventSeries(series.definition)
        clone.restore(json.loads(json.dumps(series.snapshot())))
        assert clone.snapshot() == series.snapshot()
    assert [float(row["bar"]["close"]) for row in emitted] == [102, 104, 106, 108]
    assert sum(float(row["bar"]["volume"]) for row in emitted) == pytest.approx(11)
    assert [row["ordinal"] for row in emitted] == [0, 1, 2, 3]
    assert emitted[0]["available_time_ms"] == 3000
    assert emitted[1]["bar"]["open_time_ms"] == emitted[2]["bar"]["open_time_ms"] == 3000
    saved = series.snapshot()
    with pytest.raises(SyntheticError):
        series.update(visible(1, 100), 1000, 1, quantity=1)
    assert series.snapshot() == saved


@pytest.mark.parametrize(
    "transform", ["heikin-ashi", "renko", "point-and-figure", "kagi", "line-break"]
)
@pytest.mark.parametrize("mode", ["traditional", "atr"])
def test_event_prefix_is_future_independent_and_checkpoints_own_forming_state(transform, mode):
    definition = dict(
        transform=transform, mode=mode, box_size=2, min_tick=1, reversal_amount=2, atr_length=3
    )
    series = ChartEventSeries(definition)
    for key, price in enumerate([100, 101, 106, 108, 100, 104], 1):
        series.update(visible(key, price), key * 1000, key, quantity=1)
        list(series.observations(key * 1000, preview=True))
    prefix = deepcopy(series.snapshot())
    clone = ChartEventSeries(definition)
    clone.restore(prefix)
    series.update(visible(7, 200), 7000, 7, quantity=1)
    clone.update(visible(7, 200), 7000, 7, quantity=1)
    assert list(series.observations(7000, preview=True)) == list(
        clone.observations(7000, preview=True)
    )
    assert prefix != series.snapshot()
    assert len(json.dumps(series.snapshot())) < 10000


def test_ha_previews_recompute_from_confirmed_source_state_and_atr_counts_source_closes():
    series = ChartEventSeries(dict(transform="heikin-ashi"))
    row = visible(1, 104)
    series.update(row, 1000, 1, quantity=1)
    first = list(series.observations(1000, preview=True))[-1]
    row = visible(2, 102)
    row["high"] = 104
    series.update(row, 2000, 2, quantity=1)
    second = list(series.observations(2000, preview=True))[-1]
    assert first["ordinal"] == second["ordinal"] == 0
    assert series.count == 0 and series.source.atr_count == 0
    assert float(second["bar"]["open"]) == 101
    assert float(second["bar"]["close"]) == 101.5
    series.close_source(row, 59999)
    closed = list(series.observations(59999, preview=False))
    assert len(closed) == 1 and closed[0]["confirmed"]
    assert series.count == series.source.atr_count == 1
