"""Local batches preserve ordinary bounded pages without eager preparation."""
from threading import Event

import pytest
from app.replay import indicator_market_columns as columns
from app.replay.training.errors import TrainingRunError
from app.replay.training.indexed_indicator_closes import (
    LocalIndicatorCloseBuffer,
    read_indexed_closes,
)
from app.replay.training.indexed_tape_context import MAX_CONTEXT_MINUTES

from tests.fixtures.replay.fakes import make_bar
from tests.test_replay_indexed_tape_context import (
    DAY,
    END,
    MINUTE,
    START,
    archive,
    history,
)
from tests.test_replay_indexed_tape_context import prepared as prepared  # noqa: PLC0414


def pin_local(repo, revision):
    for start in range(START, END, MAX_CONTEXT_MINUTES * MINUTE):
        assert repo.tape_indicator_closes_at_revision(
            revision, "BTCUSDT", "1m", start_ms=start,
            end_ms=min(END, start + MAX_CONTEXT_MINUTES * MINUTE),
            close_times=[start], exchange="binance", market_type="futures", cancelled=Event(),
        )


def context_for(repo, revision, offset=0):
    context = history(repo, revision, offset)
    context.snapshot.warmup_rows = ()
    context.revealed_boundary_ms = END + offset
    return context


@pytest.mark.parametrize("offset", [0, 946_684_800_000 - START])
def test_local_batch_pages_cover_exact_source_and_revalidate_next_worker(prepared, monkeypatch, offset):
    repo, revision, source = prepared
    pin_local(repo, revision)
    context = context_for(repo, revision, offset)
    calls = []
    original = repo.local_tape_indicator_closes_at_revision

    def local(*args, **kwargs):
        calls.append((kwargs["start_ms"], kwargs["end_ms"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(repo, "local_tape_indicator_closes_at_revision", local)
    monkeypatch.setattr(repo, "query_bars_at_revision", lambda *a, **kw: pytest.fail("prepared history downloaded again"))
    reader = LocalIndicatorCloseBuffer(context, "1m", MINUTE, Event())
    actual, cursor = [], START + offset
    while cursor < END + offset:
        page = reader.read(cursor, END + offset)
        assert 0 < len(page.bars) <= 500
        assert page.start_ms == cursor and cursor < page.stop_ms <= END + offset
        actual.extend(page.bars)
        cursor = page.stop_ms
    assert [(row.open_time_ms, float(row.close)) for row in actual] == [
        (row.open_time_ms + offset, float(row.close)) for row in source
    ]
    assert len(calls) == 2
    assert all(stop - start <= MAX_CONTEXT_MINUTES * MINUTE for start, stop in calls)
    assert reader.inputs.stop_ms == END + offset
    # New workers cannot inherit a validation receipt across disk changes.
    def corrupt(*args):
        raise ValueError("pinned checksum changed between workers")
    monkeypatch.setattr(columns, "_column", corrupt)
    with pytest.raises(TrainingRunError, match="could not be read"):
        LocalIndicatorCloseBuffer(context, "1m", MINUTE, Event()).read(START + offset, END + offset)


def test_missing_local_pin_never_eagerly_prepares_a_batch(tmp_path, monkeypatch):
    repo, revision = archive(tmp_path, [
        {**make_bar(at), "market_type": "futures"}
        for at in range(START, START + 3 * DAY, MINUTE)
    ])
    context = context_for(repo, revision)
    context.snapshot.replay_start_ms = START + 3 * DAY
    context.arguments["binding"]["history_policy"]["actual_replay_start_ms"] = START + 3 * DAY
    calls = []
    original = repo.query_bars_at_revision
    def query(*args, **kwargs):
        calls.append((kwargs["start_ms"], kwargs["end_ms"]))
        return original(*args, **kwargs)
    monkeypatch.setattr(repo, "query_bars_at_revision", query)
    args = {"start_ms": START, "end_ms": START + 3 * DAY, "close_times": [START],
            "exchange": "binance", "market_type": "futures", "cancelled": Event()}
    assert repo.local_tape_indicator_closes_at_revision(revision, "BTCUSDT", "1m", **args) is None
    assert calls == []
    reader = LocalIndicatorCloseBuffer(context, "1m", MINUTE, Event())
    first = reader.read(START, START + 3 * DAY)
    assert len(first.bars) == 500 and not reader.enabled
    assert calls == [(START, START + 500 * MINUTE - 1)]
    assert not (repo.root / "bindings" / revision[7:] / "2025-01-02.json").exists()


@pytest.mark.parametrize("interval,width", [("7m", 7), ("90m", 90), ("1M", 43_200)])
def test_buffer_preserves_partial_origin_calendar_frozen_seam_and_cancel(prepared, interval, width):
    from app.data_engine.interval_policy import compute_bucket_start_ms
    repo, revision, _ = prepared
    pin_local(repo, revision)
    context = context_for(repo, revision)
    context.origin_ms = START + 489 * MINUTE
    context.snapshot.warmup_rows = (type("Warmup", (), {"open_time_ms": START + 1001 * MINUTE})(),)
    origin = compute_bucket_start_ms(context.origin_ms, width * MINUTE, interval=interval)
    cancel = Event()
    reader = LocalIndicatorCloseBuffer(context, interval, width * MINUTE, cancel)
    ordinary = read_indexed_closes(context, origin, END, interval, width * MINUTE, cancel)
    page = reader.read(origin, END)
    assert page == ordinary
    if page is not None:
        assert all(bar.close_time_ms < context.snapshot.warmup_rows[0].open_time_ms for bar in page.bars)
        assert reader.read(page.stop_ms, END) is None
    cancel.set()
    with pytest.raises(InterruptedError):
        reader.read(origin, END)


def test_buffer_replaces_later_prefetch_when_request_moves_back(prepared):
    repo, revision, _ = prepared
    pin_local(repo, revision)
    context = context_for(repo, revision)
    reader = LocalIndicatorCloseBuffer(context, "1m", MINUTE, Event())
    first = reader.read(START, END)
    assert reader.inputs.stop_ms > first.stop_ms
    earlier = START + 120 * MINUTE
    page = reader.read(START, earlier)
    assert len(page.bars) == 120 and page.stop_ms == earlier
    assert reader.inputs.stop_ms == earlier


def test_cancel_during_prefetch_publishes_no_mathematical_checkpoint(prepared, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.replay.bars.builder import ReplayDisplayBar
    from app.replay.training.indicator_checkpoint import IndicatorCheckpointStore
    from app.replay.training.indicator_prefix import CanonicalReplayIndicators

    repo, revision, _ = prepared
    pin_local(repo, revision)
    cancel = Event()
    original = repo.local_tape_indicator_closes_at_revision
    def cancelled(*args, **kwargs):
        result = original(*args, **kwargs)
        cancel.set()
        return result
    monkeypatch.setattr(repo, "local_tape_indicator_closes_at_revision", cancelled)
    reader = LocalIndicatorCloseBuffer(context_for(repo, revision), "1m", MINUTE, cancel)
    prefix = SimpleNamespace(origin_ms=START, revealed_boundary_ms=END,
        identity={"identity": {"symbol": "BTCUSDT", "exchange": "binance", "market_type": "futures", "display_interval": "1m"}},
        read_closes=reader.read)
    before = END - MINUTE
    row = ReplayDisplayBar(before, END - 1, "100", "100", "100", "100", "0",
                           None, None, None, None, before, before, 1, 1, True)
    cache = IndicatorCheckpointStore(tmp_path / "cancelled.sqlite3")
    with pytest.raises(InterruptedError):
        CanonicalReplayIndicators(cache).compute(history=prefix, name="RSI", params={}, rows=(row,), cancelled=cancel)
    with cache._connect() as db:
        assert db.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 0
