"""D126: transactionally coalesced changes and optimistic acquisition fences.

SQLite triggers cover *every* physical writer (including offline repair and
another process). One watermark per semantic series replaces a per-row event
log. Consumers must invalidate the whole reported series: ranges are a
conservative envelope, not a replayable sequence of individual edits.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import threading

from app.data_engine.series_identity import KlineSeriesIdentity

IDENTITY_COLUMNS = ("exchange", "market_type", "symbol", "interval",
                    "provider_id", "venue", "asset_class", "series_variant",
                    "price_adjustment", "session_variant", "volume_semantics")


class StaleAcquisition(RuntimeError):
    """The input was acquired before a newer canonical mutation; reacquire it."""


def init_revision_storage(conn):
    columns = ", ".join(f"{name} TEXT NOT NULL" for name in IDENTITY_COLUMNS)
    keys = ", ".join(IDENTITY_COLUMNS)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS kline_revision_clock (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL
        );
        INSERT OR IGNORE INTO kline_revision_clock VALUES (1,0);
        CREATE TABLE IF NOT EXISTS kline_series_changes (
            {columns}, revision INTEGER NOT NULL, delete_revision INTEGER NOT NULL,
            start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, operation TEXT NOT NULL,
            PRIMARY KEY ({keys})
        );
        CREATE TABLE IF NOT EXISTS kline_derived_series ({columns}, PRIMARY KEY ({keys}));
        CREATE INDEX IF NOT EXISTS idx_kline_changes_revision ON kline_series_changes(revision);
        CREATE TABLE IF NOT EXISTS kline_mutation_context (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), mode TEXT NOT NULL
        );
        INSERT OR IGNORE INTO kline_mutation_context VALUES (1,'');
        CREATE TABLE IF NOT EXISTS kline_acquisitions (
            owner TEXT PRIMARY KEY, revision INTEGER NOT NULL
        );
    """)
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS manual_history_acquisition
        AFTER INSERT ON manual_history_jobs BEGIN
            INSERT OR IGNORE INTO kline_acquisitions VALUES
                ('manual:' || NEW.job_id, (SELECT revision FROM kline_revision_clock WHERE singleton=1));
        END;
        CREATE TRIGGER IF NOT EXISTS manual_history_acquisition_done
        AFTER UPDATE OF state ON manual_history_jobs
        WHEN NEW.state IN ('SUCCEEDED','FAILED','CANCELLED') BEGIN
            DELETE FROM kline_acquisitions WHERE owner='manual:' || NEW.job_id;
        END;
    """)
    # Pre-migration queued/running jobs have no acquisition trigger receipt.
    # Their inputs predate this ledger; never grant them a post-delete floor.
    conn.execute("""INSERT OR IGNORE INTO kline_acquisitions
        SELECT 'manual:' || job_id, 0 FROM manual_history_jobs
        WHERE state NOT IN ('SUCCEEDED','FAILED','CANCELLED')""")
    conn.execute(f"INSERT OR IGNORE INTO kline_derived_series SELECT DISTINCT {keys} FROM klines "
                 "WHERE source IN ('backfill_aggregated','data_manager_composite_closed',"
                 "'settings_manual_repair','repair_derived_verified','manual_history_derived')")
    changed_key = " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in (*IDENTITY_COLUMNS, "open_time"))
    conn.executescript(f"""
        CREATE TRIGGER IF NOT EXISTS kline_identity_immutable BEFORE UPDATE ON klines
        WHEN {changed_key} BEGIN
            SELECT RAISE(ABORT, 'K-line identity changes require delete and insert');
        END;
    """)
    for operation, alias in (("insert", "NEW"), ("update", "NEW"), ("delete", "OLD")):
        values = ", ".join(f"{alias}.{name}" for name in IDENTITY_COLUMNS)
        revision = "(SELECT revision FROM kline_revision_clock WHERE singleton=1)"
        deletion = revision if operation == "delete" else "0"
        changed_fields = (*IDENTITY_COLUMNS, "open_time", "close_time", "open", "high", "low", "close", "volume",
                          "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "source")
        condition = "WHEN " + " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in changed_fields) if operation == "update" else ""
        source_derived_predicate = " AND ".join(f"s.{name}={alias}.{name}" for name in IDENTITY_COLUMNS)
        derived_predicate = " AND ".join(f"d.{name}=klines.{name}" for name in IDENTITY_COLUMNS)
        family_predicate = " AND ".join(f"{name}={alias}.{name}" for name in IDENTITY_COLUMNS if name != "interval")
        conn.executescript(f"""
            CREATE TRIGGER IF NOT EXISTS kline_change_{operation}
            AFTER {operation.upper()} ON klines {condition} BEGIN
                UPDATE kline_revision_clock SET revision=revision+1 WHERE singleton=1;
                INSERT INTO kline_series_changes
                VALUES ({values}, {revision}, {deletion}, {alias}.open_time,
                        COALESCE({alias}.close_time,{alias}.open_time), '{operation}')
                ON CONFLICT({keys}) DO UPDATE SET
                    revision=excluded.revision,
                    delete_revision=MAX(delete_revision,excluded.delete_revision),
                    start_ms=MIN(start_ms,excluded.start_ms), end_ms=MAX(end_ms,excluded.end_ms),
                    operation=excluded.operation;
            END;
        """)
        dependent_family = " AND ".join(f"d.{name}={alias}.{name}" for name in IDENTITY_COLUMNS if name != "interval")
        mutation_condition = "(" + " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in changed_fields) + ") AND " if operation == "update" else ""
        # Avoid a K-line range scan for every row of an ordinary native import
        # when the semantic family has no registered derived projections.
        conn.executescript(f"""
            CREATE TRIGGER IF NOT EXISTS kline_dependents_{operation}
            AFTER {operation.upper()} ON klines
            WHEN {mutation_condition}(SELECT mode FROM kline_mutation_context WHERE singleton=1)<>'retention'
                AND NOT EXISTS(SELECT 1 FROM kline_derived_series s WHERE {source_derived_predicate})
                AND EXISTS(SELECT 1 FROM kline_derived_series d WHERE {dependent_family} AND d.interval<>{alias}.interval)
            BEGIN
                DELETE FROM klines WHERE {family_predicate}
                    AND interval<>{alias}.interval
                    AND EXISTS(SELECT 1 FROM kline_derived_series d WHERE {derived_predicate})
                    AND NOT EXISTS(SELECT 1 FROM kline_derived_series s WHERE {source_derived_predicate})
                    AND open_time<=COALESCE({alias}.close_time,{alias}.open_time)
                    AND COALESCE(close_time,open_time)>={alias}.open_time;
            END;
        """)


def current_revision(conn):
    return int(conn.execute("SELECT revision FROM kline_revision_clock WHERE singleton=1").fetchone()[0])


def series_values(symbol, interval, exchange, market_type, identity=None):
    identity = identity or KlineSeriesIdentity.for_exchange(exchange)
    return (exchange, market_type, symbol, interval, *identity.storage_values)


def series_change(conn, values):
    return conn.execute("SELECT * FROM kline_series_changes WHERE " +
                        " AND ".join(f"{name}=?" for name in IDENTITY_COLUMNS), values).fetchone()


def mark_deleted(conn, values, start_ms=None, end_ms=None):
    """Fence deletion of even an empty range, in the deleting transaction."""
    conn.execute("UPDATE kline_revision_clock SET revision=revision+1 WHERE singleton=1")
    revision = current_revision(conn)
    keys = ",".join(IDENTITY_COLUMNS)
    conn.execute(f"""INSERT INTO kline_series_changes VALUES ({','.join('?' for _ in range(16))})
        ON CONFLICT({keys}) DO UPDATE SET revision=excluded.revision,
        delete_revision=excluded.delete_revision, start_ms=MIN(start_ms,excluded.start_ms),
        end_ms=MAX(end_ms,excluded.end_ms), operation='delete'""",
        (*values, revision, revision, start_ms if start_ms is not None else 0,
         end_ms if end_ms is not None else 9223372036854775807, "delete"))


class RevisionStore:
    def __init__(self, connect):
        self.connect = connect
        self.observed_revision = 0

    def changes_since(self, revision, *, limit=4096):
        # Head and changes belong to the same read transaction. A bounded
        # overrun tells the consumer to clear its projection and use the head.
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN")
            head = current_revision(conn)
            rows = conn.execute("SELECT * FROM kline_series_changes WHERE revision>? ORDER BY revision LIMIT ?",
                                (revision, limit + 1)).fetchall()
            self.observed_revision = head
            return {"revision": head, "reset": len(rows) > limit or revision > head,
                    "changes": [dict(row) for row in rows[:limit]]}

    def head(self):
        with closing(self.connect()) as conn:
            self.observed_revision = current_revision(conn)
            return self.observed_revision

    def acquisition(self, *, owner=None, revision=None):
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE" if owner else "BEGIN")
            start = current_revision(conn)
            deletion_floor = start if revision is None else int(revision)
            if owner:
                conn.execute("INSERT OR IGNORE INTO kline_acquisitions VALUES (?,?)", (owner, deletion_floor))
                deletion_floor = conn.execute("SELECT revision FROM kline_acquisitions WHERE owner=?", (owner,)).fetchone()[0]
            return Acquisition(int(start), delete_revision=int(deletion_floor))

    def forget_acquisition(self, owner):
        with closing(self.connect()) as conn, conn:
            conn.execute("DELETE FROM kline_acquisitions WHERE owner=?", (owner,))


@dataclass
class Acquisition:
    revision: int
    delete_revision: int | None = None
    # Only the active job's written series are retained. Persistent jobs keep
    # their initial revision on disk; after restart re-read/recompute inputs.
    accepted: dict[tuple, int] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def check(self, conn, values):
        # Include the complete semantic family: derived output must not be
        # built from a source deleted/repaired after acquisition, even when
        # that target did not exist at deletion time.
        family = [(name, value) for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval"]
        for row in conn.execute("SELECT * FROM kline_series_changes WHERE " +
                                " AND ".join(f"{name}=?" for name, _ in family),
                                tuple(value for _, value in family)):
            key = tuple(row[name] for name in IDENTITY_COLUMNS)
            allowed = self.accepted.get(key, self.revision)
            delete_floor = self.revision if self.delete_revision is None else self.delete_revision
            if int(row["revision"]) > allowed or int(row["delete_revision"]) > max(delete_floor, self.accepted.get(key, 0)):
                raise StaleAcquisition("canonical series family changed after acquisition began")

    def accept(self, conn, values):
        row = series_change(conn, values)
        if row is not None:
            self.accepted[values] = int(row["revision"])


_acquisition: ContextVar[Acquisition | None] = ContextVar("kline_acquisition", default=None)


@contextmanager
def acquisition_scope(acquisition):
    token = _acquisition.set(acquisition)
    try:
        yield acquisition
    finally:
        _acquisition.reset(token)


@contextmanager
def guarded_write(conn, values, *, commit=True):
    """Hold optimistic check and SQL write in one SQLite writer transaction."""
    scope = _acquisition.get()
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    if scope is None:
        yield
        if commit:
            conn.commit()
        return
    with scope.lock:
        scope.check(conn, values)
        yield
        family = [(name, value) for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval"]
        accepted = {tuple(row[name] for name in IDENTITY_COLUMNS): int(row["revision"])
                    for row in conn.execute("SELECT * FROM kline_series_changes WHERE " +
                        " AND ".join(f"{name}=?" for name, _ in family), tuple(v for _, v in family))}
        if commit:
            conn.commit()
            scope.accepted.update(accepted)


def fenced_acquisition(function):
    """Capture before network/CPU acquisition, propagated through run_storage.

    Adapters other than SQLite can expose the same revision_store contract.
    Nested backfill runs inherit the initiating job's permission.
    """
    @wraps(function)
    async def run(self, *args, **kwargs):
        if _acquisition.get() is not None:
            return await function(self, *args, **kwargs)
        storage = getattr(self, "_storage", None)
        store = getattr(storage, "revision_store", None)
        if store is None:
            return await function(self, *args, **kwargs)
        from app.core.executors import run_storage
        metadata = kwargs.get("metadata") or {}
        scope = await run_storage(store.acquisition, revision=metadata.get("acquisition_revision"))
        with acquisition_scope(scope):
            return await function(self, *args, **kwargs)
    return run


@contextmanager
def ensure_acquisition(revision):
    scope = _acquisition.get()
    if scope is not None:
        yield scope
    else:
        with acquisition_scope(Acquisition(revision)) as scope:
            yield scope


def fenced_manual_job(function):
    @wraps(function)
    async def run(self, job_id):
        store = getattr(self.storage, "revision_store", None)
        if store is None:
            return await function(self, job_id)
        from app.core.executors import run_storage
        owner = "manual:" + job_id
        scope = await run_storage(store.acquisition, owner=owner)
        with acquisition_scope(scope):
            result = await function(self, job_id)
        if str(getattr(getattr(result, "state", None), "value", "")) in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            await run_storage(store.forget_acquisition, owner)
        return result
    return run


def acquisition_delete_floor(default):
    scope = _acquisition.get()
    if scope is None:
        return default
    return scope.revision if scope.delete_revision is None else scope.delete_revision


def register_derived(conn, values):
    conn.execute("INSERT OR IGNORE INTO kline_derived_series VALUES (" + ",".join("?" for _ in values) + ")", values)
