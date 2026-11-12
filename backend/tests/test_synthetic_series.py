from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, SeriesKey
from app.data_engine.data_manager.stream_version import StreamVersionClock
from app.data_engine.synthetic_series.core import SyntheticConfig, SyntheticError, SyntheticKernel
from app.data_engine.synthetic_series.service import SyntheticDefinition, SyntheticSeriesService


def bar(time, close, *, closed=True, opening=None):
    opening = close if opening is None else opening
    return dict(time=time, open=opening, high=max(opening, close), low=min(opening, close),
        close=close, volume=2, is_closed=closed)


def test_renko_independent_brick_reference_and_same_time_reversal():
    kernel = SyntheticKernel(SyntheticConfig("renko", semantics="anchored/1", box_size=2, min_tick=1))
    output = kernel.replace([bar(60, 100), bar(120, 106), bar(180, 100)])
    assert [(row["open"], row["close"]) for row in output] == [
        (100, 102), (102, 104), (104, 106), (104, 102), (102, 100)]
    assert [row["time"]["order"] for row in output] == list(range(5))
    assert [row["time"]["sourceTime"] for row in output] == [120, 120, 120, 180, 180]
    assert output[0]["customValues"]["chartProjection"]["sourceFromTime"] == 60


def test_ha_independent_recursive_reference():
    kernel = SyntheticKernel(SyntheticConfig("heikin-ashi"))
    output = kernel.replace([
        dict(time=60, open=10, high=15, low=9, close=14, volume=2, is_closed=True),
        dict(time=120, open=14, high=18, low=13, close=17, volume=3, is_closed=True)])
    assert [(row["open"], row["high"], row["low"], row["close"]) for row in output] == [
        (12, 15, 9, 12), (12, 18, 12, 15.5)]
    assert [row["volume"] for row in output] == [2, 3]


@pytest.mark.parametrize("transform", ["renko", "heikin-ashi"])
def test_preview_replacements_close_and_append_equal_batch(transform):
    config = SyntheticConfig(transform, semantics="anchored/1", box_size=2, min_tick=1)
    kernel = SyntheticKernel(config)
    kernel.replace([bar(60, 100)])
    confirmed_state = deepcopy(kernel._state)
    kernel.apply(bar(120, 108, closed=False))
    kernel.apply(bar(120, 104, closed=False))
    assert kernel._state == confirmed_state
    assert all(row["customValues"]["chartProjection"]["provisional"]
        for row in kernel.output if row["customValues"]["chartProjection"]["sourceToTime"] == 120)
    kernel.apply(bar(120, 104))
    kernel.apply(bar(180, 98, closed=False))
    kernel.apply(bar(180, 96))
    reference = SyntheticKernel(config)
    reference.replace([bar(60, 100), bar(120, 104), bar(180, 96)])
    assert kernel.output == reference.output
    kernel.apply(bar(120, 102))
    reference.replace([bar(60, 100), bar(120, 102), bar(180, 96)])
    assert kernel.output == reference.output
    kernel.apply(bar(180, 999, closed=False))
    assert kernel.output == reference.output


def test_extreme_output_rejected_atomically():
    kernel = SyntheticKernel(SyntheticConfig("renko", semantics="anchored/1", min_tick=1))
    kernel.replace([bar(60, 100)])
    before = deepcopy(kernel.__dict__)
    with pytest.raises(SyntheticError, match="brick budget"):
        kernel.apply(bar(120, 20_000))
    assert kernel.__dict__ == before


def test_causal_prefix_and_display_atr_are_distinct_contracts():
    with pytest.raises(SyntheticError, match="requires fixed"):
        SyntheticConfig("renko", semantics="anchored/1", mode="atr", min_tick=1)
    with pytest.raises(SyntheticError, match="unsupported"):
        SyntheticConfig("pyne")
    first = SyntheticDefinition(SeriesKey("BTCUSDT", "1m"), SyntheticConfig("renko"), 60, 120)
    second = SyntheticDefinition(SeriesKey("BTCUSDT", "1m"), SyntheticConfig("renko"), 60, 180)
    assert first.key != second.key
    assert first.key != SyntheticDefinition(SeriesKey("BTCUSDT", "5m"), first.config, 60, 120).key


