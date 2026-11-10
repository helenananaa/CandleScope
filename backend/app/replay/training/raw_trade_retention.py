"""Retention inventory and reference fences for verified replay trade days."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, closing, contextmanager
from itertools import islice
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.executors import run_archive
from app.data_engine.storage.raw_trade_archive import (
    ParquetRawAggTradeArchive,
    RawAggTradeDatasetRef,
    VerifiedTradeReclaimResult,
    _sync_retention_directory,
)
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
    def collect():
        report = inventory(limit=limit)
        cache = _policy_archive(archive)
        for item in report["items"]:
            _annotate_policy(cache, item)
        return report

    report = await run_archive(collect)
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
        "policy_state": _policy_state(report["items"]),
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


def _scan_reference_stores(
    directory: Path, database: Path,
) -> tuple[dict[str, int], bool, int, int]:
    saved, complete, local_id = _read_store_references(
        database, None, max_references=_MAX_REFERENCES, max_objects=_MAX_REFERENCED_OBJECTS,
    )
    external, registered_complete, scanned, unavailable = _registered_references(
        directory, database, local_id,
    )
    return dict(Counter(saved) + Counter(external)), complete and registered_complete, scanned, unavailable


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
                    saved, complete, scanned, unavailable = _scan_reference_stores(directory, store.path)
            except (OSError, OverflowError, sqlite3.Error, ValueError):
                return {**result, "status": "SAVED_REFERENCE_SCAN_UNAVAILABLE"}
            _annotate_policy(_policy_archive(archive), item)
            _annotate_references(item, saved, complete)
            return {
                **result, "status": status, "item": item, "policy_state": _policy_state([item]),
                "saved_reference_scan_complete": complete,
                "saved_reference_store_count": 1 + scanned, "unavailable_reference_store_count": unavailable,
            }

    return await run_archive(inspect)


@contextmanager
def _reference_free(
    directory: Path, database: Path, partition: str,
) -> Iterator[bool]:
    with ExitStack() as leases:
        try:
            leases.enter_context(_registry_lease(directory, shared=False))
            saved, complete, _, _ = _scan_reference_stores(directory, database)
        except (OSError, OverflowError, sqlite3.Error, ValueError):
            yield False
            return
        yield complete and not saved.get(partition)


async def reclaim_retired_day(
    store: ReplaySQLiteStore, archive: ParquetRawAggTradeArchive, *,
    identity: tuple[str, str, str], day: str, day_id: str, max_files: int, max_bytes: int,
    policy: Callable[[str, str], AbstractContextManager[bool]],
) -> VerifiedTradeReclaimResult:
    """Recheck policy and saved references inside the reclaim operation's leases."""
    directory = _registry(archive)
    if directory is None:
        return VerifiedTradeReclaimResult("RETENTION_NOT_AUTHORIZED")

    @contextmanager
    def authorize(partition: str, receipt_id: str) -> Iterator[bool]:
        with policy(partition, receipt_id) as approved:
            if not approved:
                yield False
                return
            with _reference_free(directory, store.path, partition) as free:
                yield free

    return await run_archive(
        archive.reclaim_retired_verified_day,
        identity=identity, day=day, day_id=day_id, max_files=max_files,
        max_bytes=max_bytes, authorize=authorize,
    )


_POLICY_SCHEMA = "replay.raw-trade-retention.policy.v1"
_PLAN_SCHEMA = "replay.raw-trade-retention.plan.v1"
_PLAN_TTL_MS = 300_000
_MAX_PLAN_FILES = 8_192


def _policy_archive(archive: object) -> ParquetRawAggTradeArchive | None:
    cache = getattr(archive, "cache", archive)
    return cache if isinstance(cache, ParquetRawAggTradeArchive) else None


def _retention_record(path: Path, schema: str) -> dict[str, Any] | None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("unsafe retention metadata path")
    try:
        with path.open("rb") as handle:
            raw = handle.read(4097)
    except FileNotFoundError:
        return None
    if len(raw) > 4096:
        raise ValueError("retention record exceeds its metadata budget")
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("schema") != schema:
        raise ValueError("invalid retention record")
    return result


def _persist_retention_record(path: Path, record: dict[str, Any]) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("unsafe retention metadata path")
    _atomic_write_json(path, record)
    _sync_retention_directory(path.parent)
    _sync_retention_directory(path.parent.parent)


def _current_policy(archive: ParquetRawAggTradeArchive, key: str, day_id: str) -> dict[str, Any] | None:
    record = _retention_record(archive.retention_policy_path(key, plan=False), _POLICY_SCHEMA)
    if record is None:
        return None
    if (set(record) != {"schema", "day_id", "revision", "retain_until_ms"}
            or type(record["revision"]) is not int or record["revision"] < 1
            or (record["retain_until_ms"] is not None and (
                type(record["retain_until_ms"]) is not int or record["retain_until_ms"] < 0
            ))):
        raise ValueError("invalid retention policy")
    return record if record["day_id"] == day_id else None


def _annotate_policy(cache: ParquetRawAggTradeArchive | None, item: dict[str, Any]) -> None:
    if cache is None:
        return
    reasons = item["protection_reasons"]
    try:
        policy = _current_policy(cache, item["partition_key"], item["day_id"])
    except (OSError, ValueError):
        reasons.append("RETENTION_POLICY_UNAVAILABLE")
        return
    if policy is None:
        return
    item["retention_policy"] = policy
    reasons.remove("UNMANAGED_RETENTION_POLICY")
    cutoff = policy["retain_until_ms"]
    if cutoff is None or cutoff > _now_ms():
        reasons.append("POLICY_RETAINS_DAY")


