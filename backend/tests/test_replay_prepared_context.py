import asyncio
from dataclasses import replace
import copy

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.data_preparation import router
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.models import PreparationError
from app.data_preparation.replay_context import ReplayHistoryContext, project_context
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.replay.catalog import ReplaySeriesIdentity
from app.replay.display_time import SourceBucketTimeMapper
from app.replay.history_archive import ReplayHistoryRepository
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.replay.training.errors import TrainingRunError
from tests.fixtures.replay.service_fakes import replay_settings
from tests.test_data_preparation import async_test, bars, START, terminal
from tests.test_replay_v2_run_centric import _setup_payload


@async_test
@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("disclosure", ["NONE", "HIDE_ALL"])
async def test_old_prepared_run_pages_older_context_without_changing_execution(tmp_path, progressive, disclosure):
    archive = tmp_path / "archive"
    replay = ReplayService(settings=replace(replay_settings(tmp_path / "replay.db"),
        replay_history_archive_dir=archive, controller_ttl_seconds=10),
        store=ReplaySQLiteStore(tmp_path / "replay.db"), repository=ReplayHistoryRepository(archive),
        native_intervals=lambda _: ("1m",))
    await replay.start()
    values, downloads = {}, []
    fail_download = False
    class Coordinator:
        async def request_and_wait(self, repair):
            if fail_download:
                raise PreparationError("PROVIDER_UNAVAILABLE", "fixture network outage")
            downloads.append((repair.start_ms, repair.end_ms))
            for timestamp in range(repair.start_ms, repair.end_ms + 1, 60_000):
                values[timestamp] = {**bars()[0], "open_time": timestamp, "close_time": timestamp + 59999}
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(), replay_service=replay,
        query=lambda *args, **kw: [values[t] for t in sorted(values) if kw["start_ms"] <= t <= kw["end_ms"]])
    preparation = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await preparation.start()
    try:
        setup = {**_setup_payload(), "requested_start_ms": START + 12 * 60_000,
                 "visible_history_lookback": {"mode": "ALL_AVAILABLE", "duration_ms": None},
                 "time_disclosure_policy": disclosure}
        app = FastAPI(); app.state.data_preparation_service = preparation; app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/replay", json={
                "idempotency_key": "create-old-run", "setup": setup,
                "exchange": "binance", "market_type": "spot", "symbol": "BTCUSDT", "progressive": progressive})
        assert response.status_code == 202, response.text
        job = await terminal(preparation, response.json()["id"])
        assert job["state"] == "READY", job
        session = job["result"]["run"]["adapter_session_id"]
        state = await replay.get_session_state(session)
        dataset = await replay.store.load_dataset(session)
        baseline = copy.deepcopy(state)
        before = state["cursor"]["virtual_time_ms"]
        args = dict(track_id="track-1", revealed_boundary_ms=before, limit=10,
                    data_epoch=state["data_epoch"], history_epoch=None, display_interval="1m")
        original = await replay.training.history_page(session, before_ms=before, **args)
        assert len(original["bars"]) == 2 and not original["has_more"]
        # Enable the new path only AFTER creating the run: existing saves work.
        replay.history_context = ReplayHistoryContext(preparation)
        if not progressive and disclosure == "NONE":
            fail_download = True
            with pytest.raises(TrainingRunError) as failed:
                await replay.training.history_page(session, before_ms=before, **args)
            assert failed.value.code == "HISTORY_DOWNLOAD_FAILED"
            fail_download = False
        if progressive and disclosure == "HIDE_ALL":
            replay.history_context = ReplayHistoryContext(preparation, wait_seconds=0)
            with pytest.raises(TrainingRunError) as pending:
                await replay.training.history_page(session, before_ms=before, **args)
            assert pending.value.code == "HISTORY_DOWNLOAD_PENDING"
            replay.history_context = ReplayHistoryContext(preparation)
        first, concurrent = await asyncio.gather(
            replay.training.history_page(session, before_ms=before, **args),
            replay.training.history_page(session, before_ms=before, **args))
        assert concurrent == first
        assert len(first["bars"]) == 10 and first["has_more"]
        assert first["bars"][-2:] == original["bars"]
        args["history_epoch"] = first["history_epoch"]
        second = await replay.training.history_page(session, before_ms=first["next_before_ms"], **args)
        assert len(second["bars"]) == 10 and second["has_more"]
        assert second["bars"][-1]["close_time_ms"] + 1 == first["bars"][0]["open_time_ms"]
        assert second["history_epoch"] == first["history_epoch"]
        count = len(downloads)
        # Recreate the loader to demonstrate durable preparation-cache reuse.
        replay.history_context = ReplayHistoryContext(preparation)
        repeated = await replay.training.history_page(session, before_ms=before, **args)
        assert repeated == first and len(downloads) == count
        # Higher intervals must load across the short warmup seam, on source grids.
        coarse = await replay.training.history_page(session, before_ms=before, **{**args,
            "history_epoch": None, "display_interval": "5m", "limit": 3})
        assert coarse["bars"] and len(coarse["bars"]) <= 3
        assert all(bar["is_closed"] and bar["component_count"] == 5 for bar in coarse["bars"])
        assert all(bar["close_time_ms"] <= before for bar in coarse["bars"])
        # Multi-chart coarse cells can have no initial projected bar at all.
        # Their server-owned public cursor must still connect to older context.
        for interval, components in [("4h", 240), ("1d", 1440)]:
            projection = await replay.training.display_projection(session, track_id="track-1",
                revealed_boundary_ms=before, limit=10, data_epoch=state["data_epoch"],
                display_interval=interval)
            assert len(projection["bars"]) == 1
            tail = projection["bars"][0]
            assert not tail["is_closed"] and tail["last_base_open_ms"] < before
            assert tail["component_count"] < tail["expected_components"]
            assert tail["close"] == str(bars()[0]["close"])
            cursor = projection["history_before_ms"]
            assert cursor <= before
            bootstrap = await replay.training.history_page(session, before_ms=cursor,
                **{**args, "history_epoch": None, "display_interval": interval, "limit": 2})
            assert len(bootstrap["bars"]) == 2
            assert bootstrap["bars"][-1]["close_time_ms"] + 1 == cursor
            assert all(bar["is_closed"] and bar["component_count"] == components
                       and bar["close_time_ms"] <= before for bar in bootstrap["bars"])
        assert await replay.store.load_dataset(session) == dataset
        after = await replay.get_session_state(session)
        assert after["cursor"] == baseline["cursor"]
        assert after["data_epoch"] == baseline["data_epoch"]
        with pytest.raises(TrainingRunError) as bad:
            await replay.training.history_page(session, before_ms=before, **{**args, "history_epoch": "sha256:" + "0"*64})
        assert bad.value.code == "HISTORY_EPOCH_MISMATCH"
        with pytest.raises(TrainingRunError) as future:
            await replay.training.history_page(session, before_ms=before, **{**args, "revealed_boundary_ms": before + 60_000})
        assert future.value.code == "HISTORY_BOUNDARY_AHEAD"
    finally:
        await preparation.shutdown(); await replay.shutdown()


