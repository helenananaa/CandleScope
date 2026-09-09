import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import threading

import pytest

from app.replay.storage import ReplaySQLiteStore
from app.replay.timing import collect_timings, current_timing, timed_to_thread


def test_replay_io_and_projection_do_not_queue_behind_default_executor(tmp_path):
    async def scenario():
        loop = asyncio.get_running_loop()
        pool = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(pool)
        started = asyncio.Event()
        release = threading.Event()
        def block_default():
            loop.call_soon_threadsafe(started.set)
            release.wait(10)
        blocker = loop.run_in_executor(None, block_default)
        await started.wait()
        store = ReplaySQLiteStore(tmp_path / "isolated.db")
        marker = ContextVar("test_marker", default="missing")
        marker.set("owned")
        timings = {}
        try:
            with collect_timings(timings):
                result = await asyncio.wait_for(store.run_extension_read(lambda connection: connection.execute("SELECT 7").fetchone()[0]), 2)
                assert result == 7
                assert await asyncio.wait_for(store.run_worker("projection", marker.get), 2) == "owned"
                await asyncio.wait_for(store.run_extension_write(lambda connection: connection.execute("CREATE TABLE probe (id INTEGER)")), 2)
            assert not blocker.done()
            assert timings["sql_read_queue"] >= 0
            assert timings["sql_commit"] >= 0
            assert timings["projection_work"] >= 0
            assert current_timing.get() is None
        finally:
            release.set()
            await blocker
            await store.close()
        with pytest.raises(RuntimeError, match="closed"):
            await store.run_extension_read(lambda connection: 1)
    asyncio.run(scenario())


def test_timing_context_restores_on_failure_and_preserves_nested_scopes():
    async def scenario():
        outer, inner = {}, {}
        with collect_timings(outer):
            original = current_timing.get()
            with pytest.raises(ValueError):
                with collect_timings(inner):
                    await timed_to_thread("failure", lambda: (_ for _ in ()).throw(ValueError("expected")))
            assert current_timing.get() is original
            assert "failure_work" not in original.values
        assert "failure_work" in inner
        assert current_timing.get() is None
    asyncio.run(scenario())


def test_replay_foreground_activity_is_released_after_command_failure():
    from app.replay.training.service import TrainingRunService
    async def scenario():
        service = object.__new__(TrainingRunService)
        service._foreground_controls = 0
        service._last_foreground_control = None
        async def failed(*args, **kwargs):
            assert service.has_foreground_work()
            assert service.foreground_idle_seconds() == 0
            raise ValueError("expected")
        service._command_with_timings = failed
        assert service.foreground_idle_seconds() == float("inf")
        with pytest.raises(ValueError, match="expected"):
            await service.command("test", None)
        assert not service.has_foreground_work()
        assert 0 <= service.foreground_idle_seconds() < 1
    asyncio.run(scenario())
