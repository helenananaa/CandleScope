from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import ensure_managed_plugins as manager
from scripts import managed_plugin_installer as installer


SOURCE_COMMIT = "a" * 40
RELEASE_COMMIT = "b" * 40
WINDOWS_WHEEL = "example_plugin-1.2.3-cp310-abi3-win_amd64.whl"
LINUX_WHEEL = (
    "example_plugin-1.2.3-cp310-abi3-"
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


def _manifest_bytes(
    *, windows_payload: bytes = b"windows", linux_payload: bytes = b"linux"
) -> bytes:
    value = {
        "schema_version": 1,
        "channel": "stable",
        "distribution": "example-plugin",
        "module": "example_plugin",
        "version": "1.2.3",
        "tag": "release-1.2.3",
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


def _lock_value(
    manifest_bytes: bytes,
    *,
    plugin_id: str = "example",
    legacy_stamp_files: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "pluginId": plugin_id,
        "displayName": "Example plugin",
        "installer": {
            "kind": "python-wheel",
            "package": "example-plugin",
            "pythonModule": "example_plugin",
            "version": "1.2.3",
            "pythonRequires": ">=3.10",
            "pythonTag": "cp310",
            "abiTag": "abi3",
        },
        "source": {
            "url": "https://github.com/example/example-plugin",
            "commit": SOURCE_COMMIT,
        },
        "release": {
            "tag": "release-1.2.3",
            "commit": RELEASE_COMMIT,
            "manifestUrl": (
                "https://downloads.example.test/example-plugin/"
                "release-1.2.3/manifest.json"
            ),
            "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "assetBaseUrl": (
                "https://downloads.example.test/example-plugin/release-1.2.3"
            ),
        },
        "verification": {"probe": "python-import"},
        "legacyStampFiles": legacy_stamp_files or [],
    }


def _write_lock(
    tmp_path: Path,
    manifest_bytes: bytes,
    *,
    filename: str = "CANDLESCOPE_PLUGIN.json",
    plugin_id: str = "example",
    legacy_stamp_files: list[str] | None = None,
) -> Path:
    path = tmp_path / filename
    path.write_text(
        json.dumps(
            _lock_value(
                manifest_bytes,
                plugin_id=plugin_id,
                legacy_stamp_files=legacy_stamp_files,
            )
        ),
        encoding="utf-8",
    )
    return path


def _write_registry(
    tmp_path: Path,
    entries: list[dict[str, object]],
) -> Path:
    path = tmp_path / "CANDLESCOPE_PLUGINS.json"
    path.write_text(
        json.dumps({"schemaVersion": 1, "plugins": entries}),
        encoding="utf-8",
    )
    return path


def _load_lock(tmp_path: Path, raw: bytes | None = None) -> installer.PluginLock:
    manifest = raw or _manifest_bytes()
    return installer.load_plugin_lock(_write_lock(tmp_path, manifest))


def test_registry_loads_generic_plugin_lock_and_manifest(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock_path = _write_lock(tmp_path, raw)
    registry_path = _write_registry(
        tmp_path,
        [
            {
                "id": "example",
                "lockFile": lock_path.name,
                "autoInstall": True,
            }
        ],
    )

    plugins = installer.load_plugin_registry(registry_path)
    manifest = installer.validate_release_manifest(raw, plugins[0].lock)

    assert plugins[0].auto_install is True
    assert plugins[0].lock.installer_kind == "python-wheel"
    assert plugins[0].lock.source_commit == SOURCE_COMMIT
    assert manifest["version"] == "1.2.3"


def test_registry_rejects_id_mismatch_before_install(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock_path = _write_lock(tmp_path, raw)
    registry_path = _write_registry(
        tmp_path,
        [
            {
                "id": "different-id",
                "lockFile": lock_path.name,
                "autoInstall": True,
            }
        ],
    )

    with pytest.raises(installer.InstallerError, match="does not match lock pluginId"):
        installer.load_plugin_registry(registry_path)


def test_manifest_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = _load_lock(tmp_path, raw)

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
    lock = _load_lock(tmp_path, raw)
    manifest = installer.validate_release_manifest(raw, lock)

    selected = installer.select_release_asset(
        manifest,
        lock,
        sys_platform=sys_platform,
        machine=machine,
        python_implementation="CPython",
        python_version=(3, 13),
        gil_disabled=False,
    )

    assert selected["filename"] == expected_filename


@pytest.mark.parametrize(
    ("sys_platform", "machine"),
    [
        ("darwin", "arm64"),
        ("win32", "arm64"),
        ("linux", "riscv64"),
    ],
)
def test_unsupported_platform_or_architecture_is_explicit(
    tmp_path: Path,
    sys_platform: str,
    machine: str,
) -> None:
    raw = _manifest_bytes()
    lock = _load_lock(tmp_path, raw)
    manifest = installer.validate_release_manifest(raw, lock)

    with pytest.raises(installer.InstallerError, match="no Example plugin wheel"):
        installer.select_release_asset(
            manifest,
            lock,
            sys_platform=sys_platform,
            machine=machine,
            python_implementation="CPython",
            python_version=(3, 13),
            gil_disabled=False,
        )


def test_free_threaded_python_is_rejected(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = _load_lock(tmp_path, raw)
    manifest = installer.validate_release_manifest(raw, lock)

    with pytest.raises(installer.InstallerError, match="free-threaded"):
        installer.select_release_asset(
            manifest,
            lock,
            sys_platform="win32",
            machine="AMD64",
            python_implementation="CPython",
            python_version=(3, 13),
            gil_disabled=True,
        )


def test_verified_cached_artifact_is_reused_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel_payload = b"verified-wheel"
    raw = _manifest_bytes(windows_payload=wheel_payload)
    lock = _load_lock(tmp_path, raw)
    manifest = installer.validate_release_manifest(raw, lock)
    asset = installer.select_release_asset(
        manifest,
        lock,
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
        raise AssertionError("a verified cached artifact must not be downloaded again")

    monkeypatch.setattr(installer, "_download_artifact", unexpected_download)

    result = installer.ensure_cached_artifact(
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
    lock = _load_lock(tmp_path, raw)
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


def test_offline_mode_rejects_missing_artifact(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = _load_lock(tmp_path, raw)
    manifest = installer.validate_release_manifest(raw, lock)
    asset = installer.select_release_asset(
        manifest,
        lock,
        sys_platform="win32",
        machine="AMD64",
        python_implementation="CPython",
        python_version=(3, 13),
        gil_disabled=False,
    )

    with pytest.raises(installer.InstallerError, match="offline mode"):
        installer.ensure_cached_artifact(
            lock,
            asset,
            cache_dir=tmp_path,
            offline=True,
            timeout=1,
        )


def test_install_stamp_locks_plugin_and_release_identity(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = _load_lock(tmp_path, raw)
    manifest = installer.validate_release_manifest(raw, lock)
    asset = installer.select_release_asset(
        manifest,
        lock,
        sys_platform="win32",
        machine="AMD64",
        python_implementation="CPython",
        python_version=(3, 13),
        gil_disabled=False,
    )
    stamp_path = tmp_path / "install-stamp.json"

    installer.write_install_stamp(lock, asset, path=stamp_path)
    stamp = installer.validate_install_stamp(lock, path=stamp_path)

    assert stamp["pluginId"] == "example"
    assert stamp["releaseCommit"] == RELEASE_COMMIT
    assert stamp["artifactFilename"] == WINDOWS_WHEEL

    changed_lock_data = json.loads(lock.path.read_text(encoding="utf-8"))
    changed_lock_data["release"]["commit"] = "c" * 40
    changed_lock_path = tmp_path / "changed-lock.json"
    changed_lock_path.write_text(json.dumps(changed_lock_data), encoding="utf-8")
    changed_lock = installer.load_plugin_lock(changed_lock_path)
    with pytest.raises(installer.InstallerError, match="releaseCommit.*mismatch"):
        installer.validate_install_stamp(changed_lock, path=stamp_path)


def test_legacy_pine_style_stamp_is_accepted_and_migrated(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    lock = installer.load_plugin_lock(
        _write_lock(
            tmp_path,
            raw,
            legacy_stamp_files=["example-runtime-install.json"],
        )
    )
    legacy_path = tmp_path / ".candlescope" / "example-runtime-install.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "package": lock.package,
                "version": lock.version,
                "tag": lock.tag,
                "releaseCommit": lock.release_commit,
                "manifestSha256": lock.manifest_sha256,
                "wheelFilename": WINDOWS_WHEEL,
                "wheelSha256": "d" * 64,
            }
        ),
        encoding="utf-8",
    )

    managed = installer.load_managed_stamp(lock, prefix=tmp_path)
    migrated_path = installer.migrate_legacy_stamp(lock, managed, prefix=tmp_path)
    migrated = installer.validate_install_stamp(lock, path=migrated_path)

    assert managed.legacy is True
    assert migrated_path == tmp_path / ".candlescope" / "plugins" / "example.json"
    assert migrated["schemaVersion"] == 2
    assert migrated["artifactFilename"] == WINDOWS_WHEEL
    assert legacy_path.exists()


def test_check_mode_never_downloads_or_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = _load_lock(tmp_path)
    monkeypatch.setattr(
        installer,
        "probe_installed_plugin",
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
        "install_artifact",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("check mode must not install")
        ),
    )

    assert installer.ensure_managed_plugin(lock, check=True) is False


@pytest.mark.parametrize(("check", "expected_migrations"), [(False, 1), (True, 0)])
def test_ready_legacy_stamp_migrates_only_during_normal_ensure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    check: bool,
    expected_migrations: int,
) -> None:
    lock = _load_lock(tmp_path)
    legacy_value = {
        "schemaVersion": 1,
        "package": lock.package,
        "version": lock.version,
        "tag": lock.tag,
        "releaseCommit": lock.release_commit,
        "manifestSha256": lock.manifest_sha256,
        "wheelFilename": WINDOWS_WHEEL,
        "wheelSha256": "d" * 64,
    }
    monkeypatch.setattr(
        installer,
        "probe_installed_plugin",
        lambda value: {
            "ok": True,
            "sourcePath": "example_plugin.pyd",
            "legacyStamp": True,
            "managedRelease": legacy_value,
            "managedStampPath": str(tmp_path / "legacy.json"),
        },
    )
    migrations: list[installer.ManagedStamp] = []
    monkeypatch.setattr(
        installer,
        "migrate_legacy_stamp",
        lambda value, stamp: migrations.append(stamp) or tmp_path / "new.json",
    )
    monkeypatch.setattr(
        installer,
        "install_artifact",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("a ready legacy install must not reinstall")
        ),
    )

    assert installer.ensure_managed_plugin(lock, check=check) is True
    assert len(migrations) == expected_migrations


def test_failed_upgrade_restores_hash_verified_cached_previous_wheel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = _load_lock(tmp_path)
    cache_dir = tmp_path / "cache"
    previous_version = "1.2.2"
    previous_tag = "release-1.2.2"
    previous_name = "example_plugin-1.2.2-cp310-abi3-win_amd64.whl"
    previous_payload = b"previous verified wheel"
    previous_digest = hashlib.sha256(previous_payload).hexdigest()
    previous_artifact = cache_dir / lock.package / previous_tag / previous_name
    previous_artifact.parent.mkdir(parents=True)
    previous_artifact.write_bytes(previous_payload)
    stamp_path = tmp_path / "prefix" / ".candlescope" / "plugins" / "example.json"
    stamp_path.parent.mkdir(parents=True)
    previous_stamp = {
        "schemaVersion": installer.INSTALL_STAMP_SCHEMA_VERSION,
        "pluginId": lock.plugin_id,
        "installerKind": lock.installer_kind,
        "package": lock.package,
        "version": previous_version,
        "tag": previous_tag,
        "releaseCommit": "c" * 40,
        "manifestSha256": "d" * 64,
        "artifactFilename": previous_name,
        "artifactSha256": previous_digest,
    }
    stamp_path.write_text(json.dumps(previous_stamp), encoding="utf-8")
    monkeypatch.setattr(
        installer,
        "install_stamp_path",
        lambda plugin_id, prefix=None: stamp_path,
    )
    manifest = installer.validate_release_manifest(_manifest_bytes(), lock)
    new_artifact = tmp_path / WINDOWS_WHEEL
    new_artifact.write_bytes(b"new wheel")
    monkeypatch.setattr(installer, "load_pinned_manifest", lambda *args, **kwargs: manifest)
    monkeypatch.setattr(
        installer,
        "ensure_cached_artifact",
        lambda *args, **kwargs: new_artifact,
    )
    probe_calls = 0

    def probe(_lock: installer.PluginLock, *, require_stamp: bool = True) -> dict[str, object]:
        nonlocal probe_calls
        probe_calls += 1
        return (
            {"ok": False, "reason": "old version differs"}
            if probe_calls == 1
            else {"ok": False, "reason": "new realtime ABI failed"}
        )

    monkeypatch.setattr(installer, "probe_installed_plugin", probe)
    installed: list[Path] = []
    monkeypatch.setattr(
        installer,
        "install_artifact",
        lambda _lock, path: installed.append(path),
    )
    monkeypatch.setattr(
        installer,
        "_probe_package_identity",
        lambda _lock, *, expected_version: {"ok": expected_version == previous_version},
    )

    with pytest.raises(installer.InstallerError, match="restored previous.*1.2.2"):
        installer.ensure_managed_plugin(lock, cache_dir=cache_dir, quiet=True)

    assert installed == [new_artifact, previous_artifact]
    assert json.loads(stamp_path.read_text(encoding="utf-8")) == previous_stamp


def test_failed_first_install_reports_when_rollback_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = _load_lock(tmp_path)
    manifest = installer.validate_release_manifest(_manifest_bytes(), lock)
    new_artifact = tmp_path / WINDOWS_WHEEL
    new_artifact.write_bytes(b"new wheel")
    monkeypatch.setattr(
        installer,
        "probe_installed_plugin",
        lambda *args, **kwargs: {"ok": False, "reason": "probe failed"},
    )
    monkeypatch.setattr(installer, "load_pinned_manifest", lambda *args, **kwargs: manifest)
    monkeypatch.setattr(
        installer,
        "ensure_cached_artifact",
        lambda *args, **kwargs: new_artifact,
    )
    monkeypatch.setattr(installer, "install_artifact", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "_capture_previous_install", lambda *args, **kwargs: None)

    with pytest.raises(installer.InstallerError, match="rollback unavailable"):
        installer.ensure_managed_plugin(lock, cache_dir=tmp_path / "cache", quiet=True)


def test_plugin_selection_supports_auto_explicit_and_exclude(tmp_path: Path) -> None:
    raw = _manifest_bytes()
    first = _write_lock(tmp_path, raw, filename="first.json", plugin_id="first")
    second = _write_lock(tmp_path, raw, filename="second.json", plugin_id="second")
    registry_path = _write_registry(
        tmp_path,
        [
            {"id": "first", "lockFile": first.name, "autoInstall": True},
            {"id": "second", "lockFile": second.name, "autoInstall": False},
        ],
    )
    plugins = installer.load_plugin_registry(registry_path)

    assert [item.lock.plugin_id for item in installer.select_plugins(plugins)] == [
        "first"
    ]
    assert [
        item.lock.plugin_id
        for item in installer.select_plugins(plugins, requested=["second"])
    ] == ["second"]
    assert installer.select_plugins(plugins, excluded=["first"]) == []


def test_manager_check_aggregates_selected_plugin_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _manifest_bytes()
    lock_path = _write_lock(tmp_path, raw)
    registry_path = _write_registry(
        tmp_path,
        [{"id": "example", "lockFile": lock_path.name, "autoInstall": True}],
    )
    calls: list[tuple[str, bool]] = []

    def fake_ensure(lock: installer.PluginLock, **kwargs: object) -> bool:
        calls.append((lock.plugin_id, bool(kwargs.get("check"))))
        return False

    monkeypatch.setattr(manager, "ensure_managed_plugin", fake_ensure)

    assert manager.main(["--check", "--registry-file", str(registry_path)]) == 1
    assert calls == [("example", True)]
