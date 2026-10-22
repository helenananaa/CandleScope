from dataclasses import replace
from threading import Event

import pytest
from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.indicator.warmup import indicator_warmup_bars
from app.replay.training.indicator_checkpoint import BUILTINS, IndicatorCheckpointStore
from app.replay.training.indicator_history import IndicatorHistoryChunk
from app.replay.training.indicator_viewport import ViewportReplayIndicators

from tests.test_replay_indicator_prefix import (
    START,
    STEP,
    History,
    bar,
    lines,
    reference,
)


def compute(path, history, rows, name="RSI", params=None, **options):
    engine = ViewportReplayIndicators(IndicatorCheckpointStore(path), **options)
    for _ in range(100):
        result = engine.compute(
            history=history, name=name, params=params or {}, rows=tuple(rows)
        )
        if result["status"] == "ready":
            return result
    pytest.fail("bounded display math did not finish")


def values(result):
    return {
        title: {p["time"]: p["value"] for p in points}
        for title, points in lines(result["payload"])
    }


def overlap(a, b):
    av, bv = values(a), values(b)
    for title in av.keys() & bv.keys():
        common = av[title].keys() & bv[title].keys()
        assert common
        assert {t: av[title][t] for t in common} == {t: bv[title][t] for t in common}


@pytest.mark.parametrize(
    "name,params",
    [
        ("RSI", {}),
        ("EMA", {"period": 20}),
        ("MACD", {}),
        ("MA", {"period": 20}),
        ("BOLL", {}),
        ("ATR", {}),
        ("VOL", {}),
    ],
)
def test_cold_display_reads_only_live_warmup_and_matches_live_formula(
    tmp_path, name, params
):
    rows = [bar(i) for i in range(4000)]
    history = History(rows)
    result = compute(tmp_path / "math.db", history, rows[-128:], name, params)
    count = indicator_warmup_bars(name, params)
    assert result["prefix_rows_read"] == count
    assert all(start >= rows[-128 - count].open_time_ms for start, _ in history.reads)
    expected = reference(name, params, rows[-128 - count :])
    first = rows[-128].open_time_ms // 1000
    assert lines(result["payload"]) == [
        (title, [p for p in points if p["time"] >= first])
        for title, points in lines(expected)
    ]


@pytest.mark.parametrize("name", ["RSI", "EMA", "MACD", "MA", "BOLL", "ATR", "VOL"])
def test_pan_left_zoom_pan_right_reopen_and_color_preserve_displayed_points(
    tmp_path, name
):
    rows = [bar(i) for i in range(2400)]
    history = History(rows)
    path = tmp_path / "display.db"
    original = compute(path, history, rows[1200:1900], name)
    left = compute(path, history, rows[900:1600], name)
    overlap(original, left)
    zoom = compute(path, history, rows[1255:1800], name)
    overlap(original, zoom)
    right = compute(path, history, rows[1700:2200], name)
    overlap(original, right)
    wide = compute(path, history, rows[950:2150], name)
    for earlier in [original, left, zoom, right]:
        overlap(earlier, wide)
    reopened = compute(path, History(rows), rows[1200:1900], name)
    assert reopened["payload"] == original["payload"]
    assert reopened["prefix_rows_read"] == 0
    # Existing numerical anchors are shared across cosmetic changes.
    if name != "VOL":
        schema = BUILTINS[name].get_spec()
        colors = [p.key for p in schema.param_schema if p.type == "color"]
        if colors:
            styled = compute(
                path, history, rows[1200:1900], name, {colors[0]: "#123456"}
            )
            assert values(styled) == values(original)
            assert styled["prefix_rows_read"] == 0


def test_unseen_far_window_does_not_replay_hidden_gap_and_epoch_is_isolated(tmp_path):
    rows = [bar(i) for i in range(5000)]
    history = History(rows)
    path = tmp_path / "windows.db"
    compute(path, history, rows[100:200])
    result = compute(path, history, rows[4500:4600])
    assert result["prefix_rows_read"] == 42
    changed = compute(path, History(rows, epoch="different"), rows[4500:4600])
    assert changed["prefix_rows_read"] == 42
    assert changed["payload"] == result["payload"]


