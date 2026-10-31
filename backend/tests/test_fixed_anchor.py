from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.data_engine.interval_policy import parse_interval_spec, interval_tiles
from app.data_engine.interval_resolution import IntervalResolver
from app.data_engine.data_manager.models import SeriesKey, BarData
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.data_manager.query import QueryEngine
from app.data_engine.data_manager.custom_query import CustomIntervalQueryService
from app.data_engine.data_manager.warm_start import AggregatorWarmStartService
from app.data_engine.bar_aggregator import BarAggregator, BarAggregatorConfig
from app.data_engine.ingestion.models import DataSource, MarketEvent, StreamType
from app.data_engine.storage import klines_repo

A = int(datetime.fromisoformat("2026-10-27T00:02:00+00:00").timestamp() * 1000)
MINUTE = 60_000
WIDTH = 7 * MINUTE


def anchored(anchor=A, duration="7m"):
    spec = parse_interval_spec(f"{duration}~a1~{anchor}")
    assert spec is not None
    return spec.canonical


def row(index):
    ts = A + index * MINUTE
    return dict(open_time=ts, close_time=ts + MINUTE - 1, open=100 + index,
                high=102 + index, low=99 + index, close=101 + index, volume=1,
                quote_volume=10, trades=0, taker_buy_base=0, taker_buy_quote=0, is_closed=True)


def event(index):
    raw = row(index)
    return MarketEvent(event_type=StreamType.KLINE, symbol="BTC-USDT", exchange="okx",
        market_type="spot", source=DataSource.WEBSOCKET, event_time_ms=raw["close_time"],
        received_at_ms=raw["close_time"], stream_key="fixture", sequence=raw["close_time"],
        data={**raw, "interval": "1m"})


def test_anchor_extends_both_ways_and_equivalent_anchors_share_identity():
    value = anchored()
    spec = parse_interval_spec(value)
    for offset in [-100, -2, -1, 0, 1, 2, 100]:
        start = A + offset * WIDTH
        assert spec.floor_ms(start + WIDTH - 1) == start
        assert spec.next_ms(start) == start + WIDTH
        assert spec.previous_ms(start) == start - WIDTH
    assert anchored(A + WIDTH) == value
    assert anchored(A - WIDTH) == value
    assert SeriesKey("BTC-USDT", value) == SeriesKey("BTC-USDT", f"420s~a1~{A + WIDTH}")
    assert SeriesKey("BTC-USDT", value).topic != SeriesKey("BTC-USDT", anchored(A + MINUTE)).topic
    assert parse_interval_spec("1h~a1~0").canonical == "1h"


@pytest.mark.parametrize("value", ["7m~a1~30000", "7m~a1~120001", "7s~a1~60000", "1w~a1~60000", "1M~a1~60000", "7m~a2~60000"])
def test_unrepresentable_or_unknown_anchor_is_rejected(value):
    assert parse_interval_spec(value) is None


def test_route_checks_phase_not_just_divisibility():
    target = anchored(A, "10m")
    assert not interval_tiles(parse_interval_spec("5m"), parse_interval_spec(target))
    route = IntervalResolver().resolve(exchange="okx", market_type="spot", interval=target, purpose="history")
    assert route.source_interval == "1m"


def test_history_realtime_and_duplicate_final_snapshots_agree(monkeypatch):
    async def run():
        targets = [anchored(), anchored(A + MINUTE)]
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        for target in targets:
            agg.add_target("BTC-USDT", target, exchange="okx")
        for index in range(-7, 22):
            # Replay the wall clock along with the fixture's event clock.
            monkeypatch.setattr("app.data_engine.bar_aggregator.aggregator.time.time", lambda: row(index)["close_time"] / 1000)
            await agg.on_market_event(event(index))
            await agg.on_market_event(event(index))
        bars = [BarData.from_storage_row(row(i)) for i in range(-7, 22)]
        for target, first in zip(targets, [A, A + MINUTE]):
            history = CustomIntervalQueryService._aggregate_read_only(bars, target, 420, source_interval="1m")
            for start in [first, first + WIDTH]:
                historical = next(b for b in history if b.time * 1000 == start)
                state = next((b for b in agg.get_recent_bars("BTC-USDT", target, exchange="okx") if b.bucket_start_ms == start), None)
                assert state is not None
                assert (state.open, state.high, state.low, state.close, state.volume) == (historical.open, historical.high, historical.low, historical.close, historical.volume)
                assert state.volume == 7
    asyncio.run(run())


