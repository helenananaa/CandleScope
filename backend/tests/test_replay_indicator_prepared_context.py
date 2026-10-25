from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest
from app.api.v1.data_preparation import router
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.replay_context import ReplayHistoryContext, project_context
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.display_time import SourceBucketTimeMapper
from app.replay.history_archive import ReplayHistoryRepository
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.replay.training.errors import TrainingRunError
from app.replay.training.indicator_prefix import CanonicalReplayIndicators
from fastapi import FastAPI

from tests.fixtures.replay.service_fakes import replay_settings
from tests.test_data_preparation import START, bars, terminal
from tests.test_replay_indicator_prefix import lines, reference
from tests.test_replay_v2_run_centric import _setup_payload
from tests.test_replay_v2_training_api import _app, _request

pytestmark = pytest.mark.anyio
MINUTE = 60_000
REPLAY_START = START + 1207 * MINUTE


@pytest.fixture(autouse=True)
def one_page_indicator_budget(monkeypatch):
    # Exercise continuation deterministically, including on fast machines.
    original = CanonicalReplayIndicators.__init__

    def initialize(self, checkpoints, **options):
        original(self, checkpoints, **{**options, "max_prefix_pages": 1})

    monkeypatch.setattr(CanonicalReplayIndicators, "__init__", initialize)


async def ready_indicator(compute):
    pending = []
    async with asyncio.timeout(30):
        while True:
            result = await compute()
            assert result["status"] in {"ready", "preparing"}, result
            if pending:
                assert result["seed"] == pending[-1]["seed"]
            if result["status"] == "ready":
                return result, pending
            assert "payload" not in result
            assert result["prepared_before_ms"] <= result["target_before_ms"]
            if pending:
                assert result["target_before_ms"] == pending[-1]["target_before_ms"]
                assert result["prepared_before_ms"] >= pending[-1]["prepared_before_ms"]
            pending.append(result)
            await asyncio.sleep(0.01)


def market_row(timestamp):
    index = (timestamp - START) // MINUTE
    price = 100 + index % 17 + index / 500
    return {
        **bars()[0],
        "open_time": timestamp,
        "close_time": timestamp + MINUTE - 1,
        "open": price - 1,
        "high": price + 2,
        "low": price - 2,
        "close": price,
        "volume": index + 1,
    }


@asynccontextmanager
async def prepared_run(tmp_path, progressive, disclosure, *, prepare_timeout=5):
    archive = tmp_path / "archive"

    def new_replay():
        return ReplayService(
            settings=replace(
                replay_settings(tmp_path / "replay.db"),
                replay_history_archive_dir=archive,
                controller_ttl_seconds=10,
            ),
            store=ReplaySQLiteStore(tmp_path / "replay.db"),
            repository=ReplayHistoryRepository(archive),
            native_intervals=lambda _: ("1m",),
        )

    replay = new_replay()
    await replay.start()
    values, downloads, origin_calls = {}, [], []

    class Coordinator:
        async def request_and_wait(self, repair):
            downloads.append((repair.start_ms, repair.end_ms))
            for timestamp in range(repair.start_ms, repair.end_ms + 1, MINUTE):
                values[timestamp] = market_row(timestamp)

    async def origin(identity, frozen_start):
        origin_calls.append((identity, frozen_start))
        return START

    adapter = BarPreparationAdapter(
        tmp_path / "chunks",
        coordinator=Coordinator(),
        replay_service=replay,
        query=lambda *args, **kw: [
            values[t] for t in sorted(values) if kw["start_ms"] <= t <= kw["end_ms"]
        ],
    )
    preparation = PreparationService(
        PreparationRepository(tmp_path / "jobs.db"), adapter
    )
    await preparation.start()
    replay.history_context = ReplayHistoryContext(preparation, origin_resolver=origin)
    try:
        setup = {
            **_setup_payload(),
            "requested_start_ms": REPLAY_START,
            "visible_history_lookback": {"mode": "ALL_AVAILABLE", "duration_ms": None},
            "time_disclosure_policy": disclosure,
        }
        app = FastAPI()
        app.state.data_preparation_service = preparation
        app.include_router(router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/data-preparations/replay",
                json={
                    "idempotency_key": "canonical-prepared-context",
                    "setup": setup,
                    "exchange": "binance",
                    "market_type": "spot",
                    "symbol": "BTCUSDT",
                    "progressive": progressive,
                },
            )
        assert response.status_code == 202, response.text
        job = await terminal(preparation, response.json()["id"], timeout=prepare_timeout)
        assert job["state"] == "READY", job
        session = job["result"]["run"]["adapter_session_id"]
        yield (
            replay,
            preparation,
            session,
            new_replay,
            origin,
            origin_calls,
            downloads,
            values,
        )
    finally:
        await preparation.shutdown()
        await replay.shutdown()


