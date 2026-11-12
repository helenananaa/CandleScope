from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType, SeriesKey
from app.data_engine.data_manager.stream_version import StreamVersionClock
from app.data_engine.synthetic_series.core import SyntheticConfig, SyntheticError, SyntheticKernel
from app.data_engine.synthetic_series.service import SyntheticDefinition, SyntheticSeriesService
from app.data_engine.history.calendar import AlwaysOpenCalendar


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


@pytest.mark.parametrize("transform", ["renko", "heikin-ashi", "point-and-figure", "kagi", "line-break"])
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


@pytest.mark.parametrize("transform", ["point-and-figure", "kagi"])
def test_active_column_or_leg_replacement_does_not_duplicate_output(transform):
    kernel = SyntheticKernel(SyntheticConfig(transform, semantics="anchored/1", box_size=2,
        reversal_amount=2, min_tick=1))
    kernel.replace([bar(60, 100), bar(120, 104)])
    assert len(kernel.output) == 1
    kernel.apply(bar(180, 110, closed=False))
    assert len(kernel.output) == 1 and kernel.output[0]["close"] == 110
    assert kernel.output[0]["time"]["order"] == 0
    kernel.apply(bar(180, 104, closed=False))
    assert len(kernel.output) == 1 and kernel.output[0]["close"] == 104
    assert kernel.output[0]["time"]["sourceTime"] == 120
    kernel.apply(bar(180, 110))
    kernel.apply(bar(240, 100, closed=False))
    assert len(kernel.output) == 2
    assert [item["time"]["order"] for item in kernel.output] == [0, 1]
    kernel.apply(bar(240, 110, closed=False))
    assert len(kernel.output) == 1 and kernel.output[0]["close"] == 110


def test_kagi_strict_style_boundaries_and_line_break_reference_window():
    kernel = SyntheticKernel(SyntheticConfig("kagi", semantics="anchored/1", min_tick=1, reversal_amount=2))
    result = kernel.replace([bar(60, 100), bar(120, 106), bar(180, 102), bar(240, 106), bar(300, 108)])
    tail = result[-1]["customValues"]["kagi"]
    assert tail["state"] == "yang"
    assert tail["sections"] == [{"from": 102, "to": 106, "style": "yin"},
        {"from": 106, "to": 108, "style": "yang"}]
    line = SyntheticKernel(SyntheticConfig("line-break", semantics="anchored/1", min_tick=1, number_of_lines=2))
    result = line.replace([bar(60, 100), bar(120, 106), bar(180, 108), bar(240, 107), bar(300, 99)])
    assert [(item["open"], item["close"]) for item in result] == [(100, 106), (106, 108), (106, 99)]
    assert result[-1]["customValues"]["lineBreak"]["referenceHigh"] == 108
    assert result[-1]["customValues"]["lineBreak"]["referenceLow"] == 100


@pytest.mark.parametrize("transform", ["heikin-ashi", "renko", "point-and-figure", "kagi", "line-break"])
@pytest.mark.parametrize("mode", ["traditional", "atr"])
def test_repeated_forming_observations_and_parameter_recalibration_equal_full_prefix(transform, mode):
    config = SyntheticConfig(transform, mode=mode, box_size=2, reversal_amount=2, number_of_lines=2)
    actual, expected = SyntheticKernel(config), SyntheticKernel(config)
    rows = [bar(60, 100)]
    actual.replace(rows)
    for index, price in enumerate([106, 102, 110, 114, 100, 96, 108, 104, 98, 112], start=2):
        preview = bar(index * 60, price + 8, closed=False)
        actual.apply(preview)
        expected.replace([*rows, preview])
        assert actual.output == expected.output
        preview = bar(index * 60, price, closed=False)
        actual.apply(preview)
        expected.replace([*rows, preview])
        assert actual.output == expected.output
        rows.append(bar(index * 60, price))
        actual.apply(rows[-1])
        expected.replace(rows)
        assert actual.output == expected.output


def test_extreme_output_rejected_atomically():
    kernel = SyntheticKernel(SyntheticConfig("renko", semantics="anchored/1", min_tick=1))
    kernel.replace([bar(60, 100)])
    before = deepcopy(kernel.__dict__)
    with pytest.raises(SyntheticError, match="brick budget"):
        kernel.apply(bar(120, 20_000))
    assert kernel.__dict__ == before


def test_rounding_at_safe_integer_boundary_does_not_overflow_on_half_addition():
    kernel = SyntheticKernel(SyntheticConfig("renko", semantics="anchored/1", min_tick=1))
    kernel.replace([bar(60, 2**53 - 1)])
    assert kernel._state["last"] == 2**53 - 1
    with pytest.raises(SyntheticError, match="safe integer"):
        kernel.apply(bar(120, 2**53))


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


def test_source_calendar_is_reused_for_session_gaps_instead_of_crypto_grid():
    async def run():
        class SessionCalendar(AlwaysOpenCalendar):
            def expected_opens(self, start_ms, end_ms, interval):
                return iter(value for value in (60_000, 180_000) if start_ms <= value <= end_ms)
            def count_expected(self, start_ms, end_ms, interval):
                return len(list(self.expected_opens(start_ms, end_ms, interval)))
            def next_expected_open(self, open_ms, interval):
                return 180_000 if open_ms == 60_000 else 240_000
        source = Source([bar(60, 100), bar(180, 106)])
        source.calendar_for = lambda key: SessionCalendar()
        service = SyntheticSeriesService(source)
        key = SeriesKey("BTCUSDT", "1m", asset_class="equity", session_variant="regular")
        lease = await service.attach(SyntheticDefinition(key, SyntheticConfig("heikin-ashi"), 60, 180))
        assert (await lease.snapshot())["status"] == "ready"
        assert lease.instance.calendar.next_expected_open(60_000, "1m") == 180_000
        await lease.close()
    asyncio.run(run())


def test_complete_window_chunks_pin_one_snapshot_then_deliver_queued_tail():
    async def run():
        source = Source([bar(60, 100), bar(120, 6100, closed=False)])
        service = SyntheticSeriesService(source)
        lease = await service.attach(SyntheticDefinition(SeriesKey("BTCUSDT", "1m"),
            SyntheticConfig("renko", min_tick=1), 60, 120))
        parts = lease.snapshot_chunks(limit=2000)
        first = await anext(parts)
        assert first["from_index"] == 0 and first["total"] == 6000 and first["complete"] is False
        await source.emit(DataEventType.BAR_UPDATED, bar(120, 6105, closed=False))
        rest = [part async for part in parts]
        assert [part["from_index"] for part in rest] == [2000, 4000]
        assert all(part["revision"] == first["revision"] and part["generation"] == first["generation"] for part in rest)
        assert rest[-1]["complete"] is True
        assert sum(len(part["rows"]) for part in [first, *rest]) == 6000
        delta = await lease.next()
        assert delta["from_index"] == 6000 and delta["total"] == 6005 and len(delta["rows"]) == 5
        await lease.close()
    asyncio.run(run())