class Source:
    """No exchange I/O; actual DM clock and immutable DM bar envelopes."""
    query_row_limit = 5000

    def __init__(self, rows):
        self.rows = rows
        self.event_bus = SimpleNamespace(stream_versions=StreamVersionClock())
        self.clock = self.event_bus.stream_versions
        self.callbacks = {}
        self.active = set()
        self.ensures = 0
        self.reads = 0

    def query(self, **kwargs):
        self.reads += 1
        key = SeriesKey.create(kwargs["symbol"], kwargs["interval"], exchange=kwargs["exchange"],
            market_type=kwargs["market_type"], identity=kwargs["series_identity"])
        return SimpleNamespace(bars=[BarData(**row, source="backfill") for row in self.rows], has_tail_gap=False, missing_ranges=[],
            metadata={"stream_version": self.event_bus.stream_versions.snapshot(key), "storage_revision": 1})

    def subscribe(self, callback, **_kwargs):
        self.callbacks[callback] = callback
        return callback

    def unsubscribe(self, handle):
        self.callbacks.pop(handle, None)

    async def ensure_stream(self, **kwargs):
        self.ensures += 1
        self.active.add(kwargs["consumer_id"])

    async def release_stream(self, **kwargs):
        self.active.discard(kwargs["consumer_id"])

    async def emit(self, kind, row=None):
        key = SeriesKey("BTCUSDT", "1m")
        if row is not None:
            self.rows = sorted([item for item in self.rows if item["time"] != row["time"]] + [row], key=lambda item: item["time"])
        event = DataEvent(kind, key, BarData(**row, source="backfill") if row else None)
        ticket = self.event_bus.stream_versions.begin(event)
        self.event_bus.stream_versions.finish(ticket)
        for callback in list(self.callbacks):
            await callback(event)


def test_shared_owner_lease_release_preview_revision_and_pagination():
    async def run():
        source = Source([bar(60, 100), bar(120, 106, closed=False)])
        service = SyntheticSeriesService(source)
        definition = SyntheticDefinition(SeriesKey("BTCUSDT", "1m"),
            SyntheticConfig("renko", box_size=2, min_tick=1), 60, 120)
        first, second = await service.attach(definition), await service.attach(definition)
        assert first.instance is second.instance
        assert source.ensures == 1 and source.reads == 1
        snapshot = await first.snapshot(limit=2)
        assert snapshot["status"] == "ready"
        assert snapshot["total"] == 3 and snapshot["before"] == 1
        page = await first.snapshot(before=1, limit=2, generation=snapshot["generation"])
        assert len({row["id"] for row in snapshot["rows"] + page["rows"]}) == 3
        await first.close()
        assert len(source.active) == 1
        await source.emit(DataEventType.BAR_UPDATED, bar(120, 104, closed=False))
        patch = await second.next()
        assert patch["type"] == "patch" and patch["total"] == 2
        assert all(row["customValues"]["chartProjection"]["provisional"] for row in patch["rows"])
        await source.emit(DataEventType.BAR_CLOSED, bar(120, 104))
        patch = await second.next()
        assert all(not row["customValues"]["chartProjection"]["provisional"] for row in patch["rows"])
        await source.emit(DataEventType.BAR_AMENDED, bar(60, 102))
        assert (await second.next())["type"] == "resync"
        with pytest.raises(SyntheticError, match="generation"):
            await second.snapshot(generation=snapshot["generation"])
        await second.close()
        assert not source.active and not source.callbacks and not service.instances
    asyncio.run(run())


def test_gap_and_missing_confirmation_fail_closed():
    async def run():
        source = Source([bar(60, 100), bar(120, 106, closed=False)])
        service = SyntheticSeriesService(source)
        definition = SyntheticDefinition(SeriesKey("BTCUSDT", "1m"),
            SyntheticConfig("renko", semantics="anchored/1", box_size=2, min_tick=1), 60, 120)
        lease = await service.attach(definition)
        await source.emit(DataEventType.SOURCE_GAP)
        assert (await lease.next())["status"] == "stale"
        source.rows = [bar(60, 100), bar(120, 106)]
        await source.emit(DataEventType.SOURCE_GAP_RESOLVED)
        assert (await lease.next())["type"] == "resync"
        assert (await lease.snapshot())["status"] == "ready"
        await service.close()
        assert not source.active
    asyncio.run(run())


