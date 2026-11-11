"""Durable per-account authorization for automatic history repair."""
from __future__ import annotations

import asyncio
import logging
from hashlib import sha256
import time

from app.core.bounded_executor import ExecutorBusyError
from app.core.executors import run_storage
from .continuous_repair_plan import preview
from .errors import BacktestError
from .continuous_store import _counter, _text, _wire, fail

WAKE = "automatic-history-repair"
KEY_PREFIX = "auto-repair/"
logger = logging.getLogger(__name__)


def create_schema(db):
    db.execute("""CREATE TABLE continuous_auto_repair (
        run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
        enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
        version INTEGER NOT NULL,
        attempted_revision INTEGER)""")


class AutoRepairPolicy:
    def __init__(self, store):
        self.store = store

    def get(self, run_id):
        _text(run_id, 128)
        with self.store.lock:
            self.store.summary(run_id)
            row = self.store.db.execute(
                "SELECT enabled,version FROM continuous_auto_repair WHERE run_id=?", (run_id,),
            ).fetchone()
            return {"run_id": run_id, "enabled": bool(row["enabled"]) if row else False,
                    "version": row["version"] if row else 0}

    def set(self, run_id, *, enabled, expected_version):
        _counter(expected_version)
        if type(enabled) is not bool:
            raise fail("CONTINUOUS_INPUT_INVALID", "Automatic repair authorization must be explicit")
        cancelled = []
        with self.store._transaction():
            current = self.get(run_id)
            if current["version"] != expected_version:
                raise fail("CONTINUOUS_COMMIT_CONFLICT", "Automatic repair setting changed")
            if current["enabled"] == enabled:
                return current
            if enabled and self.store.summary(run_id)["phase"] not in {"PAUSED", "LIVE", "CATCHING_UP"}:
                raise fail("CONTINUOUS_NOT_READY", "Authorize automatic repair before a history revision")
            version = expected_version + 1
            _counter(version)
            self.store.db.execute(
                "INSERT INTO continuous_auto_repair VALUES(?,?,?,NULL) "
                "ON CONFLICT(run_id) DO UPDATE SET enabled=excluded.enabled,version=excluded.version",
                (run_id, enabled, version),
            )
            if not enabled:
                for row in self.store.db.execute(
                    "SELECT id,request_key FROM continuous_epochs WHERE run_id=? "
                    "AND phase IN ('REQUESTED','PREPARING','READY') AND request_key LIKE ?",
                    (run_id, KEY_PREFIX + "%"),
                ).fetchall():
                    self.store.epochs._write_failure(row["id"], code="CONTINUOUS_AUTO_REPAIR_REVOKED",
                        message="Automatic history repair authorization was withdrawn", cancelled=True)
                    cancelled.append(row["request_key"])
        for key in cancelled:
            self.store.updates.notify("repair:" + key)
        if cancelled:
            self.store.updates.notify(run_id)
        self.store.updates.notify(WAKE)
        return {"run_id": run_id, "enabled": enabled, "version": version}

    def candidates(self):
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT p.run_id,p.version FROM continuous_auto_repair p JOIN runs r ON r.id=p.run_id "
                "WHERE p.enabled=1 AND r.phase='REPAIR_REQUIRED' "
                "AND p.attempted_revision IS NOT r.revision "
                "AND NOT EXISTS(SELECT 1 FROM continuous_epochs e WHERE e.run_id=r.id "
                "AND json_extract(e.base_identity_json,'$.revision')=r.revision) "
                "ORDER BY r.updated_at_ms,r.id",
            ).fetchall()
            return [(self.store.summary(row["run_id"]), row["version"]) for row in rows]

    def guard(self, run_id, version):
        current = self.get(run_id)
        if not current["enabled"] or current["version"] != version:
            raise fail("CONTINUOUS_AUTO_REPAIR_REVOKED", "Automatic history repair authorization was withdrawn")

    def claim(self, run_id, revision, version):
        self.guard(run_id, version)
        cursor = self.store.db.execute(
            "UPDATE continuous_auto_repair SET attempted_revision=? WHERE run_id=? AND attempted_revision IS NOT ?",
            (revision, run_id, revision),
        )
        if cursor.rowcount != 1:
            raise fail("CONTINUOUS_COMMIT_CONFLICT", "This revision already had an automatic repair attempt")

    def suppress(self, run_id):
        with self.store._transaction():
            row = self.store.summary(run_id)
            if row["phase"] == "REPAIR_REQUIRED":
                self.store.db.execute("UPDATE continuous_auto_repair SET attempted_revision=? WHERE run_id=?",
                                      (row["revision"], run_id))

    def failed(self, run_id, expected, version, failure):
        with self.store._transaction():
            row = self.store.summary(run_id)
            current = self.get(run_id)
            if (row["phase"] != "REPAIR_REQUIRED" or self.store.results.identity(row) != expected
                    or not current["enabled"] or current["version"] != version):
                return
            error = {"code": str(getattr(failure, "code", "CONTINUOUS_REPAIR_FAILED"))[:64],
                     "message": str(failure)[:256]}
            revision = row["revision"] + 1
            claimed = self.store.db.execute(
                "UPDATE continuous_auto_repair SET attempted_revision=? WHERE run_id=? AND attempted_revision IS NOT ?",
                (revision, run_id, row["revision"]),
            )
            if claimed.rowcount != 1:
                return
            self.store.db.execute("UPDATE runs SET revision=?,error_json=?,updated_at_ms=? WHERE id=?",
                                  (revision, _wire(error, 4096), int(time.time()*1000), run_id))
        self.store.updates.notify(run_id)