def test_context_rejects_gaps_and_wrong_market():
    from app.replay.errors import ReplayDomainError
    mapper = SourceBucketTimeMapper.create(interval="1m", actual_replay_start_ms=START + 120000,
                                           public_replay_start_ms=START + 120000)
    identity = ReplaySeriesIdentity("binance", "spot", "BTCUSDT")
    with pytest.raises(PreparationError, match="missing bars"):
        project_context(bars()[:1], START, START + 120000, mapper, identity)
    with pytest.raises(ReplayDomainError):
        project_context([{**row, "symbol": "ETHUSDT"} for row in bars()], START, START+120000, mapper, identity)


@async_test
@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("old_track", [False, True])
async def test_added_market_inherits_prepared_base_history_without_native_archives(
    tmp_path, monkeypatch, progressive, old_track,
):
    from app.data_preparation.models import PreparationRequest, Requirement
    from app.replay.training.models import ReplayV2CommandType
    from app.replay.official_trade_history import TradeHistoryRouter
    from tests.test_replay_v2_training_phase5 import _acquire
    from tests.test_replay_v2_training_phase6 import _send

    archive = tmp_path / "archive"
    replay = ReplayService(settings=replace(replay_settings(tmp_path / "replay.db"),
        replay_history_archive_dir=archive, controller_ttl_seconds=30),
        store=ReplaySQLiteStore(tmp_path / "replay.db"), repository=TradeHistoryRouter(
            ReplayHistoryRepository(archive), type("UnusedOfficial", (), {"owns": staticmethod(lambda _: False)})()),
        native_intervals=lambda _: ("1m", "5m", "4h", "1d"))
    await replay.start()
    values = {}
    class Coordinator:
        async def request_and_wait(self, repair):
            price = 31 if repair.symbol == "SOLUSDT" else 101
            for timestamp in range(repair.start_ms, repair.end_ms + 1, 60_000):
                values[(repair.symbol, timestamp)] = {**bars()[0], "open_time": timestamp,
                    "close_time": timestamp + 59999, "open": price, "high": price + 1,
                    "low": price - 1, "close": price}
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(), replay_service=replay,
        query=lambda symbol, *args, **kw: [values[(symbol, t)] for s, t in sorted(values)
            if s == symbol and kw["start_ms"] <= t <= kw["end_ms"]])
    preparation = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await preparation.start()
    try:
        start = START + 12 * 60_000
        setup = {**_setup_payload(), "requested_start_ms": start,
            "visible_history_lookback": {"mode": "ALL_AVAILABLE", "duration_ms": None},
            "time_disclosure_policy": "NONE"}
        app = FastAPI(); app.state.data_preparation_service = preparation; app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/replay", json={
                "idempotency_key": "prepared-primary", "setup": setup,
                "exchange": "binance", "market_type": "spot", "symbol": "BTCUSDT", "progressive": progressive})
        job = await terminal(preparation, response.json()["id"])
        assert job["state"] == "READY", job
        run = job["result"]["run"]; session = run["adapter_session_id"]; run_id = run["run_id"]
        prepared = await preparation.submit(PreparationRequest(idempotency_key="added-sol", consumer="REPLAY",
            requirements=[Requirement(exchange="binance", market_type="spot", symbol="SOLUSDT",
                start_ms=start - 2 * 60000, end_ms=start + 5 * 60000)]))
        assert (await terminal(preparation, prepared["id"]))["state"] == "READY"
        if old_track:
            # Reproduce pre-fix admission, retaining its SOURCE_LATEST_CLOSED
            # execution snapshot. Recovery must not rewrite that immutable data.
            original_select = replay.select_training_window
            async def legacy_select(config, **kwargs):
                kwargs.pop("_prepared_bar_window", None)
                return await original_select(config, **kwargs)
            monkeypatch.setattr(replay, "select_training_window", legacy_select)
        await _acquire(replay, run_id=run_id, selected_session_id=session, command_id="acquire-add")
        await _send(replay, run_id=run_id, session_id=session, command_id="add-sol",
            command_type=ReplayV2CommandType.ADD_TRACK, payload={"exchange": "binance", "market_type": "spot",
                "symbol": "SOLUSDT", "settlement_asset": "USDT", "subscription_tier": "FULL"})
        tracks = (await replay.training.get_market_tracks(run_id))["tracks"]
        added = next(track for track in tracks if track["symbol"] == "SOLUSDT")
        sol_session = added["adapter_session_id"]
        dataset = await replay.store.load_dataset(sol_session)
        state = await replay.get_session_state(sol_session)
        replay.history_context = ReplayHistoryContext(preparation)
        boundary = state["cursor"]["virtual_time_ms"]
        for interval in ["5m", "4h", "1d"]:
            projection = await replay.training.display_projection(sol_session, track_id=added["track_id"],
                revealed_boundary_ms=boundary, limit=10, data_epoch=state["data_epoch"], display_interval=interval)
            assert projection["bars"] and projection["bars"][-1]["close"] == "31"
            assert all(bar["last_base_open_ms"] < boundary for bar in projection["bars"])
            page = await replay.training.history_page(sol_session, track_id=added["track_id"],
                before_ms=projection["history_before_ms"], revealed_boundary_ms=boundary,
                limit=2, data_epoch=state["data_epoch"], history_epoch=None, display_interval=interval)
            assert len(page["bars"]) == 2
            assert all(bar["close"] == "31" and bar["is_closed"] and bar["close_time_ms"] < boundary
                and bar["component_count"] == bar["expected_components"] for bar in page["bars"])
        assert await replay.store.load_dataset(sol_session) == dataset
        assert (await replay.get_session_state(sol_session))["cursor"] == state["cursor"]
    finally:
        await preparation.shutdown(); await replay.shutdown()


