"""Ownership records that survive a moved, copied or restored data folder.

Several derived stores live beside the database that owns them and record that
database in an ownership marker. The marker used to hold only the database's
absolute path, so a profile restored to another path (a new Mac with another
user name, a copied folder) was treated as foreign and the backend refused to
start. A marker now carries the database's own identity, a random id stored
inside the database, and the absolute path only as the last known location.

``check_owner`` decides whether a marker belongs to a database:

* Both sides have an identity: the identities must match. A marker for the
  same path also passes, as it always did: the database file there was
  replaced, and only one database can sit at one path.
* Either side predates identities: the marker must name this path, or a path
  that ends the way this database's path ends, seen from the marker's
  directory. Moving or copying the whole folder keeps that shape. A marker
  naming another database in the same folder, or another layout, does not.

Everything else is a real mismatch and the caller refuses it, as before.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from uuid import uuid4


@dataclass(frozen=True)
class OwnerCheck:
    owned: bool
    #: The marker named another location of this database: the folder moved.
    relocated: bool = False
    #: The location the marker recorded, when it differs from the current one.
    previous: Path | None = None


def new_identity() -> str:
    return uuid4().hex


def valid_identity(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 32
            and all(char in "0123456789abcdef" for char in value))


def _tail(database: Path, directory: Path) -> tuple[str, ...]:
    relative = PurePath(os.path.relpath(database, directory)).parts
    index = 0
    while index < len(relative) and relative[index] == os.pardir:
        index += 1
    return tuple(relative[index:])


def same_shape(recorded: Path, database: Path, directory: Path) -> bool:
    """The recorded path is this database's path with an earlier root."""
    tail = _tail(database, directory)
    parts = recorded.parts
    return bool(tail) and len(parts) > len(tail) and tuple(parts[-len(tail):]) == tail


def check_owner(recorded_path: object, recorded_id: object, *, database: Path,
                database_id: str | None, directory: Path) -> OwnerCheck:
    if not isinstance(recorded_path, str) or "\0" in recorded_path:
        return OwnerCheck(False)
    recorded = Path(recorded_path)
    if not recorded.is_absolute():
        return OwnerCheck(False)
    if recorded_id is not None and not valid_identity(recorded_id):
        return OwnerCheck(False)
    same_place = recorded_path == str(database)
    if recorded_id is not None and database_id is not None:
        owned = recorded_id == database_id or same_place
    else:
        owned = same_place or same_shape(recorded, database, directory)
    if not owned:
        return OwnerCheck(False)
    return OwnerCheck(True, relocated=not same_place, previous=None if same_place else recorded)


def check_marker(actual: object, fields: dict[str, object], *, database: Path,
                 database_id: str | None, directory: Path) -> OwnerCheck:
    """A JSON owner marker: exactly ``fields``, plus the database's location and optional id."""
    if not isinstance(actual, dict):
        return OwnerCheck(False)
    if set(actual) - set(fields) - {"database", "database_id"}:
        return OwnerCheck(False)
    if any(key not in actual or actual[key] != value for key, value in fields.items()):
        return OwnerCheck(False)
    return check_owner(actual.get("database"), actual.get("database_id"), database=database,
                       database_id=database_id, directory=directory)


_NAMESPACE_FILE = ".secret-namespace.json"
_NAMESPACE_SCHEMA = "candlescope.secret-namespace/1"


def _read_namespace(path: Path) -> tuple[str, str] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(payload, dict) or payload.get("schema") != _NAMESPACE_SCHEMA
            or not all(isinstance(payload.get(key), str) and Path(payload[key]).is_absolute()
                       for key in ("origin", "directory"))):
        return None
    return payload["origin"], payload["directory"]


def secret_namespace_origin(directory: Path) -> str:
    """The path whose hash names this folder's secrets in the OS secret store.

    Earlier versions hashed the folder's current path, so secrets were lost
    when the folder moved. The first path is now saved in the folder and kept
    when it moves. A copy whose original folder still holds the same origin is
    another live profile: it starts its own namespace, as before, so two
    profiles never share or delete each other's secrets.
    """
    directory = directory.resolve()
    current = str(directory)
    marker = directory / _NAMESPACE_FILE
    saved = _read_namespace(marker)
    if saved is not None:
        origin, recorded = saved
        if recorded == current:
            return origin
        original = _read_namespace(Path(recorded) / _NAMESPACE_FILE)
        if original is None or original[0] != origin:
            _write_namespace(marker, origin, current)
            return origin
    elif marker.exists() or marker.is_symlink():
        return current  # Unreadable: keep the path-derived namespace, change nothing.
    if directory.is_dir():
        _write_namespace(marker, current, current)
    return current


def _write_namespace(marker: Path, origin: str, directory: str) -> None:
    import tempfile
    try:
        descriptor, name = tempfile.mkstemp(prefix=".secret-namespace-", dir=marker.parent)
    except OSError:
        return
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump({"schema": _NAMESPACE_SCHEMA, "origin": origin, "directory": directory}, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(marker)
    except OSError:
        pass
    finally:
        temporary.unlink(missing_ok=True)


def relocation_prefixes(previous: Path, current: Path) -> tuple[Path, Path] | None:
    """The folder that moved: strip the path components both locations share at the end."""
    old, new = previous.parts, current.parts
    shared = 0
    while shared < min(len(old), len(new)) - 1 and old[-1 - shared] == new[-1 - shared]:
        shared += 1
    if not shared:
        return None
    old_root, new_root = Path(*old[:len(old) - shared]), Path(*new[:len(new) - shared])
    if old_root == new_root or len(old_root.parts) < 2:
        return None
    return old_root, new_root


def rebase(path: str, old_root: Path, new_root: Path) -> str | None:
    """Map a path recorded under the old root to the same place under the new root."""
    root = str(old_root)
    if path == root:
        return str(new_root)
    prefix = root.rstrip(os.sep) + os.sep
    if not path.startswith(prefix):
        return None
    return str(new_root / path[len(prefix):])