class AutomaticRepairs:
    """One bounded scheduler sharing the manual repair worker and its admission."""
    def __init__(self, repairs):
        self.repairs = repairs
        self.owner = repairs.owner
        self.event = asyncio.Event()
        self.release = None
        self.task = None

    def start(self):
        if self.owner.closed or (self.task is not None and not self.task.done()):
            return
        loop = asyncio.get_running_loop()
        self.release = self.owner.store.updates.listen_commits(
            WAKE, lambda: loop.call_soon_threadsafe(self.event.set),
        )
        self.event.set()
        self.task = asyncio.create_task(self.serve())

    def stop(self):
        if self.release is not None:
            self.release()
            self.release = None
        self.event.set()

    async def serve(self):
        try:
            while not self.owner.closed:
                await self.event.wait()
                self.event.clear()
                if self.owner.closed:
                    break
                try:
                    retry = await self.admit()
                except ExecutorBusyError:
                    retry = True
                if retry and not self.owner.closed:
                    # Existing manual repair, account preparation or controls
                    # can briefly hold the single slot.
                    await asyncio.sleep(.25)
                    self.event.set()
        except Exception:
            logger.exception("Automatic continuous history repair scheduler stopped")
        finally:
            self.stop()

    async def admit(self):
        store = self.owner.store
        for row, version in await run_storage(store.auto_repair.candidates):
            if self.owner.closed:
                return False
            run_id = row["id"]
            try:
                self.repairs._capacity(run_id)
            except BacktestError as failure:
                if failure.code != "BUDGET_EXCEEDED":
                    raise
                return True
            expected = store.results.identity(row)
            key = KEY_PREFIX + sha256(f"{run_id}:{row['revision']}".encode()).hexdigest()
            job = None
            try:
                plan = await run_storage(preview, store, self.owner.manager, run_id, expected=expected,
                                         resume_after=True, now_ms=self.owner.clock_ms())
                if self.owner.closed:
                    return False
                try:
                    job = self.repairs._start(key, run_id, {**plan, "auto_policy_version": version})
                except BacktestError as failure:
                    if failure.code == "BUDGET_EXCEEDED":
                        return True
                    raise
                await asyncio.shield(job.reserved)
            except ExecutorBusyError:
                raise
            except Exception as failure:
                if self.owner.closed:
                    return False
                if job is None or job.record is None:
                    await run_storage(store.auto_repair.failed, run_id, expected, version, failure)
            else:
                # The worker wakes us when its serial slot is physically drained.
                return False
        return False
