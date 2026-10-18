"""Capacity pressure may reclaim only unclaimed startup recovery handles."""

import asyncio
from dataclasses import replace

import pytest

from app.replay.constants import CommandType, SessionState
from app.replay.errors import ReplayDomainError, ReplayErrorCode
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from tests.fixtures.replay.service_fakes import (
    NOW_MS, SessionIdFactory, replay_config, replay_repository, replay_settings,
)
from tests.test_replay_service import _command

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("use", ["unclaimed", "read", "controller", "subscriber", "in_flight", "race"])
async def test_deferred_archive_reclaims_only_unclaimed_startup_handle(tmp_path, use, monkeypatch):
    path = tmp_path / "capacity.db"
    def make(capacity):
        return ReplayService(
            settings=replace(replay_settings(path), max_active_sessions=capacity, idle_ttl_seconds=60),
            store=ReplaySQLiteStore(path, now_ms=lambda: NOW_MS),
            repository=replay_repository(), now_ms=lambda: NOW_MS,
            session_id_factory=SessionIdFactory("seed"), native_intervals=lambda _identity: ("1m",),
        )
    seed = make(2)
    await seed.start()
    try:
        created = [await seed.create_session(replay_config()) for _ in range(2)]
        snapshots = {item["session_id"]: item["snapshot"] for item in created}
    finally:
        await seed.shutdown(step_timeout=1.0)
    service = make(1)
    await service.start()
    lease = None
    pending = None
    actor = subscription = None
    try:
        resident = next(iter(service._sessions))
        deferred = next(sid for sid in snapshots if sid != resident)
        assert service.diagnostics()["startup_recoveries_deferred"] == 1
        if use == "read":
            await service.get_session(resident)
        elif use == "controller":
            snapshot = await service.get_session_state(resident)
            await service.command(resident, _command("claim", CommandType.ACQUIRE_CONTROLLER, revision=snapshot["revision"]))
        elif use == "subscriber":
            actor, subscription = await service.subscribe(resident, after_sequence=None, data_epoch=None)
        elif use == "in_flight":
            lease = service._lease_handle(resident)
            await lease.__aenter__()
        elif use == "race":
            ready, proceed = asyncio.Event(), asyncio.Event()
            original_snapshot = service._snapshot_for_prune
            async def delayed_snapshot(actor):
                snapshot = await original_snapshot(actor)
                ready.set()
                await proceed.wait()
                return snapshot
            monkeypatch.setattr(service, "_snapshot_for_prune", delayed_snapshot)
            pending = asyncio.create_task(service.get_session(deferred))
            await asyncio.wait_for(ready.wait(), timeout=2)
            await service.get_session(resident)
            proceed.set()
        if use == "unclaimed":
            restored = await service.get_session(deferred)
            assert resident not in service._sessions
            assert restored["snapshot"]["state"] == SessionState.PAUSED.value
            assert restored["snapshot"]["cursor"] == snapshots[deferred]["cursor"]
            # Reopening the evicted archive preserves its source and components.
            await service.release_session_to_hub(deferred)
            resident_restored = (await service.get_session(resident))["snapshot"]
            assert resident_restored["cursor"] == snapshots[resident]["cursor"]
            assert resident_restored["data_epoch"] == snapshots[resident]["data_epoch"]
        else:
            with pytest.raises(ReplayDomainError) as blocked:
                if pending is None:
                    await service.get_session(deferred)
                else:
                    await pending
            assert blocked.value.code is ReplayErrorCode.SCAN_LIMIT_EXCEEDED
            assert resident in service._sessions
        assert len(service._sessions) == 1
        assert service.diagnostics()["pending_session_reservations"] == 0
        assert (await service.store.get_session(resident))["degraded_reason"] is None
        assert (await service.store.get_session(deferred))["degraded_reason"] is None
    finally:
        if lease is not None:
            await lease.__aexit__(None, None, None)
        if actor is not None and subscription is not None:
            await actor.unsubscribe(subscription.token)
        await service.shutdown(step_timeout=1.0)
