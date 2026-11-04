import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.replay import router
from app.data_engine.data_manager.core import DataManagerCore


@pytest.mark.anyio
async def test_core_without_replay_binding_cannot_bypass_it_through_legacy_state():
    """An inactive composition root must not revive a previous service alias."""
    class Service:
        def capabilities(self):
            return {"enabled": True, "available": True}

        training = SimpleNamespace()

    app = FastAPI()
    app.state.data_manager_core = DataManagerCore()
    app.state.replay_service = Service()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        result = await client.get("/api/v1/replay/capabilities")
    assert result.status_code == 200
    assert result.json()["enabled"] is False
    assert result.json()["available"] is False


@pytest.mark.anyio
async def test_training_stream_double_cancel_releases_subscription_before_child_cleanup(monkeypatch):
    from app.api.v1 import stream_replay_training as module

    started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    subscribers = set()
    queue = asyncio.Queue()

    class Training:
        async def subscribe_market_tracks(self, run_id, **kwargs):
            subscribers.add(run_id)
            return {"protocol": "replay.v3", "run_id": run_id}, queue

        def unsubscribe_market_tracks(self, run_id, owned):
            assert owned is queue
            subscribers.discard(run_id)

    class Socket:
        async def accept(self):
            pass

        async def send_json(self, value):
            pass

    async def blocked(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            raise

    monkeypatch.setattr(module, "_send_market_tracks", blocked)
    monkeypatch.setattr(module, "_receive_disconnect", blocked)
    stream = asyncio.create_task(module.stream_replay_training_run(Socket(), training=Training(), run_id="run-a"))
    try:
        await asyncio.wait_for(started.wait(), 1)
        stream.cancel()
        await asyncio.wait_for(cleaning.wait(), 1)
        stream.cancel()
        release.set()
        await asyncio.gather(stream, return_exceptions=True)
        assert not subscribers
    finally:
        release.set()
        if not stream.done():
            stream.cancel()
        await asyncio.gather(stream, return_exceptions=True)


@pytest.mark.anyio
async def test_bound_http_access_and_closed_gate_never_use_another_service_alias():
    class Training:
        async def list_runs(self, **kwargs):
            return {"owner": "bound"}

    class Service:
        training = Training()

        def capabilities(self):
            return {"enabled": True, "available": True, "owner": "bound"}

    class Stale:
        def capabilities(self):
            pytest.fail("stale service alias was accessed")

    core = DataManagerCore()
    service = Service()
    manager = core.bind_replay(service)
    assert core.bind_replay(service) is manager
    with pytest.raises(RuntimeError, match="already bound"):
        core.bind_replay(Stale())
    app = FastAPI()
    app.state.data_manager_core = core
    app.state.replay_service = Stale()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/v1/replay/capabilities")).json()["owner"] == "bound"
        assert (await client.get("/api/v1/replay/runs")).json() == {"owner": "bound"}
        core.close_replay()
        assert (await client.get("/api/v1/replay/capabilities")).json()["enabled"] is False
        assert (await client.get("/api/v1/replay/runs")).status_code == 503
    assert manager.diagnostics()["control_accesses"] >= 2


@pytest.mark.anyio
async def test_real_actor_streams_release_one_consumer_and_host_close_preserves_both_runs(tmp_path):
    from app.api.v1.stream_replay import stream_replay_session
    from app.replay.service import ReplayService
    from app.replay.storage import ReplaySQLiteStore
    from starlette.websockets import WebSocketDisconnect
    from tests.fixtures.replay.service_fakes import (
        NOW_MS, SessionIdFactory, replay_config, replay_repository, replay_settings,
    )

    path = tmp_path / "replay.db"
    service = ReplayService(settings=replay_settings(path), store=ReplaySQLiteStore(path),
                            repository=replay_repository(), now_ms=lambda: NOW_MS,
                            session_id_factory=SessionIdFactory("manager"))
    await service.start()
    core = DataManagerCore()
    manager = core.bind_replay(service)
    sockets, streams = [], []

    class Socket:
        def __init__(self):
            self.app = SimpleNamespace(state=SimpleNamespace(data_manager_core=core, replay_service=None))
            self.sent = asyncio.Event()
            self.disconnect = asyncio.Event()
            self.close_codes = []

        async def accept(self):
            pass

        async def send_json(self, value):
            self.sent.set()

        async def receive_json(self):
            await self.disconnect.wait()
            raise WebSocketDisconnect()

        async def close(self, code=1000, reason=""):
            self.close_codes.append(code)

    try:
        ids = [(await service.create_session(replay_config()))["session_id"] for _ in range(2)]
        before = [await service.get_session_state(sid) for sid in ids]
        for sid in ids:
            socket = Socket()
            sockets.append(socket)
            streams.append(asyncio.create_task(stream_replay_session(socket, session_id=sid,
                                                                     after_sequence=None, data_epoch=None)))
        await asyncio.wait_for(asyncio.gather(*(s.sent.wait() for s in sockets)), 2)
        assert manager.diagnostics()["streams"] == 2
        assert manager.diagnostics()["scopes"] == 2
        sockets[0].disconnect.set()
        await asyncio.wait_for(streams[0], 2)
        assert manager.diagnostics()["streams"] == 1
        assert service._sessions[ids[0]].actor.diagnostics()["subscribers"] == 0
        assert service._sessions[ids[1]].actor.diagnostics()["subscribers"] == 1
        await core.shutdown_replay(step_timeout=1)
        await asyncio.wait_for(streams[1], 2)
        assert manager.diagnostics()["streams"] == 0
        assert sockets[1].close_codes == [1001]
        assert [await service.get_session_state(sid) for sid in ids] == before
        assert all(service._sessions[sid].actor.diagnostics()["subscribers"] == 0 for sid in ids)
    finally:
        core.close_replay()
        for socket in sockets:
            socket.disconnect.set()
        await asyncio.gather(*streams, return_exceptions=True)
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
async def test_repeated_caller_cancel_does_not_interrupt_owned_stream_cleanup():
    from app.data_engine.data_manager.replay import ReplayDataManager

    started, cleaning, release, finished = (asyncio.Event() for _ in range(4))
    manager = ReplayDataManager(SimpleNamespace())

    async def consume():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            finished.set()

    stream = asyncio.create_task(manager.serve_stream("run", "run-a", consume))
    try:
        await asyncio.wait_for(started.wait(), 1)
        stream.cancel()
        await asyncio.wait_for(cleaning.wait(), 1)
        stream.cancel()
        await asyncio.sleep(0)
        assert manager.diagnostics()["streams"] == 1
        assert not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await stream
        assert finished.is_set()
        assert manager.diagnostics()["streams"] == 0
    finally:
        release.set()
        await asyncio.gather(stream, return_exceptions=True)


@pytest.mark.anyio
async def test_bounded_host_shutdown_keeps_ownership_until_a_slow_transport_finishes():
    from app.data_engine.data_manager.replay import ReplayDataManager

    started, cleaning, release = (asyncio.Event() for _ in range(3))
    manager = ReplayDataManager(SimpleNamespace())

    async def consume():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    stream = asyncio.create_task(manager.serve_stream("run", "run-a", consume))
    try:
        await asyncio.wait_for(started.wait(), 1)
        await manager.shutdown(step_timeout=0.01)
        assert cleaning.is_set()
        assert manager.diagnostics()["closed"] is True
        assert manager.diagnostics()["streams"] == 1
        with pytest.raises(Exception, match="closed"):
            manager.control_plane()
        release.set()
        await asyncio.wait_for(stream, 1)
        assert manager.diagnostics()["streams"] == 0
    finally:
        release.set()
        await asyncio.gather(stream, return_exceptions=True)


@pytest.mark.anyio
async def test_managed_run_streams_release_only_their_own_subscription():
    from app.api.v1.stream_replay_training import stream_replay_training_run

    class Training:
        def __init__(self):
            self.subscribers = {}

        async def subscribe_market_tracks(self, run_id, **kwargs):
            queue = asyncio.Queue()
            self.subscribers[run_id] = queue
            return {"protocol": "replay.v3", "run_id": run_id}, queue

        def unsubscribe_market_tracks(self, run_id, queue):
            assert self.subscribers[run_id] is queue
            del self.subscribers[run_id]

    training = Training()
    core = DataManagerCore()
    manager = core.bind_replay(SimpleNamespace(training=training))

    class Socket:
        def __init__(self):
            self.app = SimpleNamespace(state=SimpleNamespace(data_manager_core=core))
            self.sent, self.disconnect = asyncio.Event(), asyncio.Event()
            self.close_codes = []

        async def accept(self):
            pass

        async def send_json(self, value):
            self.sent.set()

        async def receive(self):
            await self.disconnect.wait()
            return {"type": "websocket.disconnect", "code": 1000}

        async def close(self, code=1000, reason=""):
            self.close_codes.append(code)

    sockets = [Socket(), Socket()]
    streams = [asyncio.create_task(stream_replay_training_run(socket, training=training, run_id=run))
               for socket, run in zip(sockets, ("run-a", "run-b"))]
    try:
        await asyncio.wait_for(asyncio.gather(*(s.sent.wait() for s in sockets)), 1)
        assert manager.diagnostics()["streams"] == 2
        assert set(training.subscribers) == {"run-a", "run-b"}
        sockets[0].disconnect.set()
        await asyncio.wait_for(streams[0], 1)
        assert set(training.subscribers) == {"run-b"}
        assert manager.diagnostics()["streams"] == 1
        await core.shutdown_replay(step_timeout=1)
        await asyncio.wait_for(streams[1], 1)
        assert not training.subscribers
        assert manager.diagnostics()["streams"] == 0
        assert sockets[1].close_codes == [1001]
    finally:
        core.close_replay()
        await asyncio.gather(*streams, return_exceptions=True)


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["unbound", "wrong-owner", "closed"])
async def test_run_stream_cannot_bypass_a_root_or_reuse_a_foreign_training_port(mode):
    from app.api.v1.stream_replay_training import stream_replay_training_run

    class Training:
        async def subscribe_market_tracks(self, *args, **kwargs):
            pytest.fail("an unavailable or foreign training port was used")

    expected, foreign = Training(), Training()
    core = DataManagerCore()
    if mode != "unbound":
        core.bind_replay(SimpleNamespace(training=expected))
    if mode == "closed":
        core.close_replay()

    class Socket:
        app = SimpleNamespace(state=SimpleNamespace(data_manager_core=core))
        messages, codes = [], []

        async def accept(self):
            pass

        async def send_json(self, value):
            self.messages.append(value)

        async def close(self, code=1000, reason=""):
            self.codes.append(code)

    socket = Socket()
    await stream_replay_training_run(socket, training=foreign if mode == "wrong-owner" else expected, run_id="run-a")
    assert socket.messages[0]["error"]["code"] == "REPLAY_TRAINING_UNAVAILABLE"
    assert socket.codes == [1013]
