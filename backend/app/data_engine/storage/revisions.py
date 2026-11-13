"""D126: transactionally coalesced changes and optimistic acquisition fences.

SQLite triggers cover *every* physical writer (including offline repair and
another process). One watermark per semantic series replaces a per-row event
log. Its ranges are conservative envelopes. B130 also consumes a bounded
transactional suffix of exact footprints when it can prove continuity.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import TYPE_CHECKING
import threading
import sqlite3

from app.data_engine.series_identity import KlineSeriesIdentity

if TYPE_CHECKING:
    from .warmup_revision_fence import WarmupView

IDENTITY_COLUMNS = ("exchange", "market_type", "symbol", "interval",
                    "provider_id", "venue", "asset_class", "series_variant",
                    "price_adjustment", "session_variant", "volume_semantics")
BLOCK_CHANGE_WINDOW = 1024


REVISION_CHANGED_FIELDS = (*IDENTITY_COLUMNS, "open_time", "close_time", "open", "high", "low", "close", "volume",
                           "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "source")


class StaleAcquisition(RuntimeError):
    """The input was acquired before a newer canonical mutation; reacquire it."""


def _execute_schema(conn, script):
    """Execute trigger DDL without sqlite3.executescript's implicit commit."""
    statement = ""
    for character in script:
        statement += character
        if character == ";" and sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete revision schema statement")


def _block_change_sql(values, predicate, revision, start_ms, end_ms):
    return f"""
        INSERT INTO kline_block_changes VALUES (
            {revision}, {values},
            COALESCE((SELECT revision FROM kline_series_changes WHERE {predicate}), 0),
            {start_ms}, {end_ms}
        );
        DELETE FROM kline_block_changes WHERE revision<={revision}-{BLOCK_CHANGE_WINDOW};
    """


def _readback_receipt_sql(values, revision, start, end, *, condition="1"):
    keys = ",".join(IDENTITY_COLUMNS)
    return f"""
        INSERT INTO kline_history_readback
        SELECT {values}, {revision}, 0, {start}, {end} WHERE {condition}
        ON CONFLICT({keys}) DO UPDATE SET
            previous_revision=kline_history_readback.revision,
            revision=excluded.revision, start_ms=excluded.start_ms, end_ms=excluded.end_ms;
    """


@contextmanager
def mutation_mode(conn, mode):
    """Tag writes already announced by their production owner."""
    previous = conn.execute("SELECT mode FROM kline_mutation_context WHERE singleton=1").fetchone()[0]
    conn.execute("UPDATE kline_mutation_context SET mode=? WHERE singleton=1", (mode,))
    try:
        yield
    finally:
        conn.execute("UPDATE kline_mutation_context SET mode=? WHERE singleton=1", (previous,))


