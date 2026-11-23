"""Read preserved extension records and explicitly repackage appearance data."""

from __future__ import annotations

import tempfile
from pathlib import Path

from candlescope_plugin_sdk.platform_v2 import canonical_dumps

from app.trusted_extensions.store import ExtensionStore

from .appearance import APPEARANCE_KINDS
from .bundle import build_package
from .store import LifecycleError


def legacy_extensions(store):
    legacy = ExtensionStore(store.root.parent)
    legacy._check_links(legacy.state_path)
    if not legacy.state_path.exists():
        return []
    catalog = legacy.catalog()
    return [
        {
            "id": item["manifest"]["id"],
            "name": item["manifest"]["name"],
            "version": item["manifest"].get("version"),
            "digest": item["digest"],
            "enabled": item["enabled"],
            "error": item["error"],
            "appearanceOnly": not item["error"] and not item["manifest"].get("entries"),
        }
        for item in catalog["plugins"]
    ]


def stage_legacy_appearance(store, digest):
    legacy = ExtensionStore(store.root.parent)
    manifest, _ = legacy.package(digest)
    if manifest.get("entries"):
        raise LifecycleError("Executable extensions require an updated unified package")
    contributions = {
        kind: manifest[kind]
        for kind in APPEARANCE_KINDS
        if manifest.get(kind) is not None
    }
    with tempfile.TemporaryDirectory(prefix="candlescope-appearance-") as temporary:
        root = Path(temporary)
        source = root / "package"
        source.mkdir()
        entries = []
        for kind, value in contributions.items():
            name = f"{kind}.json"
            (source / name).write_text(
                canonical_dumps({"schema": f"candlescope.{kind}/1", **value}),
                encoding="utf-8",
            )
            entries.append({"id": kind, "kind": "data", "path": name})
        (source / "manifest.json").write_text(
            canonical_dumps(
                {
                    "schema": "candlescope.unified-plugin/1",
                    "id": manifest["id"],
                    "name": manifest["name"],
                    "version": manifest["version"],
                    "hostApiVersion": 1,
                    "trust": "full-trust"
                    if "layout" in contributions
                    else "restricted",
                    "entries": entries,
                    "dependencies": manifest.get("dependencies", {}),
                }
            ),
            encoding="utf-8",
        )
        archive = root / "appearance.cspkg"
        build_package(source, archive)
        staged = store.stage(archive)
        return store.review(staged.sha256)
