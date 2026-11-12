from __future__ import annotations

import asyncio
from dataclasses import replace
import time as py_time
from unittest.mock import patch

import pytest

from app.data_engine.bar_aggregator import (
    BarAggregator,
    BarAggregatorConfig,
    BarEvent,
    BarEventType,
    BarFinality,
    BarInput,
    BarInputSource,
    BarState,
)
from app.data_engine.bar_aggregator.models import MergeMode
from app.data_engine.data_manager.aggregator_bridge import AggregatorBridge
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.event_bus import DataEventBus
from app.data_engine.data_manager.models import BarData, DataEventType, SeriesKey
from app.data_engine.data_manager.warm_start import AggregatorWarmStartService
from app.data_engine.storage import klines_repo
from app.data_engine.series_identity import KlineSeriesIdentity


def _row(open_time_ms: int, interval_ms: int, close: float) -> dict:
    return {
        "open_time": open_time_ms,
        "close_time": open_time_ms + interval_ms - 1,
        "open": close,
        "high": close + 2,
        "low": close - 1,
        "close": close + 1,
        "volume": close * 10,
        "quote_volume": close * 100,
        "trades": int(close),
        "taker_buy_base": close,
        "taker_buy_quote": close * 2,
    }


class _Storage:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.query_calls: list[dict] = []
        self.upsert_calls: list[dict] = []

    def query_bars(self, **kwargs):
        self.query_calls.append(kwargs)
        return list(self.rows)

    def upsert_bars(
        self,
        symbol,
        interval,
        rows,
        source,
        exchange,
        market_type,
    ) -> None:
        self.upsert_calls.append({
            "symbol": symbol,
            "interval": interval,
            "rows": rows,
            "source": source,
            "exchange": exchange,
            "market_type": market_type,
        })


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


def _service(
    *,
    cache: BarCache,
    aggregator: BarAggregator,
    storage: _Storage,
    triggers: list[tuple],
    base_interval: str = "1m",
) -> AggregatorWarmStartService:
    return AggregatorWarmStartService(
        cache=cache,
        bar_aggregator=aggregator,
        base_interval=base_interval,
        storage_provider=lambda: storage,  # type: ignore[return-value]
        backfill_trigger_provider=lambda: (lambda *args: triggers.append(args)),
    )


def test_warm_start_standard_interval_seeds_active_bar_without_events() -> None:
    async def _run() -> None:
        fixed_now_ms = int(py_time.time() * 1000)
        fixed_time = fixed_now_ms / 1000
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target("BTC-USDT", "1m", exchange="okx", market_type="spot")
        bucket_start_ms = agg.compute_bucket("1m", fixed_now_ms)
        assert bucket_start_ms is not None

        events = []

        async def _capture(event):
            events.append(event)

        agg.publisher.on_bar_event(_capture)
        storage = _Storage(rows=[_row(bucket_start_ms, 60_000, close=10)])
        cache = BarCache()
        triggers: list[tuple] = []
        service = _service(
            cache=cache,
            aggregator=agg,
            storage=storage,
            triggers=triggers,
        )

        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=fixed_time):
            await service.seed_if_needed(
                "BTC-USDT",
                "1m",
                exchange="okx",
                market_type="spot",
                had_stream=False,
            )

        state = agg.get_bucket_state(
            "BTC-USDT",
            "1m",
            bucket_start_ms,
            exchange="okx",
            market_type="spot",
        )
        assert state is not None
        assert state.open == 10
        assert state.high == 12
        assert state.low == 9
        assert state.close == 11
        assert state.volume == 100
        assert state.quote_volume == 1_000
        assert state.enhanced_fields == frozenset({"quote_volume"})
        assert state.exchange == "okx"
        assert state.market_type == "spot"
        assert storage.query_calls == [{
            "symbol": "BTC-USDT",
            "interval": "1m",
            "start_ms": bucket_start_ms,
            "end_ms": bucket_start_ms,
            "limit": 1,
            "order": "ASC",
            "exchange": "okx",
            "market_type": "spot",
        }]
        assert events == []
        assert triggers == []

    asyncio.run(_run())