def test_missing_component_stays_provisional_until_backfill_repairs_it(monkeypatch):
    from dataclasses import replace
    from app.data_engine.bar_aggregator.models import BarFinality

    async def run():
        target = anchored()
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target("BTC-USDT", target, exchange="okx")
        for index in [0, 1, 3, 4, 5, 6, 7]:
            monkeypatch.setattr("app.data_engine.bar_aggregator.aggregator.time.time", lambda: row(index)["close_time"] / 1000)
            await agg.on_market_event(event(index))
        state = next(b for b in agg.get_recent_bars("BTC-USDT", target, exchange="okx") if b.bucket_start_ms == A)
        assert state.volume == 6
        assert state.finality is BarFinality.PROVISIONAL
        repair = replace(event(2), source=DataSource.HTTP_BACKFILL)
        await agg.on_market_event(repair)
        await agg.on_market_event(repair)
        assert state.volume == 6  # Published snapshots remain detached.
        state = next(b for b in agg.get_recent_bars("BTC-USDT", target, exchange="okx") if b.bucket_start_ms == A)
        assert state.volume == 7
        assert state.finality is BarFinality.AUTHORITATIVE
    asyncio.run(run())


def test_sqlite_queries_restart_and_warm_start_keep_anchor(monkeypatch, tmp_path):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "anchor.sqlite")
    klines_repo.init_klines_storage()
    source_rows = [row(i) for i in range(-14, 29)]
    klines_repo.upsert_klines("BTC-USDT", "1m", source_rows, exchange="okx", source="backfill_rest_verified")
    storage = klines_repo.KlinesRepoAdapter(exchange="okx")
    target = anchored()
    for _ in range(2):  # discard all in-memory state, reopen from the same DB
        engine = QueryEngine(cache=BarCache(), storage=storage, config=QueryConfig(auto_backfill=False))
        result = engine.query("BTC-USDT", target, A - WIDTH, A + WIDTH, limit=3, exchange="okx", auto_backfill=False)
        assert [b.time * 1000 for b in result.bars] == [A - WIDTH, A, A + WIDTH]
        assert all(b.volume == 7 for b in result.bars)
        before = engine.query_before("BTC-USDT", target, A + WIDTH, 2, exchange="okx", auto_backfill=False)
        assert [b.time * 1000 for b in before.bars] == [A - WIDTH, A]
    # Independent namespace: another phase cannot read these materialized rows.
    assert storage.query_bars("BTC-USDT", anchored(A + MINUTE)) == []

    async def warm():
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target("BTC-USDT", target, exchange="okx")
        service = AggregatorWarmStartService(cache=BarCache(), bar_aggregator=agg,
            base_interval="1m", storage_provider=lambda: storage, backfill_trigger_provider=lambda: None)
        monkeypatch.setattr("app.data_engine.data_manager.warm_start.time.time", lambda: (A + 4 * MINUTE) / 1000)
        await service.seed_if_needed("BTC-USDT", target, exchange="okx", market_type="spot", had_stream=False)
        state = agg.get_bucket_state("BTC-USDT", target, A, exchange="okx")
        assert state is not None and state.bucket_start_ms == A
        assert state.volume == 5  # 4 closed minutes plus the current snapshot
        for i in range(4, 7):
            await agg.on_market_event(event(i))
        assert state.volume == 5
        state = next(b for b in agg.get_recent_bars("BTC-USDT", target, exchange="okx") if b.bucket_start_ms == A)
        assert state.volume == 7
    asyncio.run(warm())


def test_series_identity_overrides_legacy_process_alignment():
    from app.data_engine.bar_aggregator.aggregator import IntervalPipeline
    for target in ["7m", anchored(), "7m~a1~0"]:
        spec = parse_interval_spec(target)
        pipeline = IntervalPipeline(target, WIDTH, BarAggregatorConfig(default_alignment_mode="custom", alignment_epoch_ms=123000))
        assert pipeline.time_bucket.compute_bucket(A) == spec.floor_ms(A)


def test_two_anchor_subscriptions_share_only_the_native_source():
    from app.data_engine.data_manager.stream_policy import StreamEnsurePlanner
    planner = StreamEnsurePlanner()
    first = planner.plan("BTC-USDT", anchored(), exchange="okx")
    second = planner.plan("BTC-USDT", anchored(A + MINUTE), exchange="okx")
    assert first.requested != second.requested
    assert first.prerequisite_streams == second.prerequisite_streams
    assert [key.interval for key in first.prerequisite_streams] == ["1m"]
    assert first.requested in first.aggregation_targets
    assert second.requested in second.aggregation_targets
