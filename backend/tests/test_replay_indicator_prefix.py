from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from threading import Event

import pytest
from app.data_engine.data_manager.models import BarData
from app.indicator.serialization import serialize_indicator_result
from app.indicator.types import IndicatorKey
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.training.indicator_checkpoint import (
    IndicatorCheckpointStore,
    new_indicator,
    normalized_parameters,
)
from app.replay.training.indicator_history import IndicatorHistoryChunk
from app.replay.training.indicator_prefix import (
    CanonicalReplayIndicators,
)

START = 1_800_000_000_000
STEP = 60_000


def bar(index: int) -> ReplayDisplayBar:
    price = Decimal(100) + Decimal(index % 23) / 10
    start = START + index * STEP
    return ReplayDisplayBar(
        open_time_ms=start,
        close_time_ms=start + STEP - 1,
        open=price,
        high=price + 2,
        low=price - 1,
        close=price + Decimal(index % 3) / 10,
        volume=Decimal(index + 1),
        quote_volume=None,
        trades=None,
        taker_buy_base=None,
        taker_buy_quote=None,
        first_base_open_ms=start,
        last_base_open_ms=start,
        component_count=1,
        expected_components=1,
        is_closed=True,
        synthetic=False,
    )


class History:
    def __init__(self, rows, *, gaps=(), epoch="epoch-a", boundary=None):
        self.rows = {item.open_time_ms: item for item in rows}
        self.origin_ms = START
        self.revealed_boundary_ms = (
            boundary if boundary is not None else rows[-1].close_time_ms
        )
        self.identity = {
            "run_id": "run-a",
            "session_id": "session-a",
            "track_id": "track-a",
            "data_epoch": epoch,
            "origin_ms": START,
            "history_epoch": "pinned-a",
            "identity": {
                "symbol": "FIXTURE",
                "display_interval": "1m",
                "exchange": "fixture",
                "market_type": "spot",
            },
        }
        self.gaps = gaps
        self.reads = []

    def read(self, start_ms, stop_before_ms):
        stop = min(stop_before_ms, start_ms + 127 * STEP)
        self.reads.append((start_ms, stop))
        rows = tuple(
            self.rows[time] for time in range(start_ms, stop, STEP) if time in self.rows
        )
        gaps = tuple(
            (max(start, start_ms), min(end, stop - 1))
            for start, end in self.gaps
            if end >= start_ms and start < stop
        )
        return IndicatorHistoryChunk(start_ms, stop, rows, gaps)


def reference(name, params, rows):
    params = normalized_parameters(name, params)
    instance = new_indicator(name, params)
    instance.retain_outputs(len(rows))
    # Compare the replay input contract against the ordinary live indicator
    # value type, rather than constructing both sides through the same adapter.
    instance.recompute([
        BarData(time=row.open_time_ms // 1000, is_closed=row.is_closed,
                **{field: float(getattr(row, field))
                   for field in ("open", "high", "low", "close", "volume")})
        for row in rows
    ])
    key = IndicatorKey(
        "FIXTURE", "1m", name, params, exchange="fixture", market_type="spot"
    )
    return serialize_indicator_result(instance.build_result(key))


def lines(payload):
    return [(line["name"], line["data"]) for line in payload["lines"]]


def ready(engine, history, name, params, window):
    progress = []
    while True:
        result = engine.compute(
            history=history, name=name, params=params, rows=tuple(window)
        )
        if result["status"] == "ready":
            return result, progress
        progress.append(result["prepared_before_ms"])
        assert len(progress) < 100
        assert len(progress) == 1 or progress[-1] > progress[-2]