def test_warm_start_custom_interval_replays_components_and_warms_cache() -> None:
    async def _run() -> None:
        fixed_now_ms = int(py_time.time() * 1000)
        fixed_time = fixed_now_ms / 1000
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target("BTC-USDT", "45m", exchange="okx", market_type="spot")
        events: list[BarEvent] = []

        async def _capture(event: BarEvent) -> None:
            events.append(event)

        agg.publisher.on_bar_event(_capture)
        bucket_start_ms = agg.compute_bucket("45m", fixed_now_ms)
        assert bucket_start_ms is not None

        base_ms = 15 * 60_000
        elapsed_ms = max(0, fixed_now_ms - bucket_start_ms)
        component_count = max(1, min(3, int(elapsed_ms // base_ms) + 1))
        rows = [
            _row(bucket_start_ms + (idx * base_ms), base_ms, close=10 + idx)
            for idx in range(component_count)
        ]
        storage = _Storage(rows=rows)
        cache = BarCache()
        triggers: list[tuple] = []
        service = _service(
            cache=cache,
            aggregator=agg,
            storage=storage,
            triggers=triggers,
            base_interval="15m",
        )

        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=fixed_time):
            await service.seed_if_needed(
                "BTC-USDT",
                "45m",
                exchange="okx",
                market_type="spot",
                had_stream=True,
            )

        state = agg.get_bucket_state(
            "BTC-USDT",
            "45m",
            bucket_start_ms,
            exchange="okx",
            market_type="spot",
        )
        assert state is not None
        assert state.open == 10
        assert state.high == max(row["high"] for row in rows)
        assert state.low == min(row["low"] for row in rows)
        assert state.close == rows[-1]["close"]
        assert state.volume == sum(row["volume"] for row in rows)
        assert state.quote_volume == sum(row["quote_volume"] for row in rows)
        assert state.enhanced_fields == frozenset({"quote_volume"})
        assert state.tick_count == len(rows)
        assert len(state.source_snapshots) == len(rows)

        cached = cache.get_latest(
            SeriesKey("BTC-USDT", "45m", exchange="okx", market_type="spot"),
            1,
        )
        assert cached and cached[0].close == state.close
        assert cached[0].quote_volume == state.quote_volume
        assert [event.event_type for event in events] == [BarEventType.UPDATED]
        assert storage.query_calls[0]["interval"] == "15m"
        assert storage.query_calls[0]["exchange"] == "okx"
        assert storage.query_calls[0]["market_type"] == "spot"
        assert triggers == []

    asyncio.run(_run())


def test_custom_tail_repair_is_coalesced_within_one_target_bucket() -> None:
    agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
    agg.add_target("BTC-USDT", "45m", exchange="okx", market_type="spot")
    triggers: list[tuple] = []
    service = _service(
        cache=BarCache(),
        aggregator=agg,
        storage=_Storage(),
        triggers=triggers,
        base_interval="15m",
    )
    fixed_now_ms = 10 * 45 * 60_000 + 15 * 60_000

    with patch(
        "app.data_engine.data_manager.warm_start.time.time",
        return_value=fixed_now_ms / 1000,
    ):
        service._trigger_custom_tail_repair(
            "BTC-USDT",
            "45m",
            exchange="okx",
            market_type="spot",
        )
        service._trigger_custom_tail_repair(
            "BTC-USDT",
            "45m",
            exchange="okx",
            market_type="spot",
        )

    assert len(triggers) == 1

    with patch(
        "app.data_engine.data_manager.warm_start.time.time",
        return_value=(fixed_now_ms + 45 * 60_000) / 1000,
    ):
        service._trigger_custom_tail_repair(
            "BTC-USDT",
            "45m",
            exchange="okx",
            market_type="spot",
        )

    assert len(triggers) == 2


def test_custom_tail_repair_reopens_after_target_is_removed_and_recreated() -> None:
    """A closed chart's cancelled repair cannot suppress its replacement."""
    agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
    triggers: list[tuple] = []
    service = _service(cache=BarCache(), aggregator=agg, storage=_Storage(),
                       triggers=triggers, base_interval="15m")
    target = dict(exchange="okx", market_type="spot")
    agg.add_target("BTC-USDT", "45m", **target)
    with patch("app.data_engine.data_manager.warm_start.time.time", return_value=27_900):
        service._trigger_custom_tail_repair("BTC-USDT", "45m", **target)
        # Closing the last consumer destroys this aggregation lifetime. Its
        # queued repair may be cancelled; a new lifetime needs a fresh demand.
        agg.remove_target("BTC-USDT", "45m", **target)
        agg.add_target("BTC-USDT", "45m", **target)
        service._trigger_custom_tail_repair("BTC-USDT", "45m", **target)
        service._trigger_custom_tail_repair("BTC-USDT", "45m", **target)
    assert len(triggers) == 2


def test_storage_rebinding_invalidates_tail_repair_deduplication(tmp_path, monkeypatch) -> None:
    from app.core import config as core_config
    from app.data_engine.data_manager import DataManager

    database = tmp_path / "tail-rebind.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", database)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", database)
    klines_repo.init_klines_storage()
    dm = DataManager()
    calls = []
    dm.warm_start._backfill_trigger_provider = lambda: (
        lambda *args, **kwargs: calls.append((args, kwargs))
    )
    target = dict(exchange="okx", market_type="spot")
    dm.bar_aggregator.add_target("BTC-USDT", "45m", **target)
    try:
        dm.set_storage(klines_repo.KlinesRepoAdapter())
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=27_900):
            dm.warm_start._trigger_custom_tail_repair("BTC-USDT", "45m", **target)
            dm.warm_start._trigger_custom_tail_repair("BTC-USDT", "45m", **target)
            assert len(calls) == 1
            # A new canonical binding establishes its own recovery state even
            # when it reopens the same SQLite file and target bucket.
            dm.set_storage(klines_repo.KlinesRepoAdapter())
            dm.warm_start._trigger_custom_tail_repair("BTC-USDT", "45m", **target)
            dm.warm_start._trigger_custom_tail_repair("BTC-USDT", "45m", **target)
        assert len(calls) == 2
    finally:
        asyncio.run(dm.shutdown())


