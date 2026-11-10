"""Read-only retention preview and execution preflight for committed replay trade days."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections import Counter
from contextlib import AbstractContextManager, closing
from itertools import islice
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.executors import run_archive
from app.data_engine.storage.raw_trade_archive import RawAggTradeDatasetRef
from app.data_engine.storage.raw_trade_retention_lock import partition_lease
from app.replay.errors import ReplayDomainError
from app.replay.history_archive import _atomic_write_json
from app.replay.storage.sqlite_store import ReplaySQLiteStore

_MAX_REFERENCES = 2_000
_MAX_REFERENCED_OBJECTS = 32_768
_MAX_STORE_REGISTRATIONS = 16
_STORE_SCHEMA = "replay-trade-reference-store.v1"


def _registry(archive: object) -> Path | None:
    root = getattr(archive, "root", None)
    if isinstance(root, Path) and callable(getattr(archive, "verified_retention_inventory", None)):
        return root / ".replay-reference-stores"
    return None


def _store_key(database: Path, store_id: str) -> str:
    return hashlib.sha256(f"{store_id}\0{database}".encode()).hexdigest()


def _store_identity(connection: sqlite3.Connection) -> str | None:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='replay_trade_reference_store'",
    ).fetchone()
    if exists is None:
        return None
    row = connection.execute(
        "SELECT store_id FROM replay_trade_reference_store WHERE singleton=1",
    ).fetchone()
    return None if row is None else str(row[0])


def _ensure_store_identity(connection: sqlite3.Connection) -> str:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS replay_trade_reference_store "
        "(singleton INTEGER PRIMARY KEY CHECK (singleton=1), store_id TEXT NOT NULL)",
    )
    connection.execute(
        "INSERT OR IGNORE INTO replay_trade_reference_store VALUES (1, ?)", (uuid4().hex,),
    )
    store_id = _store_identity(connection)
    assert store_id is not None
    return store_id


def _register_store(directory: Path, database: Path, store_id: str) -> None:
    if directory.is_symlink():
        raise OSError("reference store registry is a symlink")
    path = directory / f"{_store_key(database, store_id)}.json"
    payload = {"schema": _STORE_SCHEMA, "store_id": store_id, "database": str(database)}
    try:
        if _read_registration(path) == (database, store_id):
            return
    except (OSError, ValueError):
        pass
    _atomic_write_json(path, payload)
    if os.name == "posix":
        for parent in (directory, directory.parent):
            descriptor = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _registry_lease(directory: Path, *, shared: bool) -> AbstractContextManager[None]:
    return partition_lease(
        directory.parent / ".trade-reference-store.lock", shared=shared, create=True,
        timeout_seconds=5 if shared else 0,
    )


def _register_store_with_lease(directory: Path, database: Path, store_id: str) -> None:
    with _registry_lease(directory, shared=True):
        _register_store(directory, database, store_id)


async def register_store(store: ReplaySQLiteStore, archive: object) -> None:
    directory = _registry(archive)
    if directory is None:
        return
    try:
        store_id = await store.run_extension_write(_ensure_store_identity)
        await run_archive(_register_store_with_lease, directory, store.path, store_id)
    except (OSError, ReplayDomainError, sqlite3.Error):
        # Legacy/read-only archives retain local playback; preview reports the
        # missing registration, and unmanaged data remains protected.
        return


def _read_registration(path: Path) -> tuple[Path, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid replay reference store registration")
    with path.open("rb") as handle:
        encoded = handle.read(8193)
    if len(encoded) > 8192:
        raise ValueError("replay reference store registration exceeds size limit")
    payload = json.loads(encoded)
    if not isinstance(payload, dict) or set(payload) != {"schema", "database", "store_id"}:
        raise ValueError("invalid replay reference store registration")
    store_id, location = payload["store_id"], payload["database"]
    if (
        payload["schema"] != _STORE_SCHEMA
        or not isinstance(store_id, str)
        or len(store_id) != 32
        or any(char not in "0123456789abcdef" for char in store_id)
        or not isinstance(location, str)
        or "\0" in location
    ):
        raise ValueError("invalid replay reference store identity")
    database = Path(location)
    if not database.is_absolute() or path.stem != _store_key(database, store_id):
        raise ValueError("invalid replay reference store location")
    return database, store_id


def _read_store_references(
    database: Path, store_id: str | None, *, max_references: int, max_objects: int,
) -> tuple[dict[str, int], bool, str | None]:
    if database.is_symlink() or not database.is_file():
        raise OSError("registered replay reference store is unavailable")
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=0.1)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("BEGIN")
        deadline = time.monotonic() + 0.25
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1_000)
        identity = _store_identity(connection)
        if store_id is not None and identity != store_id:
            raise ValueError("registered replay reference store identity changed")
        saved, complete = _saved_partitions(connection, max_references=max_references, max_objects=max_objects)
        return saved, complete, identity


def _registered_references(
    directory: Path, database: Path, local_id: str | None,
) -> tuple[dict[str, int], bool, int, int]:
    if directory.is_symlink():
        return {}, False, 0, 1
    try:
        paths = list(islice(directory.glob("*.json"), _MAX_STORE_REGISTRATIONS + 1))
    except OSError:
        return {}, False, 0, 1
    counts: Counter[str] = Counter()
    complete = len(paths) <= _MAX_STORE_REGISTRATIONS
    present_local = False
    scanned = unavailable = 0
    for path in sorted(paths[:_MAX_STORE_REGISTRATIONS]):
        try:
            registered, store_id = _read_registration(path)
            if registered == database:
                if store_id != local_id:
                    raise ValueError("registered local replay store identity changed")
                present_local = True
                continue
            refs, foreign_complete, _ = _read_store_references(
                registered, store_id, max_references=256, max_objects=4096,
            )
        except (OSError, OverflowError, sqlite3.Error, ValueError):
            unavailable += 1
            complete = False
            continue
        scanned += 1
        complete = complete and foreign_complete
        counts.update(refs)
    return dict(counts), complete and present_local, scanned, unavailable


def _saved_partitions(
    connection: sqlite3.Connection, *,
    max_references: int = _MAX_REFERENCES, max_objects: int = _MAX_REFERENCED_OBJECTS,
) -> tuple[dict[str, int], bool]:
    # Every saved trade session counts, including stopped sessions whose
    # in-memory pin was released. The lightweight ref owns the object list.
    rows = connection.execute(
        """
        SELECT CASE WHEN length(ref.snapshot_ref_json) <= 2097152
                    THEN ref.snapshot_ref_json END AS snapshot_ref_json,
               ref.data_epoch
        FROM replay_session AS session
        LEFT JOIN replay_dataset_ref AS ref USING (session_id)
        WHERE CASE
            WHEN (ref.snapshot_ref_json IS NOT NULL AND NOT json_valid(ref.snapshot_ref_json))
                 OR NOT json_valid(session.config_json)
                THEN 1
            ELSE lower(json_extract(session.config_json, '$.source_kind')) = 'agg_trade'
                 OR lower(json_extract(ref.snapshot_ref_json, '$.source_kind')) = 'agg_trade'
                 OR json_type(ref.snapshot_ref_json, '$.trade_dataset_ref') IS NOT NULL
        END
        ORDER BY session.session_id
        LIMIT ?
        """,
        (max_references + 1,),
    )
    counts: Counter[str] = Counter()
    complete = True
    objects_left = max_objects
    for index, row in enumerate(rows):
        if index == max_references:
            complete = False
            break
        try:
            envelope = json.loads(row["snapshot_ref_json"])
            reference = RawAggTradeDatasetRef.from_dict(envelope["trade_dataset_ref"])
            if reference.data_epoch != row["data_epoch"]:
                raise ValueError("saved trade dataset epoch differs from its reference")
        except (KeyError, OverflowError, TypeError, ValueError):
            complete = False
            continue
        if len(reference.objects) > objects_left:
            complete = False
            break
        objects_left -= len(reference.objects)
        counts.update({item.object_id.rsplit("/", 1)[0] for item in reference.objects})
    return dict(counts), complete


async def preview(
    store: ReplaySQLiteStore, archive: object, *, limit: int,
) -> dict[str, object]:
    inventory = getattr(archive, "verified_retention_inventory", None)
    result = {
        "protocol": "replay.raw-trade-retention.preview.v1",
        "policy_state": "UNMANAGED",
        "reference_scope": "REGISTERED_REPLAY_STORES_AND_ARCHIVE_LEASES",
        "estimated_reclaim_bytes": 0,
        "limit": limit,
    }
    if not callable(inventory):
        return {
            **result, "status": "UNAVAILABLE", "saved_reference_scan_complete": False,
            "observed_bytes": 0, "items": [], "unreadable_day_count": 0, "truncated": False,
            "saved_reference_store_count": 0, "unavailable_reference_store_count": 0,
        }
    # Sample active pins before reading saved references. A session that
    # publishes and releases its pin between these reads remains represented.
    report = await run_archive(inventory, limit=limit)
    saved, complete, local_id = await store.run_extension_read(
        lambda connection: (*_saved_partitions(connection), _store_identity(connection)),
    )
    directory = _registry(archive)
    scanned = unavailable = 0
    if directory is None:
        complete = False
    else:
        external, registered_complete, scanned, unavailable = await run_archive(
            _registered_references, directory, store.path, local_id,
        )
        saved = dict(Counter(saved) + Counter(external))
        complete = complete and registered_complete
    for item in report["items"]:
        _annotate_references(item, saved, complete)
    return {
        **result,
        **report,
        "status": "PREVIEW",
        "saved_reference_scan_complete": complete,
        "saved_reference_store_count": 1 + scanned,
        "unavailable_reference_store_count": unavailable,
        "observed_bytes": sum(item["byte_size"] for item in report["items"]),
    }


def _annotate_references(item: dict[str, Any], saved: dict[str, int], complete: bool) -> None:
    reference_count = saved.get(item.pop("partition_key"), 0)
    item["saved_reference_count"] = reference_count
    if reference_count:
        item["protection_reasons"].append("SAVED_REPLAY_REFERENCE")
    if not complete:
        item["protection_reasons"].append("SAVED_REFERENCE_SCAN_INCOMPLETE")


async def recheck(
    store: ReplaySQLiteStore, archive: object, *, day_id: str, limit: int,
) -> dict[str, object]:
    directory = _registry(archive)
    guard = getattr(archive, "verified_retention_recheck", None)
    result = {
        "protocol": "replay.raw-trade-retention.recheck.v1",
        "day_id": day_id,
        "policy_state": "UNMANAGED",
        "estimated_reclaim_bytes": 0,
        "saved_reference_scan_complete": False,
        "item": None,
    }
    if directory is None or not callable(guard):
        return {**result, "status": "UNAVAILABLE"}

    def inspect() -> dict[str, object]:
        # The partition lease excludes session creation until this scan returns.
        # Serialize registry publication as well, since an older profile can
        # register pre-existing saved references without pinning the day.
        with guard(day_id=day_id, limit=limit) as (status, item):
            if item is None:
                return {**result, "status": status}
            try:
                with _registry_lease(directory, shared=False):
                    saved, complete, local_id = _read_store_references(
                        store.path, None, max_references=_MAX_REFERENCES, max_objects=_MAX_REFERENCED_OBJECTS,
                    )
                    external, registered_complete, scanned, unavailable = _registered_references(
                        directory, store.path, local_id,
                    )
            except (OSError, OverflowError, sqlite3.Error, ValueError):
                return {**result, "status": "SAVED_REFERENCE_SCAN_UNAVAILABLE"}
            complete = complete and registered_complete
            _annotate_references(item, dict(Counter(saved) + Counter(external)), complete)
            return {
                **result, "status": status, "item": item, "saved_reference_scan_complete": complete,
                "saved_reference_store_count": 1 + scanned, "unavailable_reference_store_count": unavailable,
            }

    return await run_archive(inspect)
