"""Debounce WAL merging without weakening commit durability or adding a writer."""

import asyncio
import sqlite3
import time


class IdleCheckpoint:
    def __init__(self, store, *, delay=0.75):
        self.store = store
        self.delay = delay
        self.enabled = False
        self.timer = None
        self.task = None
        self.pending = 0
        self.observed_size = 0
        self.checkpoint_size = 0
        self.wal_path = store.path.with_name(store.path.name + "-wal")

    async def enable(self):
        async with self.store._async_lock:

            def configure():
                with self.store._thread_lock:
                    if (
                        self.store._connection.execute("PRAGMA journal_mode")
                        .fetchone()[0]
                        .lower()
                        != "wal"
                    ):
                        return False
                    # FULL remains in force: every transaction still syncs its WAL.
                    try:
                        self.store._connection.execute("PRAGMA wal_autocheckpoint=0")
                        return True
                    except sqlite3.Error:
                        return False

            self.enabled = await self.store.run_worker("wal_configure", configure)
        return self.enabled

    def cancel_timer(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None

    def observe_size(self):
        # Called in the writer worker, never on the event loop.
        try:
            self.observed_size = self.wal_path.stat().st_size
        except OSError:
            self.observed_size = 0

    def committed(self):
        if not self.enabled:
            return
        self.pending += 1
        self.cancel_timer()
        if self.task is not None:
            return
        # Continuous workloads cannot postpone maintenance indefinitely.
        # Long-lived external readers may still pin WAL pages, as in SQLite's
        # automatic checkpoint mode; expose the remaining page count.
        due = (
            self.observed_size - self.checkpoint_size >= 8 * 1024 * 1024
            or self.pending >= 64
        )
        self.timer = asyncio.get_running_loop().call_later(
            0 if due else self.delay, self.start
        )

    def start(self):
        self.timer = None
        if self.enabled and self.task is None:
            self.task = asyncio.create_task(self.run())

    async def run(self):
        try:
            async with self.store._async_lock:
                if not self.enabled or self.store.closed:
                    return
                await self.store.run_worker("wal_checkpoint", self.checkpoint)
                self.pending = 0
                self.checkpoint_size = self.observed_size
        finally:
            self.task = None

    def checkpoint(self):
        # Use the same connection and mutex as commits. No concurrent
        # checkpoint/write connections or uninterruptible FULL checkpoints.
        with self.store._thread_lock:
            if not self.enabled or self.store.closed:
                return
            started = time.perf_counter()
            try:
                _, logged, completed = self.store._connection.execute(
                    "PRAGMA wal_checkpoint(PASSIVE)"
                ).fetchone()
                metrics = self.store._metrics
                metrics["idle_wal_checkpoints"] = (
                    metrics.get("idle_wal_checkpoints", 0) + 1
                )
                metrics["idle_wal_pending_pages"] = max(0, logged - completed)
                metrics["idle_wal_checkpoint_ms"] = (
                    time.perf_counter() - started
                ) * 1000
            except sqlite3.Error as error:
                self.enabled = False
                self.store._metrics["idle_wal_checkpoint_failures"] = (
                    self.store._metrics.get("idle_wal_checkpoint_failures", 0) + 1
                )
                # Retain the old maintenance policy if optional deferral fails.
                from .sqlite_store import _WAL_AUTOCHECKPOINT_PAGES

                try:
                    self.store._connection.execute(
                        f"PRAGMA wal_autocheckpoint={_WAL_AUTOCHECKPOINT_PAGES}"
                    )
                except sqlite3.Error:
                    self.store._degraded_reason = (
                        f"WAL checkpoint maintenance failed: {type(error).__name__}"
                    )

    async def close(self):
        self.enabled = False
        self.cancel_timer()
        task = self.task
        if task is not None:
            await asyncio.shield(task)