def test_warm_start_exchange_derived_standard_uses_resolved_four_hour_base() -> None:
    async def _run() -> None:
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target("BTC-USDT", "8h", exchange="okx", market_type="spot")
        bucket_start_ms = agg.compute_bucket("8h", 1_750_000_000_000)
        assert bucket_start_ms is not None
        fixed_now_ms = bucket_start_ms + 5 * 3_600_000
        four_hours_ms = 4 * 3_600_000
        rows = [
            _row(bucket_start_ms, four_hours_ms, close=10),
            _row(bucket_start_ms + four_hours_ms, four_hours_ms, close=20),
        ]
        storage = _Storage(rows=rows)
        service = _service(
            cache=BarCache(),
            aggregator=agg,
            storage=storage,
            triggers=[],
            base_interval="1m",
        )

        with patch(
            "app.data_engine.data_manager.warm_start.time.time",
            return_value=fixed_now_ms / 1000,
        ):
            await service.seed_if_needed(
                "BTC-USDT",
                "8h",
                exchange="okx",
                market_type="spot",
                had_stream=True,
            )

        state = agg.get_bucket_state(
            "BTC-USDT",
            "8h",
            bucket_start_ms,
            exchange="okx",
            market_type="spot",
        )
        assert storage.query_calls[0]["interval"] == "4h"
        assert state is not None
        assert state.open == 10
        assert state.close == 21
        assert state.volume == 300
        assert state.tick_count == 2

    asyncio.run(_run())


def test_warm_start_does_not_close_derived_history_from_a_forming_base_row():
    async def run():
        base_ms = 15 * 60_000
        now_ms = 4 * base_ms
        aggregator = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        aggregator.add_target("BTC-USDT", "45m", exchange="okx", market_type="spot")
        rows = [{**_row(index * base_ms, base_ms, close=10 + index),
                 "source": "backfill", "is_closed": index != 2} for index in range(3)]
        service = _service(cache=BarCache(), aggregator=aggregator, storage=_Storage(rows),
                           triggers=[], base_interval="15m")
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=now_ms / 1000):
            await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
        previous = aggregator.get_latest_bar("BTC-USDT", "45m", exchange="okx", market_type="spot")
        assert previous is not None and previous.bucket_start_ms == 0
        assert previous.finality != BarFinality.AUTHORITATIVE
        assert any(not component["is_closed"] for component in previous.source_snapshots.values())

    asyncio.run(run())