def _policy_state(items: list[dict[str, Any]]) -> str:
    managed = sum("retention_policy" in item for item in items)
    if not managed:
        return "UNMANAGED"
    return "MANAGED" if managed == len(items) else "MIXED"


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


async def set_managed_policy(
    archive: object, *, identity: tuple[str, str, str], day: str, day_id: str,
    expected_revision: int, retain_until_ms: int | None,
) -> dict[str, object]:
    cache = _policy_archive(archive)
    if cache is None:
        return {"status": "UNAVAILABLE"}

    def save() -> dict[str, object]:
        with cache.retention_policy_candidate(identity=identity, day=day, day_id=day_id) as (status, item):
            if item is None:
                return {"status": status}
            key = item["partition_key"]
            try:
                previous = _current_policy(cache, key, day_id)
                revision = previous["revision"] if previous else 0
                if expected_revision != revision:
                    return {"status": "POLICY_CONFLICT", "policy": previous}
                policy = {"schema": _POLICY_SCHEMA, "day_id": day_id, "revision": revision + 1,
                          "retain_until_ms": retain_until_ms}
                _persist_retention_record(cache.retention_policy_path(key, plan=False), policy)
                cache.invalidate_retention_plan(key)
            except (OSError, ValueError):
                return {"status": "POLICY_UNAVAILABLE"}
            return {"status": "POLICY_SAVED", "policy": policy}

    return await run_archive(save)


async def plan_managed_retention(
    store: ReplaySQLiteStore, archive: object, *,
    identity: tuple[str, str, str], day: str, day_id: str, max_files: int, max_bytes: int,
) -> dict[str, object]:
    cache = _policy_archive(archive)
    directory = _registry(archive)
    if cache is None or directory is None:
        return {"status": "UNAVAILABLE"}

    def plan() -> dict[str, object]:
        with cache.retention_policy_candidate(identity=identity, day=day, day_id=day_id) as (status, item):
            if item is None:
                return {"status": status}
            key = item["partition_key"]
            try:
                policy = _current_policy(cache, key, day_id)
                if policy is None:
                    return {"status": "UNMANAGED"}
                now = _now_ms()
                cutoff = policy["retain_until_ms"]
                if cutoff is None or cutoff > now:
                    return {"status": "POLICY_RETAINS_DAY", "policy": policy}
                with _reference_free(directory, store.path, key) as free:
                    if not free:
                        return {"status": "SAVED_REFERENCES_PROTECTED"}
                    record = {"schema": _PLAN_SCHEMA, "day_id": day_id, "plan_id": uuid4().hex,
                              "revision": policy["revision"], "created_ms": now, "expires_ms": now + _PLAN_TTL_MS,
                              "max_files": max_files, "max_bytes": max_bytes}
                    _persist_retention_record(cache.retention_policy_path(key, plan=True), record)
            except (OSError, ValueError):
                return {"status": "POLICY_UNAVAILABLE"}
            return {"status": "PLANNED", "plan": record,
                    "candidate": {name: value for name, value in item.items() if name != "partition_key"}}

    return await run_archive(plan)


async def execute_managed_retention(
    store: ReplaySQLiteStore, archive: object, *,
    identity: tuple[str, str, str], day: str, day_id: str, plan_id: str, action: str,
) -> dict[str, object]:
    cache = _policy_archive(archive)
    directory = _registry(archive)
    if cache is None or directory is None:
        return {"status": "UNAVAILABLE"}
    # Budget lookup is provisional. Authorization repeats the read inside
    # the archive's day and partition leases before any mutation.
    key = cache.retention_partition_key(identity, day)
    path = cache.retention_policy_path(key, plan=True)
    try:
        plan = await run_archive(_retention_record, path, _PLAN_SCHEMA)
    except (OSError, ValueError):
        return {"status": "POLICY_UNAVAILABLE"}
    if plan is None or plan.get("plan_id") != plan_id or plan.get("day_id") != day_id:
        return {"status": "STALE_PLAN"}
    max_files, max_bytes = plan.get("max_files"), plan.get("max_bytes")
    if type(max_files) is not int or not 1 <= max_files <= _MAX_PLAN_FILES or type(max_bytes) is not int or max_bytes < 1:
        return {"status": "POLICY_UNAVAILABLE"}

    @contextmanager
    def policy(partition: str, receipt_id: str) -> Iterator[bool]:
        try:
            current = _current_policy(cache, partition, receipt_id)
            now = _now_ms()
            valid = (
                partition == key and receipt_id == day_id and current is not None
                and type(plan.get("revision")) is int and current["revision"] == plan["revision"]
                and current["retain_until_ms"] is not None and current["retain_until_ms"] <= now
                and type(plan.get("created_ms")) is int and type(plan.get("expires_ms")) is int
                and plan["created_ms"] <= now < plan["expires_ms"]
                and _retention_record(path, _PLAN_SCHEMA) == plan
            )
        except (OSError, ValueError):
            valid = False
        yield valid

    if action == "RECLAIM":
        result = await reclaim_retired_day(
            store, cache, identity=identity, day=day, day_id=day_id,
            max_files=max_files, max_bytes=max_bytes, policy=policy,
        )
        return {"status": result.status, "removed_files": result.removed_files,
                "removed_logical_bytes": result.removed_logical_bytes, "remaining_files": result.remaining_files}
    if action != "RETIRE":
        raise ValueError("unsupported retention action")

    @contextmanager
    def authorize(partition: str, receipt_id: str) -> Iterator[bool]:
        with policy(partition, receipt_id) as approved:
            if not approved:
                yield False
                return
            with _reference_free(directory, store.path, partition) as free:
                yield free

    status = await run_archive(
        cache.move_verified_retention_day, identity=identity, day=day, day_id=day_id,
        restore=False, authorize=authorize,
    )
    return {"status": status}
