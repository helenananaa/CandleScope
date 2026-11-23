"""Keep one copy of a SQLite database before its schema version moves forward.

An older release cannot open a database that a newer release migrated, and an
older release cannot be changed after it ships. Before a startup migration
raises a file's schema version, the store calls :func:`keep_pre_migration_copy`
so a downgrade can be recovered by restoring the copy.

The copy sits next to the database as
``<name>.pre-<schema>-v<from>-to-v<to>.sqlite``, the same ``<name>.pre-*``
family as ``candlescope.db.pre-basis-v1-<id>.sqlite``. Like that copy it is
kept until the user removes it: the app never deletes or rewrites it. There is
at most one copy per database, schema and from→to step, so a retried or
repeated start does not add another one.
"""

from __future__ import annotations

from contextlib import closing
import logging
import os
from pathlib import Path
import sqlite3
import uuid

logger = logging.getLogger(__name__)


class PreMigrationCopyError(RuntimeError):
    """The pre-migration copy could not be written; the migration must not run."""


def pre_migration_copy_path(database: Path, *, schema: str, from_version: int, to_version: int) -> Path:
    return database.with_name(f"{database.name}.pre-{schema}-v{int(from_version)}-to-v{int(to_version)}.sqlite")


def keep_pre_migration_copy(
    connection: sqlite3.Connection,
    *,
    schema: str,
    from_version: int,
    to_version: int,
) -> Path | None:
    """Copy the committed database behind ``connection`` before it is migrated.

    Call it inside the migration's write transaction (or before the first
    schema change when the store migrates in autocommit), before anything is
    changed: the copy is read through a separate read-only connection with
    SQLite's backup API in one step, so it is the committed database as one
    consistent snapshot while the caller's write lock keeps other writers out.

    Returns the copy's path, or ``None`` for an in-memory or temporary
    database. An existing copy for the same step is kept as it is. Raises
    :class:`PreMigrationCopyError` when no verified copy could be written; the
    caller lets it abort the migration so the database stays unchanged.
    """

    if int(from_version) >= int(to_version):
        raise ValueError("a pre-migration copy needs a forward schema step")
    database = _main_database_file(connection)
    if database is None:
        return None
    target = pre_migration_copy_path(database, schema=schema, from_version=from_version, to_version=to_version)
    if target.exists():
        return target
    partial = target.with_name(f"{target.name}.{uuid.uuid4().hex}.partial")
    try:
        # Our own unfinished copies from an interrupted start. They are never
        # the user's data, and only ever stand next to a copy not yet written.
        for stale in target.parent.glob(f"{_glob_escape(target.name)}.*.partial*"):
            stale.unlink(missing_ok=True)
        with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=5)) as source:
            with closing(sqlite3.connect(partial, isolation_level=None)) as copy:
                # pages=-1 copies every page in one step, under one read
                # transaction. CPython retries BUSY/LOCKED forever, so give up
                # after the source's busy timeout instead of hanging startup.
                source.backup(copy, progress=_fail_when_blocked)
                # A copy of a WAL database inherits WAL mode. Make it one
                # self-contained file that can be renamed back into place.
                copy.execute("PRAGMA journal_mode=DELETE")
                if copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise PreMigrationCopyError(f"pre-migration copy of {database.name} failed verification")
        _fsync(partial)
        os.replace(partial, target)
        _fsync_directory(target.parent)
    except PreMigrationCopyError:
        _discard(partial)
        raise
    except (OSError, sqlite3.Error) as exc:
        _discard(partial)
        raise PreMigrationCopyError(
            f"could not keep a pre-migration copy of {database.name} before {schema} "
            f"v{from_version}->v{to_version}: {exc}; the database was not changed"
        ) from exc
    logger.warning(
        "Kept %s before migrating %s %s schema v%s -> v%s; restore it to reopen this data with an older release",
        target.name, database.name, schema, from_version, to_version,
    )
    return target


def _main_database_file(connection: sqlite3.Connection) -> Path | None:
    for _, name, file in connection.execute("PRAGMA database_list").fetchall():
        if name == "main":
            if not file:
                return None
            path = Path(file)
            return path if path.is_file() else None
    return None


def _fail_when_blocked(status: int, _remaining: int, _total: int) -> None:
    if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        raise sqlite3.OperationalError("database is locked")


def _glob_escape(value: str) -> str:
    return "".join(f"[{char}]" if char in "*?[" else char for char in value)


def _discard(partial: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            Path(f"{partial}{suffix}").unlink(missing_ok=True)
        except OSError:
            pass


def _fsync(path: Path) -> None:
    # Windows only flushes a handle opened for writing.
    descriptor = os.open(path, os.O_RDWR)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["PreMigrationCopyError", "keep_pre_migration_copy", "pre_migration_copy_path"]
