#!/usr/bin/env python3
"""Validate Pine release assets and prepare a fail-closed CandleScope lock.

This command never builds or uploads a runtime.  It consumes the exact
``manifest.json`` and wheel assets produced by the upstream release workflow,
checks their identities locally, and only writes the managed lock when
``--write`` is explicit.  The generated lock opts into the Pine v2 host probe,
which exercises the native realtime-session ABI after installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from copy import deepcopy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__:
    from .managed_plugin_installer import (
        InstallerError,
        load_plugin_lock,
        validate_release_manifest,
    )
else:
    from managed_plugin_installer import (
        InstallerError,
        load_plugin_lock,
        validate_release_manifest,
    )


EXPECTED_RENDER_METADATA_VERSION = 1
EXPECTED_REALTIME_SESSION_SCHEMA_VERSION = 1
EXPECTED_WHEEL_TAGS = {
    ("cp310", "abi3", "win_amd64"),
    (
        "cp310",
        "abi3",
        "manylinux_2_17_x86_64.manylinux2014_x86_64",
    ),
}
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class ReleasePreparationError(RuntimeError):
    """Release evidence is incomplete or inconsistent."""


def _default_lock_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "pine-compat-runtime"
        / "CANDLESCOPE_RUNTIME.json"
    )


def _read_object(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleasePreparationError(f"unable to read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleasePreparationError(f"{label} must be a JSON object")
    return raw, value


def _required_string(value: Mapping[str, Any], key: str, label: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ReleasePreparationError(f"{label}.{key} must be a non-empty string")
    return result.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReleasePreparationError(f"unable to hash release asset {path}: {exc}") from exc
    return digest.hexdigest()


def _version_tuple(value: str, label: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ReleasePreparationError(f"{label} must use stable X.Y.Z form")
    return tuple(int(part) for part in match.groups())


def _normalized_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _wheel_metadata(path: Path) -> Mapping[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_members = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            wheel_members = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/WHEEL")
            ]
            if len(metadata_members) != 1:
                raise ReleasePreparationError(
                    f"{path.name}: expected exactly one wheel METADATA file"
                )
            if len(wheel_members) != 1:
                raise ReleasePreparationError(
                    f"{path.name}: expected exactly one wheel WHEEL file"
                )
            metadata = BytesParser().parsebytes(archive.read(metadata_members[0]))
            wheel = BytesParser().parsebytes(archive.read(wheel_members[0]))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleasePreparationError(f"{path.name}: invalid wheel archive: {exc}") from exc
    return {
        "name": str(metadata.get("Name") or ""),
        "version": str(metadata.get("Version") or ""),
        "pythonRequires": str(metadata.get("Requires-Python") or ""),
        "tags": tuple(str(value) for value in wheel.get_all("Tag", [])),
    }


def _validate_assets(
    manifest: Mapping[str, Any],
    *,
    assets_dir: Path,
    package: str,
    version: str,
) -> None:
    assets = manifest.get("assets")
    if not isinstance(assets, list) or len(assets) != len(EXPECTED_WHEEL_TAGS):
        raise ReleasePreparationError(
            f"release manifest must contain exactly {len(EXPECTED_WHEEL_TAGS)} wheels"
        )
    observed_tags: set[tuple[str, str, str]] = set()
    for index, raw_asset in enumerate(assets):
        if not isinstance(raw_asset, Mapping):
            raise ReleasePreparationError(f"release manifest.assets[{index}] must be an object")
        label = f"release manifest.assets[{index}]"
        filename = _required_string(raw_asset, "filename", label)
        if filename != Path(filename).name or filename in {".", ".."}:
            raise ReleasePreparationError(f"{label}.filename must be a plain file name")
        tags = (
            _required_string(raw_asset, "python_tag", label).lower(),
            _required_string(raw_asset, "abi_tag", label).lower(),
            _required_string(raw_asset, "platform_tag", label).lower(),
        )
        expected_filename = (
            f"{package.replace('-', '_')}-{version}-{'-'.join(tags)}.whl"
        )
        if filename != expected_filename:
            raise ReleasePreparationError(
                f"{filename}: filename does not match declared wheel identity "
                f"{expected_filename}"
            )
        if tags in observed_tags:
            raise ReleasePreparationError(f"duplicate release wheel tags {tags!r}")
        observed_tags.add(tags)
        expected_digest = _required_string(raw_asset, "sha256", label).lower()
        if _HEX_64.fullmatch(expected_digest) is None:
            raise ReleasePreparationError(f"{label}.sha256 must be a SHA-256 digest")
        expected_size = raw_asset.get("size")
        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size <= 0
        ):
            raise ReleasePreparationError(f"{label}.size must be a positive integer")
        path = assets_dir / filename
        try:
            actual_size = path.stat().st_size
        except OSError as exc:
            raise ReleasePreparationError(f"missing release wheel {path}: {exc}") from exc
        if actual_size != expected_size:
            raise ReleasePreparationError(
                f"{filename}: expected {expected_size} bytes, got {actual_size}"
            )
        actual_digest = _sha256(path)
        if actual_digest != expected_digest:
            raise ReleasePreparationError(
                f"{filename}: SHA-256 mismatch; expected {expected_digest}, got {actual_digest}"
            )
        metadata = _wheel_metadata(path)
        if _normalized_distribution(metadata["name"]) != _normalized_distribution(package):
            raise ReleasePreparationError(f"{filename}: wheel distribution does not match {package}")
        if metadata["version"] != version:
            raise ReleasePreparationError(f"{filename}: wheel version does not match {version}")
        if metadata["pythonRequires"] != ">=3.10":
            raise ReleasePreparationError(
                f"{filename}: wheel Requires-Python must be >=3.10"
            )
        embedded_tags = metadata["tags"]
        expected_tag = "-".join(tags)
        if embedded_tags != (expected_tag,):
            raise ReleasePreparationError(
                f"{filename}: embedded wheel tags must be exactly ({expected_tag!r},), "
                f"got {embedded_tags!r}"
            )
    if observed_tags != EXPECTED_WHEEL_TAGS:
        raise ReleasePreparationError(
            "release wheel matrix mismatch: "
            f"expected {sorted(EXPECTED_WHEEL_TAGS)!r}, got {sorted(observed_tags)!r}"
        )


def prepare_release_lock(
    *,
    lock_path: Path,
    manifest_path: Path,
    assets_dir: Path,
) -> dict[str, Any]:
    _, current = _read_object(lock_path, "Pine runtime lock")
    manifest_bytes, manifest = _read_object(manifest_path, "release manifest")
    if current.get("schemaVersion") != 2 or current.get("runtimeId") != "pine-compat":
        raise ReleasePreparationError("Pine release preparation requires the schema-v2 Pine lock")
    current_version = _required_string(current, "version", "Pine runtime lock")
    package = _required_string(current, "package", "Pine runtime lock")
    module = _required_string(current, "pythonModule", "Pine runtime lock")
    upstream = _required_string(current, "upstream", "Pine runtime lock").rstrip("/")

    version = _required_string(manifest, "version", "release manifest")
    if _version_tuple(version, "release manifest.version") <= _version_tuple(
        current_version,
        "Pine runtime lock.version",
    ):
        raise ReleasePreparationError(
            f"release version {version} must be newer than locked version {current_version}"
        )
    tag = _required_string(manifest, "tag", "release manifest")
    if tag != f"v{version}":
        raise ReleasePreparationError(f"release tag {tag!r} does not match version {version!r}")
    commit = _required_string(manifest, "commit", "release manifest").lower()
    if _HEX_40.fullmatch(commit) is None:
        raise ReleasePreparationError("release manifest.commit must be a full Git SHA")
    expected_manifest = {
        "schema_version": 1,
        "channel": "stable",
        "distribution": package,
        "module": module,
        "python_requires": ">=3.10",
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            raise ReleasePreparationError(
                f"release manifest {key!r} mismatch: expected {expected!r}, got {manifest.get(key)!r}"
            )
    _validate_assets(
        manifest,
        assets_dir=assets_dir.resolve(),
        package=package,
        version=version,
    )

    base_url = f"{upstream}/releases/download/{tag}"
    candidate = deepcopy(current)
    candidate.update({
        "version": version,
        "commit": commit,
        "renderMetadataVersion": EXPECTED_RENDER_METADATA_VERSION,
        "realtimeSessionSchemaVersion": EXPECTED_REALTIME_SESSION_SCHEMA_VERSION,
    })
    candidate["release"] = {
        "tag": tag,
        "commit": commit,
        "manifestUrl": f"{base_url}/manifest.json",
        "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "assetBaseUrl": base_url,
    }

    try:
        with tempfile.TemporaryDirectory(prefix="candlescope-pine-lock-") as temp_dir:
            candidate_path = Path(temp_dir) / "CANDLESCOPE_RUNTIME.json"
            candidate_path.write_text(
                json.dumps(candidate, indent=2) + "\n",
                encoding="utf-8",
            )
            parsed = load_plugin_lock(candidate_path)
            validate_release_manifest(manifest_bytes, parsed)
    except InstallerError as exc:
        raise ReleasePreparationError(f"generated managed lock is invalid: {exc}") from exc
    if parsed.probe_kind != "pine-runtime-v2":
        raise ReleasePreparationError("generated lock did not enable the Pine v2 probe")
    return candidate


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, default=_default_lock_path())
    parser.add_argument(
        "--write",
        action="store_true",
        help="atomically replace --lock-file after every validation passes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        candidate = prepare_release_lock(
            lock_path=args.lock_file.expanduser().resolve(),
            manifest_path=args.manifest.expanduser().resolve(),
            assets_dir=args.assets_dir.expanduser().resolve(),
        )
        rendered = (json.dumps(candidate, indent=2) + "\n").encode("utf-8")
        if args.write:
            _atomic_write(args.lock_file.expanduser().resolve(), rendered)
            print(f"updated Pine runtime lock: {args.lock_file}")
        else:
            print(rendered.decode("utf-8"), end="")
        return 0
    except ReleasePreparationError as exc:
        print(f"Pine release preparation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
