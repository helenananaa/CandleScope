from __future__ import annotations

import hashlib
import io
import json
import platform
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.first_party_plugin_bootstrap import (
    DEFAULT_RELEASE_LOCK_PATH,
    FirstPartyPluginBootstrapError,
    OfficialPluginRelease,
    download_official_plugin_bundle,
    ensure_first_party_plugins_from_environment,
    load_official_plugin_releases,
    load_bundled_plugin_releases,
)
from app.plugin_runtime.errors import PluginBundleError
from app.plugin_runtime.registry import load_runtime_registry
from tests.plugin_runtime_bundle_testkit import build_hello_bundle


OFFICIAL_SHA256 = (
    "sha256:889ffeb4a70b330c1cf529b66422fe0c11c303b781968b12e8156fbb854f3918"
)
OFFICIAL_PINE_SHA256 = (
    "sha256:b70f4e2bcf1dbf65ae3ce57ce3c28114e846d19f45b48898c025f923415d388a"
)


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _release(
    payload: bytes,
    *,
    runtime_id: str = "candlescope.pyne",
) -> OfficialPluginRelease:
    pine = runtime_id == "candlescope.pine-compat"
    return OfficialPluginRelease(
        runtime_id=runtime_id,
        package=(
            "candlescope-plugin-pine-compat" if pine else "candlescope-plugin-pyne"
        ),
        version="0.2.0",
        filename=(
            "candlescope-pine-compat-test.cspkg"
            if pine
            else "candlescope-pyne-test.cspkg"
        ),
        url="https://github.com/helenananaa/CandleScope/releases/download/test/test.cspkg",
        sha256=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        size=len(payload),
        system=platform.system(),
        machine=platform.machine(),
        implementation=platform.python_implementation(),
        python_version=f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}",
    )


