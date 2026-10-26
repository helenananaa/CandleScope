from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.market_inputs import MarketObjectCache, MarketRows
from app.data_preparation.models import (
    PreparationError,
    PreparationRequest,
    Requirement,
)
from app.data_preparation.replay_context import ReplayHistoryContext, project_context
from app.data_preparation.replay_origin import DAY, ReplayContextOrigin
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.display_time import SourceBucketTimeMapper

from tests.test_data_preparation import Adapter, async_test, terminal
from tests.test_replay_indicator_prepared_context import START, market_row


def stored(adapter, start=START, count=1440, symbol="BTCUSDT"):
    requirement = Requirement(
        exchange="binance",
        market_type="spot",
        symbol=symbol,
        start_ms=start,
        end_ms=start + count * 60_000,
    )
    rows = [
        dict(market_row(t), symbol=symbol)
        for t in range(start, requirement.end_ms, 60_000)
    ]
    receipt, _ = adapter._write(rows, requirement)
    return {"receipt": receipt, "requirement": requirement.model_dump()}


def test_inputs_are_shared_but_public_rows_are_detached_and_revalidated(
    tmp_path, monkeypatch
):
    adapter = BarPreparationAdapter(tmp_path, coordinator=None)
    chunk = stored(adapter)
    calls = []
    complete = adapter._complete
    monkeypatch.setattr(
        adapter, "_complete", lambda *a, **kw: (calls.append(1), complete(*a, **kw))[1]
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(adapter.read_shared, [chunk] * 4))
    assert len(calls) == 1
    assert all(item[0] is results[0][0] for item in results)
    with pytest.raises(TypeError):
        results[0][0]["close"] = "999"
    detached = adapter.read(chunk)
    detached[0]["close"] = "999"
    assert adapter.read(chunk)[0]["close"] != "999"
    with pytest.raises(PreparationError, match="corrupt"):
        adapter.read_shared(
            {**chunk, "receipt": {**chunk["receipt"], "origin": "other"}}
        )
    with pytest.raises(PreparationError, match="corrupt"):
        adapter.read_shared(
            {
                **chunk,
                "source_requirement": {**chunk["requirement"], "symbol": "DOGEUSDT"},
            }
        )
    path = tmp_path / (chunk["receipt"]["sha256"] + ".json.gz")
    path.write_bytes(b"corrupt replacement")
    with pytest.raises(PreparationError, match="corrupt"):
        adapter.read_shared(chunk)
    path.unlink()
    with pytest.raises(PreparationError, match="corrupt"):
        adapter.read_shared(chunk)


@pytest.mark.parametrize(
    "interval,phase", [("1m", 0), ("7m", 60_000), ("90m", 0), ("3d", 60_000)]
)
@pytest.mark.parametrize("blind,active", [(False, False), (True, False), (True, True)])
def test_source_projection_matches_reference_and_is_shared_across_public_time(
    tmp_path, monkeypatch, interval, phase, blind, active
):
    adapter = BarPreparationAdapter(tmp_path, coordinator=None)
    count = 1440 * 4 if interval == "3d" else 1440
    chunk = stored(adapter, count=count)
    rows = adapter.read_shared(chunk)
    end = START + count * 60_000
    mapper = SourceBucketTimeMapper.create(
        interval=interval,
        actual_replay_start_ms=end,
        public_replay_start_ms=10 * DAY if blind else end,
        source_bucket_anchor_ms=phase,
    )
    # A partial final bucket and an unaligned left edge retain the builder's
    # original behavior; cached projection cannot invent a complete candle.
    expected = project_context(
        list(rows),
        START,
        end,
        mapper,
        ReplaySeriesIdentity("binance", "spot", "BTCUSDT"),
        include_active=active,
    )
    identity = ReplaySeriesIdentity("binance", "spot", "BTCUSDT")
    actual = project_context(rows, START, end, mapper, identity, include_active=active)
    assert actual == expected
    from app.data_preparation import market_projection

    original = market_projection.project_bucket

    def forbidden(*a, **kw):
        raise AssertionError("resident source buckets should not be projected again")

    monkeypatch.setattr(market_projection, "project_bucket", forbidden)
    other = replace(mapper, public_anchor_ms=mapper.public_anchor_ms + 100 * DAY)
    shared = project_context(rows, START, end, other, identity, include_active=active)
    monkeypatch.setattr(market_projection, "project_bucket", original)
    assert shared == project_context(
        list(rows), START, end, other, identity, include_active=active
    )
    assert (
        adapter.market_inputs.snapshot()["retained_bytes"]
        <= adapter.market_inputs.max_bytes
    )