def test_warm_start_replaces_changed_components_even_when_target_totals_match():
    async def run():
        base_ms = 15 * 60_000
        bucket_start = 3 * base_ms
        now_ms = bucket_start + 2 * base_ms - 1
        aggregator = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        aggregator.add_target("BTC-USDT", "45m", exchange="okx", market_type="spot")
        rows = [{**_row(bucket_start + index * base_ms, base_ms, close=10 + index),
                 "source": "backfill", "is_closed": index == 0} for index in range(2)]
        storage = _Storage(rows)
        service = _service(cache=BarCache(), aggregator=aggregator, storage=storage, triggers=[], base_interval="15m")
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=now_ms / 1000):
            await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
            storage.rows[0]["volume"] -= 5
            storage.rows[1]["volume"] += 5
            await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
        state = aggregator.get_bucket_state("BTC-USDT", "45m", bucket_start, exchange="okx", market_type="spot")
        assert state.volume == 210
        assert {item["open_time_ms"]: item["volume"] for item in state.source_snapshots.values()} == {
            bucket_start: 95, bucket_start + base_ms: 115,
        }

    asyncio.run(run())


@pytest.mark.parametrize("staged_tail", ["missing", "stale"])
def test_warm_start_keeps_an_accepted_forming_tail_while_rebuilding_history(staged_tail):
    async def run():
        width = 15 * 60_000
        start = 3 * width
        tail_start = start + width
        aggregator = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        aggregator.add_target("BTC-USDT", "45m", exchange="okx", market_type="spot")
        revision = 10
        aggregator.acquisition_revision_provider = lambda: revision
        storage = _Storage([{**_row(start, width, close=10), "source": "backfill"}])
        if staged_tail == "stale":
            storage.rows.append({**_row(tail_start, width, close=20), "is_closed": False})
        service = _service(cache=BarCache(), aggregator=aggregator, storage=storage,
                           triggers=[], base_interval="15m")
        tail = BarInput(symbol="BTC-USDT", exchange="okx", source_interval="15m",
                        open_time_ms=tail_start, close_time_ms=tail_start + width - 1,
                        open=20, high=28, low=18, close=25, volume=350,
                        quote_volume=7500, trades=30, taker_buy_base=30, taker_buy_quote=50,
                        enhanced_fields=frozenset({"quote_volume", "trades", "taker_buy_base", "taker_buy_quote"}),
                        sequence=42, source=BarInputSource.REALTIME, is_closed=False,
                        merge_mode=MergeMode.COMPONENT)
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=(tail_start + 1000) / 1000):
            if staged_tail == "stale":
                await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
            await aggregator.ingest_bar_input("okx", "spot", "BTC-USDT", "45m", tail)
            revision = 11
            await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
        state = aggregator.get_bucket_state("BTC-USDT", "45m", start, exchange="okx")
        assert state is not None and state.volume == 450 and state.close == 25
        assert state.acquisition_revision == 10
        assert state.source_snapshots[tail.input_key]["sequence"] == 42
        assert state.finality != BarFinality.AUTHORITATIVE
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=(tail_start + 2000) / 1000):
            await aggregator.ingest_bar_input("okx", "spot", "BTC-USDT", "45m", replace(tail, volume=370, sequence=43))
            await aggregator.ingest_bar_input("okx", "spot", "BTC-USDT", "45m", replace(tail, volume=500, sequence=41))
        state = aggregator.get_bucket_state("BTC-USDT", "45m", start, exchange="okx")
        assert state is not None and state.volume == 470

        storage.rows = [storage.rows[0], {**_row(tail_start, width, close=20), "source": "backfill"}]
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=(tail_start + width + 1) / 1000):
            await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
        state = aggregator.get_bucket_state("BTC-USDT", "45m", start, exchange="okx")
        assert state is not None and state.volume == 300 and state.close == 21
        assert state.source_snapshots[tail.input_key]["is_closed"]

    asyncio.run(run())


