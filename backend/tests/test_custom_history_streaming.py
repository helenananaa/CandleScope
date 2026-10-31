from __future__ import annotations

import time
import asyncio
import threading
import weakref
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.data_manager.custom_query import (
    CustomIntervalQueryService, _aggregate_fixed_bars_to_interval,
)
from app.data_engine.data_manager.history_stream import FixedHistoryStream, StreamingOrderError
from app.data_engine.data_manager.models import BarData, MissingRange, QueryResult, QuerySource
from app.data_engine.data_manager.query import QueryEngine
from app.data_engine.interval_policy import parse_interval_ms
from app.data_engine.storage import klines_repo


REGULAR = [("45m", "15m", 3), ("90m", "30m", 3), ("2d", "1d", 2),
           ("3d", "3d", 1), ("4d", "1d", 4), ("5d", "1d", 5)]


def rows(count, width=60):
    return [BarData(
        time=index * width,
        open=1 + index % 19 / 11, high=4 + index % 7 / 11,
        low=0.5, close=1 + index % 13 / 11,
        volume=1e8 if index % 17 == 0 else 0.00000003 + index / 13,
        quote_volume=5e8 if index % 17 == 0 else 0.00000007 + index / 3,
        trades=index % 23, taker_buy_base=0.00000001,
        taker_buy_quote=0.00000003, source="backfill",
    ) for index in range(count)]


@pytest.mark.parametrize("factor", [2, 3, 4, 5, 10007])
@pytest.mark.parametrize("page_size", [1, 7, 127])
def test_descending_pages_preserve_exact_canonical_math(factor, page_size):
    # 10007 is only a stress case; it deliberately splits a bucket many times.
    base = rows(factor * (2 if factor == 10007 else 29))
    base[3] = replace(base[3], quote_volume=None, taker_buy_quote=None)
    base[-1] = replace(base[-1], is_closed=False)
    reduce = lambda items: _aggregate_fixed_bars_to_interval(
        items, factor * 60, source_interval_seconds=60,
    )
    stream = FixedHistoryStream(factor * 60, reduce)
    for end in range(len(base), 0, -page_size):
        # Each page may be unordered; page order itself moves backward.
        stream.push(list(reversed(base[max(0, end - page_size):end])))
    actual, _ = stream.finish()
    assert actual == reduce(base)
    assert stream.unique_rows == len(base)
    assert stream.peak_buffered_rows <= page_size + factor


def test_overlap_within_held_bucket_uses_stronger_source_and_preserves_equal_authority():
    base = rows(12)
    reduce = lambda items: _aggregate_fixed_bars_to_interval(items, 4 * 60, source_interval_seconds=60)
    stream = FixedHistoryStream(4 * 60, reduce)
    weak = replace(base[6], source="unknown", volume=99)
    stream.push([weak, *base[7:]])
    stream.push([*base[:7], replace(base[7], volume=999)])
    actual, _ = stream.finish()
    assert actual == reduce(base)
    assert stream.unique_rows == len(base)


def test_overlap_revising_a_reduced_bucket_is_rejected_before_mutating_stream():
    base = rows(12)
    stream = FixedHistoryStream(180, lambda items: _aggregate_fixed_bars_to_interval(
        items, 180, source_interval_seconds=60,
    ))
    stream.push(base[4:])
    previous = list(stream.targets_desc)
    with pytest.raises(StreamingOrderError):
        stream.push([*base[:4], replace(base[-1], volume=777)])
    assert stream.targets_desc == previous


