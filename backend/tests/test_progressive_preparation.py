import asyncio
from decimal import Decimal
from dataclasses import replace

import pytest
import httpx
from fastapi import FastAPI

from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.api.v1.data_preparation import router
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.models import PreparationError
from app.data_preparation.service import PreparationService
from app.replay.history_archive import ReplayHistoryRepository
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from tests.fixtures.replay.service_fakes import replay_settings
from tests.test_data_preparation import async_test, bars, START, terminal
from tests.test_replay_v2_run_centric import _setup_payload


@async_test
@pytest.mark.parametrize("recovery", ["none", "restart", "retry", "cancel", "all_history"])
@pytest.mark.parametrize("playback", ["manual", "auto", "paused"])
async def test_progressive_job_launches_before_tail_and_recovers_download(tmp_path, monkeypatch, recovery, playback):
    monkeypatch.setattr("app.data_preparation.progressive.PREFIX_MS", 120_000)
    archive = tmp_path / "archive"
    replay = ReplayService(
        # This is a storage/restart journey, not the one-second lease-expiry
        # fixture. Use the production default while filesystem work drains.
        settings=replace(replay_settings(tmp_path / "replay.db"), replay_history_archive_dir=archive,
                         controller_ttl_seconds=10),
        store=ReplaySQLiteStore(tmp_path / "replay.db"), repository=ReplayHistoryRepository(archive),
        native_intervals=lambda _: ("1m",),
    )
    await replay.start()
    start, initial_end, end = START + 120_000, START + 240_000, START + 480_000
    tail_entered, release_tail = asyncio.Event(), asyncio.Event()
    inventory, calls = {}, []

    class Coordinator:
        async def request_and_wait(self, repair):
            calls.append((repair.start_ms, repair.end_ms))
            if repair.start_ms >= initial_end:
                tail_entered.set()
                await release_tail.wait()
                if recovery == "retry" and sum(a >= initial_end for a, _ in calls) == 1:
                    raise PreparationError("PROVIDER_UNAVAILABLE", "fixture tail failure")
            for timestamp in range(repair.start_ms, repair.end_ms + 1, 60_000):
                price = 100 + (timestamp - START) // 60_000
                inventory[timestamp] = {**bars()[0], "open_time": timestamp, "close_time": timestamp + 59_999,
                    "open": price, "high": price + 2, "low": price - 1, "close": price + 1}

    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(), replay_service=replay,
        query=lambda *a, **kw: [inventory[t] for t in sorted(inventory) if kw["start_ms"] <= t <= kw["end_ms"]])
    repository = PreparationRepository(tmp_path / "jobs.db")
    service = PreparationService(repository, adapter)
    await service.start()
    try:
        setup = {**_setup_payload(), "requested_start_ms": start, "forward_cache_ms": end - start}
        if recovery == "all_history":
            setup["visible_history_lookback"] = {"mode": "ALL_AVAILABLE", "duration_ms": None}
        app = FastAPI()
        app.state.data_preparation_service = service
        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/replay", json={
                "idempotency_key": "progressive-launch", "setup": setup,
                "exchange": "binance", "market_type": "spot", "symbol": "BTCUSDT",
                "progressive": True,
            })
            assert response.status_code == 202, response.text
            job = response.json()
            assert job["request"]["progressive"] is True
        await asyncio.wait_for(tail_entered.wait(), 10)
        early = repository.get(job["id"])
        assert early["state"] == "RUNNING", early
        assert early["completed"] == 1 and early["total"] == 2
        run_id = early["result"]["run"]["run_id"]
        session_id = early["result"]["run"]["adapter_session_id"]
        assert session_id
        state = await replay.get_session_state(session_id, include_config=True)
        assert state["config"]["horizon_ms"] == end - start
        feed_id = early["result"]["progressive"]["feed_id"]
        feed = replay.progressive_history.status(feed_id)
        assert feed["ready_end_ms"] == initial_end and not feed["complete"]
        from app.replay.training.models import ReplayV2CommandType
        from tests.test_replay_v2_training_phase3 import _v2_command

        async def control(command_id, kind, payload):
            snapshot = await replay.get_session(session_id)
            return await replay.training.command(run_id, _v2_command(
                run_id=run_id, command_id=command_id, command_type=kind, snapshot=snapshot, payload=payload))

        await control("owner", ReplayV2CommandType.ACQUIRE_CONTROLLER, {"takeover": False})
        order = {"client_order_id": "holding", "side": "BUY",
            "order_type": "MARKET", "quantity": "1", "reduce_only": False,
            "limit_price": None, "stop_price": None}
        await control("holding", ReplayV2CommandType.PLACE_ORDER, order)
        prefix_state = await control("first", ReplayV2CommandType.ADVANCE, {"basis": "BASE_BAR", "count": 2})
        assert prefix_state["cursor"]["source_sequence"] == 2
        from app.replay.errors import ReplayDomainError
        from app.replay.training.errors import TrainingRunError
        with pytest.raises((ReplayDomainError, TrainingRunError)) as pending:
            await control("pending", ReplayV2CommandType.ADVANCE, {"basis": "BASE_BAR", "count": 1})
        assert pending.value.code == "DATASET_PENDING"
        waiting = await replay.get_session_state(session_id)
        assert waiting["cursor"]["source_sequence"] == 2
        assert not waiting["cursor"]["at_end"]
        if playback != "manual":
            await control("play", ReplayV2CommandType.PLAY, {"basis": "BASE_BAR", "rate": 100})
            async def waiting_for_data():
                while replay.training._run_actors[run_id].playback_snapshot()["reason"] != "DATASET_PENDING":
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(waiting_for_data(), 3)
            assert (await replay.get_session_state(session_id))["cursor"]["source_sequence"] == 2
            if playback == "paused":
                await control("pause", ReplayV2CommandType.PAUSE, {})
        if recovery == "cancel":
            await service.cancel(job["id"])
            cancelled = await terminal(service, job["id"])
            assert cancelled["state"] == "CANCELLED"
            assert cancelled["result"]["run"]["run_id"] == run_id
            assert replay.progressive_history.status(feed_id)["ready_end_ms"] == initial_end
            return
        if recovery == "restart":
            await service.shutdown()
            service = PreparationService(repository, adapter)
            await service.start()
        release_tail.set()
        finished = await terminal(service, job["id"])
        if recovery == "retry":
            assert finished["state"] == "FAILED"
            assert finished["result"]["run"]["run_id"] == run_id
            await service.retry(job["id"])
            finished = await terminal(service, job["id"])
        assert finished["state"] == "READY", finished
        assert finished["completed"] == finished["total"] == 2
        assert finished["result"]["run"]["run_id"] == run_id
        feed = replay.progressive_history.status(feed_id)
        assert feed["complete"] and feed["revision"] == 2
        await asyncio.shield(service._inventory_task)
        assert repository.cache_inventory()["publication_bytes"] > 0
        with repository.connect() as db:
            kinds = {row[0] for row in db.execute("SELECT DISTINCT kind FROM preparation_publications")}
        assert {"replay_bar", "replay_index", "replay_catalog", "replay_session_inputs"} <= kinds
        app.state.data_preparation_service = service
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            released = await client.post(f"/data-preparations/{job['id']}/release-cache")
            assert released.status_code == 200, released.text
        with replay.progressive_history.connect() as db:
            owners = {row["owner"] for row in db.execute(
                "SELECT owner FROM progressive_bar_refs WHERE feed_id=?", (feed_id,))}
        assert owners == {replay._progressive_session_owner(session_id)}
        assert sum(a == START for a, _ in calls) == 1
        if playback == "auto":
            async def finished_playback():
                while (await replay.get_session_state(session_id))["cursor"]["source_sequence"] < 6:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(finished_playback(), 3)
        else:
            if playback == "paused":
                await asyncio.sleep(0.3)
                assert (await replay.get_session_state(session_id))["cursor"]["source_sequence"] == 2
            complete_state = await control("rest", ReplayV2CommandType.ADVANCE, {"basis": "BASE_BAR", "count": 4})
            assert complete_state["cursor"]["source_sequence"] == 6
        snapshot = (await replay.get_session(session_id))["snapshot"]
        assert Decimal(snapshot["components"]["position"]["quantity"]) == 1
        boundary = snapshot["cursor"]["virtual_time_ms"]
        history_page = await replay.training.history_page(session_id, track_id="track-1",
            before_ms=boundary + 1, revealed_boundary_ms=boundary, limit=20,
            data_epoch=snapshot["data_epoch"], history_epoch=None)
        assert len(history_page["bars"]) == 8
        assert history_page["bars"][-1]["close_time_ms"] == boundary
        coarse = await replay.training.history_page(session_id, track_id="track-1",
            before_ms=boundary + 1, revealed_boundary_ms=boundary, limit=20,
            data_epoch=snapshot["data_epoch"], history_epoch=None, display_interval="2m")
        assert len(coarse["bars"]) == 4
        projection = await replay.training.display_projection(session_id, track_id="track-1",
            revealed_boundary_ms=boundary, limit=20, data_epoch=snapshot["data_epoch"], display_interval="2m")
        assert projection["bars"][-1]["close_time_ms"] == boundary
        assert len(projection["bars"]) >= 3
        assert coarse["bars"][-1]["close_time_ms"] == boundary
        old_boundary = prefix_state["cursor"]["virtual_time_ms"]
        old_page = await replay.training.history_page(session_id, track_id="track-1",
            before_ms=boundary + 1, revealed_boundary_ms=old_boundary, limit=20,
            data_epoch=snapshot["data_epoch"], history_epoch=history_page["history_epoch"])
        assert len(old_page["bars"]) == 4
        assert max(bar["close_time_ms"] for bar in old_page["bars"]) <= old_boundary
        runs = await replay.training.list_runs(limit=50, cursor=None, state=None, source_kind=None, compatibility=None)
        assert len(runs["items"]) == 1
        if recovery == "none" and playback == "manual":
            from app.data_preparation.models import PreparationRequest
            reference_request = PreparationRequest.model_validate(job["request"]).model_copy(
                update={"idempotency_key": "complete-reference", "progressive": False})
            reference_job = await terminal(service, (await service.submit(reference_request))["id"])
            assert reference_job["state"] == "READY", reference_job
            reference_run = reference_job["result"]["run"]["run_id"]
            reference_session = reference_job["result"]["run"]["adapter_session_id"]
            async def reference_control(command_id, kind, payload):
                snap = await replay.get_session(reference_session)
                return await replay.training.command(reference_run, _v2_command(run_id=reference_run,
                    command_id=command_id, command_type=kind, snapshot=snap, payload=payload))
            await reference_control("owner", ReplayV2CommandType.ACQUIRE_CONTROLLER, {"takeover": False})
            await reference_control("holding", ReplayV2CommandType.PLACE_ORDER, order)
            await reference_control("first", ReplayV2CommandType.ADVANCE, {"basis": "BASE_BAR", "count": 2})
            await reference_control("rest", ReplayV2CommandType.ADVANCE, {"basis": "BASE_BAR", "count": 4})
            reference_components = (await replay.get_session(reference_session))["snapshot"]["components"]
            assert snapshot["components"]["account"] == reference_components["account"]
            assert snapshot["components"]["position"] == reference_components["position"]
    finally:
        release_tail.set()
        await service.shutdown()
        await replay.shutdown()