def test_warm_start_requests_repair_for_an_elapsed_provisional_component():
    async def run():
        base_ms = 15 * 60_000
        bucket_start = 3 * base_ms
        now_ms = bucket_start + base_ms + 1
        aggregator = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        aggregator.add_target("BTC-USDT", "45m", exchange="okx", market_type="spot")
        storage = _Storage([{**_row(bucket_start, base_ms, close=10),
                             "source": "data_manager_closed", "is_closed": True}])
        cache = BarCache()
        triggers = []
        service = AggregatorWarmStartService(
            cache=cache, bar_aggregator=aggregator, base_interval="15m",
            storage_provider=lambda: storage,
            backfill_trigger_provider=lambda: lambda *args, **kwargs: triggers.append((args, kwargs)),
        )
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=now_ms / 1000):
            await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
            state = aggregator.get_bucket_state("BTC-USDT", "45m", bucket_start, exchange="okx", market_type="spot")
            assert state is not None and not state.last_close_received
            assert len(triggers) == 1
            assert triggers[0][1]["requester"] == "warm_start_custom_seed"
            assert triggers[0][1]["metadata"]["requires_trusted_finality"] is True

            storage.rows[0]["source"] = "backfill"
            cache.upsert(SeriesKey("BTC-USDT", "15m", exchange="okx", market_type="spot"),
                         BarData(time=bucket_start // 1000, open=10, high=12, low=9, close=11,
                                 volume=999, is_closed=False))
            await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
            repaired = aggregator.get_bucket_state("BTC-USDT", "45m", bucket_start, exchange="okx", market_type="spot")
            assert repaired is not None and repaired.last_close_received and repaired.volume == 100
            assert len(triggers) == 1

    asyncio.run(run())


@pytest.mark.parametrize("cached_source", ["data_manager_exchange_closed", "source_snapshot_verified"])
def test_derived_warm_start_prefers_the_committed_final_component(cached_source):
    async def run():
        base_ms = 15 * 60_000
        bucket_start = 3 * base_ms
        now_ms = bucket_start + base_ms + 1
        aggregator = BarAggregator()
        aggregator.add_target("BTC-USDT", "45m", exchange="okx")
        storage = _Storage([dict(_row(bucket_start, base_ms, 10), source="source_snapshot_verified")])
        cache = BarCache()
        key = SeriesKey("BTC-USDT", "15m", exchange="okx")
        cache.upsert(key, BarData(time=bucket_start // 1000, open=20, high=25, low=19, close=22,
                                  volume=999, is_closed=True, source=cached_source))
        service = _service(cache=cache, aggregator=aggregator, storage=storage, triggers=[], base_interval="15m")
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=now_ms / 1000):
            await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
        result = aggregator.get_bucket_state("BTC-USDT", "45m", bucket_start, exchange="okx")
        assert result is not None and result.last_close_received and result.volume == 100
        assert result.high == 12 and result.close == 11

    asyncio.run(run())


@pytest.mark.parametrize(("interval", "source_interval", "width", "source_width"), [
    ("15m", "15m", 900_000, 900_000), ("45m", "15m", 2_700_000, 900_000),
])
def test_warm_start_keeps_nondefault_identity_on_storage_target_and_repair(interval, source_interval, width, source_width):
    async def run():
        opened = 3 * width
        now_ms = opened + 1
        identities = [KlineSeriesIdentity.for_exchange("okx", series_variant=variant)
                      for variant in ("archive", "alternate")]
        aggregator = BarAggregator()
        for identity in identities:
            aggregator.add_target("BTC-USDT", interval, exchange="okx", series_identity=identity)
        storage = _Storage([_row(opened, source_width, 10)])
        triggers = []
        service = AggregatorWarmStartService(
            cache=BarCache(), bar_aggregator=aggregator, base_interval=source_interval,
            storage_provider=lambda: storage,
            backfill_trigger_provider=lambda: lambda *args, **kwargs: triggers.append((args, kwargs)),
        )
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=now_ms / 1000):
            for identity in identities:
                await service.seed_if_needed("BTC-USDT", interval, exchange="okx", market_type="spot",
                                             had_stream=False, series_identity=identity)
                result = aggregator.get_bucket_state("BTC-USDT", interval, opened,
                                                     exchange="okx", series_identity=identity)
                assert result is not None and result.series_identity == identity and result.volume == 100
        assert [call["series_identity"] for call in storage.query_calls] == identities
        assert all(call["interval"] == source_interval for call in storage.query_calls)
        assert aggregator.get_bucket_state("BTC-USDT", interval, opened, exchange="okx") is None
        if interval != source_interval:
            assert [kw["metadata"]["series_identity"] for _, kw in triggers] == [
                identity.to_dict() for identity in identities
            ]
        else:
            assert not triggers

    asyncio.run(run())