@pytest.mark.parametrize("name", ["RSI", "EMA", "ATR", "MACD", "MA", "BOLL", "VOL"])
def test_different_windows_large_prefix_restart_and_seek_match_one_origin(
    tmp_path, name
):
    rows = [bar(index) for index in range(16_020)]
    history = History(rows)
    path = tmp_path / "indicators.sqlite3"
    engine = CanonicalReplayIndicators(
        IndicatorCheckpointStore(path), max_prefix_pages=16
    )
    expected = reference(name, {}, rows)
    first, progress = ready(engine, history, name, {}, rows[-200:])
    if name in {"MA", "BOLL", "VOL"}:
        assert not progress, "finite windows must not scan the historical origin"
        assert first["prefix_rows_read"] <= 19
    else:
        assert progress, "cold recursive work must yield bounded preparation progress"
    for window in (rows[-700:], rows[-10:]):
        result, _ = ready(engine, history, name, {}, window)
        end = window[0].open_time_ms // 1000
        assert lines(result["payload"]) == [
            (title, [p for p in points if p["time"] >= end])
            for title, points in lines(expected)
        ]
        assert result["prefix_rows_read"] < 4096
        assert result["seed"] == first["seed"]
    # A new process owner uses only the persisted mathematical state.
    restarted = CanonicalReplayIndicators(IndicatorCheckpointStore(path))
    restored, _ = ready(restarted, history, name, {}, rows[-200:])
    assert lines(restored["payload"]) == lines(first["payload"])
    assert restored["prefix_rows_read"] == 0
    old_window = rows[100:160]
    old, _ = ready(restarted, history, name, {}, old_window)
    assert lines(old["payload"]) == [
        (title, [p for p in points if p["time"] >= old_window[0].open_time_ms // 1000])
        for title, points in lines(reference(name, {}, rows[:160]))
    ]
    assert old["checkpoint_before_ms"] is None, "seek must not use a later checkpoint"


def test_forming_equal_millisecond_updates_never_enter_a_checkpoint(tmp_path):
    rows = [bar(index) for index in range(80)]
    tail = replace(rows[-1], is_closed=False)
    history = History(rows, boundary=tail.close_time_ms)
    cache = IndicatorCheckpointStore(tmp_path / "indicators.sqlite3")
    engine = CanonicalReplayIndicators(cache)
    for change in (Decimal(0), Decimal("0.37"), Decimal("-0.21"), Decimal(0)):
        current = replace(tail, close=tail.close + change)
        result, _ = ready(engine, history, "RSI", {}, [*rows[60:-1], current])
        expected = reference("RSI", {}, [*rows[:-1], current])
        assert lines(result["payload"]) == [
            (name, [p for p in points if p["time"] >= rows[60].open_time_ms // 1000])
            for name, points in lines(expected)
        ]
    with cache._connect() as conn:
        assert (
            conn.execute("SELECT max(before_ms) FROM checkpoints").fetchone()[0]
            == rows[60].open_time_ms
        )
    history.revealed_boundary_ms = tail.open_time_ms + 5
    with pytest.raises(ValueError, match="revealed boundary"):
        engine.compute(history=history, name="RSI", params={}, rows=tuple(rows[60:]))


def test_declared_gap_resets_state_and_missing_history_cannot_be_a_seed(tmp_path):
    rows = [bar(index) for index in range(200)]
    available = [*rows[:100], *rows[110:]]
    history = History(
        available, gaps=[(rows[100].open_time_ms, rows[109].close_time_ms)]
    )
    engine = CanonicalReplayIndicators(
        IndicatorCheckpointStore(tmp_path / "gaps.sqlite3")
    )
    result, _ = ready(engine, history, "RSI", {}, rows[-30:])
    expected = reference("RSI", {}, rows[110:])
    assert lines(result["payload"]) == [
        (name, [p for p in points if p["time"] >= rows[-30].open_time_ms // 1000])
        for name, points in lines(expected)
    ]
    broken = History(available, epoch="missing-without-gap")
    with pytest.raises(ValueError, match="undeclared prefix"):
        engine.compute(history=broken, name="RSI", params={}, rows=tuple(rows[-30:]))


def test_epochs_parameters_corrupt_cache_and_cancellation_are_isolated(tmp_path):
    rows = [bar(index) for index in range(500)]
    cache = IndicatorCheckpointStore(tmp_path / "cache.sqlite3", max_entries=3)
    engine = CanonicalReplayIndicators(cache)
    a, _ = ready(engine, History(rows), "RSI", {}, rows[-30:])
    b, _ = ready(engine, History(rows, epoch="epoch-b"), "RSI", {}, rows[-30:])
    assert b["prefix_rows_read"] == 470
    different, _ = ready(engine, History(rows), "RSI", {"period": 2}, rows[-30:])
    assert lines(different["payload"]) != lines(a["payload"])
    assert different["prefix_rows_read"] == 470
    with cache._connect() as conn:
        conn.execute("UPDATE checkpoints SET body='{}'")
    rebuilt, _ = ready(engine, History(rows), "RSI", {}, rows[-30:])
    assert lines(rebuilt["payload"]) == lines(a["payload"])
    assert rebuilt["prefix_rows_read"] == 470
    cancelled = Event()
    cancelled.set()
    with pytest.raises(InterruptedError):
        engine.compute(
            history=History(rows, epoch="cancelled"),
            name="RSI",
            params={},
            rows=tuple(rows[-30:]),
            cancelled=cancelled,
        )
    with cache._connect() as conn:
        assert conn.execute("SELECT count(*) FROM checkpoints").fetchone()[0] <= 3
