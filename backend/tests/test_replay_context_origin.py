from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from app.data_engine.ingestion.models import StreamType
from app.data_preparation.models import PreparationError
from app.data_preparation.replay_origin import (
    ReplayContextOrigins,
    ReplayOriginResolver,
)
from app.data_preparation.repository import PreparationRepository
from app.replay.catalog import ReplaySeriesIdentity

pytestmark = pytest.mark.anyio
MINUTE = 60_000


@pytest.mark.parametrize("exchange", ["binance", "okx"])
async def test_metadata_origin_is_not_local_cache_left_edge(exchange):
    identity = ReplaySeriesIdentity(exchange, "spot", "BTCUSDT")
    resolver = ReplayOriginResolver(
        symbol_lookup=lambda *_: {"listedAtMs": 1, "continuousTradingAtMs": MINUTE + 1}
    )
    assert await resolver(identity, 50 * MINUTE) == 2 * MINUTE
    assert await resolver(identity, MINUTE) == MINUTE
    unknown = ReplayOriginResolver(symbol_lookup=lambda *_: {})
    with pytest.raises(PreparationError) as failure:
        await unknown(identity, 50 * MINUTE)
    assert failure.value.code == "HISTORY_ORIGIN_UNKNOWN"


@pytest.mark.parametrize(
    "bad", [None, "wrong_market", "fractional", "future", "unavailable"]
)
async def test_ascending_provider_probe_validates_identity_and_bounds(bad):
    calls = []

    class Provider:
        async def fetch_market(self, descriptor, **kwargs):
            calls.append((descriptor, kwargs))
            if bad == "unavailable":
                raise RuntimeError("provider offline")
            return [
                SimpleNamespace(
                    exchange="binance",
                    market_type="futures" if bad == "wrong_market" else "spot",
                    symbol="BTCUSDT",
                    event_type=StreamType.KLINE,
                    data={
                        "open_time": 3 * MINUTE + 1
                        if bad == "fractional"
                        else 51 * MINUTE
                        if bad == "future"
                        else 3 * MINUTE
                    },
                )
            ]

    resolver = ReplayOriginResolver(factory=Provider(), symbol_lookup=lambda *_: {})
    identity = ReplaySeriesIdentity("binance", "spot", "BTCUSDT")
    if bad is None:
        assert await resolver(identity, 50 * MINUTE) == 3 * MINUTE
    else:
        with pytest.raises(PreparationError) as failure:
            await resolver(identity, 50 * MINUTE)
        assert failure.value.code == "HISTORY_ORIGIN_UNAVAILABLE"
    assert calls[0][1] == {
        "limit": 1,
        "start_ms": 0,
        "end_ms": 51 * MINUTE - 1,
        "history": True,
        "defer_on_rate_limit": True,
    }


async def test_unknown_provider_never_assumes_ascending_probe_and_retention_is_explicit():
    class Provider:
        async def fetch_market(self, *args, **kwargs):
            pytest.fail("unknown provider pagination must not be guessed")

    identity = ReplaySeriesIdentity("okx", "spot", "BTCUSDT")
    resolver = ReplayOriginResolver(factory=Provider(), symbol_lookup=lambda *_: {})
    with pytest.raises(PreparationError, match="verified history origin"):
        await resolver(identity, 50 * MINUTE)
    policy = SimpleNamespace(
        series_key=lambda **_: None,
        resolve=lambda _: SimpleNamespace(
            availability=SimpleNamespace(rolling_retention_ms=MINUTE)
        ),
    )
    resolver = ReplayOriginResolver(
        policy=policy, symbol_lookup=lambda *_: {"listedAtMs": 0}
    )
    with pytest.raises(PreparationError, match="rolling retention"):
        await resolver(identity, 50 * MINUTE)


async def test_origin_publication_is_durable_first_wins_and_rejects_cache_release_race(
    tmp_path,
):
    path = tmp_path / "jobs.sqlite3"
    store = ReplayContextOrigins(PreparationRepository(path))
    generation = store.generation()
    selected = store.pin("source", generation, MINUTE, 50 * MINUTE)
    assert store.pin("source", generation, 2 * MINUTE, 50 * MINUTE) == selected
    reopened = ReplayContextOrigins(PreparationRepository(path))
    assert reopened.get("source") == selected
    from threading import Barrier

    barrier = Barrier(2)

    def competing_pin(start):
        barrier.wait(timeout=2)
        return store.pin("concurrent", generation, start, 50 * MINUTE)

    left, right = await asyncio.gather(
        asyncio.to_thread(competing_pin, MINUTE),
        asyncio.to_thread(competing_pin, 2 * MINUTE),
    )
    assert left == right and left.start_ms in {MINUTE, 2 * MINUTE}
    with store.repository.connect() as db:
        db.execute("UPDATE preparation_context_state SET generation=generation+1")
        db.execute("DELETE FROM preparation_context_origins")
    with pytest.raises(PreparationError) as failure:
        store.pin("source", generation, MINUTE, 50 * MINUTE)
    assert failure.value.code == "HISTORY_ORIGIN_CHANGED"