def init_revision_storage(conn):
    columns = ", ".join(f"{name} TEXT NOT NULL" for name in IDENTITY_COLUMNS)
    keys = ", ".join(IDENTITY_COLUMNS)
    # Serialize first-migration detection and seeding with every physical writer.
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    had_delete_permissions = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kline_delete_permissions'").fetchone() is not None
    schema = f"""
        CREATE TABLE IF NOT EXISTS kline_revision_clock (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL
        );
        INSERT OR IGNORE INTO kline_revision_clock VALUES (1,0);
        CREATE TABLE IF NOT EXISTS kline_series_changes (
            {columns}, revision INTEGER NOT NULL, delete_revision INTEGER NOT NULL,
            start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, operation TEXT NOT NULL,
            PRIMARY KEY ({keys})
        );
        CREATE TABLE IF NOT EXISTS kline_history_readback (
            {columns}, revision INTEGER NOT NULL, previous_revision INTEGER NOT NULL,
            start_ms INTEGER, end_ms INTEGER, PRIMARY KEY ({keys})
        );
        CREATE TABLE IF NOT EXISTS kline_derived_series ({columns}, PRIMARY KEY ({keys}));
        CREATE INDEX IF NOT EXISTS idx_kline_changes_revision ON kline_series_changes(revision);
        CREATE TABLE IF NOT EXISTS kline_block_changes (
            revision INTEGER PRIMARY KEY, {columns}, previous_revision INTEGER NOT NULL,
            start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS kline_mutation_context (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), mode TEXT NOT NULL
        );
        INSERT OR IGNORE INTO kline_mutation_context VALUES (1,'');
        CREATE TABLE IF NOT EXISTS kline_acquisitions (
            owner TEXT PRIMARY KEY, revision INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS kline_delete_permissions (
            {columns}, revision INTEGER NOT NULL, PRIMARY KEY ({keys})
        );
        CREATE TABLE IF NOT EXISTS kline_projection_invalidation (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), depth INTEGER NOT NULL CHECK(depth>=0)
        );
        INSERT OR IGNORE INTO kline_projection_invalidation VALUES (1,0);
    """
    for statement in schema.split(";"):
        if statement.strip():
            conn.execute(statement)
    if not had_delete_permissions:
        # Old pending jobs have no distinction between explicit deletion and
        # automatic projection invalidation. Preserve their conservative floor.
        conn.execute(f"INSERT OR IGNORE INTO kline_delete_permissions SELECT {keys},delete_revision "
                     "FROM kline_series_changes WHERE delete_revision>0")
    _execute_schema(conn, """
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
    _execute_schema(conn, f"""
        CREATE TRIGGER IF NOT EXISTS kline_identity_immutable BEFORE UPDATE ON klines
        WHEN {changed_key} BEGIN
            SELECT RAISE(ABORT, 'K-line identity changes require delete and insert');
        END;
    """)
    for operation, alias in (("insert", "NEW"), ("update", "NEW"), ("delete", "OLD")):
        values = ", ".join(f"{alias}.{name}" for name in IDENTITY_COLUMNS)
        revision = "(SELECT revision FROM kline_revision_clock WHERE singleton=1)"
        deletion = revision if operation == "delete" else "0"
        changed_fields = REVISION_CHANGED_FIELDS
        condition = "WHEN " + " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in changed_fields) if operation == "update" else ""
        watermark_predicate = " AND ".join(f"{name}={alias}.{name}" for name in IDENTITY_COLUMNS)
        # Canonical blocks select candles by open, including inserts and replacements.
        footprint = _block_change_sql(values, watermark_predicate, revision,
                                      f"{alias}.open_time", f"{alias}.open_time")
        source_derived_predicate = " AND ".join(f"s.{name}={alias}.{name}" for name in IDENTITY_COLUMNS)
        derived_predicate = " AND ".join(f"d.{name}=klines.{name}" for name in IDENTITY_COLUMNS)
        family_predicate = " AND ".join(f"{name}={alias}.{name}" for name in IDENTITY_COLUMNS if name != "interval")
        mode = "(SELECT mode FROM kline_mutation_context WHERE singleton=1)"
        direct = f"{mode} NOT IN ('bar_delivery', 'derived_materialization')"
        if operation == "delete":
            direct = f"({direct}) OR (SELECT depth FROM kline_projection_invalidation WHERE singleton=1)>0"
        readback = _readback_receipt_sql(values, revision, f"{alias}.open_time", f"{alias}.open_time",
                                         condition=direct)
        _execute_schema(conn, f"""
            DROP TRIGGER IF EXISTS kline_change_{operation};
            CREATE TRIGGER kline_change_{operation}
            AFTER {operation.upper()} ON klines {condition} BEGIN
                UPDATE kline_revision_clock SET revision=revision+1 WHERE singleton=1;
                {footprint}
                INSERT INTO kline_series_changes
                VALUES ({values}, {revision}, {deletion}, {alias}.open_time,
                        COALESCE({alias}.close_time,{alias}.open_time), '{operation}')
                ON CONFLICT({keys}) DO UPDATE SET
                    revision=excluded.revision,
                    delete_revision=MAX(delete_revision,excluded.delete_revision),
                    start_ms=MIN(start_ms,excluded.start_ms), end_ms=MAX(end_ms,excluded.end_ms),
                    operation=excluded.operation;
                {readback}
                {('INSERT INTO kline_delete_permissions SELECT ' + values + ',' + revision +
                  ' WHERE (SELECT depth FROM kline_projection_invalidation WHERE singleton=1)=0 '
                  'ON CONFLICT(' + keys + ') DO UPDATE SET revision=excluded.revision;' if operation == 'delete' else '')}
            END;
        """)
        dependent_family = " AND ".join(f"d.{name}={alias}.{name}" for name in IDENTITY_COLUMNS if name != "interval")
        mutation_condition = "(" + " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in changed_fields) + ") AND " if operation == "update" else ""
        # Avoid a K-line range scan for every row of an ordinary native import
        # when the semantic family has no registered derived projections.
        _execute_schema(conn, f"""
            DROP TRIGGER IF EXISTS kline_dependents_{operation};
            CREATE TRIGGER IF NOT EXISTS kline_dependents_{operation}
            AFTER {operation.upper()} ON klines
            WHEN {mutation_condition}(SELECT mode FROM kline_mutation_context WHERE singleton=1)
                NOT IN ('retention', 'provenance_migration')
                AND NOT EXISTS(SELECT 1 FROM kline_derived_series s WHERE {source_derived_predicate})
                AND EXISTS(SELECT 1 FROM kline_derived_series d WHERE {dependent_family} AND d.interval<>{alias}.interval)
            BEGIN
                UPDATE kline_projection_invalidation SET depth=depth+1 WHERE singleton=1;
                DELETE FROM klines WHERE {family_predicate}
                    AND interval<>{alias}.interval
                    AND EXISTS(SELECT 1 FROM kline_derived_series d WHERE {derived_predicate})
                    AND NOT EXISTS(SELECT 1 FROM kline_derived_series s WHERE {source_derived_predicate})
                    AND open_time<=COALESCE({alias}.close_time,{alias}.open_time)
                    AND COALESCE(close_time,open_time)>={alias}.open_time;
                UPDATE kline_projection_invalidation SET depth=depth-1 WHERE singleton=1;
            END;
        """)
    conn.commit()


def init_empty_coverage_revision_triggers(conn, table: str, *, native: bool = False) -> None:
    assert table in {"native_empty_seconds", "trade_empty_buckets"}
    keys = ",".join(IDENTITY_COLUMNS)
    conn.executescript(f"""
        CREATE TRIGGER IF NOT EXISTS {table}_immutable BEFORE UPDATE ON {table}
        BEGIN
            SELECT RAISE(ABORT, 'Empty coverage changes require delete and insert');
        END;
    """)
    for operation, alias in (("insert", "NEW"), ("delete", "OLD")):
        exchange = "'upbit'" if native else f"{alias}.exchange"
        market = "'spot'" if native else f"{alias}.market_type"
        interval = "'1s'" if native else f"{alias}.interval"
        values = (exchange, market, f"{alias}.symbol", interval,
                  exchange, exchange, "'crypto'", "'native'", "'raw'", "'continuous'", "'base_asset'")
        head = "(SELECT revision FROM kline_revision_clock WHERE singleton=1)"
        deletion = head if operation == "delete" else "0"
        if native and operation == "delete":
            # Atomic union replaces old spans without withdrawing any absence
            # evidence. It is a content revision, not permission to recreate
            # deleted candles. Actual clear/delete/invalidation stays fenced.
            deletion = ("CASE WHEN (SELECT mode FROM kline_mutation_context WHERE singleton=1)="
                        "'native_empty_union' THEN 0 ELSE " + head + " END")
        migration_start = f"BEGIN IMMEDIATE; DROP TRIGGER IF EXISTS {table}_change_{operation};"
        migration_end = "COMMIT;"
        family = " AND ".join(f"d.{name}={value}" for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval")
        selected_family = " AND ".join(f"{name}={value}" for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval")
        match = " AND ".join(f"d.{name}=klines.{name}" for name in IDENTITY_COLUMNS)
        predicate = " AND ".join(f"{name}={value}" for name, value in zip(IDENTITY_COLUMNS, values))
        readback = _readback_receipt_sql(",".join(values), head, f"{alias}.start_ms", f"{alias}.end_ms")
        conn.executescript(f"""
            {migration_start}
            CREATE TRIGGER IF NOT EXISTS {table}_change_{operation}
            AFTER {operation.upper()} ON {table} BEGIN
                UPDATE kline_revision_clock SET revision=revision+1 WHERE singleton=1;
                {_block_change_sql(','.join(values), predicate, head, f'{alias}.start_ms', f'{alias}.end_ms')}
                INSERT INTO kline_series_changes VALUES
                    ({','.join(values)}, {head}, {deletion}, {alias}.start_ms, {alias}.end_ms, 'empty_{operation}')
                ON CONFLICT({keys}) DO UPDATE SET revision=excluded.revision,
                    delete_revision=MAX(delete_revision,excluded.delete_revision),
                    start_ms=MIN(start_ms,excluded.start_ms), end_ms=MAX(end_ms,excluded.end_ms),
                    operation=excluded.operation;
                {readback}
                UPDATE kline_projection_invalidation SET depth=depth+1 WHERE singleton=1;
                DELETE FROM klines WHERE {selected_family} AND
                    EXISTS(SELECT 1 FROM kline_derived_series d WHERE {match} AND {family} AND d.interval<>{interval})
                    AND open_time<={alias}.end_ms AND COALESCE(close_time,open_time)>={alias}.start_ms
                    AND (SELECT mode FROM kline_mutation_context WHERE singleton=1)<>'retention';
                UPDATE kline_projection_invalidation SET depth=depth-1 WHERE singleton=1;
            END;
            {migration_end}
        """)

    from .prefix_watches import init_prefix_watch_storage
    init_prefix_watch_storage(conn)


def current_revision(conn):
    return int(conn.execute("SELECT revision FROM kline_revision_clock WHERE singleton=1").fetchone()[0])


def block_change_receipts(conn, revision, head):
    """Read the complete bounded footprint journal in the caller's transaction."""
    if not 0 < head - revision <= BLOCK_CHANGE_WINDOW:
        return ()
    receipts = conn.execute(
        "SELECT * FROM kline_block_changes WHERE revision>? AND revision<=? ORDER BY revision",
        (revision, head),
    ).fetchall()
    return receipts if len(receipts) == head - revision else ()


def series_values(symbol, interval, exchange, market_type, identity=None):
    identity = identity or KlineSeriesIdentity.for_exchange(exchange)
    return (exchange, market_type, symbol, interval, *identity.storage_values)


def series_change(conn, values):
    return conn.execute("SELECT * FROM kline_series_changes WHERE " +
                        " AND ".join(f"{name}=?" for name in IDENTITY_COLUMNS), values).fetchone()


def mark_deleted(conn, values, start_ms=None, end_ms=None):
    """Fence deletion of even an empty range, in the deleting transaction."""
    from .prefix_watches import invalidate_deleted_prefix
    invalidate_deleted_prefix(conn, values, start_ms, end_ms)
    conn.execute("UPDATE kline_revision_clock SET revision=revision+1 WHERE singleton=1")
    revision = current_revision(conn)
    keys = ",".join(IDENTITY_COLUMNS)
    start = start_ms if start_ms is not None else 0
    end = end_ms if end_ms is not None else 9223372036854775807
    predicate = " AND ".join(f"{name}=?" for name in IDENTITY_COLUMNS)
    conn.execute(f"""INSERT INTO kline_block_changes VALUES (
        ?, {','.join('?' for _ in IDENTITY_COLUMNS)},
        COALESCE((SELECT revision FROM kline_series_changes WHERE {predicate}), 0), ?, ?
    )""", (revision, *values, *values, start, end))
    conn.execute("DELETE FROM kline_block_changes WHERE revision<=?", (revision - BLOCK_CHANGE_WINDOW,))
    conn.execute(f"INSERT INTO kline_delete_permissions VALUES ({','.join('?' for _ in range(12))}) "
                 f"ON CONFLICT({keys}) DO UPDATE SET revision=excluded.revision", (*values, revision))
    conn.execute(f"""INSERT INTO kline_series_changes VALUES ({','.join('?' for _ in range(16))})
        ON CONFLICT({keys}) DO UPDATE SET revision=excluded.revision,
        delete_revision=excluded.delete_revision, start_ms=MIN(start_ms,excluded.start_ms),
        end_ms=MAX(end_ms,excluded.end_ms), operation='delete'""",
        (*values, revision, revision, start, end, "delete"))
    conn.execute(_readback_receipt_sql(",".join("?" for _ in values), "?", "?", "?"),
                 (*values, revision, start_ms, end_ms))


class ScopedRevisionRead:
    """One short-lived connection for sequential checks within a live input.

    SQLite's data_version changes on commits from another connection. Check
    it before reusing a result, with no read transaction held between checks.
    """

    def __init__(self, store):
        self.store = store
        self._connection = None
        self._key = None
        self._result = None

    def read_versions(self, series):
        if self._connection is None:
            self._connection = self.store.connect()
        conn = self._connection
        version = conn.execute("PRAGMA data_version").fetchone()[0]
        values = tuple(series)
        key = (values, version)
        if key != self._key:
            self._result = self.store._read_versions(conn, values)
            self._key = key
        return self._result

    def close(self):
        if self._connection is not None:
            conn, self._connection = self._connection, None
            self._key = self._result = None
            conn.close()


class RevisionStore:
    def __init__(self, connect):
        self.connect = connect
        self.observed_revision = 0
        from .prefix_watches import PrefixWatchStore
        self.prefix_watches = PrefixWatchStore(connect)

    def changes_since(self, revision, *, limit=4096):
        # Head and changes belong to the same read transaction. A bounded
        # overrun tells the consumer to clear its projection and use the head.
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN")
            head = current_revision(conn)
            keys = ",".join(IDENTITY_COLUMNS)
            rows = conn.execute(f"""
                SELECT c.*, h.revision AS readback_revision, h.previous_revision AS readback_previous,
                       h.start_ms AS readback_start_ms, h.end_ms AS readback_end_ms
                FROM kline_series_changes c LEFT JOIN kline_history_readback h USING ({keys})
                WHERE c.revision>? ORDER BY c.revision LIMIT ?
                """, (revision, limit + 1)).fetchall()
            self.observed_revision = head
            return {"revision": head, "reset": len(rows) > limit or revision > head,
                    "changes": [dict(row) for row in rows[:limit]]}

    def head(self):
        with closing(self.connect()) as conn:
            self.observed_revision = current_revision(conn)
            return self.observed_revision

    def read_versions(self, series):
        """Bounded per-series view tokens from one SQLite read transaction.

        Tokens identify the latest committed content change, including empty
        deletions. Unrelated series writes do not change a source's token.
        Consumers still fence their entire acquisition before publication.
        """
        with closing(self.connect()) as conn:
            return self._read_versions(conn, tuple(series))

    def read_series_changes(self, series):
        """Bounded current per-series mutation/deletion evidence, one snapshot.

        The coalesced range is conservative. Consumers must not interpret it
        as exact per-row history or compare revision numbers across series.
        """
        values = tuple(series)
        if not 1 <= len(values) <= 32:
            raise ValueError("one to 32 source dependencies required")
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN")
            return current_revision(conn), tuple(
                dict(row) if (row := series_change(conn, key)) is not None else None
                for key in values)

    def scoped_version_reader(self):
        return ScopedRevisionRead(self)

    def _read_versions(self, conn, values):
        if len(values) > 32:
            raise ValueError("at most 32 source dependencies per revision view")
        with conn:
            conn.execute("BEGIN")
            head = current_revision(conn)
            return head, self._versions(conn, values)

    @staticmethod
    def _versions(conn, series):
        rows = (series_change(conn, key) for key in series)
        return tuple(int(row["revision"]) if row is not None else 0 for row in rows)

    def read_block_changes(self, revision, series, *, limit=4096):
        """Read B130 versions and invalidation evidence from one snapshot."""
        if len(series) > 32:
            raise ValueError("at most 32 source dependencies per revision view")
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN")
            head = current_revision(conn)
            versions = self._versions(conn, series)
            changes = conn.execute(
                "SELECT * FROM kline_series_changes WHERE revision>? ORDER BY revision LIMIT ?",
                (revision, limit + 1),
            ).fetchall()
            reset = len(changes) > limit or revision > head
            exact = () if reset else block_change_receipts(conn, revision, head)
            self.observed_revision = head
            return head, versions, changes[:limit], reset, exact

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
    native_history_views: list = field(default_factory=list, repr=False)
    derived_target_views: list = field(default_factory=list, repr=False)
    warmup_view: WarmupView | None = field(default=None, repr=False)
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


def acquisition_revision():
    """Readonly permission floor for consumers of an already acquired view."""
    scope = _acquisition.get()
    return scope.revision if scope is not None else None


@contextmanager
def acquisition_scope(acquisition):
    token = _acquisition.set(acquisition)
    try:
        yield acquisition
    finally:
        _acquisition.reset(token)


@contextmanager
def guarded_write(conn, values, *, commit=True, native_rows=None, source=None, native_empty_ranges=None):
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
        family = [(name, value) for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval"]
        def versions():
            return {tuple(row[name] for name in IDENTITY_COLUMNS): int(row["revision"])
                    for row in conn.execute("SELECT * FROM kline_series_changes WHERE " +
                        " AND ".join(f"{name}=?" for name, _ in family), tuple(v for _, v in family))}
        from .native_history_fence import matching_view, matching_empty_view, fingerprint
        from .derived_history_fence import matching_computation, affected_targets
        view = matching_view(scope, values, native_rows, source) if commit else None
        if view is None and commit and native_empty_ranges is not None:
            view = matching_empty_view(scope, values, native_empty_ranges)
        computation = matching_computation(scope, values, native_rows, source) if commit else None
        targets = affected_targets(scope, values, native_rows) if view is not None else ()
        warmup = scope.warmup_view
        # Native range permission still belongs to this warmup acquisition.
        # Record its own source commits so subsequent derived writes do not
        # mistake them for intervening external corrections.
        warmup_head = (warmup.check_write(conn, scope, values, native_rows, source)
                       if commit and warmup is not None and computation is None else None)
        if computation is not None:
            computation.check(conn, scope)
            targets = (computation.target,)
        elif view is None:
            if warmup_head is None:
                scope.check(conn, values)
        else:
            view.check_history_receipts(conn, native_rows)
            view.check(conn, scope)
            for target in targets:
                target.check(conn, scope)
        before = versions() if view is not None or computation is not None or warmup_head is not None else None
        yield
        accepted = versions()
        # A native range view does not consume other intervals as input.
        # Grant only mutations performed by this write, never unrelated family
        # revisions that happened while REST was in flight.
        if before is not None:
            accepted = {key: rev for key, rev in accepted.items() if before.get(key) != rev}
        digest = fingerprint(conn, values, view.start, view.end) if view else None
        target_digests = [(target, fingerprint(conn, target.key, target.start, target.end))
                          for target in targets]
        if commit:
            after = current_revision(conn) if warmup_head is not None else None
            conn.commit()
            scope.accepted.update(accepted)
            if warmup_head is not None:
                warmup.accept(warmup_head, after)
            if view is not None:
                view.digest = digest
            for target, target_digest in target_digests:
                target.digest = target_digest


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


def prepare_warmup_view(windows):
    scope = _acquisition.get()
    if scope is not None and windows:
        from .warmup_revision_fence import make_warmup_view
        scope.warmup_view = make_warmup_view(windows)


async def prepare_native_history_views(storage, tasks):
    from app.core.executors import run_storage
    from .native_history_fence import capture_native_history_views
    await run_storage(capture_native_history_views, getattr(storage, "revision_store", None),
                      _acquisition.get(), tasks)


async def prepare_derived_targets(storage, plan):
    from app.core.executors import run_storage
    from .derived_history_fence import capture_targets
    await run_storage(capture_targets, getattr(storage, 'revision_store', None),
                      _acquisition.get(), plan)


async def prepare_derived_inputs(storage, decomp, grouped):
    from app.core.executors import run_storage
    from .derived_history_fence import capture_inputs
    return await run_storage(capture_inputs, getattr(storage, 'revision_store', None),
                             _acquisition.get(), decomp, grouped)


def register_derived(conn, values):
    conn.execute("INSERT OR IGNORE INTO kline_derived_series VALUES (" + ",".join("?" for _ in values) + ")", values)
