import asyncio

import pytest
from app.replay.training.errors import TrainingRunError
from app.replay.training.indicator_http import compute_for_observer

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("disconnect", [False, True])
async def test_http_observer_cancellation_drains_disposable_calculation(disconnect):
    started, stopping, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Observer:
        async def is_disconnected(self):
            return disconnect and started.is_set()

    async def calculate():
        started.set()
        try:
            if disconnect:
                await asyncio.Event().wait()
            return {"status": "ready"}
        finally:
            stopping.set()
            await finish.wait()

    task = asyncio.create_task(compute_for_observer(Observer(), calculate()))
    await asyncio.wait_for(stopping.wait(), 2)
    assert not task.done()
    finish.set()
    if disconnect:
        with pytest.raises(TrainingRunError) as failure:
            await task
        assert failure.value.code == "INDICATOR_OBSERVER_DISCONNECTED"
        assert failure.value.status_code == 499
    else:
        assert await task == {"status": "ready"}


async def test_real_http_disconnect_drains_prefix_worker_without_account_write(tmp_path, monkeypatch):
    import json
    from copy import deepcopy
    from threading import Event

    from app.replay.training.indicator_history import PinnedIndicatorHistory

    from tests.test_replay_v2_training_api import _app
    from tests.test_replay_v2_training_history import _create_run, _service

    service, _ = await _service(tmp_path / "http-cancel.db")
    started, release = Event(), Event()
    original = PinnedIndicatorHistory.read

    def paused(self, *args):
        started.set()
        assert release.wait(5)
        return original(self, *args)

    task = None
    try:
        _, snapshot = await _create_run(service, history_mode="ALL_AVAILABLE", requested_start_index=12)
        boundary = snapshot["cursor"]["virtual_time_ms"]
        page = await service.training.history_page("adapter-1", track_id="track-1", before_ms=boundary + 1,
            revealed_boundary_ms=boundary, limit=1, data_epoch=snapshot["data_epoch"], history_epoch=None)
        before = deepcopy((await service.get_session("adapter-1"))["snapshot"])
        monkeypatch.setattr(PinnedIndicatorHistory, "read", paused)
        payload = {"track_id": "track-1", "display_interval": "1m", "revealed_boundary_ms": boundary,
            "data_epoch": snapshot["data_epoch"], "name": "RSI", "params": {}, "bars": page["bars"]}
        body = json.dumps(payload).encode()
        incoming = asyncio.Queue()
        await incoming.put({"type": "http.request", "body": body, "more_body": False})
        sent = []

        async def send(message):
            sent.append(message)

        path = "/api/v1/replay/runs/session/adapter-1/indicator-compute"
        task = asyncio.create_task(_app(service)({"type": "http", "asgi": {"version": "3.0"},
            "http_version": "1.1", "method": "POST", "scheme": "http", "path": path,
            "raw_path": path.encode(), "query_string": b"", "root_path": "",
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            "client": ("127.0.0.1", 1234), "server": ("test", 80)}, incoming.get, send))
        assert await asyncio.to_thread(started.wait, 3)
        await incoming.put({"type": "http.disconnect"})
        # The real Starlette Request sees a disconnected observer while the real
        # repository worker is still paused. Cancellation cannot release its lane.
        await asyncio.sleep(0.2)
        assert not task.done()
        assert service.training._display_service._indicator_preparation_jobs._waiting
        assert await asyncio.wait_for(service.store.run_extension_write(
            lambda conn: conn.execute("SELECT 42").fetchone()[0]), 1) == 42
        release.set()
        await asyncio.wait_for(task, 3)
        assert not service.training._display_service._indicator_preparation_jobs._waiting
        assert not any(message.get("status") == 200 for message in sent)
        assert [message["status"] for message in sent if message["type"] == "http.response.start"] == [499]
        assert (await service.get_session("adapter-1"))["snapshot"] == before
    finally:
        release.set()
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await service.shutdown(step_timeout=1.0)


async def test_external_cancellation_still_propagates_after_owned_cleanup():
    started, stopping, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Observer:
        async def is_disconnected(self):
            return False

    async def calculate():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopping.set()
            await finish.wait()

    task = asyncio.create_task(compute_for_observer(Observer(), calculate()))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.wait_for(stopping.wait(), 2)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