def test_period_return_preserves_values(tmp_path):
    rows = [bar(i) for i in range(1000)]
    path = tmp_path / "period.db"
    first = compute(path, History(rows), rows[500:650], params={"period": 14})
    compute(path, History(rows), rows[500:650], params={"period": 30})
    restored = compute(path, History(rows), rows[500:650], params={"period": 14})
    assert first["payload"] == restored["payload"]
    assert restored["prefix_rows_read"] == 0


def test_partial_tail_never_seeds_future_and_closed_overlap_stays_stable(tmp_path):
    rows = [bar(i) for i in range(500)]
    tail = replace(rows[-1], is_closed=False)
    history = History(rows, boundary=tail.open_time_ms + 1000)
    history.closed_before_ms = tail.open_time_ms
    path = tmp_path / "forming.db"
    first = compute(path, history, rows[350:-1] + [tail])
    tick = replace(tail, close=tail.high)
    updated = compute(path, history, rows[350:-1] + [tick])
    a, b = values(first), values(updated)
    for title in a:
        assert {t: v for t, v in a[title].items() if t < tail.open_time_ms // 1000} == {
            t: v for t, v in b[title].items() if t < tail.open_time_ms // 1000
        }
    with IndicatorCheckpointStore(path)._connect() as conn:
        assert (
            conn.execute(
                "SELECT max(before_ms) FROM display_indicator_anchors"
            ).fetchone()[0]
            <= tail.open_time_ms
        )
    with pytest.raises(ValueError, match="ahead"):
        compute(path, history, [replace(tail, open_time_ms=tail.open_time_ms + STEP)])


@pytest.mark.parametrize("interval", ["7m", "90m", "1M"])
def test_interval_roundtrip_calendar_grid_and_warmup_are_bounded(tmp_path, interval):
    width = parse_interval_ms(interval)
    start = compute_bucket_start_ms(START, width, interval=interval)
    rows = []
    for i in range(250):
        end = compute_bucket_end_ms(start, width, interval=interval)
        rows.append(
            replace(
                bar(i),
                open_time_ms=start,
                close_time_ms=end - 1,
                first_base_open_ms=start,
                last_base_open_ms=end - 60_000,
            )
        )
        start = end

    class CalendarHistory(History):
        def __init__(self):
            super().__init__(rows)
            self.origin_ms = rows[0].open_time_ms
            self.identity = {
                **self.identity,
                "origin_ms": self.origin_ms,
                "identity": {**self.identity["identity"], "display_interval": interval},
            }

        def read(self, start, stop):
            selected = tuple(
                r for r in rows if start <= r.open_time_ms and r.close_time_ms < stop
            )
            self.reads.append((start, stop))
            return IndicatorHistoryChunk(start, stop, selected)

    path = tmp_path / "calendar.db"
    h = CalendarHistory()
    original = compute(path, h, rows[100:170])
    assert original["prefix_rows_read"] == 42
    left = compute(path, h, rows[80:140])
    overlap(original, left)
    one_minute = [bar(i) for i in range(500)]
    compute(path, History(one_minute), one_minute[-100:])
    restored = compute(path, CalendarHistory(), rows[100:170])
    assert restored["payload"] == original["payload"]


def test_invalid_input_and_cancelled_prefix_do_not_publish_anchors(tmp_path):
    rows = [bar(i) for i in range(500)]
    path = tmp_path / "cancel.db"
    cache = IndicatorCheckpointStore(path)
    engine = ViewportReplayIndicators(cache)
    with pytest.raises(ValueError):
        engine.compute(
            history=History(rows),
            name="RSI",
            params={},
            rows=tuple(rows[-30:-1] + [replace(rows[-1], close="NaN")]),
        )
    cancel = Event()
    h = History(rows)
    read = h.read

    def cancelled_read(start, stop):
        chunk = read(start, stop)
        cancel.set()
        return chunk

    h.read = cancelled_read
    with pytest.raises(InterruptedError):
        engine.compute(
            history=h, name="RSI", params={}, rows=tuple(rows[-30:]), cancelled=cancel
        )
    with cache._connect() as conn:
        assert (
            conn.execute("SELECT count(*) FROM display_indicator_anchors").fetchone()[0]
            == 0
        )


