import time
from datetime import datetime, timezone

import pytest

from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.data_manager.custom_query import CustomIntervalQueryService
from app.data_engine.data_manager.models import BarData, QueryResult, QuerySource
from app.data_engine.interval_policy import parse_interval_spec
from app.data_engine.interval_resolution import (
    IntervalPurpose,
    IntervalRoute,
    IntervalRouteKind,
)


def timestamp(year, month):
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp()) * 1000


@pytest.mark.parametrize(
    "case", ["listing", "no_proof", "cooldown", "gap", "untrusted", "forming"]
)
def test_annual_listing_bucket_requires_final_contiguous_source_and_exhaustion(case):
    rows = [
        BarData(
            time=timestamp(2017, month) // 1000,
            open=month,
            high=month + 1,
            low=month - 1,
            close=month + 0.5,
            volume=2,
            quote_volume=4,
            trades=3,
            taker_buy_base=1,
            taker_buy_quote=2,
            source="backfill",
            is_closed=not (case == "forming" and month == 12),
        )
        for month in range(8, 13)
        if not (case == "gap" and month == 10)
    ]
    if case == "untrusted":
        rows[-1] = rows[-1].with_source("unknown")
    exclusions = (
        []
        if case == "no_proof"
        else [
            {
                "start_ms": 0,
                "end_ms": timestamp(2017, 8) - 1,
                "disposition": "terminal",
                "reason": "gap_ledger_suppressed"
                if case == "cooldown"
                else "source_exhausted",
            }
        ]
    )
    base = QueryResult(
        bars=rows,
        symbol="BTCUSDT",
        interval="1M",
        source=QuerySource.STORAGE,
        complete=True,
        history_state="exhausted",
        earliest_available_ms=timestamp(2017, 8),
        excluded_ranges=exclusions,
        metadata={"all_rows_final": all(row.trusted_final for row in rows)},
    )
    service = CustomIntervalQueryService(
        cache=BarCache(), config=QueryConfig(), base_query=lambda *a, **kw: base
    )
    result = service.query_from_base(
        symbol="BTCUSDT",
        interval="12M",
        limit=10,
        start_ms=timestamp(2017, 1),
        end_ms=timestamp(2017, 1),
        started_at=time.monotonic(),
        auto_backfill=False,
        route=IntervalRoute(
            exchange="binance",
            market_type="spot",
            requested_interval="12M",
            canonical_interval="12M",
            purpose=IntervalPurpose.HISTORY,
            kind=IntervalRouteKind.DERIVED,
            spec=parse_interval_spec("12M"),
            base_interval="1M",
        ),
    )
    assert len(result.bars) == 1
    bar = result.bars[0]
    assert bar.time_ms == timestamp(2017, 1)
    assert bar.open == 8 and bar.close == 12.5
    assert bar.trusted_final is (case == "listing")
    if case == "listing":
        assert (
            bar.is_closed
            and bar.volume == 10
            and bar.quote_volume == 20
            and bar.trades == 15
        )


@pytest.mark.parametrize("year", [2017, 2020, 2024])
def test_annual_month_components_follow_calendar_not_thirty_day_spacing(year):
    rows = [
        BarData(
            time=timestamp(year, month) // 1000,
            open=1,
            high=2,
            low=1,
            close=2,
            volume=1,
            source="backfill",
        )
        for month in range(1, 13)
    ]
    service = CustomIntervalQueryService(
        cache=BarCache(),
        config=QueryConfig(),
        base_query=lambda *a, **kw: QueryResult(),
    )
    result = service.aggregate_custom_bars(
        rows, symbol="BTCUSDT", interval="12M", source_interval="1M"
    )
    assert len(result) == 1 and result[0].is_closed and result[0].volume == 12
