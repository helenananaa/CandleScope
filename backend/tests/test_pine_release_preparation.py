from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import ensure_pine_runtime
from scripts import managed_plugin_installer
from scripts import prepare_pine_runtime_release as release


RELEASE_COMMIT = "d" * 40
VERSION = "0.2.1"


def _write_wheel(
    directory: Path,
    platform_tag: str,
    *,
    embedded_platform_tag: str | None = None,
) -> Path:
    name = f"pine_compat_runtime-{VERSION}-cp310-abi3-{platform_tag}.whl"
    path = directory / name
    metadata_dir = f"pine_compat_runtime-{VERSION}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{metadata_dir}/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: pine-compat-runtime\n"
            f"Version: {VERSION}\n"
            "Requires-Python: >=3.10\n\n",
        )
        archive.writestr(
            f"{metadata_dir}/WHEEL",
            "Wheel-Version: 1.0\n"
            "Generator: CandleScope test\n"
            "Root-Is-Purelib: false\n"
            f"Tag: cp310-abi3-{embedded_platform_tag or platform_tag}\n\n",
        )
    return path


def _asset(path: Path, platform_tag: str) -> dict[str, object]:
    return {
        "filename": path.name,
        "python_tag": "cp310",
        "abi_tag": "abi3",
        "platform_tag": platform_tag,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _release_fixture(tmp_path: Path) -> tuple[Path, Path]:
    assets = tmp_path / "assets"
    assets.mkdir()
    linux_tag = "manylinux_2_17_x86_64.manylinux2014_x86_64"
    linux = _write_wheel(assets, linux_tag)
    windows = _write_wheel(assets, "win_amd64")
    manifest = {
        "schema_version": 1,
        "channel": "stable",
        "distribution": "pine-compat-runtime",
        "module": "pine_compat",
        "version": VERSION,
        "tag": f"v{VERSION}",
        "commit": RELEASE_COMMIT,
        "python_requires": ">=3.10",
        "assets": [
            _asset(linux, linux_tag),
            _asset(windows, "win_amd64"),
        ],
    }
    manifest_path = assets / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path, assets


def test_prepare_release_lock_requires_full_matrix_and_enables_v2_probe(
    tmp_path: Path,
) -> None:
    manifest_path, assets = _release_fixture(tmp_path)

    candidate = release.prepare_release_lock(
        lock_path=ensure_pine_runtime._default_lock_path(),
        manifest_path=manifest_path,
        assets_dir=assets,
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    parsed = managed_plugin_installer.load_plugin_lock(candidate_path)

    assert candidate["version"] == VERSION
    assert candidate["commit"] == RELEASE_COMMIT
    assert candidate["renderMetadataVersion"] == 1
    assert candidate["realtimeSessionSchemaVersion"] == 1
    assert parsed.probe_kind == "pine-runtime-v2"
    assert parsed.release_commit == RELEASE_COMMIT


def test_prepare_release_lock_rejects_tampered_wheel(tmp_path: Path) -> None:
    manifest_path, assets = _release_fixture(tmp_path)
    wheel = next(assets.glob("*win_amd64.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"tampered")

    with pytest.raises(release.ReleasePreparationError, match="expected .* bytes"):
        release.prepare_release_lock(
            lock_path=ensure_pine_runtime._default_lock_path(),
            manifest_path=manifest_path,
            assets_dir=assets,
        )


def test_prepare_release_lock_rejects_non_advancing_version(tmp_path: Path) -> None:
    manifest_path, assets = _release_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "0.2.0"
    manifest["tag"] = "v0.2.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(release.ReleasePreparationError, match="must be newer"):
        release.prepare_release_lock(
            lock_path=ensure_pine_runtime._default_lock_path(),
            manifest_path=manifest_path,
            assets_dir=assets,
        )


def test_prepare_release_lock_rejects_filename_tag_disagreement(tmp_path: Path) -> None:
    manifest_path, assets = _release_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets"][0]["platform_tag"] = "manylinux_2_17_aarch64"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(release.ReleasePreparationError, match="filename does not match"):
        release.prepare_release_lock(
            lock_path=ensure_pine_runtime._default_lock_path(),
            manifest_path=manifest_path,
            assets_dir=assets,
        )


def test_prepare_release_lock_rejects_embedded_wheel_tag_disagreement(
    tmp_path: Path,
) -> None:
    manifest_path, assets = _release_fixture(tmp_path)
    wheel = _write_wheel(
        assets,
        "win_amd64",
        embedded_platform_tag="win_arm64",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset = next(item for item in manifest["assets"] if item["filename"] == wheel.name)
    asset["size"] = wheel.stat().st_size
    asset["sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(release.ReleasePreparationError, match="embedded wheel tags"):
        release.prepare_release_lock(
            lock_path=ensure_pine_runtime._default_lock_path(),
            manifest_path=manifest_path,
            assets_dir=assets,
        )