def test_custom_sync_ignores_rows_from_previous_target_bucket():
    async def run():
        base_ms = 15 * 60_000
        bucket_start = 3 * base_ms
        aggregator = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        aggregator.add_target("BTC-USDT", "45m", exchange="okx", market_type="spot")
        rows = [_row(bucket_start + index * base_ms, base_ms, close=10 + index)
                for index in (-1, 0, 1)]
        storage = _Storage(rows)
        service = _service(cache=BarCache(), aggregator=aggregator, storage=storage, triggers=[], base_interval="15m")
        events = []

        async def capture(event):
            events.append(event)

        aggregator.publisher.on_bar_event(capture)
        now_ms = bucket_start + 2 * base_ms - 1
        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=now_ms / 1000):
            for _ in range(2):
                await service.seed_if_needed("BTC-USDT", "45m", exchange="okx", market_type="spot", had_stream=True)
        assert [event.event_type for event in events] == [BarEventType.UPDATED]

    asyncio.run(run())


def test_warm_start_marks_full_subscription_base_backfill_priority() -> None:
    async def _run() -> None:
        fixed_now_ms = (10 * 60 * 60 * 1000) + (50 * 60 * 1000)
        fixed_time = fixed_now_ms / 1000
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        agg.add_target("BTC-USDT", "45m", exchange="okx", market_type="spot")
        bucket_start_ms = agg.compute_bucket("45m", fixed_now_ms)
        assert bucket_start_ms is not None

        storage = _Storage(rows=[])
        cache = BarCache()
        calls: list[tuple[tuple, dict]] = []
        service = AggregatorWarmStartService(
            cache=cache,
            bar_aggregator=agg,
            base_interval="15m",
            storage_provider=lambda: storage,  # type: ignore[return-value]
            backfill_trigger_provider=lambda: (
                lambda *args, **kwargs: calls.append((args, kwargs))
            ),
        )

        with patch("app.data_engine.data_manager.warm_start.time.time", return_value=fixed_time):
            await service.seed_if_needed(
                "BTC-USDT",
                "45m",
                exchange="okx",
                market_type="spot",
                had_stream=True,
                focus_scope="subscription",
                subscription_tier="full",
            )

        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args == (
            "BTC-USDT",
            "15m",
            bucket_start_ms,
            fixed_now_ms,
            "okx",
            "spot",
        )
        assert kwargs["reason"] == "full_subscription_warmup"
        assert kwargs["priority"] == 110
        assert kwargs["requester"] == "warm_start_custom_seed"
        assert kwargs["metadata"]["focus_scope"] == "subscription"
        assert kwargs["metadata"]["subscription_tier"] == "full"
        assert kwargs["metadata"]["requested_interval"] == "45m"

    asyncio.run(_run())