def test_declared_gap_resets_math_and_left_extension_keeps_existing_tail(tmp_path):
    rows = [bar(i) for i in range(1000) if not 700 <= i < 710]
    history = History(rows, gaps=((START + 700 * STEP, START + 710 * STEP - 1),))
    window = [
        row
        for row in rows
        if START + 720 * STEP <= row.open_time_ms < START + 850 * STEP
    ]
    path = tmp_path / "gaps.db"
    result = compute(path, history, window)
    expected = reference(
        "RSI",
        {},
        [
            row
            for row in rows
            if START + 710 * STEP <= row.open_time_ms < START + 850 * STEP
        ],
    )
    first = window[0].open_time_ms // 1000
    assert lines(result["payload"]) == [
        (title, [p for p in points if p["time"] >= first])
        for title, points in lines(expected)
    ]
    extended = compute(
        path,
        history,
        [
            row
            for row in rows
            if START + 650 * STEP <= row.open_time_ms < START + 900 * STEP
        ],
    )
    overlap(result, extended)


@pytest.mark.parametrize("source", ["open", "high", "low", "hl2", "hlc3", "ohlc4"])
def test_non_close_sources_use_bounded_authoritative_bars(tmp_path, source):
    rows = [bar(i) for i in range(600)]
    result = compute(
        tmp_path / "source.db", History(rows), rows[-100:], params={"source": source}
    )
    expected = reference("RSI", {"source": source}, rows[-142:])
    first = rows[-100].open_time_ms // 1000
    assert lines(result["payload"]) == [
        (title, [p for p in points if p["time"] >= first])
        for title, points in lines(expected)
    ]


def test_slow_warmup_yields_and_new_owner_resumes_without_restarting(
    tmp_path, monkeypatch
):
    import app.replay.training.indicator_viewport as viewport

    clock = [0.0]
    monkeypatch.setattr(viewport, "monotonic", lambda: clock[0])
    rows = [bar(i) for i in range(2000)]
    history = History(rows)
    ordinary = history.read

    def read(start, stop):
        chunk = ordinary(start, stop)
        clock[0] += 0.6
        return chunk

    history.read = read
    path = tmp_path / "yield.db"
    engine = ViewportReplayIndicators(IndicatorCheckpointStore(path))
    args = {
        "history": history,
        "name": "EMA",
        "params": {"period": 200},
        "rows": tuple(rows[-100:]),
    }
    first = engine.compute(**args)
    assert first["status"] == "preparing" and first["prefix_rows_read"] == 127
    result = compute(path, history, rows[-100:], "EMA", {"period": 200})
    assert result["status"] == "ready"
    assert all(a[1] == b[0] for a, b in zip(history.reads, history.reads[1:]))
    expected = reference("EMA", {"period": 200}, rows[-1100:])
    at = rows[-100].open_time_ms // 1000
    assert lines(result["payload"]) == [
        (title, [p for p in points if p["time"] >= at])
        for title, points in lines(expected)
    ]


def test_display_does_not_read_or_rewrite_legacy_math_checkpoint_table(tmp_path):
    rows = [bar(i) for i in range(500)]
    path = tmp_path / "separate.db"
    cache = IndicatorCheckpointStore(path)
    with cache._connect() as conn:
        conn.execute(
            "INSERT INTO checkpoints VALUES (?,?,?,?)",
            ("legacy", 123, b"legacy opaque state", 456),
        )
        before = conn.execute("SELECT * FROM checkpoints").fetchall()
    compute(path, History(rows), rows[-100:])
    with cache._connect() as conn:
        assert conn.execute("SELECT * FROM checkpoints").fetchall() == before


@pytest.mark.parametrize("name", ["MACD", "VOL"])
def test_gap_keeps_histogram_colors_for_the_entire_visible_window(tmp_path, name):
    rows = [
        replace(bar(i), open=bar(i).high if i % 2 else bar(i).low)
        for i in range(1000) if not 700 <= i < 710
    ]
    history = History(rows, gaps=((START + 700 * STEP, START + 710 * STEP - 1),))
    path = tmp_path / "gap-colors.db"
    window = rows[600:900]
    result = compute(path, history, window, name)
    histogram = next(s for s in result["payload"]["series"] if s["type"] == "histogram")
    colors = {p["time"]: p["color"] for p in histogram["style"]["colorData"]}
    source = {r.open_time_ms // 1000: r for r in window}
    expected = {}
    for point in histogram["data"]:
        if point["value"] is None:
            continue
        row = source[point["time"]]
        up = row.close >= row.open if name == "VOL" else point["value"] >= 0
        expected[point["time"]] = "#22c55e" if up else "#ef4444"
    assert colors == expected
    reopened = compute(path, history, window, name)
    assert reopened["payload"] == result["payload"]
