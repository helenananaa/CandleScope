from __future__ import annotations

import asyncio
from dataclasses import replace

from app.api.v1.klines import _history_contract_payload
from app.api.v1.stream_klines import _serialize_kline_event
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.event_bus import DataEventBus
from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, QueryResult, SeriesKey
from app.data_engine.data_manager.stream_version import StreamVersionClock


KEY = SeriesKey("ETHUSDT", "1m")


def event(kind=DataEventType.BAR_UPDATED, key=KEY, time=180):
    return DataEvent(kind, key, BarData(time=time, open=10, high=20, low=0, close=12, volume=1))


def publish(clock, value):
    ticket = clock.begin(value)
    clock.finish(ticket)
    return value.detail["stream_version"]


def test_forming_coalescence_and_critical_gaps_have_distinct_watermarks():
    clock = StreamVersionClock()
    first = publish(clock, event(DataEventType.BAR_CREATED))
    for _ in range(5):
        last = publish(clock, event())
    final = publish(clock, event(DataEventType.BAR_CLOSED))
    assert first["sequence"] == first["barrier"] == 1
    assert last["sequence"] == 6 and last["barrier"] == 1
    assert final["sequence"] == 7 and final["barrier"] == 2


def test_versions_scope_all_semantics_and_change_generation_after_bounded_eviction():
    clock = StreamVersionClock(capacity=1)
    original = clock.snapshot(KEY)
    adjusted = clock.snapshot(replace(KEY, price_adjustment="split"))
    restored = clock.snapshot(KEY)
    assert adjusted["series"]["price_adjustment"] == "split"
    assert restored["generation"] > adjusted["generation"] > original["generation"]
    assert StreamVersionClock().snapshot(KEY)["epoch"] != original["epoch"]


def test_snapshot_crossing_a_close_or_pending_publication_cannot_claim_stability():
    clock = StreamVersionClock()
    before = clock.snapshot(KEY)
    ticket = clock.begin(event(DataEventType.BAR_CLOSED))
    assert clock.snapshot(KEY)["stable"] is False
    assert clock.finish_snapshot(KEY, before, final_only=True)["stable"] is False
    clock.finish(ticket)
    assert clock.finish_snapshot(KEY, before, final_only=True)["stable"] is False
    current = clock.snapshot(KEY)
    assert clock.finish_snapshot(KEY, current)["stable"] is True


def test_closed_history_can_link_across_forming_updates_without_claiming_a_newer_snapshot():
    clock = StreamVersionClock()
    before = clock.snapshot(KEY)
    publish(clock, event())
    assert clock.finish_snapshot(KEY, before)["stable"] is False
    final_only = clock.finish_snapshot(KEY, before, final_only=True)
    assert final_only["stable"] is True
    assert final_only["sequence"] == before["sequence"]


def test_http_and_ws_expose_the_same_clock_and_backend_calendar_predecessor(monkeypatch):
    manager = DataManager()
    sample = event(DataEventType.BAR_CREATED)
    asyncio.run(manager.event_bus.emit(sample))
    monkeypatch.setattr(manager.query_engine, "query_latest", lambda *args, **kwargs: QueryResult(
        symbol="ETHUSDT", interval="1m", metadata={"all_rows_final": True}))
    result = manager.query_latest("ETHUSDT", "1m", auto_backfill=False)
    http = _history_contract_payload(result)["stream_version"]
    ws = _serialize_kline_event(sample)
    assert {k: v for k, v in http.items() if k != "stable"} == ws["stream_version"]
    assert http["stable"] is True
    assert ws["previous_open_ms"] == 120_000
    assert ws["affected_range"] == {"from_ms": 180_000, "to_ms": 180_000}


def test_backfill_range_is_versioned_even_when_delivery_is_internal():
    clock = StreamVersionClock()
    value = DataEvent(DataEventType.BACKFILL_COMPLETED, KEY, audience="internal",
                      detail={"request_start_ms": 60_000, "request_end_ms": 120_000})
    version = publish(clock, value)
    assert version["barrier"] == 1
    assert value.detail["affected_range"] == {"from_ms": 60_000, "to_ms": 120_000}


def test_awaited_middleware_keeps_snapshot_unstable_until_publication_finishes():
    async def run():
        bus = DataEventBus()
        entered, release = asyncio.Event(), asyncio.Event()
        async def middleware(value):
            entered.set()
            await release.wait()
            return value
        bus.add_middleware(middleware)
        task = asyncio.create_task(bus.emit(event()))
        await entered.wait()
        assert bus.stream_versions.snapshot(KEY)["stable"] is False
        release.set()
        await task
        assert bus.stream_versions.snapshot(KEY)["stable"] is True
        await bus.close()
    asyncio.run(run())


def test_explicit_cache_invalidation_and_clear_revoke_server_incarnations():
    manager = DataManager()
    before = manager.event_bus.stream_versions.snapshot(KEY)
    manager.cache_invalidate("ETHUSDT", "1m")
    after = manager.event_bus.stream_versions.snapshot(KEY)
    assert after["epoch"] == before["epoch"]
    assert after["generation"] > before["generation"]
    manager.cache_clear()
    assert manager.event_bus.stream_versions.snapshot(KEY)["epoch"] != before["epoch"]