def test_missing_source_never_seeds_arbitrary_tail_and_budget_is_explicit():
    async def run():
        source = Source([bar(120, 100)])
        service = SyntheticSeriesService(source)
        definition = SyntheticDefinition(SeriesKey("BTCUSDT", "1m"), SyntheticConfig("heikin-ashi"), 60, 120)
        lease = await service.attach(definition)
        snapshot = await lease.snapshot()
        assert snapshot["status"] == "stale" and snapshot["total"] == 0
        await service.close()
        service = SyntheticSeriesService(Source([bar(60, 100)]), max_bytes=1)
        lease = await service.attach(SyntheticDefinition(definition.source, definition.config, 60, 60))
        assert (await lease.snapshot())["reason"] == "shared synthetic memory budget exceeded"
        await service.close()
    asyncio.run(run())


def test_one_cancelled_seed_consumer_does_not_cancel_other_consumer():
    async def run():
        started, proceed = asyncio.Event(), asyncio.Event()
        class DelayedSource(Source):
            async def ensure_stream(self, **kwargs):
                started.set()
                await proceed.wait()
                await super().ensure_stream(**kwargs)
        source = DelayedSource([bar(60, 100)])
        service = SyntheticSeriesService(source)
        definition = SyntheticDefinition(SeriesKey("BTCUSDT", "1m"), SyntheticConfig("heikin-ashi"), 60, 60)
        first = asyncio.create_task(service.attach(definition))
        await started.wait()
        second = asyncio.create_task(service.attach(definition))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        proceed.set()
        lease = await second
        assert (await lease.snapshot())["status"] == "ready"
        assert source.ensures == 1
        await lease.close()
        assert not source.active and not source.callbacks
    asyncio.run(run())


def test_consumer_payloads_do_not_alias_and_failed_capacity_preserves_last_result():
    async def run():
        source = Source([bar(60, 100), bar(120, 106, closed=False)])
        service = SyntheticSeriesService(source, max_bytes=20_000)
        definition = SyntheticDefinition(SeriesKey("BTCUSDT", "1m"), SyntheticConfig("renko", box_size=2, min_tick=1), 60, 120)
        first, second = await service.attach(definition), await service.attach(definition)
        await source.emit(DataEventType.BAR_UPDATED, bar(120, 108, closed=False))
        left, right = await first.next(), await second.next()
        left["rows"][0]["close"] = 999
        assert right["rows"][0]["close"] != 999
        before = deepcopy(first.instance.kernel.output)
        await source.emit(DataEventType.BAR_UPDATED, bar(120, 140, closed=False))
        assert (await first.next())["status"] == "stale"
        assert first.instance.kernel.output == before
        await service.close()
    asyncio.run(run())


def test_terminal_source_delivery_recreates_subscription_before_recovery():
    async def run():
        source = Source([bar(60, 100), bar(120, 106, closed=False)])
        service = SyntheticSeriesService(source)
        definition = SyntheticDefinition(SeriesKey("BTCUSDT", "1m"), SyntheticConfig("renko", box_size=2, min_tick=1), 60, 120)
        first = await service.attach(definition)
        instance = first.instance
        await instance.on_recovery(RuntimeError("queue exhausted"))
        assert (await first.next())["status"] == "stale"
        second = await service.attach(definition)
        assert second.instance is instance
        assert not instance.subscription_failed and len(source.callbacks) == 1
        assert (await second.snapshot())["status"] == "ready"
        assert (await second.next())["type"] == "resync"
        await source.emit(DataEventType.BAR_UPDATED, bar(120, 108, closed=False))
        assert (await second.next())["total"] == 4
        await service.close()
    asyncio.run(run())
