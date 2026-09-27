"""SQLite task journal and shared immutable input references.

Only one application owner executes jobs. SQLite transactions protect concurrent
API/worker calls; task execution never holds a database transaction across I/O.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
import uuid

from .models import PreparationError, PreparationRequest, Requirement, canonical, fingerprint

TERMINAL = frozenset({"READY", "FAILED", "CANCELLED"})


class PreparationRepository:
    def __init__(self, path: Path, *, cache_budget_bytes=None):
        self.path = Path(path)
        self._default_cache_budget_bytes = cache_budget_bytes or 2 * 1024**3
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS preparation_settings (
                    name TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preparation_jobs (
                    id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL, request TEXT NOT NULL,
                    state TEXT NOT NULL, stage TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, next_attempt_ms INTEGER NOT NULL DEFAULT 0,
                    reserved_bytes INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    result TEXT, error TEXT,
                    created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preparation_chunks (
                    key TEXT PRIMARY KEY, requirement TEXT NOT NULL,
                    receipt TEXT NOT NULL, bytes INTEGER NOT NULL,
                    accessed_ms INTEGER NOT NULL,
                    series_key TEXT, start_ms INTEGER, end_ms INTEGER
                );
                CREATE TABLE IF NOT EXISTS preparation_refs (
                    owner TEXT NOT NULL, chunk_key TEXT NOT NULL,
                    PRIMARY KEY(owner, chunk_key),
                    FOREIGN KEY(chunk_key) REFERENCES preparation_chunks(key)
                );
                CREATE TABLE IF NOT EXISTS preparation_pending_deletes (
                    receipt TEXT PRIMARY KEY, bytes INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preparation_cache_writes (
                    receipt TEXT PRIMARY KEY, bytes INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preparation_publication_writes (
                    id TEXT PRIMARY KEY, bytes INTEGER NOT NULL, state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preparation_publications (
                    path TEXT PRIMARY KEY, kind TEXT NOT NULL, bytes INTEGER NOT NULL,
                    checked_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preparation_publication_scopes (
                    path TEXT PRIMARY KEY, kind TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preparation_receipt_files (
                    receipt TEXT NOT NULL, path TEXT NOT NULL,
                    PRIMARY KEY(receipt, path),
                    FOREIGN KEY(path) REFERENCES preparation_publications(path)
                );
            """)
            # Coverage receipts can share a physical object. Pending deletion
            # may also overlap a freshly re-adopted receipt after a restart.
            db.execute("BEGIN IMMEDIATE")
            db.execute("DROP VIEW IF EXISTS preparation_storage")
            db.execute("""CREATE VIEW preparation_storage AS
                SELECT MAX(bytes) AS bytes FROM (
                    SELECT receipt,bytes FROM preparation_chunks UNION ALL
                    SELECT receipt,bytes FROM preparation_pending_deletes UNION ALL
                    SELECT receipt,bytes FROM preparation_cache_writes
                ) c WHERE NOT EXISTS (
                    SELECT 1 FROM preparation_receipt_files f WHERE f.receipt=c.receipt
                ) GROUP BY receipt UNION ALL SELECT bytes FROM preparation_publications
                UNION ALL SELECT bytes FROM preparation_publication_writes""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(preparation_jobs)")}
            if "waiting" not in columns:
                db.execute("ALTER TABLE preparation_jobs ADD COLUMN waiting TEXT")
            for column in ("attempts", "next_attempt_ms", "reserved_bytes"):
                if column not in columns:
                    db.execute(f"ALTER TABLE preparation_jobs ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
            chunk_columns = {row[1] for row in db.execute("PRAGMA table_info(preparation_chunks)")}
            for name, kind in (("series_key", "TEXT"), ("start_ms", "INTEGER"), ("end_ms", "INTEGER")):
                if name not in chunk_columns:
                    db.execute(f"ALTER TABLE preparation_chunks ADD COLUMN {name} {kind}")
            for row in db.execute("SELECT key,requirement FROM preparation_chunks WHERE series_key IS NULL").fetchall():
                requirement = json.loads(row["requirement"])
                db.execute("UPDATE preparation_chunks SET series_key=?,start_ms=?,end_ms=? WHERE key=?",
                    (self.series_key(requirement), requirement.get("start_ms"), requirement.get("end_ms"), row["key"]))
            db.execute("CREATE INDEX IF NOT EXISTS preparation_coverage ON preparation_chunks(series_key,start_ms,end_ms)")
            db.execute("INSERT OR IGNORE INTO preparation_settings VALUES ('cache_budget_bytes',?)", (str(self._default_cache_budget_bytes),))
            db.execute("INSERT OR IGNORE INTO preparation_settings VALUES ('prefetch_enabled','false')")

    @property
    def cache_budget_bytes(self):
        return self.settings()["cache_budget_bytes"]

    def settings(self):
        with self.connect() as db:
            return {row["name"]: json.loads(row["value"]) for row in db.execute("SELECT name,value FROM preparation_settings")}

    def configure(self, *, cache_budget_bytes, prefetch_enabled):
        if not isinstance(cache_budget_bytes, int) or not 16 * 1024**2 <= cache_budget_bytes <= 1024**4:
            raise PreparationError("INVALID_BUDGET", "Cache budget must be between 16 MiB and 1 TiB")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
            reserved = db.execute("SELECT COALESCE(SUM(reserved_bytes),0) FROM preparation_jobs WHERE state IN ('QUEUED','RUNNING')").fetchone()[0]
            if cache_budget_bytes < used + reserved:
                raise PreparationError("STORAGE_BUDGET", "Release unused cached inputs before reducing the cache budget")
            db.execute("UPDATE preparation_settings SET value=? WHERE name='cache_budget_bytes'", (str(cache_budget_bytes),))
            db.execute("UPDATE preparation_settings SET value=? WHERE name='prefetch_enabled'", (canonical(bool(prefetch_enabled)),))
        return self.settings()

    @staticmethod
    def series_key(requirement):
        return fingerprint({k: v for k, v in requirement.items() if k not in {"start_ms", "end_ms"}})

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def now():
        return int(time.time() * 1000)

    @staticmethod
    def wire(row):
        if row is None:
            raise PreparationError("JOB_NOT_FOUND", "Preparation job was not found")
        result = dict(row)
        for key in ("request", "result", "error", "waiting"):
            result[key] = json.loads(result[key]) if result[key] else None
        result["cancel_requested"] = bool(result["cancel_requested"])
        return result

    def create(self, request: PreparationRequest, total: int):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM preparation_jobs WHERE idempotency_key=?",
                             (request.idempotency_key,)).fetchone()
            if old:
                if old["fingerprint"] != request.identity():
                    raise PreparationError("IDEMPOTENCY_CONFLICT", "Key belongs to a different preparation")
                return self.wire(old)
            count = db.execute("SELECT COUNT(*) FROM preparation_jobs WHERE state NOT IN ('READY','FAILED','CANCELLED')").fetchone()[0]
            if count >= 64:
                raise PreparationError("QUEUE_FULL", "Too many active data preparation jobs")
            # Reserve conservatively before launching any network operation.
            # Existing cache coverage costs no additional acquisition allowance.
            reserved = 0
            requirements = [] if request.consumer == "STRATEGY" and request.intent.get("ready_resolution") else request.requirements
            for requirement in requirements:
                covered = db.execute("""SELECT 1 FROM preparation_chunks WHERE series_key=?
                    AND start_ms<=? AND end_ms>=? LIMIT 1""", (self.series_key(requirement.model_dump()),
                    requirement.start_ms, requirement.end_ms)).fetchone()
                if covered is None:
                    reserved += ((requirement.end_ms - requirement.start_ms) // 60_000 * 1024
                                 if requirement.role == "BARS" else request.max_bytes)
            used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
            active_reserved = db.execute("SELECT COALESCE(SUM(reserved_bytes),0) FROM preparation_jobs WHERE state IN ('QUEUED','RUNNING')").fetchone()[0]
            if used + active_reserved + reserved > self.cache_budget_bytes:
                raise PreparationError("STORAGE_BUDGET", "Preparation cache budget is reserved; wait for active jobs or release unused cached inputs")
            job_id = uuid.uuid4().hex
            now = self.now()
            db.execute("""INSERT INTO preparation_jobs
                (id,idempotency_key,fingerprint,request,state,stage,total,reserved_bytes,created_ms,updated_ms)
                VALUES (?,?,?,?,'QUEUED','QUEUED',?,?,?,?)""",
                (job_id, request.idempotency_key, request.identity(), canonical(request.model_dump()), total, reserved, now, now))
            return self.wire(db.execute("SELECT * FROM preparation_jobs WHERE id=?", (job_id,)).fetchone())

    def get(self, job_id):
        with self.connect() as db:
            return self.wire(db.execute("SELECT * FROM preparation_jobs WHERE id=?", (job_id,)).fetchone())

    def by_idempotency(self, key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM preparation_jobs WHERE idempotency_key=?", (key,)).fetchone()
            return self.wire(row) if row is not None else None

    def list(self, *, active=False):
        with self.connect() as db:
            where = "WHERE state NOT IN ('READY','FAILED','CANCELLED')" if active else ""
            return [self.wire(row) for row in db.execute(
                f"SELECT * FROM preparation_jobs {where} ORDER BY created_ms DESC LIMIT 200")]

    def update(self, job_id, *, state=None, stage=None, completed=None, result=None, error=None, inventory_dirty=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.wire(db.execute("SELECT * FROM preparation_jobs WHERE id=?", (job_id,)).fetchone())
            if job["state"] in TERMINAL:
                return job
            if inventory_dirty:
                # Observers must not see the new terminal state alongside an
                # old READY inventory. Publish both changes in one transaction.
                row = db.execute("SELECT value FROM preparation_settings WHERE name='storage_inventory_generation'").fetchone()
                generation = int(json.loads(row[0])) + 1 if row else 1
                db.execute("INSERT OR REPLACE INTO preparation_settings VALUES ('storage_inventory_generation',?)", (canonical(generation),))
                db.execute("INSERT OR REPLACE INTO preparation_settings VALUES ('storage_inventory_state',?)", (canonical("SCANNING"),))
            # Cancellation wins over late publication/consumer replies.
            if job["cancel_requested"] and state == "READY":
                state, stage = "CANCELLED", "CANCELLED"
            db.execute("""UPDATE preparation_jobs SET state=?,stage=?,completed=?,result=?,error=?,
                waiting=NULL,revision=revision+1,updated_ms=? WHERE id=?""",
                (state or job["state"], stage or job["stage"],
                 completed if completed is not None else job["completed"],
                 canonical(result) if result is not None else (canonical(job["result"]) if job["result"] is not None else None),
                 canonical(error) if error is not None else None, self.now(), job_id))
        return self.get(job_id)

    def set_waiting(self, job_id, waiting):
        value = canonical(waiting) if waiting is not None else None
        with self.connect() as db:
            db.execute("""UPDATE preparation_jobs SET waiting=?,revision=revision+1,updated_ms=?
                WHERE id=? AND waiting IS NOT ? AND (state='RUNNING' OR ? IS NULL)""",
                (value, self.now(), job_id, value, value))

    def cancel(self, job_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.wire(db.execute("SELECT * FROM preparation_jobs WHERE id=?", (job_id,)).fetchone())
            if row["stage"] == "STARTING":
                raise PreparationError("START_IN_PROGRESS", "Prepared data is being attached to a run; wait for the run result")
            if row["state"] not in TERMINAL:
                db.execute("UPDATE preparation_jobs SET cancel_requested=1,revision=revision+1,updated_ms=? WHERE id=?",
                           (self.now(), job_id))
        return self.get(job_id)

    def begin_start(self, job_id, result):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.wire(db.execute("SELECT * FROM preparation_jobs WHERE id=?", (job_id,)).fetchone())
            if row["cancel_requested"]:
                raise PreparationError("CANCELLED", "Data preparation was cancelled")
            db.execute("UPDATE preparation_jobs SET stage='STARTING',result=?,revision=revision+1,updated_ms=? WHERE id=?",
                       (canonical(result), self.now(), job_id))

    def retry(self, job_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.wire(db.execute("SELECT * FROM preparation_jobs WHERE id=?", (job_id,)).fetchone())
            if row["state"] not in {"FAILED", "BLOCKED_STORAGE"}:
                raise PreparationError("RETRY_NOT_ALLOWED", "Only failed or storage-blocked jobs may retry")
            occupied = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
            occupied += db.execute("SELECT COALESCE(SUM(reserved_bytes),0) FROM preparation_jobs WHERE state IN ('QUEUED','RUNNING') AND id<>?", (job_id,)).fetchone()[0]
            if occupied + row["reserved_bytes"] > self.cache_budget_bytes:
                raise PreparationError("STORAGE_BUDGET", "Insufficient preparation cache budget to resume")
            db.execute("UPDATE preparation_jobs SET state='QUEUED',stage='QUEUED',error=NULL,cancel_requested=0,attempts=0,next_attempt_ms=0,revision=revision+1,updated_ms=? WHERE id=?",
                       (self.now(), job_id))
        return self.get(job_id)

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE preparation_jobs SET state='QUEUED',stage='RECOVERING',waiting=NULL,revision=revision+1 WHERE state='RUNNING'")
            db.execute("DELETE FROM preparation_refs WHERE owner LIKE 'acquire:%'")
            db.execute("UPDATE preparation_publication_writes SET state='ABANDONED'")

    def defer(self, job_id, error):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.wire(db.execute("SELECT * FROM preparation_jobs WHERE id=?", (job_id,)).fetchone())
            attempts = job["attempts"] + 1
            db.execute("UPDATE preparation_jobs SET state='QUEUED',stage='WAITING_RETRY',attempts=?,next_attempt_ms=?,error=?,revision=revision+1,updated_ms=? WHERE id=?",
                       (attempts, self.now() + min(60_000, 2000 * 2**attempts), canonical(error), self.now(), job_id))

    def cache_inventory(self):
        with self.connect() as db:
            inventory = {"chunks": db.execute("SELECT COUNT(*) FROM preparation_chunks").fetchone()[0]}
            inventory["reserved_bytes"] = db.execute("SELECT COALESCE(SUM(reserved_bytes),0) FROM preparation_jobs WHERE state IN ('QUEUED','RUNNING')").fetchone()[0]
            inventory["pending_delete_bytes"] = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_pending_deletes").fetchone()[0]
            inventory["pending_write_bytes"] = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_cache_writes").fetchone()[0]
            inventory["publication_reserved_bytes"] = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_publication_writes").fetchone()[0]
            inventory["bytes"] = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
            inventory["publication_bytes"] = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_publications").fetchone()[0]
            inventory["shared_host_bytes"] = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_publications WHERE kind='shared_host_history'").fetchone()[0]
            inventory["referenced_bytes"] = db.execute("""SELECT COALESCE(SUM(bytes),0) FROM (
                SELECT receipt,MAX(bytes) AS bytes FROM preparation_chunks c WHERE EXISTS (
                    SELECT 1 FROM preparation_refs r WHERE r.chunk_key=c.key
                ) AND NOT EXISTS (SELECT 1 FROM preparation_receipt_files f WHERE f.receipt=c.receipt)
                GROUP BY receipt UNION ALL
                SELECT p.path,p.bytes FROM preparation_publications p WHERE EXISTS (
                    SELECT 1 FROM preparation_receipt_files f JOIN preparation_chunks c ON c.receipt=f.receipt
                    JOIN preparation_refs r ON r.chunk_key=c.key WHERE f.path=p.path
                ))""").fetchone()[0]
            inventory["engine_owned_bytes"] = db.execute("""SELECT COALESCE(SUM(bytes),0) FROM (
                SELECT receipt,MAX(bytes) AS bytes FROM preparation_chunks c
                WHERE json_extract(receipt,'$.kind')='verified_trades'
                AND NOT EXISTS (SELECT 1 FROM preparation_receipt_files f WHERE f.receipt=c.receipt)
                GROUP BY receipt UNION ALL SELECT path,bytes FROM preparation_publications
                WHERE kind='trade_archive')""").fetchone()[0]
            return {**inventory, **self.settings()}

    def retained_cache_receipts(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("""SELECT receipt FROM preparation_chunks
                UNION SELECT receipt FROM preparation_pending_deletes""")]

    def reserve_cache_write(self, receipt, size, *, reuse_existing=False):
        """Reserve the exact compressed size before opening a temporary file."""
        if size < 0:
            raise ValueError("Cache write size cannot be negative")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # A reclaimed legacy object may be written again. Its old zero-byte
            # file mapping must not hide this new reservation from the ledger.
            if not reuse_existing:
                db.execute("DELETE FROM preparation_receipt_files WHERE receipt=? AND path IN (SELECT path FROM preparation_publications WHERE kind='acquisition_legacy')", (canonical(receipt),))
            db.execute("""INSERT INTO preparation_cache_writes VALUES (?,?)
                ON CONFLICT(receipt) DO UPDATE SET bytes=MAX(bytes,excluded.bytes)""", (canonical(receipt), size))
            used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
            budget = int(db.execute("SELECT value FROM preparation_settings WHERE name='cache_budget_bytes'").fetchone()[0])
            if used > budget:
                raise PreparationError("STORAGE_BUDGET", "Insufficient storage budget for the next prepared cache object")

    def release_cache_write(self, receipt):
        with self.connect() as db:
            db.execute("DELETE FROM preparation_cache_writes WHERE receipt=?", (canonical(receipt),))

    def pending_cache_writes(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT receipt FROM preparation_cache_writes")]

    def reserve_publication(self, size):
        if size < 0:
            raise ValueError("Publication reservation cannot be negative")
        token = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
            budget = int(db.execute("SELECT value FROM preparation_settings WHERE name='cache_budget_bytes'").fetchone()[0])
            if used + size > budget:
                raise PreparationError("STORAGE_BUDGET", "Insufficient storage budget for publication working space")
            db.execute("INSERT INTO preparation_publication_writes VALUES (?,?,'ACTIVE')", (token, size))
        return token

    def publication_available_bytes(self):
        with self.connect() as db:
            used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
            budget = int(db.execute("SELECT value FROM preparation_settings WHERE name='cache_budget_bytes'").fetchone()[0])
            return max(0, budget - used)

    def resize_publication(self, token, size):
        if size < 0:
            raise ValueError("Publication reservation cannot be negative")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE preparation_publication_writes SET bytes=? WHERE id=? AND state='ACTIVE'",
                (size, token)).rowcount
            if changed != 1:
                raise PreparationError("PUBLICATION_LEASE_LOST", "Publication reservation is no longer active")
            used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
            budget = int(db.execute("SELECT value FROM preparation_settings WHERE name='cache_budget_bytes'").fetchone()[0])
            if used > budget:
                raise PreparationError("STORAGE_BUDGET", "Insufficient storage budget for imported archive expansion")

    def abandon_publication(self, token):
        with self.connect() as db:
            db.execute("UPDATE preparation_publication_writes SET state='ABANDONED' WHERE id=?", (token,))

    def abandoned_publications(self):
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT id FROM preparation_publication_writes WHERE state='ABANDONED'")]

    def reconcile_abandoned_publications(self, tokens):
        # Call only after a successful inventory of all registered scopes.
        with self.connect() as db:
            db.executemany("DELETE FROM preparation_publication_writes WHERE id=? AND state='ABANDONED'",
                [(token,) for token in tokens])

    def register_publications(self, objects, *, reservation=None):
        rows = []
        for path, kind in objects:
            try:
                if Path(path).is_file():
                    rows.append((str(Path(path).resolve()), kind, Path(path).stat().st_size, self.now()))
            except FileNotFoundError:
                pass  # an atomic publication/cleanup moved the temporary file
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany("""INSERT INTO preparation_publications VALUES (?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET bytes=excluded.bytes,checked_ms=excluded.checked_ms""", rows)
            if reservation is not None:
                db.execute("DELETE FROM preparation_publication_writes WHERE id=?", (reservation,))

    def register_publication_scopes(self, scopes):
        with self.connect() as db:
            db.executemany("INSERT OR IGNORE INTO preparation_publication_scopes VALUES (?,?)",
                [(str(Path(path).resolve()), kind) for path, kind in scopes])

    def reconcile_trade_receipts(self, *, stop):
        """Replace legacy aggregate charges only when every object is inventoried.

        Different time windows can reference the same Parquet files. The file
        ledger survives receipt GC because archive deletion belongs to the engine.
        """
        roots = [path for path, kind in self.publication_scopes() if kind == "trade_archive"]
        for receipt in self.retained_cache_receipts():
            if stop.is_set():
                raise PreparationError("STORAGE_INVENTORY_INTERRUPTED", "Storage inventory was interrupted", retryable=True)
            self.map_trade_receipt(receipt, roots=roots)

    def map_trade_receipt(self, receipt, *, roots=None):
        if receipt.get("kind") != "verified_trades":
            return
        if roots is None:
            roots = [path for path, kind in self.publication_scopes() if kind == "trade_archive"]
        from app.data_engine.storage.raw_trade_archive import RawAggTradeDatasetRef
        reference = RawAggTradeDatasetRef.from_dict(receipt["dataset"])
        for root in roots:
            paths = [(root / item.object_id).resolve() for item in reference.objects]
            if not paths or any(not path.is_relative_to(root) for path in paths):
                continue
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if not all(db.execute("SELECT 1 FROM preparation_publications WHERE path=? AND bytes>0",
                    (str(path),)).fetchone() for path in paths):
                    continue
                db.executemany("INSERT OR IGNORE INTO preparation_receipt_files VALUES (?,?)",
                    [(canonical(receipt), str(path)) for path in paths])
            break

    def publication_scopes(self):
        with self.connect() as db:
            return [(Path(row[0]), row[1]) for row in db.execute("SELECT path,kind FROM preparation_publication_scopes")]

    def map_legacy_cache_receipt(self, receipt, path):
        """An adopted file becomes a cache receipt without charging it twice."""
        path = Path(path).resolve()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM preparation_publications WHERE path=? AND kind='acquisition_legacy'", (str(path),)).fetchone():
                return
            size = path.stat().st_size
            db.execute("UPDATE preparation_publications SET bytes=?,checked_ms=? WHERE path=?", (size, self.now(), str(path)))
            db.execute("INSERT OR IGNORE INTO preparation_receipt_files VALUES (?,?)", (canonical(receipt), str(path)))

    def set_inventory_state(self, state):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO preparation_settings VALUES ('storage_inventory_state',?)", (canonical(state),))

    def begin_inventory(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR REPLACE INTO preparation_settings VALUES ('storage_inventory_state',?)", (canonical("SCANNING"),))
            row = db.execute("SELECT value FROM preparation_settings WHERE name='storage_inventory_generation'").fetchone()
            return int(json.loads(row[0])) if row else 0

    def finish_inventory(self, generation, state):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM preparation_settings WHERE name='storage_inventory_generation'").fetchone()
            current = int(json.loads(row[0])) if row else 0
            # A scan started before a newer publication cannot certify it.
            state = state if current == generation else "SCANNING"
            db.execute("INSERT OR REPLACE INTO preparation_settings VALUES ('storage_inventory_state',?)", (canonical(state),))

    def refresh_publications(self, *, stop=None, paths=None):
        if paths is None:
            with self.connect() as db:
                paths = [row[0] for row in db.execute("SELECT path FROM preparation_publications")]
        else:
            paths = [str(Path(path).resolve()) for path in paths]
        rows = []
        for path in paths:
            if stop is not None and stop.is_set():
                raise PreparationError("STORAGE_INVENTORY_INTERRUPTED", "Storage inventory was interrupted", retryable=True)
            try:
                size = Path(path).stat().st_size
            except FileNotFoundError:
                size = 0
            rows.append((size, self.now(), path))
        with self.connect() as db:
            db.executemany("UPDATE preparation_publications SET bytes=?,checked_ms=? WHERE path=?", rows)

    def check_physical_budget(self):
        with self.connect() as db:
            used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
        if used > self.cache_budget_bytes:
            raise PreparationError("STORAGE_BUDGET", "Published history exceeds the storage budget; increase it or remove unused archives")

    def release_finished(self, job_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.wire(db.execute("SELECT * FROM preparation_jobs WHERE id=?", (job_id,)).fetchone())
            if job["state"] not in TERMINAL:
                raise PreparationError("JOB_ACTIVE", "Active preparation inputs cannot be released")
            db.execute("DELETE FROM preparation_refs WHERE owner=?", (job_id,))

    def evict_unreferenced(self, remove, *, max_chunks=32):
        removed = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Acquisition writes bytes before publishing its receipt. Until
            # object publication has its own lease, GC waits for an idle queue.
            if db.execute("SELECT 1 FROM preparation_jobs WHERE state IN ('QUEUED','RUNNING') LIMIT 1").fetchone():
                return {"removed_chunks": 0, "reclaimed_bytes": 0}
            rows = db.execute("""SELECT * FROM preparation_chunks c WHERE NOT EXISTS
                (SELECT 1 FROM preparation_refs r WHERE r.chunk_key=c.key)
                ORDER BY accessed_ms LIMIT ?""", (max_chunks,)).fetchall()
            for row in rows:
                # A byte object can back more than one coverage receipt. Only
                # remove it when no other receipt (pinned or not) references it.
                others = db.execute("SELECT COUNT(*) FROM preparation_chunks WHERE receipt=? AND key<>?",
                                    (row["receipt"], row["key"])).fetchone()[0]
                if not others:
                    db.execute("INSERT OR IGNORE INTO preparation_pending_deletes VALUES (?,?)",
                               (row["receipt"], row["bytes"]))
                db.execute("DELETE FROM preparation_chunks WHERE key=?", (row["key"],))
                removed += 1
        # Commit coverage removal before unlink: a crash can leave an orphan
        # file, but never a supposedly ready receipt pointing to a deleted file.
        reclaimed = self.cleanup_pending(remove, max_chunks=max_chunks)
        return {"removed_chunks": removed, "reclaimed_bytes": reclaimed}

    def cleanup_pending(self, remove, *, max_chunks=32, before_workers=False):
        reclaimed = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not before_workers and db.execute("SELECT 1 FROM preparation_jobs WHERE state IN ('QUEUED','RUNNING') LIMIT 1").fetchone():
                return reclaimed
            for row in db.execute("SELECT * FROM preparation_pending_deletes LIMIT ?", (max_chunks,)).fetchall():
                # A new completed acquisition may have re-adopted this object
                # while physical deletion waited for the active queue to drain.
                if not db.execute("SELECT 1 FROM preparation_chunks WHERE receipt=? LIMIT 1", (row["receipt"],)).fetchone():
                    if remove(json.loads(row["receipt"])) is not False:
                        reclaimed += row["bytes"]
                    self._clear_removed_legacy_file(db, row["receipt"])
                db.execute("DELETE FROM preparation_pending_deletes WHERE receipt=?", (row["receipt"],))
            # The last observer can cancel after bytes were atomically written
            # but before the chunk callback ran. Idle cache cleanup owns these
            # abandoned writes; active acquisition workers are fenced above.
            for row in db.execute("SELECT * FROM preparation_cache_writes LIMIT ?", (max_chunks,)).fetchall():
                if not db.execute("SELECT 1 FROM preparation_chunks WHERE receipt=? LIMIT 1", (row["receipt"],)).fetchone():
                    if remove(json.loads(row["receipt"])) is not False:
                        reclaimed += row["bytes"]
                    self._clear_removed_legacy_file(db, row["receipt"])
                db.execute("DELETE FROM preparation_cache_writes WHERE receipt=?", (row["receipt"],))
        return reclaimed

    def _clear_removed_legacy_file(self, db, receipt):
        # Called inside the GC transaction after the cache deletion callback.
        # Archive files have a different owner and are deliberately excluded.
        db.execute("""UPDATE preparation_publications SET bytes=0,checked_ms=?
            WHERE kind='acquisition_legacy' AND path IN (
                SELECT path FROM preparation_receipt_files WHERE receipt=?)""", (self.now(), receipt))

    def chunk(self, key, *, owner=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM preparation_chunks WHERE key=?", (key,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE preparation_chunks SET accessed_ms=? WHERE key=?", (self.now(), key))
            if owner:
                db.execute("INSERT OR IGNORE INTO preparation_refs VALUES (?,?)", (owner, key))
            return {"key": key, "requirement": json.loads(row["requirement"]),
                    "receipt": json.loads(row["receipt"]), "bytes": row["bytes"]}

    def publish_chunk(self, key, requirement, receipt, size, owner):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # First complete publication wins. Subsequent source corrections need
            # an explicit versioned refresh, never mutate already pinned input.
            db.execute("INSERT OR IGNORE INTO preparation_chunks (key,requirement,receipt,bytes,accessed_ms,series_key,start_ms,end_ms) VALUES (?,?,?,?,?,?,?,?)",
                       (key, canonical(requirement), canonical(receipt), size, self.now(), self.series_key(requirement),
                        requirement.get("start_ms"), requirement.get("end_ms")))
            db.execute("INSERT OR IGNORE INTO preparation_refs VALUES (?,?)", (owner, key))
            db.execute("DELETE FROM preparation_cache_writes WHERE receipt=?", (canonical(receipt),))
        return self.chunk(key)

    def covering(self, requirement: Requirement, *, owner):
        selected = requirement.model_dump()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM preparation_chunks WHERE series_key=?
                AND start_ms<=? AND end_ms>=? ORDER BY bytes LIMIT 1""",
                (self.series_key(selected), requirement.start_ms, requirement.end_ms)).fetchone()
            if row is None:
                return None
            db.execute("INSERT OR IGNORE INTO preparation_refs VALUES (?,?)", (owner, row["key"]))
            db.execute("UPDATE preparation_chunks SET accessed_ms=? WHERE key=?", (self.now(), row["key"]))
            return {"key": row["key"], "requirement": selected, "source_requirement": json.loads(row["requirement"]),
                    "receipt": json.loads(row["receipt"]), "bytes": row["bytes"]}

    def partition(self, requirement: Requirement):
        with self.connect() as db:
            rows = db.execute("""SELECT start_ms,end_ms FROM preparation_chunks WHERE series_key=?
                AND start_ms<? AND end_ms>? ORDER BY start_ms""",
                (self.series_key(requirement.model_dump()), requirement.end_ms, requirement.start_ms)).fetchall()
        boundaries = {requirement.start_ms, requirement.end_ms}
        for row in rows:
            boundaries.add(max(requirement.start_ms, row["start_ms"]))
            boundaries.add(min(requirement.end_ms, row["end_ms"]))
        ordered = sorted(boundaries)
        return [requirement.model_copy(update={"start_ms": a, "end_ms": b}) for a, b in zip(ordered, ordered[1:])]

    def release(self, owner):
        with self.connect() as db:
            db.execute("DELETE FROM preparation_refs WHERE owner=?", (owner,))

    def storage_bytes(self):
        with self.connect() as db:
            return db.execute("SELECT COALESCE(SUM(bytes),0) FROM preparation_storage").fetchone()[0]
