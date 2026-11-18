"""Prepare signed market fixtures and one preserved installation in a fresh directory."""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.plugin_core_v2.private_storage import StorageNamespace
from app.plugin_core_v2.runtime import CorePluginPlatform
from app.plugin_lifecycle.bundle import BUNDLE_SCHEMA, build_package
from app.plugin_marketplace_v2 import encode_base64url
from app.plugin_security_v2.storage import atomic_write_json
from tests.plugin_marketplace_testkit import (
    PUBLISHER_ID,
    SOURCE_ORIGIN,
    SignedMarketplaceBuilder,
    build_marketplace_bundle,
)

THEME_ID = "qa.marketplace-theme"


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def add_theme(root, builder, plugin_id, version, color, published, *, broken=False):
    source = root / "source" / plugin_id / version
    (source / "sbom").mkdir(parents=True)
    entries = [{"id": "theme", "kind": "data", "path": "theme.json"}]
    if broken:
        entries.append({"id": "extra", "kind": "data", "path": "extra.json"})
        (source / "extra.json").write_text("{", encoding="utf-8")
    atomic_write_json(
        source / "manifest.json",
        {
            "schema": "candlescope.unified-plugin/1",
            "id": plugin_id,
            "version": version,
            "name": "Marketplace QA Theme",
            "trust": "restricted",
            "hostApiVersion": 1,
            "entries": entries,
        },
    )
    atomic_write_json(
        source / "theme.json",
        {
            "schema": "candlescope.theme/1",
            "base": "light",
            "tokens": {"bg-primary": color},
        },
    )
    atomic_write_json(
        source / "sbom/cyclonedx.json",
        {
            "bomFormat": "CycloneDX",
            "metadata": {
                "component": {
                    "name": plugin_id,
                    "version": version,
                    "licenses": [{"expression": "MIT"}],
                }
            },
            "components": [],
        },
    )
    output = root / "artifacts" / f"{plugin_id}-{version}.cspkg"
    package = build_package(source, output)
    builder.add_release_statement(
        {
            "pluginId": plugin_id,
            "version": version,
            "publisherId": PUBLISHER_ID,
            "artifact": {
                "packageFormat": BUNDLE_SCHEMA,
                "fileName": output.name,
                "url": f"{SOURCE_ORIGIN}/artifacts/{output.name}",
                "size": package.size,
                "sha256": package.sha256,
                "manifestSha256": digest((source / "manifest.json").read_bytes()),
                "sbomSha256": digest((source / "sbom/cyclonedx.json").read_bytes()),
            },
            "publishedAt": published.isoformat().replace("+00:00", "Z"),
            "licenseExpression": "MIT",
            "dependencies": [],
            "sha256Sums": f"{package.sha256.removeprefix('sha256:')}  {output.name}\n",
        }
    )
    return {
        "id": plugin_id,
        "version": version,
        "sha256": package.sha256,
        "file": output.name,
        "color": color,
    }


def main(root: Path) -> None:
    root = root.resolve()
    (root / "artifacts").mkdir(parents=True)
    # Fresh application storage and ephemeral signing keys for this QA session.
    profile = root / "profile"
    profile.mkdir()
    builder = SignedMarketplaceBuilder.create()
    current = datetime.now(UTC).replace(microsecond=0)
    old = build_marketplace_bundle(root / "legacy").bundle
    builder.add_release(old)
    legacy_id = old.manifest.plugin.id
    initial = add_theme(root, builder, THEME_ID, "1.0.0", "#ece5d2", current)
    upgrade = add_theme(root, builder, THEME_ID, "1.1.0", "#dcefe4", current)
    successor = add_theme(root, builder, legacy_id, "0.2.0", "#dfe7f8", current)
    failed = add_theme(
        root, builder, THEME_ID, "1.2.0", "#f7d6e2", current, broken=True
    )
    atomic_write_json(
        root / "roots.json",
        {
            "schemaVersion": 1,
            "marketplaces": [
                {
                    **builder.root.to_public_wire(),
                    "publicKey": encode_base64url(builder.root.public_key),
                }
            ],
        },
    )
    previous = None
    for sequence, length in enumerate((2, 4, 5), 1):
        index = builder.index_bytes(
            sequence=sequence,
            previous_index_sha256=previous,
            generated_at=current,
            expires_at=current + timedelta(days=2),
            releases=builder.releases[:length],
        )
        (root / f"index-{sequence}.json").write_bytes(index)
        previous = digest(index)
    platform = CorePluginPlatform(
        root=profile / "plugins",
        host_name="CandleScope",
        host_version="0.4.0",
        marketplace_enabled=True,
        marketplace_roots=(builder.root,),
    )
    # This seeds the disk installation and its signed authorization evidence.
    # The macOS product applies its normal sandbox execution gate on launch.
    platform.installer.install(old.path, expected_sha256=old.sha256, enabled=True)
    publisher_identity = f"publisher-key:{builder.publisher['keyId']}"
    platform.grant_store.reconcile(
        old.manifest,
        bundle_sha256=old.sha256,
        manifest_sha256=old.manifest_sha256,
        publisher_identity=publisher_identity,
    )
    platform.marketplace.import_index(
        (root / "index-1.json").read_bytes(), marketplace_id=builder.root.marketplace_id
    )
    namespace = StorageNamespace(legacy_id, publisher_identity)
    platform.private_storage.kv_put(namespace, "bookmark", {"row": 7})
    platform.private_storage.kv_put(
        StorageNamespace(legacy_id, "qa.other"), "unshared", True
    )
    atomic_write_json(
        platform.settings.path,
        {
            "schemaVersion": 1,
            "revision": 1,
            "records": [
                {
                    "pluginId": legacy_id,
                    "publisherIdentityHash": digest(publisher_identity.encode())[7:],
                    "contributionId": "preferences",
                    "schemaSha256": digest(b"qa-preferences"),
                    "value": {"density": "compact"},
                    "updatedAt": current.isoformat(),
                }
            ],
        },
    )
    sandbox = (
        platform.root
        / "sandbox-v2"
        / "private"
        / platform._sandbox_key(old, publisher_identity)
    )
    sandbox.mkdir(parents=True)
    (sandbox / "state.bin").write_bytes(b"original sandbox data\n")
    relative_sources = [
        platform.installer.registry_path,
        platform.grant_store.path,
        platform.settings.path,
        platform.private_storage.root
        / namespace.publisher_key
        / legacy_id
        / "storage-v1.sqlite",
        sandbox / "state.bin",
    ]
    atomic_write_json(
        root / "fixtures.json",
        {
            "marketplaceId": builder.root.marketplace_id,
            "legacy": {
                "id": legacy_id,
                "version": old.manifest.plugin.version,
                "sha256": old.sha256,
            },
            "sources": {
                str(path.relative_to(profile)): digest(path.read_bytes())
                for path in relative_sources
            },
            "initial": initial,
            "upgrade": upgrade,
            "successor": successor,
            "failed": failed,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    main(parser.parse_args().directory)