def test_overlapping_prefixes_reuse_source_buckets_and_bind_partial_end(
    tmp_path, monkeypatch
):
    from app.data_preparation import market_projection

    adapter = BarPreparationAdapter(tmp_path, coordinator=None)
    rows = adapter.read_shared(stored(adapter, count=1440 * 3))
    end = START + 3 * DAY
    mapper = SourceBucketTimeMapper.create(
        interval="90m", actual_replay_start_ms=end, public_replay_start_ms=end
    )
    identity = ReplaySeriesIdentity("binance", "spot", "BTCUSDT")
    calls = []
    original = market_projection.project_bucket

    def record(source, left, right, *args, **kwargs):
        calls.append((left, right))
        return original(source, left, right, *args, **kwargs)

    monkeypatch.setattr(market_projection, "project_bucket", record)
    narrow = MarketRows.join([rows], end - 19 * 90 * 60_000, end)
    project_context(narrow, end - 19 * 90 * 60_000, end, mapper, identity)
    wide = MarketRows.join([rows], end - 42 * 90 * 60_000, end)
    project_context(wide, end - 42 * 90 * 60_000, end, mapper, identity)
    assert len(calls) == 42
    partial = MarketRows.join([rows], end - 90 * 60_000, end - 60_000)
    answer = project_context(
        partial, end - 90 * 60_000, end - 60_000, mapper, identity, include_active=True
    )
    assert not answer[-1]["is_closed"] and answer[-1]["component_count"] == 89
    assert len(calls) == 43


def test_single_flight_is_bounded_and_release_does_not_publish_old_work():
    cache = MarketObjectCache(max_bytes=2048, max_inflight=2)
    entered, release = Event(), Event()

    def load():
        entered.set()
        assert release.wait(5)
        return ("old",)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(cache.get, "same", load)
        assert entered.wait(5)
        cache.clear()
        fresh = cache.get("same", lambda: ("new",))
        assert fresh == ("new",)
        release.set()
        assert owner.result() == ("old",)
    assert cache.get("same", lambda: pytest.fail("new generation was lost")) == ("new",)
    for i in range(50):
        cache.get(i, lambda: ("x" * 500,))
    snapshot = cache.snapshot()
    assert (
        snapshot["evictions"]
        and snapshot["retained_bytes"] <= 2048
        and snapshot["inflight"] == 0
    )


@async_test
async def test_visible_history_uses_both_workers_but_background_reserves_one(tmp_path):
    adapter = Adapter()
    service = PreparationService(
        PreparationRepository(tmp_path / "jobs.db"), adapter, workers=2
    )
    await service.start()
    try:

        def request(index, visible):
            return PreparationRequest(
                idempotency_key=f"visible-{index}-{visible}",
                consumer="PREFETCH",
                intent={"purpose": "replay_display_history"} if visible else {},
                requirements=[
                    Requirement(
                        exchange="binance",
                        market_type="spot",
                        symbol="BTCUSDT",
                        start_ms=START + index * DAY,
                        end_ms=START + index * DAY + 60_000,
                    )
                ],
            )

        background = [await service.submit(request(i, False)) for i in range(2)]
        await asyncio.wait_for(adapter.entered.wait(), 2)
        await asyncio.sleep(0.55)
        assert adapter.calls == 1
        visible = await service.submit(request(3, True))
        for _ in range(100):
            if adapter.calls == 2:
                break
            await asyncio.sleep(0.01)
        assert adapter.calls == 2 and len(service._tasks) == 2
        adapter.release.set()
        for job in [*background, visible]:
            assert (await terminal(service, job["id"]))["state"] == "READY"
        # Two visible requests may both run even though they persist as PREFETCH.
        adapter.release.clear()
        before = adapter.calls
        first, second = [await service.submit(request(i, True)) for i in [5, 6]]
        for _ in range(100):
            if adapter.calls == before + 2:
                break
            await asyncio.sleep(0.01)
        assert adapter.calls == before + 2
        adapter.release.set()
        for job in [first, second]:
            assert (await terminal(service, job["id"]))["state"] == "READY"
    finally:
        adapter.release.set()
        await service.shutdown()


@async_test
async def test_parallel_daily_reads_drain_cancelled_observers(tmp_path, monkeypatch):
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), Adapter())
    context = ReplayHistoryContext(service)
    origin = ReplayContextOrigin("test", 0, START, START + 20 * DAY)
    active = set()
    entered = asyncio.Event()
    drained = []

    async def read(requirement, **kwargs):
        active.add(requirement.start_ms)
        if len(active) == 8:
            entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.01)
            active.remove(requirement.start_ms)
            drained.append(requirement.start_ms)

    monkeypatch.setattr(context, "_prepared_rows", read)
    requirement = Requirement(
        exchange="binance",
        market_type="spot",
        symbol="BTCUSDT",
        start_ms=START,
        end_ms=START + 20 * DAY,
    )
    task = asyncio.create_task(context._rows(requirement, origin=origin))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not active and len(drained) == 8