def test_aggregator_bridge_persists_closed_and_amended_events() -> None:
    async def _run() -> None:
        cache = BarCache()
        bus = DataEventBus()
        storage = _Storage()
        marked: list[SeriesKey] = []
        events = []

        async def _capture(event):
            events.append(event)

        bus.subscribe(_capture)
        bridge = AggregatorBridge(
            cache=cache,
            event_bus=bus,
            storage_provider=lambda: storage,  # type: ignore[return-value]
            mark_bar_received=marked.append,
            is_started=lambda: True,
        )

        original = BarState(
            symbol="BTC-USDT",
            interval="1m",
            bucket_start_ms=60_000,
            bucket_end_ms=120_000,
            open=1,
            high=3,
            low=0.5,
            close=2,
            volume=10,
            exchange="okx",
            market_type="spot",
            finality=BarFinality.AUTHORITATIVE,
            close_reason="source_close",
        )
        amended = BarState(
            symbol="BTC-USDT",
            interval="1m",
            bucket_start_ms=60_000,
            bucket_end_ms=120_000,
            open=1.5,
            high=4,
            low=1,
            close=3,
            volume=20,
            exchange="okx",
            market_type="spot",
            finality=BarFinality.AUTHORITATIVE,
            close_reason="backfill_amendment",
        )

        await bridge.on_bar_event(BarEvent(BarEventType.CLOSED, original))
        await bridge.on_bar_event(
            BarEvent(BarEventType.AMENDED, amended, previous_bar=original)
        )

        key = SeriesKey("BTC-USDT", "1m", exchange="okx", market_type="spot")
        assert [call["source"] for call in storage.upsert_calls] == [
            "data_manager_exchange_closed",
            "data_manager_amended",
        ]
        assert storage.upsert_calls[1]["rows"][0]["close"] == 3
        assert storage.upsert_calls[1]["rows"][0]["quote_volume"] is None
        assert storage.upsert_calls[1]["rows"][0]["trades"] is None
        assert storage.upsert_calls[1]["exchange"] == "okx"
        assert storage.upsert_calls[1]["market_type"] == "spot"
        assert cache.get_latest(key, 1)[0].close == 3
        assert marked == [key, key]
        await _wait_until(lambda: len(events) == 2)
        assert [event.event_type for event in events] == [
            DataEventType.BAR_CLOSED,
            DataEventType.BAR_AMENDED,
        ]
        assert events[1].previous_bar is not None
        assert events[1].previous_bar.close == 2
        await bus.close()

    asyncio.run(_run())


def test_aggregator_bridge_drops_provisional_close_before_cache_and_bus() -> None:
    async def _run() -> None:
        cache = BarCache()
        bus = DataEventBus()
        storage = _Storage()
        marked: list[SeriesKey] = []
        events = []

        async def _capture(event):
            events.append(event)

        bus.subscribe(_capture)
        bridge = AggregatorBridge(
            cache=cache,
            event_bus=bus,
            storage_provider=lambda: storage,  # type: ignore[return-value]
            mark_bar_received=marked.append,
            is_started=lambda: True,
        )
        key = SeriesKey("BTC-USDT", "1m", exchange="okx", market_type="spot")
        provisional = BarState(
            symbol="BTC-USDT",
            interval="1m",
            bucket_start_ms=60_000,
            bucket_end_ms=120_000,
            open=1,
            high=3,
            low=0.5,
            close=2,
            volume=10,
            exchange="okx",
            market_type="spot",
            finality=BarFinality.PROVISIONAL,
            close_reason="time_based",
        )

        await bridge.on_bar_event(BarEvent(BarEventType.CLOSED, provisional))

        assert storage.upsert_calls == []
        assert cache.get_latest(key, 1) == []
        assert marked == []
        assert events == []
        await bus.close()

    asyncio.run(_run())


def test_aggregator_bridge_drops_amendment_below_cached_source_quality() -> None:
    async def _run() -> None:
        cache = BarCache()
        bus = DataEventBus()
        storage = _Storage()
        marked: list[SeriesKey] = []
        events = []

        async def _capture(event):
            events.append(event)

        bus.subscribe(_capture)
        bridge = AggregatorBridge(
            cache=cache,
            event_bus=bus,
            storage_provider=lambda: storage,  # type: ignore[return-value]
            mark_bar_received=marked.append,
            is_started=lambda: True,
        )
        key = SeriesKey("BTC-USDT", "1m", exchange="okx", market_type="spot")
        cache.upsert(key, BarData(
            time=60,
            open=1,
            high=5,
            low=0.5,
            close=4,
            volume=30,
            is_closed=True,
            source="repair_binance_rest_verified",
        ))
        lower_quality_amendment = BarState(
            symbol="BTC-USDT",
            interval="1m",
            bucket_start_ms=60_000,
            bucket_end_ms=120_000,
            open=1,
            high=3,
            low=0.5,
            close=2,
            volume=10,
            exchange="okx",
            market_type="spot",
            finality=BarFinality.AUTHORITATIVE,
            close_reason="backfill_amendment",
        )

        await bridge.on_bar_event(
            BarEvent(BarEventType.AMENDED, lower_quality_amendment)
        )

        canonical = cache.get_latest(key, 1)
        assert len(canonical) == 1
        assert canonical[0].close == 4
        assert canonical[0].source == "repair_binance_rest_verified"
        assert storage.upsert_calls == []
        assert marked == []
        assert events == []
        await bus.close()

    asyncio.run(_run())