async def test_indicator_context_bridge_drains_async_cleanup_before_freeing_lane():
    from threading import Event

    from app.replay.training.indicator_context import await_context
    from app.replay.training.indicator_jobs import IndicatorPreparationJobs

    started, cleanup_started, release = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    cancelled, jobs = Event(), IndicatorPreparationJobs()

    async def download():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release.wait()

    loop = asyncio.get_running_loop()
    task = asyncio.create_task(
        jobs.run(
            ("source",),
            lambda: asyncio.to_thread(
                await_context, download(), loop=loop, cancelled=cancelled
            ),
            cancelled,
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.wait_for(cleanup_started.wait(), 2)
    assert not task.done() and jobs._waiting
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not jobs._waiting


async def test_calendar_context_reads_share_one_deadline_and_keep_completed_days(
    tmp_path, monkeypatch
):
    from app.data_preparation.models import Requirement
    from app.data_preparation.replay_context import ReplayHistoryContext
    from app.data_preparation.replay_origin import DAY, ReplayContextOrigin

    owner = SimpleNamespace(repository=PreparationRepository(tmp_path / "jobs.db"))
    context = ReplayHistoryContext(owner, wait_seconds=0.5)
    origin = ReplayContextOrigin("source", 0, 0, 3 * DAY)
    clock, ready = [0.0], set()
    monkeypatch.setattr(
        "app.data_preparation.replay_context.time",
        SimpleNamespace(monotonic=lambda: clock[0]),
    )

    async def prepared(requirement, **kwargs):
        if requirement.start_ms not in ready:
            clock[0] += 0.3
            ready.add(requirement.start_ms)
        return [
            {"open_time": timestamp}
            for timestamp in range(requirement.start_ms, requirement.end_ms, MINUTE)
        ]

    async def validate(_):
        return None

    monkeypatch.setattr(context, "_prepared_rows", prepared)
    monkeypatch.setattr(context, "assert_origin", validate)
    requirement = Requirement(
        exchange="binance",
        market_type="spot",
        symbol="BTCUSDT",
        start_ms=0,
        end_ms=3 * DAY,
    )
    with pytest.raises(PreparationError) as failure:
        await context._rows(requirement, origin=origin)
    assert failure.value.code == "HISTORY_DOWNLOAD_PENDING"
    assert ready == {0, DAY}
    rows = await context._rows(requirement, origin=origin)
    assert len(rows) == 3 * DAY // MINUTE and ready == {0, DAY, 2 * DAY}


@pytest.mark.parametrize("interval,minutes", [("3m", 3), ("3d", 4320)])
@pytest.mark.parametrize("blind", [False, True])
async def test_context_aggregates_on_provider_native_phase(interval, minutes, blind):
    from decimal import Decimal

    from app.data_preparation.replay_context import (
        ReplayHistoryContext,
        project_context,
    )
    from app.data_preparation.replay_origin import ReplayContextOrigin
    from app.replay.display_time import SourceBucketTimeMapper

    from tests.test_data_preparation import START
    from tests.test_replay_indicator_prepared_context import market_row

    start = START + MINUTE
    stop = start + (2 * minutes + 2) * MINUTE
    mapper = SourceBucketTimeMapper.create(
        interval=interval,
        actual_replay_start_ms=stop,
        public_replay_start_ms=1000 * 86_400_000 if blind else stop,
        source_bucket_anchor_ms=start,
    )
    rows = [market_row(t) for t in range(start, stop, MINUTE)]
    result = project_context(
        rows,
        start,
        stop,
        mapper,
        ReplaySeriesIdentity("binance", "spot", "BTCUSDT"),
        include_active=True,
    )
    assert len(result) == 3
    for index, bar in enumerate(result):
        selected = rows[index * minutes : (index + 1) * minutes]
        assert bar["open_time_ms"] == mapper.public_from_actual(
            start + index * minutes * MINUTE
        )
        assert bar["component_count"] == len(selected)
        assert bar["is_closed"] == (index < 2)
        assert Decimal(bar["open"]) == Decimal(str(selected[0]["open"]))
        assert Decimal(bar["close"]) == Decimal(str(selected[-1]["close"]))
        assert Decimal(bar["high"]) == max(
            Decimal(str(row["high"])) for row in selected
        )
        assert Decimal(bar["low"]) == min(Decimal(str(row["low"])) for row in selected)
        assert Decimal(bar["volume"]) == sum(
            Decimal(str(row["volume"])) for row in selected
        )
    origin = ReplayContextOrigin("source", 0, start + MINUTE, stop)
    assert (
        ReplayHistoryContext.public_origin(origin, mapper) == result[1]["open_time_ms"]
    )