@pytest.mark.parametrize(
    "progressive,disclosure",
    [(False, "NONE"), (False, "HIDE_ALL"), (True, "NONE"), (True, "HIDE_ALL")],
)
async def test_automatic_context_has_one_origin_across_windows_intervals_and_restart(
    tmp_path, progressive, disclosure
):
    async with prepared_run(tmp_path, progressive, disclosure) as fixture:
        (
            replay,
            preparation,
            session,
            new_replay,
            resolver,
            origin_calls,
            downloads,
            _,
        ) = fixture
        before = (await replay.get_session(session))["snapshot"]
        state = await replay.get_session_state(session)
        boundary = state["cursor"]["virtual_time_ms"]
        dataset = await replay.store.load_dataset(session)
        for interval in ["1m", "5m", "90m"]:
            query = {
                "track_id": "track-1",
                "revealed_boundary_ms": boundary,
                "limit": 12,
                "data_epoch": state["data_epoch"],
                "history_epoch": None,
                "display_interval": interval,
            }
            window = await replay.training.history_page(
                session, before_ms=boundary, **query
            )
            assert len(window["bars"]) >= 3
            payload = {
                key: value
                for key, value in query.items()
                if key not in {"limit", "history_epoch"}
            }
            payload.update(
                name="RSI",
                params={"period": 2},
                bars=window["bars"][-3:],
                history_epoch=window["history_epoch"],
            )
            if interval == "1m":
                with pytest.raises(TrainingRunError) as stale:
                    await replay.training.canonical_indicator_compute(
                        session, **payload
                    )
                assert stale.value.code == "HISTORY_EPOCH_MISMATCH"
                assert stale.value.details["reload_history"] is True
                fresh = await replay.training.history_page(
                    session, before_ms=boundary, **query
                )
                payload.update(
                    bars=fresh["bars"][-3:], history_epoch=fresh["history_epoch"]
                )
            async def request_indicator():
                response = await _request(
                    _app(replay),
                    "POST",
                    f"/api/v1/replay/runs/session/{session}/indicator-compute",
                    json=payload,
                )
                assert response.status_code == 200, response.text
                return response.json()

            result, pending = await ready_indicator(request_indicator)
            if interval == "1m":
                assert pending, "The test must cover a partial prefix and its continuation"
            mapper = SourceBucketTimeMapper.create(
                interval=interval,
                actual_replay_start_ms=REPLAY_START,
                public_replay_start_ms=boundary + 1,
            )
            stop = mapper.actual_containing_bucket_open(REPLAY_START)
            projected = project_context(
                [market_row(t) for t in range(START, stop, MINUTE)],
                START,
                stop,
                mapper,
                ReplaySeriesIdentity("binance", "spot", "BTCUSDT"),
            )
            expected = reference(
                "RSI",
                {"period": 2},
                [ReplayDisplayBar.from_dict(row) for row in projected],
            )
            times = {row["open_time_ms"] // 1000 for row in payload["bars"]}
            assert lines(result["payload"]) == [
                (name, [point for point in points if point["time"] in times])
                for name, points in lines(expected)
            ]
            second = await replay.training.canonical_indicator_compute(
                session, **{**payload, "bars": payload["bars"][-2:]}
            )
            assert second["seed"] == result["seed"]
            assert lines(second["payload"])[0][1] == lines(result["payload"])[0][1][-2:]
            pinned = await replay.training.history_page(
                session, before_ms=boundary, **query
            )
            assert pinned["history_epoch"] == result["seed"]["history_epoch"]
            assert pinned["history_boundary_ms"] == result["seed"]["origin_ms"]
            end = await replay.training.history_page(
                session, before_ms=pinned["history_boundary_ms"], **query
            )
            assert not end["bars"] and not end["has_more"]
            if interval == "1m":
                with pytest.raises(TrainingRunError, match="epoch"):
                    await replay.training.history_page(
                        session,
                        before_ms=boundary,
                        **{**query, "history_epoch": window["history_epoch"]},
                    )
        assert len(origin_calls) == 1
        assert await replay.store.load_dataset(session) == dataset
        assert (await replay.get_session(session))["snapshot"] == before
        await replay.shutdown()
        reopened = new_replay()
        await reopened.start()
        reopened.history_context = ReplayHistoryContext(
            preparation, origin_resolver=resolver
        )
        try:
            count = len(downloads)
            restored = await reopened.training.canonical_indicator_compute(
                session, **payload
            )
            assert restored["payload"] == result["payload"]
            assert restored["seed"] == result["seed"]
            assert restored["prefix_rows_read"] == 0
            assert len(origin_calls) == 1 and len(downloads) == count
            assert (await reopened.get_session_state(session))["cursor"] == state[
                "cursor"
            ]
        finally:
            await reopened.shutdown()


async def test_release_context_cache_invalidates_saved_math_and_origin(tmp_path):
    async with prepared_run(tmp_path, False, "NONE") as fixture:
        replay, preparation, session, _, _, origin_calls, _, values = fixture
        state = await replay.get_session_state(session)
        boundary = state["cursor"]["virtual_time_ms"]
        query = {
            "track_id": "track-1",
            "revealed_boundary_ms": boundary,
            "limit": 3,
            "data_epoch": state["data_epoch"],
            "history_epoch": None,
            "display_interval": "1m",
        }
        page = await replay.training.history_page(session, before_ms=boundary, **query)
        payload = {
            key: value
            for key, value in query.items()
            if key not in {"limit", "history_epoch"}
        }
        payload.update(name="EMA", params={"period": 100}, bars=page["bars"])
        with pytest.raises(TrainingRunError) as unversioned:
            await replay.training.canonical_indicator_compute(session, **payload)
        assert unversioned.value.code == "HISTORY_EPOCH_MISMATCH"
        page = await replay.training.history_page(session, before_ms=boundary, **query)
        payload.update(bars=page["bars"], history_epoch=page["history_epoch"])
        first, pending = await ready_indicator(
            lambda: replay.training.canonical_indicator_compute(session, **payload)
        )
        assert pending
        for job in preparation.repository.list():
            if job["request"]["intent"].get("purpose") == "replay_display_history":
                preparation.repository.release_finished(job["id"])
        preparation.repository.evict_unreferenced(
            preparation.adapter.remove_cached_object
        )
        for timestamp, row in values.items():
            if timestamp < REPLAY_START - 2 * MINUTE:
                row.update(
                    {key: row[key] + 10 for key in ["open", "high", "low", "close"]}
                )
        with pytest.raises(TrainingRunError) as stale:
            await replay.training.canonical_indicator_compute(session, **payload)
        assert stale.value.code == "HISTORY_EPOCH_MISMATCH"
        page = await replay.training.history_page(session, before_ms=boundary, **query)
        payload.update(bars=page["bars"], history_epoch=page["history_epoch"])
        second, pending = await ready_indicator(
            lambda: replay.training.canonical_indicator_compute(session, **payload)
        )
        assert pending
        assert second["seed"]["history_epoch"] != first["seed"]["history_epoch"]
        assert second["prefix_rows_read"] > 0
        assert lines(second["payload"]) != lines(first["payload"])
        assert len(origin_calls) == 2