def _write_lock(path: Path, *releases: OfficialPluginRelease) -> Path:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "plugins": [
                    {
                        "runtimeId": release.runtime_id,
                        "package": release.package,
                        "version": release.version,
                        "filename": release.filename,
                        "url": release.url,
                        "sha256": release.sha256,
                        "size": release.size,
                        "platform": {
                            "system": release.system,
                            "machine": release.machine,
                            "implementation": release.implementation,
                            "pythonVersion": release.python_version,
                        },
                    }
                    for release in releases
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_routes(
    path: Path,
    *routes: tuple[str, str],
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "routes": [
                    {
                        "language": language,
                        "mode": "sidecar",
                        "runtimeId": runtime_id,
                    }
                    for language, runtime_id in routes
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_bundled_lock(path: Path, *releases: OfficialPluginRelease) -> Path:
    _write_lock(path, *releases)
    value = json.loads(path.read_text())
    value["schemaVersion"] = 2
    value["releaseStatus"] = "desktop-source-build-unpublished"
    for item in value["plugins"]:
        del item["url"]
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize("corrupt_second", [False, True])
def test_bundled_defaults_are_offline_and_verify_all_before_activation(tmp_path, corrupt_second):
    pine = _release(b"packaged pine", runtime_id="candlescope.pine-compat")
    pyne = _release(b"packaged pyne")
    manifest = _write_bundled_lock(tmp_path / "bundled.json", pine, pyne)
    (tmp_path / pine.filename).write_bytes(b"packaged pine")
    (tmp_path / pyne.filename).write_bytes(b"tampered" if corrupt_second else b"packaged pyne")
    calls = []

    class Installer:
        def __init__(self, **kwargs):
            pass

        def list_plugins(self):
            return ()

        def install_many(self, bundles, **kwargs):
            calls.append(bundles)
            return tuple(SimpleNamespace(changed=True, installation_path=tmp_path / r.runtime_id)
                         for r in (pine, pyne))

    def execute():
        return ensure_first_party_plugins_from_environment(
            host_name="CandleScope", host_version="0.3.0",
            environ={"CANDLESCOPE_BUNDLED_PLUGIN_MANIFEST": str(manifest),
                     "CANDLESCOPE_RUNTIME_REGISTRY": str(tmp_path / "runtime-registry.json")},
            installer_factory=Installer,
            opener=lambda *args, **kwargs: pytest.fail("packaged defaults must never download"),
        )

    if corrupt_second:
        with pytest.raises(FirstPartyPluginBootstrapError, match="pinned size and SHA-256"):
            execute()
        assert calls == []
    else:
        result = execute()
        assert result.status == "installed" and result.downloaded is False
        assert calls == [tuple((tmp_path / r.filename, r.sha256) for r in (pine, pyne))]


@pytest.mark.parametrize("changed", [
    {"filename": "../escape.cspkg"}, {"filename": "..\\escape.cspkg"},
    {"url": "https://github.com/extra"}, {"runtimeId": "unrelated.plugin"},
])
def test_bundled_manifest_rejects_external_assets(tmp_path, changed):
    path = _write_bundled_lock(tmp_path / "manifest.json", _release(b"bundle"))
    value = json.loads(path.read_text())
    value["plugins"][0].update(changed)
    path.write_text(json.dumps(value))
    with pytest.raises(FirstPartyPluginBootstrapError):
        load_bundled_plugin_releases(path)


def test_bundled_symlink_cannot_escape_package(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    release = _release(b"bundle")
    path = _write_bundled_lock(assets / "manifest.json", release)
    try:
        (assets / release.filename).symlink_to(tmp_path / "outside.cspkg")
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        pytest.skip("Windows token lacks the symbolic-link privilege")
    with pytest.raises(FirstPartyPluginBootstrapError, match="escapes"):
        load_bundled_plugin_releases(path)


def test_bundled_manifest_must_cover_routes_on_this_platform(tmp_path):
    release = _release(b"bundle")
    path = _write_bundled_lock(tmp_path / "manifest.json", release)
    options = dict(host_name="CandleScope", host_version="0.3.0",
                   environ={"CANDLESCOPE_BUNDLED_PLUGIN_MANIFEST": str(path)},
                   installer_factory=lambda **kwargs: pytest.fail("invalid package must not install"))
    with pytest.raises(FirstPartyPluginBootstrapError, match="missing runtimes"):
        ensure_first_party_plugins_from_environment(**options)
    _write_bundled_lock(path, replace(release, system="OtherSystem"))
    with pytest.raises(FirstPartyPluginBootstrapError, match="does not support this host"):
        ensure_first_party_plugins_from_environment(**options)


def test_bundled_default_preserves_verified_manual_disabled_activation(tmp_path):
    release = _release(b"not read when user owns activation")
    path = _write_bundled_lock(tmp_path / "manifest.json", release)
    checks = []

    class Installer:
        def __init__(self, **kwargs):
            pass

        def list_plugins(self):
            return ({"runtimeId": release.runtime_id, "package": release.package,
                     "managed": True, "enabled": False, "version": "9.0.0",
                     "bundleSha256": "sha256:" + "f" * 64},)

        def check(self, runtime_id):
            checks.append(runtime_id)
            return SimpleNamespace(activation_id="user-choice")

    result = ensure_first_party_plugins_from_environment(
        host_name="CandleScope", host_version="0.3.0",
        environ=_single_pyne_environment(tmp_path, CANDLESCOPE_BUNDLED_PLUGIN_MANIFEST=str(path)),
        installer_factory=Installer,
        opener=lambda *args, **kwargs: pytest.fail("must preserve installed selection"),
    )
    assert result.status == "skipped" and result.reason == "user-disabled-runtime"
    assert result.version == "9.0.0" and checks == [release.runtime_id]


def _single_pyne_environment(tmp_path: Path, **values: str) -> dict[str, str]:
    routes = _write_routes(
        tmp_path / "routes.json",
        ("pyne", "candlescope.pyne"),
    )
    return {
        "LOCALAPPDATA": str(tmp_path / "local-app-data"),
        "CANDLESCOPE_INDICATOR_RUNTIME_ROUTES": str(routes),
        **values,
    }


def test_checked_in_release_lock_pins_the_stable_adapter_assets() -> None:
    releases = load_official_plugin_releases(DEFAULT_RELEASE_LOCK_PATH)

    assert len(releases) == 5
    by_runtime = {release.runtime_id: release for release in releases if release.system == "Windows"}
    pyne = by_runtime["candlescope.pyne"]
    assert pyne.version == "0.3.0"
    assert pyne.sha256 == OFFICIAL_SHA256
    assert pyne.size == 13_588_457
    assert pyne.url.endswith(
        "/candlescope-plugin-pyne-v0.3.0/"
        "candlescope-pyne-0.3.0-cp312-win_amd64.cspkg"
    )
    pine = by_runtime["candlescope.pine-compat"]
    assert pine.version == "0.3.2"
    assert pine.sha256 == OFFICIAL_PINE_SHA256
    assert pine.size == 4_195_533
    assert pine.url.endswith(
        "/candlescope-plugin-pine-compat-v0.3.2/"
        "candlescope-pine-compat-0.3.2-cp312-win_amd64.cspkg"
    )
    pine_variants = [release for release in releases if release.runtime_id == pine.runtime_id]
    assert {(item.system, item.machine) for item in pine_variants} == {
        ("Windows", "AMD64"), ("Linux", "x86_64"),
        ("Darwin", "arm64"), ("Darwin", "x86_64"),
    }
    assert all(item.version == "0.3.2" and item.python_version == "3.12"
               and item.implementation == "CPython" for item in pine_variants)


def test_download_verifies_before_committing_and_reuses_cache(tmp_path: Path) -> None:
    payload = b"deterministic test bundle"
    release = _release(payload)
    calls: list[Any] = []

    def opener(request: Any, *, timeout: float) -> _Response:
        calls.append((request.full_url, timeout))
        return _Response(payload)

    path, downloaded = download_official_plugin_bundle(
        release,
        tmp_path,
        timeout_seconds=7.5,
        opener=opener,
    )
    repeated, repeated_download = download_official_plugin_bundle(
        release,
        tmp_path,
        opener=lambda *_args, **_kwargs: pytest.fail("cache hit must not download"),
    )

    assert downloaded is True
    assert repeated_download is False
    assert repeated == path
    assert path.read_bytes() == payload
    assert calls == [(release.url, 7.5)]
    assert list(tmp_path.glob("*.download")) == []


@pytest.mark.parametrize("machine", ["arm64", "x86_64"])
def test_bootstrap_selects_matching_mac_variant(tmp_path: Path, monkeypatch, machine: str) -> None:
    payload = b"verified mac bundle"
    base = _release(payload, runtime_id="candlescope.pine-compat")
    variants = [
        replace(base, system="Windows", machine="AMD64", python_version="3.12"),
        replace(base, system="Darwin", machine="arm64", python_version="3.12",
                filename="pine-arm64.cspkg"),
        replace(base, system="Darwin", machine="x86_64", python_version="3.12",
                filename="pine-x86_64.cspkg"),
        replace(base, system="Darwin", machine=machine, python_version="3.13",
                filename="pine-other-python.cspkg"),
    ]
    pyne = replace(_release(b"windows pyne"), system="Windows", machine="AMD64")
    lock = _write_lock(tmp_path / "releases.json", pyne, *variants)
    routes = _write_routes(tmp_path / "routes.json", ("pyne", "candlescope.pyne"),
                           ("pine", "candlescope.pine-compat"))
    monkeypatch.setattr("app.first_party_plugin_bootstrap._host_platform", lambda: {
        "system": "Darwin", "machine": machine,
        "implementation": "CPython", "pythonVersion": "3.12",
    })
    selected = next(item for item in variants if item.machine == machine)
    bundle = tmp_path / selected.filename
    bundle.write_bytes(payload)
    installed = []

    class Installer:
        def __init__(self, **kwargs):
            pass

        def list_plugins(self):
            return ()

        def install_many(self, bundles, **kwargs):
            installed.extend(path.name for path, digest in bundles)
            return (SimpleNamespace(changed=True, installation_path=tmp_path / "installed"),)

        def install(self, path, **kwargs):
            installed.append(path.name)
            return SimpleNamespace(changed=True, installation_path=tmp_path / "installed")

    result = ensure_first_party_plugins_from_environment(
        host_name="CandleScope", host_version="0.3.2",
        environ={"CANDLESCOPE_INDICATOR_RUNTIME_ROUTES": str(routes),
                 "CANDLESCOPE_RUNTIME_REGISTRY": str(tmp_path / "runtime-registry.json"),
                 "CANDLESCOPE_OFFICIAL_PLUGIN_BUNDLE": str(bundle)},
        release_lock_path=lock, installer_factory=Installer,
        opener=lambda *args, **kwargs: pytest.fail("local matching bundle must not download"),
    )
    assert result.status == "installed"
    assert installed == [selected.filename]


def test_release_lock_rejects_duplicate_platform_targets(tmp_path: Path) -> None:
    release = _release(b"bundle", runtime_id="candlescope.pine-compat")
    lock = _write_lock(tmp_path / "releases.json", release, replace(release, version="0.9.0"))
    with pytest.raises(FirstPartyPluginBootstrapError, match="duplicate runtime platform targets"):
        load_official_plugin_releases(lock)


def test_download_rejects_wrong_bytes_without_poisoning_cache(tmp_path: Path) -> None:
    release = _release(b"expected")

    with pytest.raises(FirstPartyPluginBootstrapError, match="pinned size"):
        download_official_plugin_bundle(
            release,
            tmp_path,
            opener=lambda *_args, **_kwargs: _Response(b"tampered!"),
        )

    assert not (tmp_path / release.filename).exists()
    assert list(tmp_path.glob("*.download")) == []


def test_ensure_installs_exact_local_override_as_required_runtime(
    tmp_path: Path,
) -> None:
    payload = b"local verified bundle"
    release = _release(payload)
    lock = _write_lock(tmp_path / "releases.json", release)
    bundle = tmp_path / release.filename
    bundle.write_bytes(payload)
    install_calls: list[dict[str, Any]] = []

    class Installer:
        def __init__(self, **kwargs: Any) -> None:
            self.registry_path = kwargs["registry_path"]

        def list_plugins(self) -> tuple[dict[str, Any], ...]:
            return ()

        def install(self, path: Path, **kwargs: Any) -> Any:
            install_calls.append({"path": path, **kwargs})
            return SimpleNamespace(
                changed=True,
                installation_path=tmp_path / "installed",
            )

    result = ensure_first_party_plugins_from_environment(
        host_name="CandleScope",
        host_version="0.3.0",
        environ=_single_pyne_environment(
            tmp_path,
            CANDLESCOPE_OFFICIAL_PLUGIN_BUNDLE=str(bundle),
        ),
        release_lock_path=lock,
        installer_factory=Installer,
    )

    assert result.status == "installed"
    assert result.changed is True
    assert result.downloaded is False
    assert install_calls == [
        {
            "path": bundle.resolve(),
            "expected_sha256": release.sha256,
            "enabled": True,
            "auto_start": True,
            "required": True,
        }
    ]


def test_ensure_checks_matching_activation_without_downloading(tmp_path: Path) -> None:
    payload = b"unused because activation already matches"
    release = _release(payload)
    lock = _write_lock(tmp_path / "releases.json", release)
    checks: list[str] = []

    class Installer:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def list_plugins(self) -> tuple[dict[str, Any], ...]:
            return (
                {
                    "runtimeId": release.runtime_id,
                    "version": release.version,
                    "bundleSha256": release.sha256,
                    "enabled": True,
                    "autoStart": True,
                    "required": True,
                    "managed": True,
                },
            )

        def check(self, runtime_id: str) -> Any:
            checks.append(runtime_id)
            return SimpleNamespace(activation_id="activation-1")

        def install(self, *_args: Any, **_kwargs: Any) -> Any:
            pytest.fail("matching activation must not install")

    result = ensure_first_party_plugins_from_environment(
        host_name="CandleScope",
        host_version="0.3.0",
        environ=_single_pyne_environment(tmp_path),
        release_lock_path=lock,
        opener=lambda *_args, **_kwargs: pytest.fail(
            "matching activation must not download"
        ),
        installer_factory=Installer,
    )

    assert result.status == "ready"
    assert result.changed is False
    assert result.reason == "checked:activation-1"
    assert checks == [release.runtime_id]


def test_ensure_never_replaces_an_unmanaged_community_activation(
    tmp_path: Path,
) -> None:
    release = _release(b"bundle")
    lock = _write_lock(tmp_path / "releases.json", release)

    class Installer:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def list_plugins(self) -> tuple[dict[str, Any], ...]:
            return ({"runtimeId": release.runtime_id, "managed": False},)

    with pytest.raises(
        FirstPartyPluginBootstrapError,
        match="refusing to replace an unmanaged runtime activation",
    ):
        ensure_first_party_plugins_from_environment(
            host_name="CandleScope",
            host_version="0.3.0",
            environ=_single_pyne_environment(tmp_path),
            release_lock_path=lock,
            installer_factory=Installer,
        )


@pytest.mark.parametrize("runtime_id", ["candlescope.pine-compat", "candlescope.pyne"])
@pytest.mark.parametrize("enabled,version,digest", [
    (True,"0.2.0","sha256:"+"ab"*32),
    (True,"0.3.3","sha256:"+"cd"*32),
    (False,"0.2.0","sha256:"+"ab"*32),
])
def test_bootstrap_preserves_verified_user_activation_and_disabled_choice(
    tmp_path, enabled, version, digest, runtime_id,
):
    release = _release(b"must not download", runtime_id=runtime_id)
    lock = _write_lock(tmp_path / "releases.json", release)
    checks = []

    class Installer:
        def __init__(self, **kwargs):
            pass

        def list_plugins(self):
            return ({"runtimeId":release.runtime_id,"managed":True,
                "package":release.package,"version":version,"bundleSha256":digest,
                "enabled":enabled,"autoStart":False,"required":False},)

        def check(self, runtime_id):
            checks.append(runtime_id)
            return SimpleNamespace(activation_id="user-activation")

        def install(self, *args, **kwargs):
            pytest.fail("bootstrap must not replace a verified user activation")

    routes = _write_routes(tmp_path / "routes.json",
        ("pine" if runtime_id == "candlescope.pine-compat" else "pyne", runtime_id))
    if runtime_id == "candlescope.pine-compat":
        # The route contract always names Pyne, even when this test selects
        # only Pine for first-party bootstrap.
        value = json.loads(routes.read_text())
        value["routes"].append({"language": "pyne", "mode": "legacy"})
        routes.write_text(json.dumps(value))
    result = ensure_first_party_plugins_from_environment(
        host_name="CandleScope",host_version="0.3.2",
        environ={"CANDLESCOPE_RUNTIME_REGISTRY": str(tmp_path / "runtime-registry.json"),
                 "CANDLESCOPE_INDICATOR_RUNTIME_ROUTES": str(routes)},
        release_lock_path=lock,
        installer_factory=Installer,
        opener=lambda *args,**kwargs:pytest.fail("must not download"))
    assert checks == [release.runtime_id]
    assert result.status == ("ready" if enabled else "skipped")
    assert result.version == version and result.bundle_sha256 == digest
    assert not result.changed and not result.downloaded


@pytest.mark.parametrize("matches", [True, False])
def test_explicit_local_pin_is_checked_without_downloading_or_downgrading(tmp_path, matches):
    release = _release(b"official")
    lock = _write_lock(tmp_path / "releases.json", release)
    registry = tmp_path / "runtime-registry.json"
    pin = {"version": "0.4.0", "bundleSha256": "sha256:" + "ab" * 32}
    (tmp_path / "first-party-local-overrides.json").write_text(json.dumps(
        {"schemaVersion": 1, "runtimes": {release.runtime_id: pin}}), encoding="utf-8")
    class Installer:
        def __init__(self, **kwargs): pass
        def list_plugins(self):
            return [{"runtimeId": release.runtime_id, **pin, "version": "0.4.0" if matches else "0.3.0",
                     "managed": True, "enabled": True, "autoStart": True, "required": True}]
        def check(self, runtime_id):
            assert runtime_id == release.runtime_id
            return SimpleNamespace(activation_id="local-1")
        def install(self, *args, **kwargs): pytest.fail("must not replace a pinned local install")
    kwargs = dict(host_name="CandleScope", host_version="0.3.0",
                  environ=_single_pyne_environment(tmp_path, CANDLESCOPE_RUNTIME_REGISTRY=str(registry)),
                  release_lock_path=lock, installer_factory=Installer,
                  opener=lambda *args, **kwargs: pytest.fail("must not download"))
    if matches:
        result = ensure_first_party_plugins_from_environment(**kwargs)
        assert result.version == "0.4.0" and result.reason == "local-pin-checked:local-1"
    else:
        with pytest.raises(FirstPartyPluginBootstrapError, match="local runtime pin does not match"):
            ensure_first_party_plugins_from_environment(**kwargs)


def test_multi_runtime_bootstrap_verifies_then_installs_in_runtime_order(
    tmp_path: Path,
) -> None:
    pyne_payload = b"pyne bundle"
    pine_payload = b"pine bundle"
    pyne = _release(pyne_payload)
    pine = _release(pine_payload, runtime_id="candlescope.pine-compat")
    lock = _write_lock(tmp_path / "releases.json", pyne, pine)
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / pyne.filename).write_bytes(pyne_payload)
    (bundles / pine.filename).write_bytes(pine_payload)
    installs: list[str] = []

    class Installer:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def list_plugins(self) -> tuple[dict[str, Any], ...]:
            return ()

        def install_many(
            self,
            bundles: tuple[tuple[Path, str], ...],
            **_kwargs: Any,
        ) -> tuple[Any, ...]:
            installs.extend(path.name for path, _sha256 in bundles)
            return tuple(
                SimpleNamespace(
                    changed=True,
                    installation_path=tmp_path / "installed" / path.stem,
                )
                for path, _sha256 in bundles
            )

    result = ensure_first_party_plugins_from_environment(
        host_name="CandleScope",
        host_version="0.3.0",
        environ={
            "LOCALAPPDATA": str(tmp_path / "local-app-data"),
            "CANDLESCOPE_OFFICIAL_PLUGIN_BUNDLE": str(bundles),
        },
        release_lock_path=lock,
        installer_factory=Installer,
    )

    assert installs == [pine.filename, pyne.filename]
    assert result.status == "installed"
    assert result.changed is True
    assert result.downloaded is False
    assert [item.runtime_id for item in result.plugins] == [
        "candlescope.pine-compat",
        "candlescope.pyne",
    ]
    wire = result.to_wire()
    assert wire["count"] == 2
    assert [item["status"] for item in wire["plugins"]] == [
        "installed",
        "installed",
    ]


def test_multi_runtime_bootstrap_verifies_every_bundle_before_install(
    tmp_path: Path,
) -> None:
    pyne = _release(b"expected pyne")
    pine = _release(b"expected pine", runtime_id="candlescope.pine-compat")
    lock = _write_lock(tmp_path / "releases.json", pyne, pine)
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / pine.filename).write_bytes(b"expected pine")
    (bundles / pyne.filename).write_bytes(b"tampered")
    installs: list[str] = []

    class Installer:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def list_plugins(self) -> tuple[dict[str, Any], ...]:
            return ()

        def install(self, path: Path, **_kwargs: Any) -> Any:
            installs.append(path.name)
            pytest.fail("no install may happen before every bundle is verified")

    with pytest.raises(FirstPartyPluginBootstrapError, match="pinned size"):
        ensure_first_party_plugins_from_environment(
            host_name="CandleScope",
            host_version="0.3.0",
            environ={
                "LOCALAPPDATA": str(tmp_path / "local-app-data"),
                "CANDLESCOPE_OFFICIAL_PLUGIN_BUNDLE": str(bundles),
            },
            release_lock_path=lock,
            installer_factory=Installer,
        )

    assert installs == []


def test_multi_runtime_internal_bundle_failure_never_partially_activates(
    tmp_path: Path,
) -> None:
    pine_fixture = build_hello_bundle(
        tmp_path / "pine-source",
        version="0.2.0",
        runtime_id="candlescope.pine-compat",
    )
    pine_payload = pine_fixture.bundle.path.read_bytes()
    pyne_payload = b"outer-digest-valid but not a plugin bundle"
    pine = _release(pine_payload, runtime_id="candlescope.pine-compat")
    pyne = _release(pyne_payload)
    lock = _write_lock(tmp_path / "releases.json", pine, pyne)
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / pine.filename).write_bytes(pine_payload)
    (bundles / pyne.filename).write_bytes(pyne_payload)
    registry = tmp_path / "plugins" / "runtime-registry.json"

    with pytest.raises(PluginBundleError):
        ensure_first_party_plugins_from_environment(
            host_name="CandleScope",
            host_version="0.3.0",
            environ={
                "LOCALAPPDATA": str(tmp_path / "local-app-data"),
                "CANDLESCOPE_RUNTIME_REGISTRY": str(registry),
                "CANDLESCOPE_OFFICIAL_PLUGIN_BUNDLE": str(bundles),
            },
            release_lock_path=lock,
        )

    assert load_runtime_registry(registry, allow_missing=True).plugins == ()


def test_default_routes_fail_closed_when_a_first_party_release_is_missing(
    tmp_path: Path,
) -> None:
    pyne = _release(b"pyne")
    lock = _write_lock(tmp_path / "releases.json", pyne)

    with pytest.raises(
        FirstPartyPluginBootstrapError,
        match="missing routed first-party runtimes: candlescope.pine-compat",
    ):
        ensure_first_party_plugins_from_environment(
            host_name="CandleScope",
            host_version="0.3.0",
            environ={"LOCALAPPDATA": str(tmp_path / "local-app-data")},
            release_lock_path=lock,
        )


def test_ensure_skips_when_no_official_bundle_matches_the_host(
    tmp_path: Path,
) -> None:
    payload = b"windows-only bundle"
    release = OfficialPluginRelease(
        runtime_id="candlescope.pyne",
        package="candlescope-plugin-pyne",
        version="0.2.0",
        filename="candlescope-pyne-test.cspkg",
        url="https://github.com/helenananaa/CandleScope/releases/download/test/test.cspkg",
        sha256=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        size=len(payload),
        system="NotThisHost",
        machine="AMD64",
        implementation="CPython",
        python_version="3.12",
    )
    lock = _write_lock(tmp_path / "releases.json", release)

    result = ensure_first_party_plugins_from_environment(
        host_name="CandleScope",
        host_version="0.3.0",
        environ=_single_pyne_environment(tmp_path),
        release_lock_path=lock,
        opener=lambda *_args, **_kwargs: pytest.fail(
            "unsupported host must not download"
        ),
        installer_factory=lambda **_kwargs: pytest.fail(
            "unsupported host must not install"
        ),
    )

    assert result.status == "skipped"
    assert result.reason == "unsupported-host-platform"
    assert [item.runtime_id for item in result.plugins] == ["candlescope.pyne"]
    assert result.to_wire()["reason"] == "unsupported-host-platform"


def test_bootstrap_can_be_disabled_without_reading_release_state(
    tmp_path: Path,
) -> None:
    result = ensure_first_party_plugins_from_environment(
        host_name="CandleScope",
        host_version="0.3.0",
        environ={
            "LOCALAPPDATA": str(tmp_path),
            "CANDLESCOPE_OFFICIAL_PLUGIN_BOOTSTRAP": "0",
        },
        release_lock_path=tmp_path / "missing.json",
    )

    assert result.to_wire() == {
        "status": "skipped",
        "changed": False,
        "downloaded": False,
        "reason": "official-bootstrap-disabled",
    }
