from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import ensure_pine_runtime as installer


SOURCE_COMMIT = "a" * 40
RELEASE_COMMIT = "b" * 40
WINDOWS_WHEEL = "pine_compat_runtime-0.1.0-cp310-abi3-win_amd64.whl"
LINUX_WHEEL = (
    "pine_compat_runtime-0.1.0-cp310-abi3-"
    "manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
)


def _asset(filename: str, platform_tag: str, payload: bytes) -> dict[str, object]:
    return {
        "filename": filename,
        "python_tag": "cp310",
        "abi_tag": "abi3",
        "platform_tag": platform_tag,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _manifest_bytes(*, windows_payload: bytes = b"windows", linux_payload: bytes = b"linux") -> bytes:
    value = {
        "schema_version": 1,
        "channel": "stable",
        "distribution": "pine-compat-runtime",
        "module": "pine_compat",
        "version": "0.1.0",
        "tag": "v0.1.0",
        "commit": RELEASE_COMMIT,
        "python_requires": ">=3.10",
        "assets": [
            _asset(WINDOWS_WHEEL, "win_amd64", windows_payload),
            _asset(
                LINUX_WHEEL,
                "manylinux_2_17_x86_64.manylinux2014_x86_64",
                linux_payload,
            ),
        ],
    }
    return json.dumps(value, sort_keys=True).encode("utf-8")


def _write_lock(tmp_path: Path, manifest_bytes: bytes) -> Path:
    lock = {
        "schemaVersion": 2,
        "runtimeId": "pine-compat",
        "package": "pine-compat-runtime",
        "pythonModule": "pine_compat",
        "version": "0.1.0",
        "upstream": "https://github.com/Ryan00956/pine-compat-runtime",
        "commit": SOURCE_COMMIT,
        "analysisSchemaVersion": 3,
        "runtimeSchemaVersion": 7,
        "release": {
            "tag": "v0.1.0",
            "commit": RELEASE_COMMIT,
            "manifestUrl": (
                "https://github.com/Ryan00956/pine-compat-runtime/"
                "releases/download/v0.1.0/manifest.json"
            ),
            "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "assetBaseUrl": (
                "https://github.com/Ryan00956/pine-compat-runtime/"
                "releases/download/v0.1.0"
            ),
        },
    }
    path = tmp_path / "CANDLESCOPE_RUNTIME.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path