def test_aggregator_bridge_honors_durable_rejection_with_cold_cache(
    tmp_path,
    monkeypatch,
) -> None:
    async def _run() -> None:
        monkeypatch.setattr(
            klines_repo,
            "KLINES_DB_PATH",
            tmp_path / "bridge-quality.sqlite",
        )
        klines_repo.init_klines_storage()
        verified_row = {
            "open_time": 60_000,
            "close_time": 119_999,
            "open": 1,
            "high": 5,
            "low": 0.5,
            "close": 4,
            "volume": 30,
            "quote_volume": None,
            "trades": None,
            "taker_buy_base": None,
            "taker_buy_quote": None,
        }
        assert klines_repo.upsert_klines(
            "BTC-USDT",
            "1m",
            [verified_row],
            source="repair_binance_rest_verified",
            exchange="okx",
            market_type="spot",
        ) == 1

        cache = BarCache()
        bus = DataEventBus()
        marked: list[SeriesKey] = []
        events = []

        async def _capture(event):
            events.append(event)

        bus.subscribe(_capture)
        bridge = AggregatorBridge(
            cache=cache,
            event_bus=bus,
            storage_provider=klines_repo.KlinesRepoAdapter,
            mark_bar_received=marked.append,
            is_started=lambda: True,
        )
        rejected_amendment = BarState(
            symbol="BTC-USDT",
            interval="1m",
            bucket_start_ms=60_000,
            bucket_end_ms=120_000,
            open=1,
            high=3,
            low=0.5,
            close=2,
            volume=10,
            exchange="okx",
            market_type="spot",
            finality=BarFinality.AUTHORITATIVE,
            close_reason="backfill_amendment",
        )

        await bridge.on_bar_event(
            BarEvent(BarEventType.AMENDED, rejected_amendment)
        )

        durable = klines_repo.query_klines(
            "BTC-USDT",
            "1m",
            exchange="okx",
            market_type="spot",
        )
        key = SeriesKey("BTC-USDT", "1m", exchange="okx", market_type="spot")
        assert len(durable) == 1
        assert durable[0]["close"] == 4
        assert durable[0]["source"] == "repair_binance_rest_verified"
        assert cache.get_latest(key, 1) == []
        assert marked == []
        assert events == []
        await bus.close()

    asyncio.run(_run())


def test_subminute_warm_start_tail_does_not_force_six_hours_of_source_history():
    """A new7s chart must not enqueue21,600source seconds before its500bar viewport."""
    now_ms = 1793524000000
    for interval, maximum_span in [('7s', 16 * 7 * 1000), ('30s', 16 * 30 * 1000),
                                   ('7m', 6 * 60 * 60 * 1000)]:
        agg = BarAggregator(BarAggregatorConfig(update_throttle_ms=0))
        calls = []
        service = AggregatorWarmStartService(cache=BarCache(), bar_aggregator=agg,
            base_interval='1m', storage_provider=lambda: _Storage(),
            backfill_trigger_provider=lambda: (lambda *args, **kwargs: calls.append((args, kwargs))))
        with patch('app.data_engine.data_manager.warm_start.time.time', return_value=now_ms / 1000):
            service._trigger_custom_tail_repair('BTCUSDT', interval)
        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args[0:2] == ('BTCUSDT', interval)
        assert args[3] == now_ms
        assert args[3] - args[2] <= maximum_span
        assert kwargs['requester'] == 'warm_start_custom_tail'
