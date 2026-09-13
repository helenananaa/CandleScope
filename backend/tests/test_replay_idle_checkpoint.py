import asyncio
import sqlite3

import pytest

from app.replay.storage import ReplaySQLiteStore


@pytest.mark.anyio
async def test_commits_schedule_idle_checkpoint_and_close_drains_it(tmp_path):
    store = ReplaySQLiteStore(tmp_path / "run.db")
    await store.enable_idle_checkpoints()
    controller = store._idle_checkpoint
    controller.delay = 0
    finished = asyncio.Event()
    original = controller.run

    async def observed():
        try:
            await original()
        finally:
            finished.set()

    controller.run = observed
    try:
        await store.run_extension_write(
            lambda c: c.execute("CREATE TABLE scheduled(value)")
        )
        await asyncio.wait_for(finished.wait(), timeout=5)
        assert store._metrics["idle_wal_checkpoints"] >= 1
        assert controller.pending == 0
        assert controller.task is None
        assert controller.timer is None
    finally:
        await store.close()
    assert not controller.enabled


@pytest.mark.anyio
async def test_idle_checkpoint_preserves_full_sync_and_handles_pinned_reader(tmp_path):
    store = ReplaySQLiteStore(tmp_path / "run.db")
    reader = sqlite3.connect(store.path)
    try:
        await store.enable_idle_checkpoints()
        controller = store._idle_checkpoint
        assert controller is not None
        controller.delay = 60
        await store.run_extension_write(
            lambda c: c.execute("CREATE TABLE example(value BLOB)")
        )
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM example").fetchone()
        await store.run_extension_write(
            lambda c: c.executemany(
                "INSERT INTO example VALUES (?)", [(b"x" * 8192,)] * 16
            )
        )

        def policy():
            with store._thread_lock:
                return [
                    store._connection.execute("PRAGMA " + name).fetchone()[0]
                    for name in ("synchronous", "wal_autocheckpoint")
                ]

        assert await store.run_worker("policy", policy) == [2, 0]
        await controller.run()
        assert store._metrics["idle_wal_pending_pages"] > 0
        reader.rollback()
        await controller.run()
        assert store._metrics["idle_wal_pending_pages"] == 0
        assert (
            await store.run_extension_read(
                lambda c: c.execute("SELECT COUNT(*) FROM example").fetchone()[0]
            )
            == 16
        )
        assert await store.run_worker("policy", policy) == [2, 0]
    finally:
        reader.close()
        await store.close()
    assert controller.timer is None and controller.task is None
    with sqlite3.connect(store.path) as reopened:
        assert reopened.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert reopened.execute("SELECT COUNT(*) FROM example").fetchone()[0] == 16


@pytest.mark.anyio
async def test_checkpoint_failure_restores_automatic_policy(tmp_path):
    store = ReplaySQLiteStore(tmp_path / "run.db")
    try:
        await store.enable_idle_checkpoints()
        controller = store._idle_checkpoint
        real = store._connection

        class BrokenCheckpoint:
            def execute(self, sql, *args):
                if sql == "PRAGMA wal_checkpoint(PASSIVE)":
                    raise sqlite3.OperationalError("injected checkpoint failure")
                return real.execute(sql, *args)

            def __getattr__(self, key):
                return getattr(real, key)

        store._connection = BrokenCheckpoint()
        await controller.run()
        assert not controller.enabled
        assert real.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert real.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 256
        await store.run_extension_write(
            lambda c: c.execute("CREATE TABLE still_writable(value)")
        )
    finally:
        await store.close()