@pytest.mark.parametrize("interval,base,factor", REGULAR)
@pytest.mark.parametrize("direction", ["range", "before"])
def test_regular_sqlite_history_matches_batch_and_materializes(monkeypatch, tmp_path, interval, base, factor, direction):
    results = []
    for enabled in [False, True]:
        monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / f"{enabled}.sqlite")
        klines_repo.init_klines_storage()
        source_ms = parse_interval_ms(base)
        target_ms = parse_interval_ms(interval)
        assert source_ms and target_ms
        source = rows(20 * factor, source_ms // 1000)
        klines_repo.upsert_klines("BTCUSDT", base, [dict(
            open_time=bar.time_ms, close_time=bar.time_ms + source_ms - 1,
            open=bar.open, high=bar.high, low=bar.low, close=bar.close,
            volume=bar.volume, quote_volume=bar.quote_volume, trades=bar.trades,
            taker_buy_base=bar.taker_buy_base, taker_buy_quote=bar.taker_buy_quote,
        ) for bar in source], source="backfill", exchange="binance", market_type="futures")
        engine = QueryEngine(BarCache(), klines_repo.KlinesRepoAdapter(), QueryConfig(
            default_limit=8, max_limit=11, auto_backfill=False, stream_custom_history=enabled,
        ))
        if direction == "range":
            result = engine.query("BTCUSDT", interval, start_ms=12 * target_ms,
                                  end_ms=19 * target_ms, limit=8, market_type="futures")
        else:
            result = engine.query_before("BTCUSDT", interval, before_ms=20 * target_ms,
                                         limit=8, market_type="futures")
        assert len(result.bars) == 8 and all(bar.trusted_final for bar in result.bars)
        assert result.complete and not result.retryable and not result.missing_ranges
        if factor > 1:
            assert result.metadata.get("base_streaming", False) is enabled
            assert result.metadata["target_materialized_written"] >= 8
            if enabled:
                assert result.metadata["base_stream_peak_buffered_rows"] <= 11 + factor
            fresh = QueryEngine(BarCache(), klines_repo.KlinesRepoAdapter(), QueryConfig(auto_backfill=False))
            reused = fresh.query("BTCUSDT", interval, start_ms=12 * target_ms,
                                 end_ms=19 * target_ms, limit=8, market_type="futures")
            assert reused.bars == result.bars
            assert reused.metadata["base_storage_reads"] == 0
        results.append(result)
    assert results[0].bars == results[1].bars
    for field in ["complete", "retryable", "history_state", "missing_ranges", "has_tail_gap", "excluded_ranges"]:
        assert getattr(results[0], field) == getattr(results[1], field)


def service_for(base, *, enabled, case="ready", page_size=7, writer=None, on_read=None):
    def read(symbol, interval, *, before_ms, limit):
        selected = [bar for bar in base if bar.time_ms < before_ms][-limit:]
        if on_read:
            on_read(selected)
        gap = MissingRange("BTCUSDT", "15m", 12 * 900_000, 12 * 900_000)
        missing = [gap] if case == "gap" and selected and selected[0].time_ms <= gap.start_ms <= selected[-1].time_ms else []
        final = all(bar.trusted_final for bar in selected)
        return QueryResult(
            bars=selected, symbol=symbol, interval=interval, source=QuerySource.STORAGE,
            total=len(selected), has_more=bool(selected and selected[0].time > base[0].time),
            complete=not missing and final, retryable=bool(missing) or not final,
            history_state="pending" if missing or not final else "ready",
            missing_ranges=missing, metadata={"all_rows_final": final, "storage_reads": 1,
                                             "storage_rows": len(selected)},
        )

    return CustomIntervalQueryService(
        cache=BarCache(), config=QueryConfig(max_limit=page_size, stream_custom_history=enabled),
        base_query=lambda symbol, interval, **kw: read(symbol, interval,
            before_ms=kw["end_ms"] + 1, limit=kw["limit"]),
        base_query_before=lambda symbol, interval, before_ms, limit, **kw: read(
            symbol, interval, before_ms=before_ms, limit=limit),
        target_writer=writer,
    )


@pytest.mark.parametrize("case", ["ready", "gap", "untrusted", "forming", "partial_prefix"])
def test_stream_quality_and_boundary_semantics_match_batch(case):
    base = rows(30, 900)
    if case == "gap":
        del base[12]
    elif case == "untrusted":
        base[12] = replace(base[12], source="unknown")
    elif case == "forming":
        base[-1] = replace(base[-1], is_closed=False)
    elif case == "partial_prefix":
        base = base[1:]
    results = []
    writes = []
    for enabled in [False, True]:
        written = []
        service = service_for(base, enabled=enabled, case=case,
                              writer=lambda *args, **kw: written.extend(args[2]) or len(args[2]))
        result = service.query_from_base(symbol="BTCUSDT", interval="45m", start_ms=0,
            end_ms=9 * 2700_000, limit=7, started_at=time.monotonic())
        results.append(result)
        writes.append(written)
    assert results[0].bars == results[1].bars
    assert writes[0] == writes[1]
    for field in ["complete", "retryable", "history_state", "missing_ranges", "has_more"]:
        assert getattr(results[0], field) == getattr(results[1], field)
    if case in ["gap", "untrusted", "forming"]:
        assert writes == [[], []]


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_stream_reduces_before_reading_next_page_and_stops_on_read_failure(monkeypatch, failure):
    from app.data_engine.data_manager import custom_query
    reduced = []
    original = custom_query.CustomIntervalQueryService._aggregate_fixed
    def reduce(*args, **kwargs):
        result = original(*args, **kwargs)
        reduced.extend(result)
        return result
    monkeypatch.setattr(custom_query.CustomIntervalQueryService, "_aggregate_fixed", reduce)
    reads = []
    writes = []
    def observe(selected):
        reads.append(len(selected))
        if len(reads) == 2:
            assert reduced, "page one must be reduced before page two is pulled"
            raise failure("source read failed")
    service = service_for(rows(30, 900), enabled=True, on_read=observe,
                          writer=lambda *a, **kw: writes.append(a) or 0)
    with pytest.raises(failure, match="source read failed"):
        service.query_before("BTCUSDT", "45m", 30 * 900_000, limit=7)
    assert len(reads) == 2 and writes == []
    assert service._flights == {} and service._base_window_flights == []


def test_write_failure_leaves_stream_result_usable_and_releases_materialization():
    writes = []
    def writer(*args, **kwargs):
        writes.append(args[2])
        if len(writes) == 1:
            raise OSError("write failed")
        return len(args[2])
    service = service_for(rows(30, 900), enabled=True, writer=writer)
    first = service.query_before("BTCUSDT", "45m", 30 * 900_000, limit=7)
    second = service.query_before("BTCUSDT", "45m", 30 * 900_000, limit=7)
    assert first.bars == second.bars
    assert first.metadata["target_materialization_role"] == "owner_failed"
    assert second.metadata["target_materialization_role"] == "owner"


def test_non_directional_overlap_replays_batch_before_any_write_and_counts_retry_reads():
    base = rows(30, 900)
    results = []
    for enabled in [False, True]:
        reads = []
        writes = []
        def overlap(selected):
            reads.append(len(selected))
            if selected and selected[-1].time < base[-1].time:
                selected.append(replace(base[-1], volume=999))
        service = service_for(base, enabled=enabled, on_read=overlap,
                              writer=lambda *a, **kw: writes.append(a[2]) or len(a[2]))
        result = service.query_before("BTCUSDT", "45m", 30 * 900_000, limit=7)
        if enabled:
            assert "reduced bucket" in result.metadata["base_stream_fallback_reason"]
            assert result.metadata["base_stream_fallback_page_count"] == 2
        assert result.metadata["base_page_count"] == len(reads)
        assert result.metadata["base_storage_reads"] == len(reads)
        assert len(writes) == 1
        results.append(result)
    assert results[0].bars == results[1].bars


def test_cross_interval_streams_share_an_exact_source_page(monkeypatch):
    from app.data_engine.data_manager import custom_query
    entered = threading.Event()
    joined = threading.Event()
    release = threading.Event()
    class ObservedFuture(Future):
        def result(self, timeout=None):
            joined.set()
            return super().result(timeout=timeout)
    monkeypatch.setattr(custom_query, "Future", ObservedFuture)
    calls = []
    base = rows(60, 86400)
    def read(symbol, interval, before_ms, limit, **kwargs):
        calls.append((before_ms, limit))
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=3)
        selected = [bar for bar in base if bar.time_ms < before_ms][-limit:]
        return QueryResult(bars=selected, total=len(selected), has_more=True,
                           complete=True, metadata={"all_rows_final": True})
    service = CustomIntervalQueryService(cache=BarCache(), config=QueryConfig(max_limit=7),
        base_query=lambda *a, **kw: QueryResult(), base_query_before=read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(service.query_before, "BTCUSDT", "4d", 60 * 86400_000, 7)
        assert entered.wait(timeout=2)
        waiter = pool.submit(service.query_before, "BTCUSDT", "5d", 60 * 86400_000, 7)
        try:
            assert joined.wait(timeout=2), "the second interval should join the live source page"
        finally:
            release.set()
        first = owner.result(timeout=3)
        second = waiter.result(timeout=3)
    assert first.metadata["base_streaming"] and second.metadata["base_streaming"]
    assert calls.count((60 * 86400_000, 7)) == 1
    assert service.snapshot()["base_window_flight_joins"] >= 1
    assert service._base_window_flights == []


def test_listing_boundary_keeps_its_source_proof_after_older_pages_are_released():
    results = []
    for enabled in [False, True]:
        service = service_for(rows(30, 900)[1:], enabled=enabled)
        def annotate(read):
            def wrapped(*args, **kwargs):
                result = read(*args, **kwargs)
                result.earliest_available_ms = 900_000
                result.excluded_ranges = [{"start_ms": 0, "end_ms": 899_999,
                                           "disposition": "terminal", "reason": "source_exhausted"}]
                if not result.has_more:
                    result.history_state = "exhausted"
                return result
            return wrapped
        service._base_query = annotate(service._base_query)
        service._base_query_before = annotate(service._base_query_before)
        result = service.query_from_base(symbol="BTCUSDT", interval="45m", start_ms=0,
            end_ms=3 * 2700_000, limit=4, started_at=time.monotonic())
        assert result.bars[0].time_ms == 0 and result.bars[0].trusted_final
        assert result.bars[0].trades == 3
        results.append(result)
    assert results[0].bars == results[1].bars
    assert results[0].excluded_ranges == results[1].excluded_ranges


def test_overlap_fallback_shares_the_original_page_budget(monkeypatch):
    from app.data_engine.data_manager import custom_query
    monkeypatch.setattr(custom_query, "_MAX_CUSTOM_BASE_PAGES", 4)
    base = rows(120, 900)
    calls = []
    def overlap(selected):
        calls.append(len(selected))
        if selected and selected[-1].time < base[-1].time:
            selected.append(base[-1])
    service = service_for(base, enabled=True, on_read=overlap)
    result = service.query_before("BTCUSDT", "45m", 120 * 900_000, limit=7)
    assert len(calls) == 4
    assert result.metadata["base_page_count"] == 4
    assert result.metadata["base_pagination_capped"] is True
    assert result.missing_ranges == [] and result.retryable is False


def test_calendar_and_non_tiling_sources_do_not_enter_fixed_stream():
    service = service_for([], enabled=True)
    assert not service._can_stream_history("2M", None, source_interval="1M")
    assert not service._can_stream_history("60d", None, source_interval="1M")
    assert not service._can_stream_history("45m", None, source_interval="30m")


def test_completed_source_pages_are_released_before_the_next_read():
    class TrackedBar(BarData):
        pass
    references = []
    calls = []
    def read(symbol, interval, before_ms, limit, **kwargs):
        # Only the bucket straddling the page boundary may survive. This
        # observes object lifetime across actual page reads, not just counters.
        assert sum(reference() is not None for reference in references) <= 3
        end = before_ms // 900_000
        selected = [TrackedBar(time=index * 900, open=1, high=2, low=1,
                               close=2, volume=1, source="backfill")
                    for index in range(end - limit, end)]
        references.extend(weakref.ref(bar) for bar in selected)
        calls.append(limit)
        return QueryResult(bars=selected, total=len(selected), has_more=True,
                           complete=True, metadata={"all_rows_final": True})
    service = CustomIntervalQueryService(cache=BarCache(), config=QueryConfig(max_limit=11),
        base_query=lambda *a, **kw: QueryResult(), base_query_before=read)
    result = service.query_before("BTCUSDT", "45m", 90 * 900_000, limit=11)
    assert len(calls) == 4 and len(result.bars) == 11
    assert all(reference() is None for reference in references)
