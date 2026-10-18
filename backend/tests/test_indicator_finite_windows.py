from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.data_engine.data_manager.models import BarData
from app.data_engine.interval_policy import compute_bucket_end_ms, parse_interval_ms
from app.indicator.indicators.boll import BOLLIndicator
from app.indicator.indicators.ma import MAIndicator
from app.replay.training.indicator_checkpoint import IndicatorCheckpointStore
from app.replay.training.indicator_history import IndicatorHistoryChunk
from app.replay.training.indicator_prefix import CanonicalReplayIndicators, prefix_start

from tests.test_replay_indicator_prefix import (
    START,
    STEP,
    History,
    bar,
    lines,
    ready,
    reference,
)


@pytest.mark.parametrize("kind,period", [(MAIndicator, 1), (MAIndicator, 20), (MAIndicator, 500), (BOLLIndicator, 2), (BOLLIndicator, 200)])
@pytest.mark.parametrize("price", [0.000001, 100_000.0, 1_000_000_000_000.0])
def test_finite_values_depend_only_on_current_window_including_previews(kind, period, price):
    values = [price + (i % 17 - 8) * price * 1e-7 for i in range(period + 231)]
    rows = [BarData(time=i * 60, open=v, high=v, low=v, close=v, volume=1) for i, v in enumerate(values)]
    full = kind({"period": period})
    full.init(rows[:-1])
    previous = full.get_latest()
    short = kind({"period": period})
    short.init(rows[-period:])
    for _ in range(3):
        full.update_partial(rows[-1])
        assert full.get_preview() == short.get_latest()
        assert full.get_latest() == previous
    full.update_closed(rows[-1])
    assert full.get_latest() == short.get_latest()
    exact = sum(Decimal.from_float(v) for v in values[-period:]) / period
    mean = full.get_latest()["ma" if kind is MAIndicator else "middle"]
    assert mean == pytest.approx(float(exact), rel=2e-16, abs=1e-20)


@pytest.mark.parametrize("name,period", [("MA", 1), ("MA", 500), ("BOLL", 2), ("BOLL", 200), ("VOL", None)])
@pytest.mark.parametrize("source", ["close", "hlc3"])
def test_finite_prefix_never_requests_old_history_and_survives_restart(tmp_path, name, period, source):
    rows = [bar(i) for i in range(1600)]
    params = {} if period is None else {"period": period, "source": source}
    history = History(rows)
    lower = rows[1200].open_time_ms - (0 if period is None else period - 1) * STEP
    original_read = history.read

    def recent_only(start, stop):
        assert start >= lower, "old archive download must not be requested"
        return original_read(start, stop)

    history.read = recent_only
    path = tmp_path / "finite.sqlite3"
    result, _ = ready(CanonicalReplayIndicators(IndicatorCheckpointStore(path)), history, name, params, rows[1200:])
    assert result["prefix_rows_read"] == (0 if period is None else period - 1)
    expected = reference(name, params, rows)
    assert lines(result["payload"]) == [(title, [p for p in points if p["time"] >= rows[1200].open_time_ms // 1000]) for title, points in lines(expected)]
    restarted, _ = ready(CanonicalReplayIndicators(IndicatorCheckpointStore(path)), history, name, params, rows[1200:])
    assert restarted["prefix_rows_read"] == 0
    assert restarted["payload"] == result["payload"]


def timestamp(year, month=1, day=1):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


@pytest.mark.parametrize("interval,before,expected", [
    ("7m", START + 1000 * 420_000, START + 981 * 420_000),
    ("90m", START + 1000 * 5_400_000, START + 981 * 5_400_000),
    ("1w", timestamp(2026, 10, 12), timestamp(2026, 6, 1)),
    ("1M", timestamp(2026, 10), timestamp(2025, 3)),
    ("12M", timestamp(2026), timestamp(2007)),
])
def test_finite_lookback_respects_duration_and_calendar_boundaries(interval, before, expected):
    history = SimpleNamespace(origin_ms=0, identity={"identity": {"display_interval": interval}})
    assert prefix_start(history, "MA", {"period": 20}, before) == expected
    history.origin_ms = before - 1
    assert prefix_start(history, "BOLL", {"period": 20}, before) == before - 1


@pytest.mark.parametrize("name", ["MA", "BOLL"])
def test_gap_in_required_window_resets_warmup_without_reaching_before_gap(tmp_path, name):
    rows = [bar(i) for i in range(100) if i != 75]
    history = History(rows, gaps=((START + 75 * STEP, START + 76 * STEP - 1),))
    result, _ = ready(CanonicalReplayIndicators(IndicatorCheckpointStore(tmp_path / "gap.sqlite3")), history, name, {"period": 20}, rows[-10:])
    expected = reference(name, {"period": 20}, [row for row in rows if row.open_time_ms >= START + 76 * STEP])
    assert lines(result["payload"]) == lines(expected)


@pytest.mark.parametrize("interval", ["1M", "12M"])
def test_calendar_prefix_result_matches_full_origin(tmp_path, interval):
    start, width = timestamp(2000), parse_interval_ms(interval)
    rows = []
    for i in range(35):
        end = compute_bucket_end_ms(start, width, interval=interval)
        rows.append(replace(bar(i), open_time_ms=start, close_time_ms=end - 1, first_base_open_ms=start, last_base_open_ms=start))
        start = end
    history = History(rows)
    history.origin_ms = rows[0].open_time_ms
    history.identity["identity"]["display_interval"] = interval
    history.read = lambda start, stop: IndicatorHistoryChunk(start, stop, tuple(row for row in rows if start <= row.open_time_ms < stop))
    result, _ = ready(CanonicalReplayIndicators(IndicatorCheckpointStore(tmp_path / "calendar.sqlite3")), history, "MA", {}, rows[-5:])
    expected = reference("MA", {}, rows)
    assert result["prefix_rows_read"] == 19
    assert lines(result["payload"]) == [(title, [p for p in points if p["time"] >= rows[-5].open_time_ms // 1000]) for title, points in lines(expected)]
