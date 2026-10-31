"""H127 streaming composed with D126 ownership, revision and admission."""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.data_manager.custom_query import _aggregate_fixed_bars_to_interval
from app.data_engine.data_manager.history_stream import FixedHistoryStream
from app.data_engine.data_manager.query import QueryEngine
from app.data_engine.memory_budget import MemoryBudget
from app.data_engine.interval_resolution import IntervalPurpose
from app.data_engine.storage import klines_repo
from tests.test_custom_history_streaming import rows


SOURCE_MS = 900_000


def write(bars):
    return klines_repo.upsert_klines("BTCUSDT", "15m", [dict(
        open_time=bar.time_ms, close_time=bar.time_ms + SOURCE_MS - 1,
        open=bar.open, high=bar.high, low=bar.low, close=bar.close,
        volume=bar.volume, quote_volume=bar.quote_volume, trades=bar.trades,
        taker_buy_base=bar.taker_buy_base, taker_buy_quote=bar.taker_buy_quote,
    ) for bar in bars], source="backfill", market_type="futures")


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "history.sqlite")
    klines_repo.init_klines_storage()
    write(rows(72, 900))
    query = QueryEngine(BarCache(), klines_repo.KlinesRepoAdapter(), QueryConfig(
        default_limit=8, max_limit=11, auto_backfill=False,
    ))
    budget = MemoryBudget(2 * 1024 * 1024)
    budget.register("history-query", limit_bytes=budget.total_bytes,
                    usage=lambda: {"estimated_bytes": 0})
    query.memory_budget = budget
    # Provider discovery must finish before entering a timed interleaving.
    query._interval_resolver.resolve(exchange="binance", market_type="futures",
                                    interval="45m", purpose=IntervalPurpose.HISTORY)
    return query


def query(engine, direction="before"):
    if direction == "before":
        return engine.query_before("BTCUSDT", "45m", 72 * SOURCE_MS, limit=8,
                                   market_type="futures", auto_backfill=False)
    return engine.query("BTCUSDT", "45m", start_ms=48 * SOURCE_MS,
                        end_ms=69 * SOURCE_MS, limit=8,
                        market_type="futures", auto_backfill=False)


@pytest.mark.parametrize("direction", ["range", "before"])
@pytest.mark.parametrize("mutation", ["correct", "delete"])
def test_cross_page_change_discards_outputs_and_cannot_materialize_stale_rows(
    engine, monkeypatch, direction, mutation,
):
    reduced, release = threading.Event(), threading.Event()
    original = FixedHistoryStream.push
    once = True

    def pause(stream, bars):
        nonlocal once
        original(stream, bars)
        if once:
            once = False
            assert stream.targets_desc
            reduced.set()
            assert release.wait(10)

    monkeypatch.setattr(FixedHistoryStream, "push", pause)
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(query, engine, direction)
        try:
            assert reduced.wait(10)
            changed = rows(72, 900)[69]
            if mutation == "correct":
                write([replace(changed, high=999, volume=12345)])
            else:
                engine.storage.delete_bars("BTCUSDT", "15m", changed.time_ms,
                                           changed.time_ms, market_type="futures")
        finally:
            release.set()
        result = future.result(10)
    assert result.bars == [] and result.retryable and result.history_state == "pending"
    assert klines_repo.query_klines("BTCUSDT", "45m", market_type="futures") == []
    assert engine.memory_budget.snapshot()["reserved_bytes"] == 0
    fresh = query(engine, direction)
    if mutation == "correct":
        assert fresh.bars and fresh.bars[-1].high == 999
    else:
        assert not fresh.complete


def test_stream_admission_precedes_source_read_and_releases_for_retry(engine, monkeypatch):
    engine.memory_budget.total_bytes = 1
    calls = []
    original = engine.custom_intervals._base_query_before
    def observe(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(engine.custom_intervals, "_base_query_before", observe)
    result = query(engine)
    assert result.bars == [] and result.retryable
    assert result.metadata["memory_budget_deferred"]
    assert calls == [] and engine.memory_budget.snapshot()["reserved_bytes"] == 0
    engine.memory_budget.total_bytes = 2 * 1024 * 1024
    assert query(engine).complete


def test_stream_lease_remains_until_materialization_then_releases(engine, monkeypatch):
    observed = []
    original = engine.custom_intervals._target_writer
    def observe(*args, **kwargs):
        observed.append(engine.memory_budget.snapshot()["reserved_bytes"])
        return original(*args, **kwargs)
    monkeypatch.setattr(engine.custom_intervals, "_target_writer", observe)
    result = query(engine)
    assert result.complete and result.metadata["base_stream_reserved_bytes"] > 0
    assert observed and min(observed) > 0
    assert engine.memory_budget.snapshot()["reserved_bytes"] == 0
    assert not hasattr(engine.custom_intervals, "_aggregate_blocks")


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_stream_failure_releases_outer_query_lease(engine, monkeypatch, failure):
    def fail(*args, **kwargs):
        assert engine.memory_budget.snapshot()["reserved_bytes"] > 0
        raise failure("interrupted source")
    monkeypatch.setattr(engine.custom_intervals, "_base_query_before", fail)
    with pytest.raises(failure, match="interrupted source"):
        query(engine)
    assert engine.memory_budget.snapshot()["reserved_bytes"] == 0
    assert engine.custom_intervals._flights == {}
    assert engine.custom_intervals._base_window_flights == []


@pytest.mark.parametrize("page_size", [1, 7, 11])
def test_anchor_phase_is_shared_by_stream_boundary_and_canonical_reducer(page_size):
    source = rows(90, 60)
    reduce = lambda items: _aggregate_fixed_bars_to_interval(
        items, 900, source_interval_seconds=60, phase_seconds=300,
    )
    stream = FixedHistoryStream(900, reduce, phase_seconds=300)
    for end in range(len(source), 0, -page_size):
        stream.push(source[max(0, end - page_size):end])
    actual, _ = stream.finish()
    assert actual == reduce(source)


def test_custom_bulk_reducer_preserves_anchor_phase(engine):
    source = rows(90, 60)
    expected = _aggregate_fixed_bars_to_interval(source, 900,
        source_interval_seconds=60, phase_seconds=300)
    assert engine.custom_intervals.aggregate_custom_bars(
        source, "BTCUSDT", "15m~a1~300000", source_interval="1m",
    ) == expected
