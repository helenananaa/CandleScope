"""Bounded async canonical reads used by mixed backfill planning."""
import asyncio

import pytest

from app.data_engine.series_identity import KlineSeriesIdentity
from app.data_engine.storage.klines_repo import AsyncKlinesRepoAdapter
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_history_reader import row, MINUTE


def test_async_pages_keep_full_canonical_rows_and_page_without_identity_leak(mixed_query):
    engine = mixed_query
    engine.storage.upsert_bars("BTCUSDT", "1m", [row(t * MINUTE, MINUTE) for t in range(300)],
                              source="backfill", market_type="futures")
    mark = KlineSeriesIdentity.for_exchange("binance", series_variant="mark")
    engine.storage.upsert_bars("BTCUSDT", "1m", [row(300 * MINUTE, MINUTE)],
                              source="backfill", market_type="futures", series_identity=mark)
    async def read():
        storage = AsyncKlinesRepoAdapter(market_type="futures")
        first = await storage.query_canonical_page("BTCUSDT", "1m", 0, 301 * MINUTE)
        rest = await storage.query_canonical_page("BTCUSDT", "1m", first[-1]["open_time"] + 1, 301 * MINUTE)
        assert len(first) == 256 and len(rest) == 44
        assert [r["open_time"] for r in first + rest] == [t * MINUTE for t in range(300)]
        assert all(r["close_time"] == r["open_time"] + MINUTE - 1 and r["source"] == "backfill"
                   and r["trades"] == 1 and r["quote_volume"] == 2 for r in first + rest)
        bounds = ((0, 1), (300 * MINUTE, 301 * MINUTE))
        assert await storage.query_bars_range_presence("BTCUSDT", "1m", bounds) == [True, False]
        assert await storage.query_bars_range_presence("BTCUSDT", "1m", bounds,
                                                       series_identity=mark) == [False, True]
        assert await storage.query_canonical_page("BTCUSDT", "1m", 0, 301 * MINUTE,
                                                  market_type="spot") == []
    asyncio.run(read())


@pytest.mark.parametrize("limit", [0, 257, True, 1.5])
def test_async_canonical_read_refuses_unbounded_page_sizes(mixed_query, limit):
    async def read():
        with pytest.raises(ValueError, match="page limit"):
            await AsyncKlinesRepoAdapter().query_canonical_page("BTCUSDT", "1m", 0, MINUTE, limit=limit)
    asyncio.run(read())


def test_async_planning_page_does_not_repair_malformed_canonical_bounds(mixed_query):
    mixed_query.storage.upsert_bars("BTCUSDT", "1m", [{**row(MINUTE, MINUTE), "close_time": 0}],
                                   source="data_manager_closed", market_type="futures")
    async def read():
        values = await AsyncKlinesRepoAdapter(market_type="futures").query_canonical_page(
            "BTCUSDT", "1m", 0, 2 * MINUTE)
        assert len(values) == 1 and values[0]["close_time"] == 0
        assert values[0]["source"] == "data_manager_closed"
    asyncio.run(read())
