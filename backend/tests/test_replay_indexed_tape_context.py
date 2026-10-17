"""Indexed official context equals scalar chart aggregation, including partial grids."""

from dataclasses import replace
from threading import Event
from time import perf_counter
from types import SimpleNamespace

import pytest
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.dataset import validate_replay_repository_bar
from app.replay.history_archive import ReplayHistoryArchiveWriter
from app.replay.official_trade_history import (
    DAY,
    MINUTE,
    OfficialTradeHistoryRepository,
)
from app.replay.shared_market_index import MarketRange
from app.replay.training.indexed_tape_context import read_indexed_context
from app.replay.training.tape_chart_builder import TapeChartBuilder

from tests.fixtures.replay.fakes import make_bar
from tests.test_official_chart_archive import START, Availability
from tests.test_replay_projection_native_seam import _batch

IDENTITY = ReplaySeriesIdentity("binance", "futures", "BTCUSDT")
END = START + 31 * DAY


def archive(root, rows):
    month = root / "months/binance/futures/BTCUSDT/2025-01"
    ReplayHistoryArchiveWriter(month).import_batches(
        IDENTITY,
        "1m",
        [_batch(rows, source_key="indexed-context", digest_character="7")],
    )
    repo = OfficialTradeHistoryRepository(
        root, Availability(), day_loader=lambda *_: month
    )
    return repo, repo.list_all_series()[0]["source_revision"]


def history(repo, revision, offset=0):
    return SimpleNamespace(
        arguments={
            "repository": repo,
            "binding": {"history_policy": {"actual_replay_start_ms": END}},
        },
        snapshot=SimpleNamespace(
            provenance=SimpleNamespace(source_revision=revision),
            replay_start_ms=END + offset,
        ),
        config=SimpleNamespace(
            base_interval="1m",
            exchange="binance",
            market_type="futures",
            symbol="BTCUSDT",
        ),
        origin_ms=START + offset,
    )


def builder(interval, offset=0):
    return TapeChartBuilder(
        base_interval="1m",
        display_interval=interval,
        replay_start_ms=END + offset,
        replay_end_time_ms=END + offset + DAY,
    )


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    rows = [
        {**make_bar(at, price=str(100 + (at // MINUTE) % 19)), "market_type": "futures"}
        for at in range(START, END, MINUTE)
    ]
    repo, revision = archive(tmp_path_factory.mktemp("indexed-official"), rows)
    validated = tuple(
        validate_replay_repository_bar(
            row,
            identity=IDENTITY,
            interval="1m",
            interval_ms=MINUTE,
            expected_open_ms=row["open_time"],
            now_ms=END,
        )
        for row in rows
    )
    return repo, revision, validated


@pytest.mark.parametrize("interval", ["15m", "90m", "4h", "1d", "1w", "1M"])
@pytest.mark.parametrize("blind", [False, True])
@pytest.mark.parametrize("include_auxiliary", [False, True])
def test_indexed_context_matches_full_scalar_partial_grid(prepared, interval, blind, include_auxiliary, monkeypatch):
    repo, revision, rows = prepared
    offset = 946_684_800_000 - START if blind else 0
    first, stop = START + 489 * MINUTE, START + 20 * DAY + 57 * MINUTE
    optimized, scalar = builder(interval, offset), builder(interval, offset)
    monkeypatch.setattr(
        MarketRange, "bound", lambda *_: pytest.fail("continuous context repeated time lookup")
    )
    MarketRange.row_visits = 0
    start = perf_counter()
    result = read_indexed_context(
        history(repo, revision, offset),
        first + offset,
        stop + offset,
        interval,
        Event(),
        include_auxiliary=include_auxiliary,
    )
    assert result is not None
    end, summaries = result
    assert end == stop + offset
    optimized.append_indexed_history(summaries)
    indexed_seconds = perf_counter() - start
    assert MarketRange.row_visits == 0
    assert len(summaries) < (stop - first) // MINUTE // 10
    start = perf_counter()
    scalar.append_history(
        replace(
            row,
            open_time_ms=row.open_time_ms + offset,
            close_time_ms=row.close_time_ms + offset,
        )
        for row in rows
        if first <= row.open_time_ms < stop
    )
    scalar_seconds = perf_counter() - start
    expected = scalar.replace_projection()
    if not include_auxiliary:
        for bar in expected["bars"]:
            for field in ("quote_volume", "trades", "taker_buy_base", "taker_buy_quote"):
                bar[field] = None
    assert optimized.replace_projection() == expected
    assert optimized.history_last_close == scalar.history_last_close
    assert optimized.previous_close == scalar.previous_close
    print(
        {
            "interval": interval,
            "blind": blind,
            "source_minutes": (stop - first) // MINUTE,
            "indexed_summaries": len(summaries),
            "indexed_seconds": indexed_seconds,
            "scalar_builder_seconds": scalar_seconds,
        }
    )


@pytest.mark.parametrize("condition", ["gap", "extreme"])
def test_indexed_context_keeps_scalar_fallback_for_gaps_and_unusual_numbers(
    tmp_path, condition
):
    rows = [
        {**make_bar(at), "market_type": "futures"}
        for at in range(START, START + DAY, MINUTE)
        if condition != "gap" or at != START + 500 * MINUTE
    ]
    if condition == "extreme":
        rows[500]["volume"] = 1e40
    repo, revision = archive(tmp_path, rows)
    assert (
        read_indexed_context(history(repo, revision), START, START + DAY, "1d", Event())
        is None
    )


def test_indexed_context_cancels_before_source_selection_and_respects_source_bounds(
    prepared,
):
    repo, revision, _ = prepared
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        read_indexed_context(history(repo, revision), START, START + DAY, "1d", cancel)
    assert (
        repo.tape_context_market_at_revision(
            revision,
            "BTCUSDT",
            "1m",
            start_ms=START - MINUTE,
            end_ms=START + DAY,
            exchange="binance",
            market_type="futures",
            cancelled=Event(),
        )
        is None
    )


@pytest.mark.parametrize("include_auxiliary", [False, True])
def test_indexed_context_cancels_between_display_buckets(prepared, monkeypatch, include_auxiliary):
    repo, revision, _ = prepared
    cancel, original, calls = Event(), MarketRange.display_summary, []
    def summary(self, start, end, **kwargs):
        calls.append((start, end))
        result = original(self, start, end, **kwargs)
        if len(calls) == 2:
            cancel.set()
        return result
    monkeypatch.setattr(MarketRange, "display_summary", summary)
    with pytest.raises(InterruptedError):
        read_indexed_context(history(repo, revision), START, START + DAY, "15m", cancel,
                             include_auxiliary=include_auxiliary)
    assert len(calls) == 2
