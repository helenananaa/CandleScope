"""Cold-path shortcuts must return exactly what the work they replace returned."""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import replace

import pytest

from app.data_engine.aggregation.adapters import chart_field_summary
from app.data_engine.backfill import mixed_plan
from app.data_engine.history import cover_plan
from app.data_engine.series_key import SeriesKey

MINUTE = 60_000


@pytest.mark.parametrize("left,right", itertools.product([
    SeriesKey("BTCUSDT", "1m", exchange="binance", market_type="futures"),
    SeriesKey("btcusdt", "1h", exchange="Binance", market_type="futures"),
    SeriesKey("BTCUSDT", "89m", exchange="binance", market_type="spot"),
    SeriesKey("ETHUSDT", "1m", exchange="binance", market_type="futures"),
    SeriesKey("BTCUSDT", "1d", exchange="okx", market_type="futures"),
    SeriesKey.create("BTCUSDT", "15m", exchange="binance", market_type="futures"),
], repeat=2))
def test_family_match_equals_replacing_the_interval(left, right):
    assert cover_plan._same_family(left, right) == (replace(left, interval=right.interval) == right)


def reference_reusable(row, width, now_ms, fields):
    """The original helper, without the value cache."""
    try:
        opened = row["open_time"]
        if (type(opened) is not int or opened % width or row.get("close_time") != opened + width - 1
                or opened + width > now_ms or not mixed_plan.source_is_trusted_final(row.get("source"))):
            return False
        if not mixed_plan.row_is_closed(row):
            return False
        values = chart_field_summary((row,), validate_ohlcv=True).project(enhanced_complete=True)
        return all(values.get(field) is not None for field in fields)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def test_cached_minute_validation_matches_k130_for_varied_rows():
    choose = random.Random(447)
    now_ms = 10_000 * MINUTE
    oddities = [None, "x", "1.5", -1.0, math.inf, math.nan, 0, 2**70, True]
    for index in range(4000):
        opened = choose.randrange(0, 200) * MINUTE + (0 if choose.random() < 0.95 else 7)
        price = choose.choice([100.0, 100, "100", 1e-9])
        row = dict(open_time=opened, close_time=opened + MINUTE - 1, open=price, high=price,
                   low=price, close=price, volume=choose.choice([1.0, 0.0, 3]),
                   quote_volume=choose.choice([100.0, None, 0.0]), trades=choose.choice([5, None, 0]),
                   taker_buy_base=choose.choice([0.5, None]), taker_buy_quote=choose.choice([50.0, None]),
                   source=choose.choice(["backfill", "backfill_rest_verified", "data_manager_exchange_closed",
                                         "data_manager", "backfill_aggregated"]),
                   is_closed=choose.choice([True, True, False]))
        if index % 7 == 0:
            row[choose.choice(["open", "high", "low", "close", "volume", "quote_volume", "trades"])] = \
                choose.choice(oddities)
        if index % 11 == 0:
            row.pop(choose.choice(["open", "taker_buy_quote", "close_time"]))
        fields = choose.choice([mixed_plan.FIELDS if hasattr(mixed_plan, "FIELDS") else ("open", "close"),
                                ("open", "high", "low", "close", "volume"),
                                ("quote_volume", "trades", "taker_buy_base", "taker_buy_quote")])
        for _ in range(2):  # the second call is served from the cache
            assert mixed_plan.reusable_component(row, MINUTE, now_ms, fields) == \
                reference_reusable(row, MINUTE, now_ms, fields), row