@async_test
@pytest.mark.parametrize("progressive", [False, True])
@pytest.mark.parametrize("disclosure", ["NONE", "HIDE_ALL"])
async def test_history_completes_warmup_bucket_after_crossing_coarse_boundary(tmp_path, progressive, disclosure):
    from app.replay.constants import CommandType
    from tests.test_replay_service import _command
    archive = tmp_path / "archive"
    replay = ReplayService(settings=replace(replay_settings(tmp_path / "replay.db"),
        replay_history_archive_dir=archive, controller_ttl_seconds=10),
        store=ReplaySQLiteStore(tmp_path / "replay.db"), repository=ReplayHistoryRepository(archive),
        native_intervals=lambda _: ("1m",))
    await replay.start()
    values = {}
    class Coordinator:
        async def request_and_wait(self, repair):
            for timestamp in range(repair.start_ms, repair.end_ms + 1, 60_000):
                values[timestamp] = {**bars()[0], "open_time": timestamp, "close_time": timestamp + 59999}
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(), replay_service=replay,
        query=lambda *args, **kw: [values[t] for t in sorted(values) if kw["start_ms"] <= t <= kw["end_ms"]])
    preparation = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await preparation.start()
    try:
        setup = {**_setup_payload(), "requested_start_ms": START + 237 * 60_000,
            "indicator_warmup_bars": 30, "forward_cache_ms": 15 * 60_000,
            "visible_history_lookback": {"mode": "ALL_AVAILABLE", "duration_ms": None},
            "time_disclosure_policy": disclosure}
        app = FastAPI(); app.state.data_preparation_service = preparation; app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/replay", json={
                "idempotency_key": "cross-coarse-boundary", "setup": setup,
                "exchange": "binance", "market_type": "spot", "symbol": "BTCUSDT", "progressive": progressive})
        assert response.status_code == 202, response.text
        job = await terminal(preparation, response.json()["id"])
        assert job["state"] == "READY", job
        session = job["result"]["run"]["adapter_session_id"]
        state = await replay.get_session_state(session)
        acquired = await replay.command(session, _command("owner", CommandType.ACQUIRE_CONTROLLER, revision=state["revision"]))
        await replay.command(session, _command("cross", CommandType.STEP, revision=acquired["revision"], payload={"count": 12}))
        baseline = await replay.get_session_state(session)
        dataset = await replay.store.load_dataset(session)
        replay.history_context = ReplayHistoryContext(preparation)
        boundary = baseline["cursor"]["virtual_time_ms"]
        projection = await replay.training.display_projection(session, track_id="track-1",
            revealed_boundary_ms=boundary, limit=10, data_epoch=baseline["data_epoch"], display_interval="4h")
        cursor = projection["history_before_ms"]
        args = dict(track_id="track-1", before_ms=cursor, revealed_boundary_ms=boundary,
            limit=3, data_epoch=baseline["data_epoch"], history_epoch=None, display_interval="4h")
        page = await replay.training.history_page(session, **args)
        assert page["bars"][-1]["close_time_ms"] + 1 == cursor
        assert all(bar["is_closed"] and bar["component_count"] == 240 for bar in page["bars"])
        assert all(bar["close_time_ms"] <= boundary for bar in page["bars"])
        assert await replay.training.history_page(session, **{**args, "history_epoch": page["history_epoch"]}) == page
        after = await replay.get_session_state(session)
        assert after["cursor"] == baseline["cursor"] and after["data_epoch"] == baseline["data_epoch"]
        assert await replay.store.load_dataset(session) == dataset
    finally:
        await preparation.shutdown(); await replay.shutdown()
