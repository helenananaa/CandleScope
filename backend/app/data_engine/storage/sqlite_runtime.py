"""Shared SQLite connection policy for DataEngine-owned repositories."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SQLiteConnectionPolicy:
    timeout_seconds: float = 30.0
    busy_timeout_ms: int | None = 30_000
    check_same_thread: bool = False
    use_row_factory: bool = True
    configure_journal_mode: bool = True
    journal_mode: str = "WAL"
    fallback_journal_mode: str = "DELETE"
    synchronous: str = "NORMAL"

    def __post_init__(self) -> None:
        if self.timeout_seconds < 0:
            raise ValueError("SQLite timeout_seconds cannot be negative")
        if self.busy_timeout_ms is not None and self.busy_timeout_ms < 0:
            raise ValueError("SQLite busy_timeout_ms cannot be negative")
        for field_name in ("journal_mode", "fallback_journal_mode", "synchronous"):
            value = str(getattr(self, field_name)).strip().upper()
            if not value or not value.replace("_", "").isalnum():
                raise ValueError(f"invalid SQLite {field_name}: {value!r}")
            object.__setattr__(self, field_name, value)


DEFAULT_SQLITE_POLICY = SQLiteConnectionPolicy()


class _WriterGate:
    """One in-process writer at a time per database file.

    SQLite admits one writer. Its default busy handler polls with sleeps of up
    to 100 ms, so threads of this process that contend for the write lock waste
    most of the wait asleep after the lock is already free. Queuing them here
    wakes the next writer as soon as the previous transaction ends. Other
    processes still meet SQLite's own busy handling.

    Acquisition is reentrant for the owning thread, since a nested connection
    on that thread would otherwise wait on itself; SQLite then reports the
    conflict exactly as before. Release does not check the thread, because a
    connection may finish its transaction on another thread.
    """

    __slots__ = ("_cond", "_owner", "_depth")

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._owner: int | None = None
        self._depth = 0

    def acquire(self, timeout: float) -> bool:
        me = threading.get_ident()
        with self._cond:
            if self._owner == me:
                self._depth += 1
                return True
            if self._owner is not None:
                if timeout <= 0 or not self._cond.wait_for(lambda: self._owner is None, timeout):
                    return False
            self._owner, self._depth = me, 1
            return True

    def release(self) -> None:
        with self._cond:
            self._depth -= 1
            if self._depth <= 0:
                self._owner, self._depth = None, 0
                self._cond.notify()


_WRITER_GATES: dict[str, _WriterGate] = {}
_WRITER_GATES_LOCK = threading.Lock()
_WRITER_STATS = {"waits": 0, "wait_ms": 0.0, "timeouts": 0}
_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")
_CTE_WRITE = re.compile(r"\b(?:INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)


def _writer_gate(database: object) -> _WriterGate | None:
    name = os.fspath(database) if isinstance(database, (str, os.PathLike)) else None
    if not name or name == ":memory:" or name.startswith("file:"):
        return None
    key = os.path.abspath(name)
    with _WRITER_GATES_LOCK:
        gate = _WRITER_GATES.get(key)
        if gate is None:
            gate = _WRITER_GATES[key] = _WriterGate()
        return gate


def _starts_write(sql: object) -> bool:
    if not isinstance(sql, str):
        return False
    text = sql.lstrip()
    while text.startswith("--"):
        text = text.partition("\n")[2].lstrip()
    head = text[:24].upper()
    if head.startswith("BEGIN"):
        return head[5:].lstrip().startswith(("IMMEDIATE", "EXCLUSIVE"))
    if head.startswith("WITH"):
        return _CTE_WRITE.search(text) is not None
    return head.startswith(_WRITE_PREFIXES)


class CoordinatedConnection(sqlite3.Connection):
    """A connection whose write transactions pass through the writer gate.

    The gate is taken before the statement that starts writing (``BEGIN
    IMMEDIATE`` or the first DML/DDL) and released once the connection has no
    open transaction. A gate wait is bounded by the connection's own timeout;
    after it, the statement proceeds and SQLite decides as before.
    """

    def __init__(self, database, *args, **kwargs):
        super().__init__(database, *args, **kwargs)
        timeout = kwargs.get("timeout", args[0] if args else 5.0)
        self._gate_timeout = max(0.0, float(timeout))
        self._gate = _writer_gate(database)
        self._gate_held = False

    def _take_gate(self, sql: object) -> None:
        if self._gate is None or self._gate_held or not _starts_write(sql):
            return
        started = time.perf_counter()
        if self._gate.acquire(self._gate_timeout):
            self._gate_held = True
        else:
            _WRITER_STATS["timeouts"] += 1
        waited = (time.perf_counter() - started) * 1000
        if waited >= 1:
            _WRITER_STATS["waits"] += 1
            _WRITER_STATS["wait_ms"] += waited

    def _settle_gate(self) -> None:
        if self._gate_held and not self.in_transaction:
            self._gate_held = False
            self._gate.release()

    def execute(self, sql, *args):
        self._take_gate(sql)
        try:
            return super().execute(sql, *args)
        finally:
            self._settle_gate()

    def executemany(self, sql, *args):
        self._take_gate(sql)
        try:
            return super().executemany(sql, *args)
        finally:
            self._settle_gate()

    def executescript(self, sql):
        self._take_gate("BEGIN IMMEDIATE")
        try:
            return super().executescript(sql)
        finally:
            self._settle_gate()

    def commit(self):
        try:
            return super().commit()
        finally:
            self._settle_gate()

    def rollback(self):
        try:
            return super().rollback()
        finally:
            self._settle_gate()

    def __exit__(self, *exc_info):
        try:
            return super().__exit__(*exc_info)
        finally:
            self._settle_gate()

    def close(self):
        try:
            return super().close()
        finally:
            if self._gate_held:
                self._gate_held = False
                self._gate.release()


def connect_coordinated(database, **kwargs) -> sqlite3.Connection:
    """``sqlite3.connect`` for database files written by several threads."""

    kwargs.setdefault("factory", CoordinatedConnection)
    return sqlite3.connect(database, **kwargs)


def writer_gate_snapshot() -> dict[str, float | int]:
    return {"waits": _WRITER_STATS["waits"], "wait_ms": round(_WRITER_STATS["wait_ms"], 1),
            "timeouts": _WRITER_STATS["timeouts"]}


class _ThreadConnections:
    """At most one idle reusable connection per thread, database file and policy.

    A new connection parses the whole schema, triggers included, before its
    first statement; a cold chart load opened thousands. Only a connection
    that its user closed outside any transaction comes back here, and the
    file it opened must still be the file at that path. ``close_idle``
    closes every idle connection at once, so file-level operations (and
    Windows deletes) are not blocked by a handle parked on another thread.
    """

    _MAX_IDLE = 256

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._idle: dict[tuple, tuple[tuple[int, int], "PooledConnection"]] = {}

    def take(self, key: tuple, identity: tuple[int, int] | None) -> "PooledConnection | None":
        with self._lock:
            held = self._idle.pop((threading.get_ident(), key), None)
        if held is None:
            return None
        if identity is None or held[0] != identity:
            held[1]._discard()
            return None
        return held[1]

    def give(self, connection: "PooledConnection") -> bool:
        slot = (threading.get_ident(), connection._pool_key)
        with self._lock:
            if slot in self._idle or connection._pool_identity is None or len(self._idle) >= self._MAX_IDLE:
                return False
            self._idle[slot] = (connection._pool_identity, connection)
        return True

    def close_idle(self) -> int:
        with self._lock:
            idle, self._idle = list(self._idle.values()), {}
        for _, connection in idle:
            connection._discard()
        return len(idle)


_THREAD_CONNECTIONS = _ThreadConnections()


def _file_identity(path: Path) -> tuple[int, int] | None:
    try:
        status = os.stat(path)
    except OSError:
        return None
    return status.st_dev, status.st_ino


class PooledConnection(CoordinatedConnection):
    """A coordinated connection that ``close`` returns to its thread's slot.

    Returning is equivalent to closing for its user: every cursor it created
    is closed, so no unfinished statement can keep an old snapshot, and
    per-use handlers are cleared. Anything left in a transaction is really
    closed, which rolls it back as before.
    """

    def __init__(self, database, *args, **kwargs):
        super().__init__(database, *args, **kwargs)
        self._pool_key: tuple | None = None
        self._pool_identity: tuple[int, int] | None = None
        self._cursors: list = []

    def _track(self, cursor):
        if len(self._cursors) >= 64:
            self._cursors = [ref for ref in self._cursors if ref() is not None]
        self._cursors.append(weakref.ref(cursor))
        return cursor

    def cursor(self, *args, **kwargs):
        return self._track(super().cursor(*args, **kwargs))

    def execute(self, sql, *args):
        return self._track(super().execute(sql, *args))

    def executemany(self, sql, *args):
        return self._track(super().executemany(sql, *args))

    def _discard(self) -> None:
        self._pool_key = None
        super().close()

    def close(self):
        key = self._pool_key
        if key is None or self.in_transaction:
            return self._discard()
        try:
            for ref in self._cursors:
                cursor = ref()
                if cursor is not None:
                    cursor.close()
            self._cursors.clear()
            self.set_progress_handler(None, 0)
            self.set_authorizer(None)
            self.set_trace_callback(None)
            self.execute("PRAGMA query_only=OFF;")
            self._cursors.clear()
        except sqlite3.Error:
            return self._discard()
        if self.in_transaction or not _THREAD_CONNECTIONS.give(self):
            return self._discard()
        return None


def close_idle_connections() -> int:
    """Close idle reusable connections, for shutdown and file-level operations."""

    return _THREAD_CONNECTIONS.close_idle()


def open_sqlite(
    db_path: Path | str,
    *,
    policy: SQLiteConnectionPolicy = DEFAULT_SQLITE_POLICY,
    logger: logging.Logger | None = None,
    reuse: bool = False,
) -> sqlite3.Connection:
    """Open one repository connection under the shared DataEngine policy.

    With ``reuse``, ``close`` hands the connection back for the next open of
    the same file and policy on this thread instead of closing it.
    """

    path = Path(db_path)
    identity = key = None
    if reuse:
        identity = _file_identity(path)
        key = (os.path.abspath(path), policy)
        reused = _THREAD_CONNECTIONS.take(key, identity)
        if reused is not None:
            reused._pool_key = key
            reused.row_factory = sqlite3.Row if policy.use_row_factory else None
            reused.text_factory = str
            reused.isolation_level = ""
            return reused
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_coordinated(
        str(path),
        timeout=float(policy.timeout_seconds),
        check_same_thread=policy.check_same_thread,
        factory=PooledConnection if reuse else CoordinatedConnection,
    )
    if reuse:
        connection._pool_key = key
        connection._pool_identity = identity or _file_identity(path)
    if policy.use_row_factory:
        connection.row_factory = sqlite3.Row
    if policy.busy_timeout_ms is not None:
        connection.execute(f"PRAGMA busy_timeout={int(policy.busy_timeout_ms)};")
    if policy.configure_journal_mode:
        try:
            connection.execute(f"PRAGMA journal_mode={policy.journal_mode};")
        except sqlite3.OperationalError as exc:
            if logger is not None:
                logger.warning(
                    "SQLite %s mode unavailable for %s, falling back to %s: %s",
                    policy.journal_mode,
                    path,
                    policy.fallback_journal_mode,
                    exc,
                )
            connection.execute(
                f"PRAGMA journal_mode={policy.fallback_journal_mode};",
            )
    connection.execute(f"PRAGMA synchronous={policy.synchronous};")
    return connection


class ReusableReads:
    """Keep one idle read-only connection per thread for self-contained reads.

    A new connection parses the entire schema before its first statement, which
    costs far more than a small indexed read. Callers that open, read and
    return inside one ``with`` block can borrow a connection instead.

    Rules that keep a borrowed connection equivalent to a new one:

    * It is exclusively held. A nested read on the same thread opens its own.
    * It returns to the idle slot only if the block finished normally and left
      no transaction open; otherwise it is closed. Callers must consume their
      results inside the block: an unfinished cursor would pin an old snapshot.
    * It is bound to the database file it opened. A different path, or a
      different file at the same path, opens a new connection.
    * It is ``query_only``. An idle connection holds no lock and no snapshot,
      so it never delays a writer or a checkpoint.

    ``close_idle`` releases every idle connection, for shutdown and before a
    file-level operation; connections borrowed at that moment are closed when
    they return.
    """

    _MAX_IDLE = 64

    def __init__(
        self,
        open_connection: Callable[[], sqlite3.Connection],
        database_path: Callable[[], Path | str],
    ) -> None:
        self._open = open_connection
        self._path = database_path
        self._lock = threading.Lock()
        self._idle: dict[int, tuple[tuple[int, int], sqlite3.Connection]] = {}
        self._generation = 0

    def _file_identity(self) -> tuple[int, int] | None:
        try:
            status = os.stat(self._path())
        except OSError:
            return None
        return status.st_dev, status.st_ino

    @contextmanager
    def reading(self, *, rows: bool = True) -> Iterator[sqlite3.Connection]:
        """Borrow a connection for one read; ``rows`` selects ``sqlite3.Row``."""

        identity = self._file_identity()
        thread = threading.get_ident()
        with self._lock:
            generation = self._generation
            held = self._idle.pop(thread, None)
        if held is not None and held[0] != identity:
            held[1].close()
            held = None
        if held is None:
            connection = self._open()
            connection.execute("PRAGMA query_only=ON;")
        else:
            connection = held[1]
        connection.row_factory = sqlite3.Row if rows else None
        try:
            yield connection
        except BaseException:
            connection.close()
            raise
        keep = identity is not None and not connection.in_transaction
        if keep:
            with self._lock:
                keep = (
                    generation == self._generation
                    and thread not in self._idle
                    and len(self._idle) < self._MAX_IDLE
                )
                if keep:
                    self._idle[thread] = (identity, connection)
        if not keep:
            connection.close()

    def close_idle(self) -> int:
        """Close every idle connection; return how many were closed."""

        with self._lock:
            self._generation += 1
            idle, self._idle = list(self._idle.values()), {}
        for _, connection in idle:
            connection.close()
        return len(idle)


__all__ = ["CoordinatedConnection", "DEFAULT_SQLITE_POLICY", "PooledConnection", "ReusableReads",
           "SQLiteConnectionPolicy", "close_idle_connections", "connect_coordinated", "open_sqlite",
           "writer_gate_snapshot"]
