"""Export one signed predecessor's private state after its executors drain."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from candlescope_plugin_sdk.platform_v2 import canonical_dumps

from app.plugin_lifecycle.paths import is_link
from app.plugin_marketplace_v2 import MarketplaceError
from app.plugin_security_v2.storage import _fsync_directory, atomic_write_json

from .private_storage import SNAPSHOT_JSON_LIMITS, StorageNamespace

MAX_PRIVATE_FILES = 8192
MAX_PRIVATE_BYTES = 128 * 1024 * 1024


def _copy_private_files(source: Path, destination: Path) -> None:
    # The old sandbox can create junctions or special files. Treat its tree as
    # data, and copy only ordinary entries after revoking its process authority.
    for parent in (*reversed(source.parents), source):
        if is_link(parent):
            raise ValueError("legacy private storage contains a link")
    if not source.exists():
        return
    pending = [(source, destination, 0)]
    remaining = MAX_PRIVATE_BYTES
    count = 0
    while pending:
        current, target, depth = pending.pop()
        if depth > 32 or is_link(current) or not current.is_dir():
            raise ValueError("legacy private directory is unsafe")
        target.mkdir()
        with os.scandir(current) as entries:
            for entry in entries:
                count += 1
                if count > MAX_PRIVATE_FILES:
                    raise ValueError("legacy private storage contains too many entries")
                path = Path(entry.path)
                info = path.lstat()
                if is_link(path):
                    raise ValueError("legacy private storage contains a link")
                if stat.S_ISDIR(info.st_mode):
                    pending.append((path, target / path.name, depth + 1))
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError(
                        "legacy private storage contains a non-regular file"
                    )
                with (
                    path.open("rb") as original,
                    (target / path.name).open("xb") as copy,
                ):
                    if not os.path.samestat(info, os.fstat(original.fileno())):
                        raise ValueError("legacy private storage changed while copying")
                    while chunk := original.read(1024 * 1024):
                        remaining -= len(chunk)
                        if remaining < 0:
                            raise ValueError(
                                "legacy private storage exceeds the migration budget"
                            )
                        copy.write(chunk)
                    copy.flush()
                    os.fsync(copy.fileno())
        _fsync_directory(target)


def export_marketplace_data(platform, plugin_id: str, migration: dict) -> None:
    service = platform.marketplace
    record, publisher_identity = service.migration_source(plugin_id, migration)
    destination = service.unified.store.private_directory(
        plugin_id, migration_generation=migration["generation"]
    )
    sandbox_key = platform._sandbox_key_for_identity(
        plugin_id, record.version, publisher_identity
    )
    try:
        with tempfile.TemporaryDirectory(
            prefix=".export-", dir=destination
        ) as temporary:
            export = Path(temporary) / "platform-v2"
            export.mkdir()
            atomic_write_json(
                export / "settings.json",
                {
                    "schemaVersion": 1,
                    "records": platform.settings.export_for_migration(
                        plugin_id, publisher_identity
                    ),
                },
            )
            data = platform.private_storage.export_for_migration(
                StorageNamespace(plugin_id, publisher_identity)
            )
            if data is not None:
                with (export / "host-storage.json").open(
                    "x", encoding="utf-8"
                ) as snapshot:
                    snapshot.write(
                        canonical_dumps(data, limits=SNAPSHOT_JSON_LIMITS) + "\n"
                    )
                    snapshot.flush()
                    os.fsync(snapshot.fileno())
            _copy_private_files(
                platform.root / "sandbox-v2" / "private" / sandbox_key,
                export / "sandbox",
            )
            _fsync_directory(export)
            os.rename(export, destination / "platform-v2")
            _fsync_directory(destination)
    except (OSError, ValueError) as exc:
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_MIGRATION_DATA_FAILED", str(exc)
        ) from exc
