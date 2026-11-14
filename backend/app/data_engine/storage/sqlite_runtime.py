"""Shared SQLite connection policy for DataEngine-owned repositories."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
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


def open_sqlite(
    db_path: Path | str,
    *,
    policy: SQLiteConnectionPolicy = DEFAULT_SQLITE_POLICY,
    logger: logging.Logger | None = None,
) -> sqlite3.Connection:
    """Open one repository connection under the shared DataEngine policy."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(path),
        timeout=float(policy.timeout_seconds),
        check_same_thread=policy.check_same_thread,
    )
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


__all__ = ["DEFAULT_SQLITE_POLICY", "ReusableReads", "SQLiteConnectionPolicy", "open_sqlite"]
