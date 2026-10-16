"""Cold recursive seeds never need the account extrema tree for ordinary sources."""

from threading import Event

import pytest
from app.replay import indicator_market_columns as columns
from app.replay.shared_market_index import MarketRange
from app.replay.training.errors import TrainingRunError
from app.replay.training.indexed_indicator_closes import read_indexed_closes

from tests.test_replay_indexed_tape_context import (
    DAY,
    END,
    IDENTITY,
    MINUTE,
    START,
    archive,
    builder,
    history,
)
from tests.test_replay_indexed_tape_context import (
    prepared as prepared,  # noqa: PLC0414 -- shared immutable month fixture
)


@pytest.mark.parametrize("offset", [0, 946_684_800_000 - START])
@pytest.mark.parametrize("interval,width", [("5m", 5), ("7m", 7), ("90m", 90)])
def test_cold_columns_use_exact_pinned_closes_without_account_tree(
    prepared, monkeypatch, offset, interval, width
):
    repo, revision, rows = prepared
    context = history(repo, revision, offset)
    context.snapshot.warmup_rows = ()
    context.revealed_boundary_ms = END + offset
    monkeypatch.setattr(repo, "tape_context_market_at_revision",
                        lambda *a, **k: pytest.fail("built account tree for close-only RSI seed"))
    monkeypatch.setattr(MarketRange, "row", lambda *a: pytest.fail("walked minute objects"))
    # Align a complete bucket; blind/public time uses the same source mapping.
    public = START + offset
    public += (-public) % (width * MINUTE)
    chunk = read_indexed_closes(context, public, END + offset, interval, width * MINUTE, Event())
    assert len(chunk.bars) == min(500, 32_768 // width)
    by_time = {row.open_time_ms: row for row in rows}
    for bar in chunk.bars:
        source = by_time[bar.last_base_open_ms - offset]
        assert float(bar.close) == float(source.close)
    assert chunk.stop_ms <= END + offset


def test_direct_columns_cancel_after_read_and_reject_unselected_minutes(prepared, monkeypatch):
    repo, revision, _ = prepared
    cancel = Event()
    original = columns._column

    def cancelled(*args):
        value = original(*args)
        cancel.set()
        return value

    monkeypatch.setattr(columns, "_column", cancelled)
    with pytest.raises(InterruptedError):
        repo.tape_indicator_closes_at_revision(
            revision, "BTCUSDT", "1m", start_ms=START, end_ms=START + DAY,
            close_times=[START + 4 * MINUTE], exchange="binance",
            market_type="futures", cancelled=cancel,
        )
    cancel.clear()
    monkeypatch.setattr(columns, "_column", original)
    for times in ([START - MINUTE], [START + DAY], [START + 1], [START, START]):
        assert repo.tape_indicator_closes_at_revision(
            revision, "BTCUSDT", "1m", start_ms=START, end_ms=START + DAY,
            close_times=times, exchange="binance", market_type="futures", cancelled=cancel,
        ) is None


def test_column_checksum_failure_never_silently_reseeds(prepared, monkeypatch):
    repo, revision, _ = prepared
    context = history(repo, revision)
    context.snapshot.warmup_rows = ()
    context.revealed_boundary_ms = END

    def corrupt(*args):
        raise ValueError("pinned source checksum changed")

    monkeypatch.setattr(columns, "_column", corrupt)
    with pytest.raises(TrainingRunError) as caught:
        read_indexed_closes(context, START, END, "5m", 5 * MINUTE, Event())
    assert caught.value.code == "HISTORY_SOURCE_UNAVAILABLE"


def test_cached_close_column_rechecks_changed_source_bytes(tmp_path):
    from tests.fixtures.replay.fakes import make_bar

    repo, revision = archive(tmp_path, [
        {**make_bar(at), "market_type": "futures"}
        for at in range(START, START + DAY, MINUTE)
    ])
    args = {"start_ms": START, "end_ms": START + DAY, "close_times": [START],
            "exchange": "binance", "market_type": "futures", "cancelled": Event()}
    assert repo.tape_indicator_closes_at_revision(revision, "BTCUSDT", "1m", **args)
    path = next((tmp_path / "months").rglob("*.parquet"))
    value = bytearray(path.read_bytes()); value[-1] ^= 1; path.write_bytes(value)
    with pytest.raises(Exception, match="checksum or size changed"):
        repo.tape_indicator_closes_at_revision(revision, "BTCUSDT", "1m", **args)


@pytest.mark.parametrize("name", ["RSI", "EMA", "MACD"])
def test_whole_pinned_month_math_matches_live_full_history(prepared, tmp_path, name):
    from app.replay.bars.builder import ReplayDisplayBar
    from app.replay.training.indicator_checkpoint import IndicatorCheckpointStore
    from app.replay.training.indicator_prefix import CanonicalReplayIndicators

    from tests.test_replay_indicator_prefix import lines, ready, reference

    repo, revision, source_rows = prepared
    context = history(repo, revision)
    context.snapshot.warmup_rows = ()
    context.revealed_boundary_ms = END
    scalar = builder("5m"); scalar.capacity = 10_000; scalar.append_history(source_rows)
    rows = [ReplayDisplayBar.from_dict(raw) for raw in scalar.replace_projection()["bars"]]

    class Prefix:
        origin_ms = START
        revealed_boundary_ms = END
        def __init__(self):
            self.identity = {"contract": "test-pinned-column-month", "identity": {
                **IDENTITY.to_dict(), "display_interval": "5m"}}

        def read_closes(self, start, stop):
            return read_indexed_closes(context, start, stop, "5m", 5 * MINUTE, Event())

        def read(self, *_):
            pytest.fail("ordinary pinned month fell back to per-minute account index")

    cache = tmp_path / "math.sqlite3"
    actual, _ = ready(CanonicalReplayIndicators(IndicatorCheckpointStore(cache)), Prefix(), name, {}, rows[-10:])
    expected = reference(name, {}, rows)
    assert [(key, data[-10:]) for key, data in lines(expected)] == lines(actual["payload"])
    restored, _ = ready(CanonicalReplayIndicators(IndicatorCheckpointStore(cache)), Prefix(), name, {}, rows[-10:])
    assert restored["prefix_rows_read"] == 0
    assert lines(restored["payload"]) == lines(actual["payload"])
