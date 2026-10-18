from datetime import datetime, timezone
from itertools import pairwise

import pytest
from app.replay.source_bucket_projection import query_source_bucket_projection

MINUTE = 60_000
DAY = 1440 * MINUTE
START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


class MinuteRepository:
    def __init__(self, missing=None):
        self.reads = []
        self.missing = missing

    def query_bars_at_revision(self, revision, symbol, interval, *, start_ms, end_ms,
                               limit, order, exchange, market_type):
        assert interval == "1m" and order == "ASC" and limit <= 4096
        self.reads.append((revision, symbol, start_ms, end_ms))
        return [{"open_time": timestamp, "open": "10", "high": "12", "low": "9",
                 "close": "11", "volume": "1"}
                for timestamp in range(start_ms, end_ms + 1, MINUTE)
                if timestamp != self.missing]


def query(repo, end, interval="1d", revision="revision-1", symbol="SOLUSDT"):
    return query_source_bucket_projection(repo, revision, symbol, "1m", interval,
        actual_start_ms=START, actual_end_ms=end, actual_replay_start_ms=START,
        public_replay_start_ms=START, limit=3, include_partial=True,
        exchange="binance", market_type="futures")


def test_closed_market_buckets_are_reused_without_revealing_future_components():
    repo = MinuteRepository()
    full = query(repo, START + 3 * DAY)
    assert [bar["component_count"] for bar in full["bars"]] == [1440] * 3
    repo.reads.clear()
    assert query(repo, START + 3 * DAY) == full
    assert not repo.reads

    earlier = query(repo, START + DAY + 20 * MINUTE)
    assert [bar["component_count"] for bar in earlier["bars"]] == [1440, 20]
    assert earlier["bars"][-1]["is_closed"] is False
    assert earlier["bars"][-1]["volume"] == "20"
    assert max(end for _, _, _, end in repo.reads) < START + DAY + 20 * MINUTE
    assert earlier["bars"][-1]["last_base_open_ms"] == START + DAY + 19 * MINUTE


@pytest.mark.parametrize("change", ["revision", "symbol"])
def test_bucket_cache_does_not_cross_source_revisions_or_markets(change):
    repo = MinuteRepository()
    query(repo, START + DAY)
    repo.reads.clear()
    query(repo, START + DAY, **{change: "other"})
    assert repo.reads
    assert all(row[0 if change == "revision" else 1] == "other" for row in repo.reads)


def test_gap_does_not_become_a_cached_complete_bucket():
    repo = MinuteRepository(missing=START + 20 * MINUTE)
    assert query(repo, START + DAY)["bars"] == []
    repo.reads.clear()
    assert query(repo, START + DAY)["bars"] == []
    assert repo.reads


def test_leap_year_projection_exceeds_old_total_budget_but_pages_remain_bounded():
    repo = MinuteRepository()
    result = query(repo, START + 366 * DAY, interval="12M")
    assert len(result["bars"]) == 1
    bar = result["bars"][0]
    assert bar["component_count"] == bar["expected_components"] == 527040
    assert bar["volume"] == "527040"
    assert bar["is_closed"] is True
    assert all(end - start < 4096 * MINUTE for _, _, start, end in repo.reads)
    repo.reads.clear()
    assert query(repo, START + 366 * DAY, interval="12M") == result
    assert not repo.reads


@pytest.mark.parametrize("interval,components", [("4h", 240), ("1d", 1440)])
def test_remote_budget_pages_recent_complete_buckets_without_a_gap(interval, components):
    repo = MinuteRepository()
    end = START + 90 * DAY
    cursor = end
    collected = []
    for _ in range(2):
        repo.reads.clear()
        page = query_source_bucket_projection(repo, "revision-1", "SOLUSDT", "1m", interval,
            actual_start_ms=START, actual_end_ms=cursor, actual_replay_start_ms=end,
            public_replay_start_ms=end, limit=500, max_base_rows=8192,
            exchange="binance", market_type="futures")
        bars = page["bars"]
        assert len(bars) == 8192 // components
        assert page["has_more"] is True
        assert bars[-1]["close_time_ms"] == cursor - 1
        assert all(bar["component_count"] == components and bar["is_closed"] for bar in bars)
        assert sum((stop - start + 1) // MINUTE for _, _, start, stop in repo.reads) <= 8192
        cursor = bars[0]["open_time_ms"]
        collected = bars + collected
    assert all(a["close_time_ms"] + 1 == b["open_time_ms"] for a, b in pairwise(collected))


def test_remote_budget_keeps_calendar_bucket_whole_and_stops_at_listing():
    repo = MinuteRepository()
    result = query_source_bucket_projection(repo, "revision-1", "SOLUSDT", "1m", "1M",
        actual_start_ms=START, actual_end_ms=START + 31 * DAY, actual_replay_start_ms=START,
        public_replay_start_ms=START, limit=500, max_base_rows=8192,
        exchange="binance", market_type="futures")
    assert len(result["bars"]) == 1
    assert result["bars"][0]["component_count"] == 31 * 1440
    assert result["has_more"] is False


def test_remote_budget_never_uses_cached_future_tail_for_partial_bucket():
    repo = MinuteRepository()
    end = START + 10 * DAY
    common = {"actual_start_ms": START, "actual_replay_start_ms": START,
        "public_replay_start_ms": START, "limit": 500, "max_base_rows": 8192,
        "exchange": "binance", "market_type": "futures", "include_partial": True}
    query_source_bucket_projection(repo, "revision-1", "SOLUSDT", "1m", "1d", actual_end_ms=end, **common)
    result = query_source_bucket_projection(repo, "revision-1", "SOLUSDT", "1m", "1d",
        actual_end_ms=end - DAY + 7 * MINUTE, **common)
    assert result["bars"][-1]["component_count"] == 7
    assert result["bars"][-1]["volume"] == "7"
    assert result["bars"][-1]["is_closed"] is False
    assert result["bars"][-1]["last_base_open_ms"] == end - DAY + 6 * MINUTE