@pytest.mark.parametrize("precision", [6, 28, 60])
@pytest.mark.parametrize("nullable", [False, True])
def test_decimal_and_optional_columns_preserve_builder_arithmetic(
    tmp_path, precision, nullable
):
    from decimal import localcontext

    adapter = BarPreparationAdapter(tmp_path, coordinator=None)
    requirement = Requirement(
        exchange="binance",
        market_type="spot",
        symbol="BTCUSDT",
        start_ms=START,
        end_ms=START + 90 * 60_000,
    )
    rows = []
    for i in range(90):
        row = market_row(START + i * 60_000)
        row.update(
            volume="123456789012345678901234567890.123456789",
            quote_volume="0.00000000000000000012345",
            taker_buy_base="12.34000",
            taker_buy_quote="0.000123",
            trades=2**53 + i,
        )
        if nullable and i == 47:
            row.update(quote_volume=None, taker_buy_base=None, trades=None)
        rows.append(row)
    receipt, _ = adapter._write(rows, requirement)
    shared = adapter.read_shared(
        {"receipt": receipt, "requirement": requirement.model_dump()}
    )
    mapper = SourceBucketTimeMapper.create(
        interval="90m",
        actual_replay_start_ms=requirement.end_ms,
        public_replay_start_ms=requirement.end_ms,
    )
    identity = ReplaySeriesIdentity("binance", "spot", "BTCUSDT")
    with localcontext() as arithmetic:
        arithmetic.prec = precision
        assert project_context(
            shared, START, requirement.end_ms, mapper, identity
        ) == project_context(rows, START, requirement.end_ms, mapper, identity)


def test_nested_provider_metadata_stays_detached(tmp_path):
    adapter = BarPreparationAdapter(tmp_path, coordinator=None)
    requirement = Requirement(
        exchange="binance",
        market_type="spot",
        symbol="BTCUSDT",
        start_ms=START,
        end_ms=START + 60_000,
    )
    row = {**market_row(START), "metadata": {"tags": ["original"]}}
    receipt, _ = adapter._write([row], requirement)
    chunk = {"receipt": receipt, "requirement": requirement.model_dump()}
    detached = adapter.read(chunk)
    detached[0]["metadata"]["tags"].append("changed")
    assert adapter.read(chunk)[0]["metadata"]["tags"] == ["original"]


def test_cache_admission_and_failed_load_retry(tmp_path):
    cache = MarketObjectCache(max_inflight=1)
    adapter = BarPreparationAdapter(tmp_path, coordinator=None)
    adapter.market_inputs = cache
    chunk = stored(adapter, count=1)
    entered, release = Event(), Event()

    def load():
        entered.set()
        assert release.wait(5)
        raise ValueError("invalid source")

    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(cache.get, "one", load)
        assert entered.wait(5)
        with pytest.raises(PreparationError) as busy:
            cache.get("two", lambda: None)
        assert busy.value.code == "HISTORY_CACHE_BUSY" and busy.value.retryable
        with pytest.raises(PreparationError) as source_busy:
            adapter.read_shared(chunk)
        assert (
            source_busy.value.code == "HISTORY_CACHE_BUSY"
            and source_busy.value.retryable
        )
        release.set()
        with pytest.raises(ValueError, match="invalid source"):
            owner.result()
    assert cache.snapshot()["inflight"] == 0
    assert cache.get("one", lambda: "recovered") == "recovered"


def test_calendar_projection_preserves_leap_month_and_blind_mapping(tmp_path):
    from datetime import datetime, timezone

    start = int(datetime(2028, 2, 1, tzinfo=timezone.utc).timestamp()) * 1000
    end = int(datetime(2028, 3, 1, tzinfo=timezone.utc).timestamp()) * 1000
    adapter = BarPreparationAdapter(tmp_path, coordinator=None)
    rows = adapter.read_shared(
        stored(adapter, start=start, count=(end - start) // 60_000)
    )
    mapper = SourceBucketTimeMapper.create(
        interval="1M", actual_replay_start_ms=end, public_replay_start_ms=800 * DAY
    )
    identity = ReplaySeriesIdentity("binance", "spot", "BTCUSDT")
    actual = project_context(rows, start, end, mapper, identity)
    assert actual == project_context(list(rows), start, end, mapper, identity)
    assert len(actual) == 1 and actual[0]["is_closed"]


@pytest.mark.parametrize("invalid", ["gap", "wrong-market", "forming", "ohlc"])
def test_shared_projection_does_not_hide_invalid_input(tmp_path, invalid):
    from app.data_preparation.market_inputs import frozen_object

    rows = [market_row(START + i * 60_000) for i in range(7)]
    if invalid == "gap":
        rows[3]["open_time"] += 60_000
    elif invalid == "wrong-market":
        rows[3]["symbol"] = "DOGEUSDT"
    elif invalid == "forming":
        rows[3]["is_closed"] = False
    else:
        rows[3]["high"] = "1"
    shared = MarketRows(
        frozen_object(rows).value,
        ((("test",), START, START + 7 * 60_000),),
        MarketObjectCache(),
    )
    mapper = SourceBucketTimeMapper.create(
        interval="7m",
        actual_replay_start_ms=START + 7 * 60_000,
        public_replay_start_ms=START + 7 * 60_000,
    )
    identity = ReplaySeriesIdentity("binance", "spot", "BTCUSDT")
    with pytest.raises(Exception) as original:
        project_context(list(shared), START, START + 7 * 60_000, mapper, identity)
    with pytest.raises(type(original.value)):
        project_context(shared, START, START + 7 * 60_000, mapper, identity)