def test_load_lock_and_validate_release_manifest(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = installer.load_release_lock(_write_lock(tmp_path, raw))

    manifest = installer.validate_release_manifest(raw, lock)

    assert lock.source_commit == SOURCE_COMMIT
    assert lock.release_commit == RELEASE_COMMIT
    assert manifest["version"] == "0.1.0"


def test_manifest_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = installer.load_release_lock(_write_lock(tmp_path, raw))

    with pytest.raises(installer.InstallerError, match="manifest SHA-256 mismatch"):
        installer.validate_release_manifest(raw + b"\n", lock)


@pytest.mark.parametrize(
    ("sys_platform", "machine", "expected_filename"),
    [
        ("win32", "AMD64", WINDOWS_WHEEL),
        ("linux", "x86_64", LINUX_WHEEL),
    ],
)
def test_selects_exact_platform_wheel(
    tmp_path: Path,
    sys_platform: str,
    machine: str,
    expected_filename: str,
) -> None:
    raw = _manifest_bytes()
    lock = installer.load_release_lock(_write_lock(tmp_path, raw))
    manifest = installer.validate_release_manifest(raw, lock)

    selected = installer.select_release_asset(
        manifest,
        sys_platform=sys_platform,
        machine=machine,
        python_implementation="CPython",
        python_version=(3, 13),
        gil_disabled=False,
    )

    assert selected["filename"] == expected_filename


@pytest.mark.parametrize(
    ("sys_platform", "machine", "reason"),
    [
        ("darwin", "arm64", "architecture"),
        ("win32", "arm64", "architecture"),
        ("darwin", "x86_64", "platform"),
    ],
)
def test_unsupported_platform_or_architecture_is_explicit(
    tmp_path: Path,
    sys_platform: str,
    machine: str,
    reason: str,
) -> None:
    raw = _manifest_bytes()
    lock = installer.load_release_lock(_write_lock(tmp_path, raw))
    manifest = installer.validate_release_manifest(raw, lock)

    with pytest.raises(installer.InstallerError, match=reason):
        installer.select_release_asset(
            manifest,
            sys_platform=sys_platform,
            machine=machine,
            python_implementation="CPython",
            python_version=(3, 13),
            gil_disabled=False,
        )


def test_free_threaded_python_is_rejected(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = installer.load_release_lock(_write_lock(tmp_path, raw))
    manifest = installer.validate_release_manifest(raw, lock)

    with pytest.raises(installer.InstallerError, match="Free-threaded"):
        installer.select_release_asset(
            manifest,
            sys_platform="win32",
            machine="AMD64",
            python_implementation="CPython",
            python_version=(3, 13),
            gil_disabled=True,
        )


def test_verified_cached_wheel_is_reused_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel_payload = b"verified-wheel"
    raw = _manifest_bytes(windows_payload=wheel_payload)
    lock = installer.load_release_lock(_write_lock(tmp_path, raw))
    manifest = installer.validate_release_manifest(raw, lock)
    asset = installer.select_release_asset(
        manifest,
        sys_platform="win32",
        machine="AMD64",
        python_implementation="CPython",
        python_version=(3, 13),
        gil_disabled=False,
    )
    wheel_path = tmp_path / lock.package / lock.tag / WINDOWS_WHEEL
    wheel_path.parent.mkdir(parents=True)
    wheel_path.write_bytes(wheel_payload)

    def unexpected_download(*args: object, **kwargs: object) -> None:
        raise AssertionError("a verified cached wheel must not be downloaded again")

    monkeypatch.setattr(installer, "_download_wheel", unexpected_download)

    result = installer.ensure_cached_wheel(
        lock,
        asset,
        cache_dir=tmp_path,
        offline=False,
        timeout=1,
    )

    assert result == wheel_path


def test_verified_cached_manifest_is_reused_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _manifest_bytes()
    lock = installer.load_release_lock(_write_lock(tmp_path, raw))
    manifest_path = tmp_path / lock.package / lock.tag / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(raw)

    def unexpected_network(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("a verified cached manifest must not be downloaded again")

    monkeypatch.setattr(installer, "_read_url_limited", unexpected_network)

    manifest = installer.load_pinned_manifest(
        lock,
        cache_dir=tmp_path,
        offline=False,
        timeout=1,
    )

    assert manifest["commit"] == RELEASE_COMMIT


def test_offline_mode_rejects_missing_wheel(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = installer.load_release_lock(_write_lock(tmp_path, raw))
    manifest = installer.validate_release_manifest(raw, lock)
    asset = installer.select_release_asset(
        manifest,
        sys_platform="win32",
        machine="AMD64",
        python_implementation="CPython",
        python_version=(3, 13),
        gil_disabled=False,
    )

    with pytest.raises(installer.InstallerError, match="Offline mode"):
        installer.ensure_cached_wheel(
            lock,
            asset,
            cache_dir=tmp_path,
            offline=True,
            timeout=1,
        )


def test_install_stamp_locks_exact_release_identity(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = installer.load_release_lock(_write_lock(tmp_path, raw))
    manifest = installer.validate_release_manifest(raw, lock)
    asset = installer.select_release_asset(
        manifest,
        sys_platform="win32",
        machine="AMD64",
        python_implementation="CPython",
        python_version=(3, 13),
        gil_disabled=False,
    )
    stamp_path = tmp_path / "install-stamp.json"

    installer.write_install_stamp(lock, asset, path=stamp_path)
    stamp = installer.validate_install_stamp(lock, path=stamp_path)

    assert stamp["releaseCommit"] == RELEASE_COMMIT
    assert stamp["wheelFilename"] == WINDOWS_WHEEL

    changed_lock_data = json.loads(lock.path.read_text(encoding="utf-8"))
    changed_lock_data["release"]["commit"] = "c" * 40
    changed_lock_path = tmp_path / "changed-lock.json"
    changed_lock_path.write_text(json.dumps(changed_lock_data), encoding="utf-8")
    changed_lock = installer.load_release_lock(changed_lock_path)
    with pytest.raises(installer.InstallerError, match="releaseCommit.*mismatch"):
        installer.validate_install_stamp(changed_lock, path=stamp_path)


def test_check_mode_never_downloads_or_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _manifest_bytes()
    lock_path = _write_lock(tmp_path, raw)
    monkeypatch.setattr(
        installer,
        "probe_installed_runtime",
        lambda lock: {"ok": False, "reason": "not installed"},
    )
    monkeypatch.setattr(
        installer,
        "load_pinned_manifest",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("check mode must not access the network/cache manifest")
        ),
    )
    monkeypatch.setattr(
        installer,
        "install_wheel",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("check mode must not install")
        ),
    )

    assert installer.main(["--check", "--lock-file", str(lock_path)]) == 1
