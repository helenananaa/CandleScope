"""Close-source optimization preserves full seeds, grids, gaps and fallback."""

from dataclasses import replace
from threading import Event

import pytest
from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.shared_market_index import MarketRange
from app.replay.training.indexed_indicator_closes import read_indexed_closes
from app.replay.training.indicator_checkpoint import IndicatorCheckpointStore
from app.replay.training.indicator_history import IndicatorCloseBar, IndicatorCloseChunk
from app.replay.training.indicator_prefix import CanonicalReplayIndicators

from tests.fixtures.replay.fakes import make_bar
from tests.test_replay_indexed_tape_context import (
    DAY,
    END,
    MINUTE,
    START,
    archive,
    builder,
    history,
)
from tests.test_replay_indexed_tape_context import (
    prepared as prepared,  # noqa: PLC0414 -- re-export the shared pytest fixture
)
from tests.test_replay_indicator_prefix import History, bar, lines, ready, reference


@pytest.mark.parametrize("interval", ["15m", "90m", "4h", "1d", "1w", "1M"])
@pytest.mark.parametrize("blind", [False, True])
def test_selected_closes_equal_scalar_full_history_including_partial_origin(
    prepared, interval, blind, monkeypatch
):
    repo, revision, rows = prepared
    offset = 946_684_800_000 - START if blind else 0
    context = history(repo, revision, offset)
    context.origin_ms = START + 489 * MINUTE + offset
    context.revealed_boundary_ms = END + offset
    context.snapshot.warmup_rows = ()
    width = parse_interval_ms(interval)
    origin = compute_bucket_start_ms(context.origin_ms, width, interval=interval)
    before = compute_bucket_start_ms(END + offset, width, interval=interval)
    scalar = builder(interval, offset)
    scalar.capacity = 5000
    scalar.append_history(
        replace(
            row,
            open_time_ms=row.open_time_ms + offset,
            close_time_ms=row.close_time_ms + offset,
        )
        for row in rows
        if row.open_time_ms + offset >= context.origin_ms
    )
    expected = [
        ReplayDisplayBar.from_dict(row) for row in scalar.replace_projection()["bars"]
    ]
    monkeypatch.setattr(MarketRange, "row", lambda *_: pytest.fail("full minute scan"))
    actual, cursor, gaps = [], origin, []
    while cursor < before:
        chunk = read_indexed_closes(context, cursor, before, interval, width, Event())
        if chunk is None:
            break
        assert cursor < chunk.stop_ms <= before
        actual.extend(chunk.bars)
        gaps.extend(chunk.gaps)
        cursor = chunk.stop_ms
    fields = lambda row: (
        row.open_time_ms,
        row.close_time_ms,
        row.last_base_open_ms,
        row.close,
    )
    assert list(map(fields, actual)) == [
        fields(row) for row in expected if row.is_closed and row.close_time_ms < cursor
    ]
    if origin < context.origin_ms and cursor > origin:
        assert gaps == [
            (origin, compute_bucket_end_ms(origin, width, interval=interval) - 1)
        ]
    else:
        assert not gaps
    assert cursor == before
    assert actual or interval == "1M"


@pytest.mark.parametrize("condition", ["gap", "extreme"])
def test_close_reader_keeps_full_path_for_unproven_context(tmp_path, condition):
    rows = [
        {**make_bar(at), "market_type": "futures"}
        for at in range(START, START + DAY, MINUTE)
        if condition != "gap" or at != START + 211 * MINUTE
    ]
    if condition == "extreme":
        rows[211]["volume"] = 1e40
    repo, revision = archive(tmp_path, rows)
    context = history(repo, revision)
    context.revealed_boundary_ms = END
    context.snapshot.warmup_rows = ()
    assert (
        read_indexed_closes(context, START, START + DAY, "15m", 15 * MINUTE, Event())
        is None
    )


def test_full_calendar_bucket_larger_than_source_budget_keeps_chart_reader(prepared):
    repo, revision, _ = prepared
    context = history(repo, revision)
    context.revealed_boundary_ms = END
    context.snapshot.warmup_rows = ()
    assert (
        read_indexed_closes(context, START, END, "1M", parse_interval_ms("1M"), Event())
        is None
    )


def test_close_reader_cancels_and_never_crosses_frozen_warmup(prepared, monkeypatch):
    repo, revision, _ = prepared
    context = history(repo, revision)
    context.revealed_boundary_ms = END
    context.snapshot.warmup_rows = (
        type("Warmup", (), {"open_time_ms": START + 1001 * MINUTE})(),
    )
    chunk = read_indexed_closes(context, START, END, "90m", 90 * MINUTE, Event())
    assert chunk.stop_ms == START + 990 * MINUTE
    assert (
        read_indexed_closes(context, chunk.stop_ms, END, "90m", 90 * MINUTE, Event())
        is None
    )
    cancel = Event()
    # Exercise cancellation in the older indexed fallback independently of
    # the new direct-column reader (covered by its own cancellation test).
    monkeypatch.setattr(repo, "tape_indicator_closes_at_revision", lambda *a, **k: None)
    original = MarketRange.indicator_closes_at

    def cancelled(self, offsets, signal):
        values = original(self, offsets, signal)
        cancel.set()
        return values

    monkeypatch.setattr(MarketRange, "indicator_closes_at", cancelled)
    with pytest.raises(InterruptedError):
        read_indexed_closes(context, START, END, "15m", 15 * MINUTE, cancel)


@pytest.mark.parametrize(
    "name,source",
    [
        (name, source)
        for name in ("MA", "EMA", "RSI", "MACD", "BOLL")
        for source in ("close", "hlc3")
    ]
    + [("ATR", "close"), ("VOL", "close")],
)
def test_builtin_input_selection_matches_ordinary_reference(tmp_path, name, source):
    rows = [bar(i) for i in range(600)]
    calls = []

    class CloseHistory(History):
        def read_closes(self, start, stop):
            chunk = super().read(start, stop)
            calls.append(start)
            return IndicatorCloseChunk(
                chunk.start_ms,
                chunk.stop_ms,
                tuple(
                    IndicatorCloseBar(
                        row.open_time_ms,
                        row.close_time_ms,
                        row.last_base_open_ms,
                        str(row.close),
                    )
                    for row in chunk.bars
                ),
            )

    params = {} if name in {"ATR", "VOL"} else {"source": source}
    engine = CanonicalReplayIndicators(IndicatorCheckpointStore(tmp_path / "math.db"))
    result, _ = ready(engine, CloseHistory(rows), name, params, rows[-100:])
    expected = reference(name, params, rows)
    assert lines(result["payload"]) == [
        (key, values[-100:]) for key, values in lines(expected)
    ]
    assert bool(calls) == (source == "close" and name not in {"ATR", "VOL"})
