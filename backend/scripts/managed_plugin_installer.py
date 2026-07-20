"""Verified, idempotent installation for CandleScope-managed plugins.

The orchestration is plugin-neutral. A checked-in registry selects plugin lock
files; an installer driver handles an artifact kind; and a host-owned probe
verifies semantics after installation. The first driver supports pinned Python
wheels without dependency or source-build fallback.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import sysconfig
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__:
    from .managed_plugin_probes import ProbeError, run_probe, validate_probe_config
else:  # Direct operational scripts import this module from their own directory.
    from managed_plugin_probes import ProbeError, run_probe, validate_probe_config


REGISTRY_SCHEMA_VERSION = 1
PLUGIN_LOCK_SCHEMA_VERSION = 1
RELEASE_MANIFEST_SCHEMA_VERSION = 1
INSTALL_STAMP_SCHEMA_VERSION = 2
LEGACY_INSTALL_STAMP_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 200 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_PYTHON_REQUIRES = re.compile(r"^>=(\d+)\.(\d+)$")
_PYTHON_TAG = re.compile(r"^(?:py3|cp\d{2,3})$")


class InstallerError(RuntimeError):
    """A fail-closed managed plugin installer error."""


@dataclass(frozen=True, slots=True)
class PluginLock:
    path: Path
    plugin_id: str
    display_name: str
    installer_kind: str
    package: str
    module: str
    version: str
    python_requires: str
    python_tag: str
    abi_tag: str
    upstream: str
    source_commit: str
    tag: str
    release_commit: str
    manifest_url: str
    manifest_sha256: str
    asset_base_url: str
    probe_kind: str
    probe_config: Mapping[str, Any]
    legacy_stamp_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ManagedPlugin:
    lock: PluginLock
    auto_install: bool


@dataclass(frozen=True, slots=True)
class ManagedStamp:
    value: Mapping[str, Any]
    path: Path
    legacy: bool


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "CANDLESCOPE_PLUGINS.json"


def default_cache_dir() -> Path:
    override = os.environ.get("CANDLESCOPE_PLUGIN_CACHE_DIR")
    if not override:
        override = os.environ.get("CANDLESCOPE_RUNTIME_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            # Keep the established directory so existing verified Pine assets
            # remain reusable after moving to the generic plugin layer.
            return Path(base) / "CandleScope" / "runtime-cache"
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base_path = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return base_path / "candlescope" / "runtime-cache"


def install_stamp_path(plugin_id: str, prefix: Path | None = None) -> Path:
    if not _PLUGIN_ID.fullmatch(plugin_id):
        raise InstallerError(f"invalid managed plugin id {plugin_id!r}")
    environment_prefix = prefix or Path(sys.prefix)
    return environment_prefix / ".candlescope" / "plugins" / f"{plugin_id}.json"


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InstallerError(f"{label} must be a JSON object")
    return value


def _require_string(value: Mapping[str, Any], key: str, label: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise InstallerError(f"{label}.{key} must be a non-empty string")
    return result.strip()


def _require_positive_int(value: Mapping[str, Any], key: str, label: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int) or result <= 0:
        raise InstallerError(f"{label}.{key} must be a positive integer")
    return result


def _require_bool(value: Mapping[str, Any], key: str, label: str) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        raise InstallerError(f"{label}.{key} must be a boolean")
    return result


def _validate_https_url(url: str, label: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise InstallerError(f"{label} must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise InstallerError(f"{label} contains unsupported URL components")


def _decode_json(data: bytes, label: str) -> Mapping[str, Any]:
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallerError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    return _require_mapping(decoded, label)


def _read_json_file(path: Path, label: str) -> Mapping[str, Any]:
    try:
        return _decode_json(path.read_bytes(), label)
    except OSError as exc:
        raise InstallerError(f"unable to read {label} {path}: {exc}") from exc


def _upgrade_legacy_pine_lock(root: Mapping[str, Any]) -> Mapping[str, Any]:
    """Adapt the shipped schema-v2 Pine lock without breaking its public path."""

    plugin_id = _require_string(root, "runtimeId", "legacy Pine runtime lock")
    if plugin_id != "pine-compat":
        raise InstallerError(
            "legacy runtime lock schema 2 is supported only for runtimeId 'pine-compat'"
        )
    package = _require_string(root, "package", "legacy Pine runtime lock")
    module = _require_string(root, "pythonModule", "legacy Pine runtime lock")
    version = _require_string(root, "version", "legacy Pine runtime lock")
    upstream = _require_string(root, "upstream", "legacy Pine runtime lock").rstrip("/")
    source_commit = _require_string(root, "commit", "legacy Pine runtime lock")
    analysis_schema = _require_positive_int(
        root, "analysisSchemaVersion", "legacy Pine runtime lock"
    )
    runtime_schema = _require_positive_int(
        root, "runtimeSchemaVersion", "legacy Pine runtime lock"
    )
    release = _require_mapping(root.get("release"), "legacy Pine runtime lock.release")
    tag = _require_string(release, "tag", "legacy Pine runtime lock.release")
    manifest_url = _require_string(
        release, "manifestUrl", "legacy Pine runtime lock.release"
    )
    asset_base_url = _require_string(
        release, "assetBaseUrl", "legacy Pine runtime lock.release"
    ).rstrip("/")
    expected_base_url = f"{upstream}/releases/download/{tag}"
    if tag != f"v{version}":
        raise InstallerError(
            f"legacy Pine release tag {tag!r} does not match version {version!r}"
        )
    if asset_base_url != expected_base_url or manifest_url != f"{expected_base_url}/manifest.json":
        raise InstallerError("legacy Pine release URLs are outside the pinned GitHub release")

    return {
        "schemaVersion": PLUGIN_LOCK_SCHEMA_VERSION,
        "pluginId": plugin_id,
        "displayName": "Pine-compatible runtime",
        "installer": {
            "kind": "python-wheel",
            "package": package,
            "pythonModule": module,
            "version": version,
            "pythonRequires": ">=3.10",
            "pythonTag": "cp310",
            "abiTag": "abi3",
        },
        "source": {"url": upstream, "commit": source_commit},
        "release": dict(release),
        "verification": {
            "probe": "pine-runtime-v1",
            "analysisSchemaVersion": analysis_schema,
            "runtimeSchemaVersion": runtime_schema,
        },
        "legacyStampFiles": ["pine-runtime-install.json"],
    }


def load_plugin_lock(path: Path | str) -> PluginLock:
    lock_path = Path(path).expanduser().resolve()
    root = _read_json_file(lock_path, "managed plugin lock")
    schema_version = root.get("schemaVersion")
    if schema_version == 2:
        root = _upgrade_legacy_pine_lock(root)
    elif schema_version != PLUGIN_LOCK_SCHEMA_VERSION:
        raise InstallerError(
            f"unsupported managed plugin lock schema: {schema_version!r}; "
            f"expected {PLUGIN_LOCK_SCHEMA_VERSION}"
        )

    plugin_id = _require_string(root, "pluginId", "managed plugin lock")
    if not _PLUGIN_ID.fullmatch(plugin_id):
        raise InstallerError("managed plugin lock.pluginId has an invalid format")
    display_name = _require_string(root, "displayName", "managed plugin lock")

    installer = _require_mapping(root.get("installer"), "managed plugin lock.installer")
    installer_kind = _require_string(installer, "kind", "managed plugin lock.installer")
    if installer_kind != "python-wheel":
        raise InstallerError(f"unsupported managed plugin installer {installer_kind!r}")
    package = _require_string(installer, "package", "managed plugin lock.installer")
    module = _require_string(installer, "pythonModule", "managed plugin lock.installer")
    version = _require_string(installer, "version", "managed plugin lock.installer")
    python_requires = _require_string(
        installer, "pythonRequires", "managed plugin lock.installer"
    )
    if not _PYTHON_REQUIRES.fullmatch(python_requires):
        raise InstallerError(
            "managed plugin lock.installer.pythonRequires must use the >=X.Y form"
        )
    python_tag = _require_string(
        installer, "pythonTag", "managed plugin lock.installer"
    ).lower()
    abi_tag = _require_string(installer, "abiTag", "managed plugin lock.installer").lower()
    if not _PYTHON_TAG.fullmatch(python_tag):
        raise InstallerError("managed plugin lock.installer.pythonTag is unsupported")
    if python_tag == "py3" and abi_tag != "none":
        raise InstallerError("py3 managed plugin wheels must use the none ABI")
    if python_tag.startswith("cp") and abi_tag not in {"abi3", python_tag}:
        raise InstallerError("CPython managed plugin wheels must use abi3 or a matching ABI")

    source = _require_mapping(root.get("source"), "managed plugin lock.source")
    upstream = _require_string(source, "url", "managed plugin lock.source").rstrip("/")
    source_commit = _require_string(
        source, "commit", "managed plugin lock.source"
    ).lower()
    if not _HEX_40.fullmatch(source_commit):
        raise InstallerError("managed plugin lock.source.commit must be a 40-character Git SHA")
    _validate_https_url(upstream, "managed plugin lock.source.url")

    release = _require_mapping(root.get("release"), "managed plugin lock.release")
    tag = _require_string(release, "tag", "managed plugin lock.release")
    release_commit = _require_string(
        release, "commit", "managed plugin lock.release"
    ).lower()
    manifest_url = _require_string(
        release, "manifestUrl", "managed plugin lock.release"
    )
    manifest_sha256 = _require_string(
        release, "manifestSha256", "managed plugin lock.release"
    ).lower()
    asset_base_url = _require_string(
        release, "assetBaseUrl", "managed plugin lock.release"
    ).rstrip("/")
    if not _HEX_40.fullmatch(release_commit):
        raise InstallerError(
            "managed plugin lock.release.commit must be a 40-character Git SHA"
        )
    if not _HEX_64.fullmatch(manifest_sha256):
        raise InstallerError(
            "managed plugin lock.release.manifestSha256 must be a SHA-256 digest"
        )
    _validate_https_url(manifest_url, "managed plugin lock.release.manifestUrl")
    _validate_https_url(asset_base_url, "managed plugin lock.release.assetBaseUrl")
    if manifest_url != f"{asset_base_url}/manifest.json":
        raise InstallerError(
            "managed plugin lock manifest URL must be manifest.json under assetBaseUrl"
        )

    verification = _require_mapping(
        root.get("verification"), "managed plugin lock.verification"
    )
    probe_kind = _require_string(
        verification, "probe", "managed plugin lock.verification"
    )
    try:
        validate_probe_config(probe_kind, verification)
    except ProbeError as exc:
        raise InstallerError(str(exc)) from exc

    raw_legacy_files = root.get("legacyStampFiles", [])
    if not isinstance(raw_legacy_files, list):
        raise InstallerError("managed plugin lock.legacyStampFiles must be a list")
    legacy_stamp_files: list[str] = []
    for index, value in enumerate(raw_legacy_files):
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != Path(value).name
            or value in {".", ".."}
        ):
            raise InstallerError(
                f"managed plugin lock.legacyStampFiles[{index}] must be a plain file name"
            )
        if value in legacy_stamp_files:
            raise InstallerError(f"duplicate legacy stamp file {value!r}")
        legacy_stamp_files.append(value)

    return PluginLock(
        path=lock_path,
        plugin_id=plugin_id,
        display_name=display_name,
        installer_kind=installer_kind,
        package=package,
        module=module,
        version=version,
        python_requires=python_requires,
        python_tag=python_tag,
        abi_tag=abi_tag,
        upstream=upstream,
        source_commit=source_commit,
        tag=tag,
        release_commit=release_commit,
        manifest_url=manifest_url,
        manifest_sha256=manifest_sha256,
        asset_base_url=asset_base_url,
        probe_kind=probe_kind,
        probe_config=dict(verification),
        legacy_stamp_files=tuple(legacy_stamp_files),
    )


def load_plugin_registry(path: Path | str = default_registry_path()) -> list[ManagedPlugin]:
    registry_path = Path(path).expanduser().resolve()
    root = _read_json_file(registry_path, "managed plugin registry")
    if root.get("schemaVersion") != REGISTRY_SCHEMA_VERSION:
        raise InstallerError(
            f"unsupported managed plugin registry schema: {root.get('schemaVersion')!r}; "
            f"expected {REGISTRY_SCHEMA_VERSION}"
        )
    raw_plugins = root.get("plugins")
    if not isinstance(raw_plugins, list):
        raise InstallerError("managed plugin registry.plugins must be a list")

    result: list[ManagedPlugin] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    for index, raw_plugin in enumerate(raw_plugins):
        label = f"managed plugin registry.plugins[{index}]"
        registration = _require_mapping(raw_plugin, label)
        expected_id = _require_string(registration, "id", label)
        raw_lock_path = _require_string(registration, "lockFile", label)
        if Path(raw_lock_path).is_absolute():
            raise InstallerError(f"{label}.lockFile must be relative to the registry")
        lock_path = (registry_path.parent / raw_lock_path).resolve()
        if lock_path in seen_paths:
            raise InstallerError(f"managed plugin registry repeats lock {lock_path}")
        lock = load_plugin_lock(lock_path)
        if expected_id != lock.plugin_id:
            raise InstallerError(
                f"{label}.id {expected_id!r} does not match lock pluginId "
                f"{lock.plugin_id!r}"
            )
        if lock.plugin_id in seen_ids:
            raise InstallerError(f"duplicate managed plugin id {lock.plugin_id!r}")
        seen_ids.add(lock.plugin_id)
        seen_paths.add(lock_path)
        result.append(
            ManagedPlugin(
                lock=lock,
                auto_install=_require_bool(registration, "autoInstall", label),
            )
        )
    return result


def select_plugins(
    plugins: Sequence[ManagedPlugin],
    *,
    requested: Sequence[str] = (),
    excluded: Sequence[str] = (),
) -> list[ManagedPlugin]:
    by_id = {plugin.lock.plugin_id: plugin for plugin in plugins}
    unknown_requested = [plugin_id for plugin_id in requested if plugin_id not in by_id]
    unknown_excluded = [plugin_id for plugin_id in excluded if plugin_id not in by_id]
    if unknown_requested:
        raise InstallerError(
            f"unknown managed plugin(s): {', '.join(dict.fromkeys(unknown_requested))}"
        )
    if unknown_excluded:
        raise InstallerError(
            "cannot exclude unknown managed plugin(s): "
            + ", ".join(dict.fromkeys(unknown_excluded))
        )
    excluded_ids = set(excluded)
    if requested:
        ordered_ids = list(dict.fromkeys(requested))
        return [by_id[plugin_id] for plugin_id in ordered_ids if plugin_id not in excluded_ids]
    return [
        plugin
        for plugin in plugins
        if plugin.auto_install and plugin.lock.plugin_id not in excluded_ids
    ]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_matches(
    path: Path, expected_sha256: str, expected_size: int | None = None
) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    if not path.is_file() or (
        expected_size is not None and stat.st_size != expected_size
    ):
        return False
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_sha256


def validate_release_manifest(data: bytes, lock: PluginLock) -> Mapping[str, Any]:
    actual_digest = _sha256_bytes(data)
    if actual_digest != lock.manifest_sha256:
        raise InstallerError(
            f"{lock.display_name} release manifest SHA-256 mismatch: "
            f"expected {lock.manifest_sha256}, got {actual_digest}"
        )
    manifest = _decode_json(data, f"{lock.plugin_id} release manifest")
    expected_fields = {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "channel": "stable",
        "distribution": lock.package,
        "module": lock.module,
        "version": lock.version,
        "tag": lock.tag,
        "commit": lock.release_commit,
        "python_requires": lock.python_requires,
    }
    for key, expected in expected_fields.items():
        if manifest.get(key) != expected:
            raise InstallerError(
                f"{lock.plugin_id} release manifest {key!r} mismatch: "
                f"expected {expected!r}, got {manifest.get(key)!r}"
            )

    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise InstallerError(
            f"{lock.plugin_id} release manifest.assets must be a non-empty list"
        )
    seen_names: set[str] = set()
    distribution = re.sub(r"[-_.]+", "_", lock.package)
    for index, raw_asset in enumerate(assets):
        label = f"{lock.plugin_id} release manifest.assets[{index}]"
        asset = _require_mapping(raw_asset, label)
        filename = _require_string(asset, "filename", label)
        if filename != Path(filename).name or filename in {".", ".."}:
            raise InstallerError(f"{label}.filename must be a plain file name")
        python_tag = _require_string(asset, "python_tag", label).lower()
        abi_tag = _require_string(asset, "abi_tag", label).lower()
        platform_tag = _require_string(asset, "platform_tag", label).lower()
        expected_filename = (
            f"{distribution}-{lock.version}-{python_tag}-{abi_tag}-{platform_tag}.whl"
        )
        if filename.lower() != expected_filename.lower():
            raise InstallerError(f"{label}.filename does not match its wheel tags")
        if filename in seen_names:
            raise InstallerError(f"release manifest contains duplicate asset {filename!r}")
        seen_names.add(filename)
        if python_tag != lock.python_tag:
            raise InstallerError(
                f"{label} targets Python tag {python_tag!r}, expected {lock.python_tag!r}"
            )
        if abi_tag != lock.abi_tag:
            raise InstallerError(
                f"{label} targets ABI {abi_tag!r}, expected {lock.abi_tag!r}"
            )
        digest = _require_string(asset, "sha256", label).lower()
        if not _HEX_64.fullmatch(digest):
            raise InstallerError(f"{label}.sha256 must be a SHA-256 digest")
        size = _require_positive_int(asset, "size", label)
        if size > MAX_ARTIFACT_BYTES:
            raise InstallerError(f"{label}.size exceeds the installer safety limit")
    return manifest


def _minimum_python(lock: PluginLock) -> tuple[int, int]:
    match = _PYTHON_REQUIRES.fullmatch(lock.python_requires)
    if match is None:  # load_plugin_lock already validates this.
        raise InstallerError(f"invalid Python requirement {lock.python_requires!r}")
    return int(match.group(1)), int(match.group(2))


def _platform_tag_matches(
    platform_tag: str, *, sys_platform: str, machine: str
) -> bool:
    tags = platform_tag.lower().split(".")
    if "any" in tags:
        return True
    normalized_machine = machine.strip().lower().replace("-", "_")
    if sys_platform == "win32":
        expected = {
            "amd64": "win_amd64",
            "x86_64": "win_amd64",
            "arm64": "win_arm64",
            "aarch64": "win_arm64",
            "x86": "win32",
            "i386": "win32",
        }.get(normalized_machine)
        return expected is not None and expected in tags
    if sys_platform.startswith("linux"):
        architecture = {
            "amd64": "x86_64",
            "x86_64": "x86_64",
            "arm64": "aarch64",
            "aarch64": "aarch64",
        }.get(normalized_machine)
        if architecture is None:
            return False
        return any(
            tag.endswith(f"_{architecture}")
            and (tag.startswith("manylinux") or tag.startswith("linux"))
            for tag in tags
        )
    return False


def select_release_asset(
    manifest: Mapping[str, Any],
    lock: PluginLock,
    *,
    sys_platform: str | None = None,
    machine: str | None = None,
    python_implementation: str | None = None,
    python_version: tuple[int, int] | None = None,
    gil_disabled: bool | None = None,
) -> Mapping[str, Any]:
    current_platform = sys_platform or sys.platform
    current_machine = machine or platform.machine()
    implementation = python_implementation or platform.python_implementation()
    version = python_version or (sys.version_info.major, sys.version_info.minor)
    if gil_disabled is None:
        gil_disabled = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    minimum = _minimum_python(lock)

    if version < minimum:
        raise InstallerError(
            f"{lock.display_name} requires Python {minimum[0]}.{minimum[1]}+, "
            f"found {version[0]}.{version[1]}"
        )
    if lock.python_tag.startswith("cp"):
        if implementation != "CPython":
            raise InstallerError(
                f"{lock.display_name} binary wheels require CPython, found {implementation}"
            )
        tag_digits = lock.python_tag[2:]
        tag_version = (int(tag_digits[0]), int(tag_digits[1:]))
        if lock.abi_tag == "abi3":
            if version < tag_version:
                raise InstallerError(
                    f"{lock.display_name} wheel ABI requires CPython "
                    f"{tag_version[0]}.{tag_version[1]}+"
                )
            if gil_disabled:
                raise InstallerError(
                    f"free-threaded CPython is not supported by {lock.display_name}'s "
                    "abi3 wheel"
                )
        elif version != tag_version or gil_disabled:
            raise InstallerError(
                f"{lock.display_name} requires the exact {lock.python_tag} CPython ABI"
            )

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise InstallerError(f"{lock.plugin_id} release manifest.assets is invalid")
    candidates = [
        asset
        for asset in assets
        if isinstance(asset, Mapping)
        and _platform_tag_matches(
            str(asset.get("platform_tag") or ""),
            sys_platform=current_platform,
            machine=current_machine,
        )
    ]
    if len(candidates) != 1:
        normalized_machine = current_machine.strip().lower().replace("-", "_")
        if not candidates:
            raise InstallerError(
                f"no {lock.display_name} wheel for platform {current_platform!r} "
                f"and architecture {normalized_machine or 'unknown'}"
            )
        raise InstallerError(
            f"expected exactly one compatible {lock.display_name} wheel, "
            f"found {len(candidates)}"
        )
    return _require_mapping(candidates[0], "selected release asset")


def _request(url: str) -> urllib.request.Request:
    _validate_https_url(url, "download URL")
    return urllib.request.Request(
        url,
        headers={"User-Agent": "CandleScope-Managed-Plugin-Installer/1"},
        method="GET",
    )


def _read_url_limited(url: str, *, timeout: float, limit: int) -> bytes:
    try:
        with urllib.request.urlopen(_request(url), timeout=timeout) as response:
            data = response.read(limit + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise InstallerError(f"unable to download {url}: {exc}") from exc
    if len(data) > limit:
        raise InstallerError(f"download from {url} exceeds the {limit}-byte safety limit")
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def load_pinned_manifest(
    lock: PluginLock,
    *,
    cache_dir: Path,
    offline: bool,
    timeout: float,
) -> Mapping[str, Any]:
    manifest_path = cache_dir / lock.package / lock.tag / "manifest.json"
    try:
        cached_data = manifest_path.read_bytes()
    except OSError:
        cached_data = None
    if cached_data is not None:
        try:
            return validate_release_manifest(cached_data, lock)
        except InstallerError:
            if offline:
                raise
    if offline:
        raise InstallerError(f"offline mode requires cached manifest {manifest_path}")

    data = _read_url_limited(lock.manifest_url, timeout=timeout, limit=MAX_MANIFEST_BYTES)
    manifest = validate_release_manifest(data, lock)
    _atomic_write(manifest_path, data)
    return manifest


def _download_artifact(
    url: str,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    timeout: float,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    digest = hashlib.sha256()
    size = 0
    try:
        try:
            response = urllib.request.urlopen(_request(url), timeout=timeout)
        except (OSError, urllib.error.URLError) as exc:
            raise InstallerError(f"unable to download {url}: {exc}") from exc
        with response, temporary.open("wb") as handle:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > expected_size or size > MAX_ARTIFACT_BYTES:
                    raise InstallerError("downloaded plugin artifact exceeds its pinned size")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size != expected_size:
            raise InstallerError(
                f"downloaded plugin artifact size mismatch: expected {expected_size}, "
                f"got {size}"
            )
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise InstallerError(
                "downloaded plugin artifact SHA-256 mismatch: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def ensure_cached_artifact(
    lock: PluginLock,
    asset: Mapping[str, Any],
    *,
    cache_dir: Path,
    offline: bool,
    timeout: float,
) -> Path:
    filename = _require_string(asset, "filename", "selected release asset")
    expected_sha256 = _require_string(
        asset, "sha256", "selected release asset"
    ).lower()
    expected_size = _require_positive_int(asset, "size", "selected release asset")
    artifact_path = cache_dir / lock.package / lock.tag / filename
    if _file_matches(artifact_path, expected_sha256, expected_size):
        return artifact_path
    if offline:
        raise InstallerError(
            f"offline mode requires a verified cached plugin artifact at {artifact_path}"
        )
    asset_url = f"{lock.asset_base_url}/{urllib.parse.quote(filename)}"
    _download_artifact(
        asset_url,
        artifact_path,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
        timeout=timeout,
    )
    if not _file_matches(artifact_path, expected_sha256, expected_size):
        raise InstallerError("cached plugin artifact failed verification after download")
    return artifact_path


def _validate_artifact_identity(stamp: Mapping[str, Any], *, legacy: bool) -> None:
    filename_key = "wheelFilename" if legacy else "artifactFilename"
    digest_key = "wheelSha256" if legacy else "artifactSha256"
    filename = stamp.get(filename_key)
    digest = stamp.get(digest_key)
    if not isinstance(filename, str) or filename != Path(filename).name:
        raise InstallerError("managed install stamp has an invalid artifact filename")
    if not isinstance(digest, str) or not _HEX_64.fullmatch(digest):
        raise InstallerError("managed install stamp has an invalid artifact SHA-256")


def _validate_stamp_value(
    lock: PluginLock, stamp: Mapping[str, Any], *, legacy: bool
) -> None:
    if legacy:
        expected = {
            "schemaVersion": LEGACY_INSTALL_STAMP_SCHEMA_VERSION,
            "package": lock.package,
            "version": lock.version,
            "tag": lock.tag,
            "releaseCommit": lock.release_commit,
            "manifestSha256": lock.manifest_sha256,
        }
    else:
        expected = {
            "schemaVersion": INSTALL_STAMP_SCHEMA_VERSION,
            "pluginId": lock.plugin_id,
            "installerKind": lock.installer_kind,
            "package": lock.package,
            "version": lock.version,
            "tag": lock.tag,
            "releaseCommit": lock.release_commit,
            "manifestSha256": lock.manifest_sha256,
        }
    for key, expected_value in expected.items():
        if stamp.get(key) != expected_value:
            raise InstallerError(
                f"managed install stamp {key!r} mismatch: "
                f"expected {expected_value!r}, got {stamp.get(key)!r}"
            )
    _validate_artifact_identity(stamp, legacy=legacy)


def load_managed_stamp(
    lock: PluginLock, *, prefix: Path | None = None
) -> ManagedStamp:
    canonical_path = install_stamp_path(lock.plugin_id, prefix)
    if canonical_path.exists():
        stamp = _read_json_file(canonical_path, "managed plugin install stamp")
        _validate_stamp_value(lock, stamp, legacy=False)
        return ManagedStamp(value=stamp, path=canonical_path, legacy=False)

    environment_prefix = prefix or Path(sys.prefix)
    for filename in lock.legacy_stamp_files:
        legacy_path = environment_prefix / ".candlescope" / filename
        if not legacy_path.exists():
            continue
        stamp = _read_json_file(legacy_path, "legacy managed plugin install stamp")
        _validate_stamp_value(lock, stamp, legacy=True)
        return ManagedStamp(value=stamp, path=legacy_path, legacy=True)
    raise InstallerError(f"managed install stamp is missing: {canonical_path}")


def validate_install_stamp(
    lock: PluginLock,
    *,
    path: Path | None = None,
    prefix: Path | None = None,
) -> Mapping[str, Any]:
    if path is None:
        return load_managed_stamp(lock, prefix=prefix).value
    stamp = _read_json_file(path, "managed plugin install stamp")
    legacy = stamp.get("schemaVersion") == LEGACY_INSTALL_STAMP_SCHEMA_VERSION
    _validate_stamp_value(lock, stamp, legacy=legacy)
    return stamp


def write_install_stamp(
    lock: PluginLock,
    asset: Mapping[str, Any],
    *,
    path: Path | None = None,
    prefix: Path | None = None,
) -> Path:
    stamp_path = path or install_stamp_path(lock.plugin_id, prefix)
    stamp = {
        "schemaVersion": INSTALL_STAMP_SCHEMA_VERSION,
        "pluginId": lock.plugin_id,
        "installerKind": lock.installer_kind,
        "package": lock.package,
        "version": lock.version,
        "tag": lock.tag,
        "releaseCommit": lock.release_commit,
        "manifestSha256": lock.manifest_sha256,
        "artifactFilename": _require_string(
            asset, "filename", "selected release asset"
        ),
        "artifactSha256": _require_string(
            asset, "sha256", "selected release asset"
        ).lower(),
    }
    data = (json.dumps(stamp, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(stamp_path, data)
    return stamp_path


def migrate_legacy_stamp(
    lock: PluginLock,
    managed_stamp: ManagedStamp,
    *,
    prefix: Path | None = None,
) -> Path:
    if not managed_stamp.legacy:
        return managed_stamp.path
    asset = {
        "filename": managed_stamp.value.get("wheelFilename"),
        "sha256": managed_stamp.value.get("wheelSha256"),
    }
    return write_install_stamp(lock, asset, prefix=prefix)


def probe_in_current_process(
    lock: PluginLock,
    *,
    require_stamp: bool = True,
) -> dict[str, Any]:
    try:
        managed_stamp = load_managed_stamp(lock) if require_stamp else None
        installed_version = importlib.metadata.version(lock.package)
        if installed_version != lock.version:
            raise InstallerError(
                f"installed version is {installed_version}, expected {lock.version}"
            )
        module = importlib.import_module(lock.module)
        probe_details = run_probe(lock.probe_kind, module, lock.probe_config)
        result: dict[str, Any] = {
            "ok": True,
            "pluginId": lock.plugin_id,
            "package": lock.package,
            "version": installed_version,
            "module": lock.module,
            "sourcePath": str(getattr(module, "__file__", "") or ""),
            "managedRelease": (
                dict(managed_stamp.value) if managed_stamp is not None else None
            ),
            "managedStampPath": (
                str(managed_stamp.path) if managed_stamp is not None else None
            ),
            "legacyStamp": bool(managed_stamp and managed_stamp.legacy),
        }
        result.update(probe_details)
        return result
    except BaseException as exc:
        return {
            "ok": False,
            "pluginId": lock.plugin_id,
            "package": lock.package,
            "version": None,
            "reason": str(exc) or exc.__class__.__name__,
        }


def probe_installed_plugin(
    lock: PluginLock,
    *,
    require_stamp: bool = True,
) -> dict[str, Any]:
    runner = Path(__file__).resolve().with_name("managed_plugin_probe.py")
    command = [
        sys.executable,
        str(runner),
        "--lock-file",
        str(lock.path),
    ]
    if not require_stamp:
        command.append("--without-stamp")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return {
            "ok": False,
            "pluginId": lock.plugin_id,
            "reason": completed.stderr.strip()
            or f"plugin probe exited with code {completed.returncode}",
        }
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"ok": False, "reason": f"invalid plugin probe output: {lines[-1]}"}
    if not isinstance(result, dict):
        return {"ok": False, "reason": "plugin probe returned a non-object result"}
    return result


def _inside_virtual_environment() -> bool:
    return bool(
        getattr(sys, "real_prefix", None)
        or getattr(sys, "base_prefix", sys.prefix) != sys.prefix
    )


def install_artifact(lock: PluginLock, artifact_path: Path) -> None:
    if lock.installer_kind != "python-wheel":
        raise InstallerError(f"unsupported managed plugin installer {lock.installer_kind!r}")
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-index",
        "--no-deps",
        "--force-reinstall",
        str(artifact_path),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise InstallerError(f"pip failed to install {artifact_path.name}")


def _print_plugin(
    lock: PluginLock, message: str, *, quiet: bool = False, error: bool = False
) -> None:
    if quiet and not error:
        return
    stream = sys.stderr if error else sys.stdout
    print(f"[plugin:{lock.plugin_id}] {message}", file=stream, flush=True)


def ensure_managed_plugin(
    lock: PluginLock,
    *,
    check: bool = False,
    offline: bool = False,
    cache_dir: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    allow_system_python: bool = False,
    quiet: bool = False,
) -> bool:
    """Ensure one locked plugin is ready; return False only for check misses."""

    probe = probe_installed_plugin(lock)
    if probe.get("ok") is True:
        if probe.get("legacyStamp") is True and not check:
            managed_release = probe.get("managedRelease")
            stamp_path = probe.get("managedStampPath")
            if not isinstance(managed_release, Mapping) or not isinstance(stamp_path, str):
                raise InstallerError("legacy managed stamp probe returned invalid metadata")
            migrate_legacy_stamp(
                lock,
                ManagedStamp(
                    value=managed_release,
                    path=Path(stamp_path),
                    legacy=True,
                ),
            )
        _print_plugin(
            lock,
            f"{lock.package} {lock.version} is ready "
            f"({probe.get('sourcePath') or 'unknown path'})",
            quiet=quiet,
        )
        return True
    if check:
        _print_plugin(
            lock,
            f"{lock.package} is not ready: {probe.get('reason') or 'unknown reason'}",
            error=True,
        )
        return False
    if not allow_system_python and not _inside_virtual_environment():
        raise InstallerError(
            "refusing to install a managed plugin into a system/base Python; run "
            "backend/setup.ps1, backend/setup.sh, or pass --allow-system-python explicitly"
        )
    if timeout <= 0:
        raise InstallerError("--timeout must be greater than zero")

    resolved_cache = (cache_dir or default_cache_dir()).expanduser().resolve()
    manifest = load_pinned_manifest(
        lock,
        cache_dir=resolved_cache,
        offline=offline,
        timeout=timeout,
    )
    asset = select_release_asset(manifest, lock)
    artifact_path = ensure_cached_artifact(
        lock,
        asset,
        cache_dir=resolved_cache,
        offline=offline,
        timeout=timeout,
    )
    _print_plugin(
        lock,
        f"installing verified artifact {artifact_path.name}",
        quiet=quiet,
    )
    install_artifact(lock, artifact_path)
    verified = probe_installed_plugin(lock, require_stamp=False)
    if verified.get("ok") is not True:
        raise InstallerError(
            f"installed {lock.display_name} failed its {lock.probe_kind} probe: "
            f"{verified.get('reason') or 'unknown reason'}"
        )
    write_install_stamp(lock, asset)
    managed_probe = probe_installed_plugin(lock)
    if managed_probe.get("ok") is not True:
        raise InstallerError(
            f"installed {lock.display_name} did not retain its managed release identity: "
            f"{managed_probe.get('reason') or 'unknown reason'}"
        )
    _print_plugin(
        lock,
        f"installed {lock.package} {lock.version} and passed {lock.probe_kind}",
        quiet=quiet,
    )
    return True


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "InstallerError",
    "ManagedPlugin",
    "ManagedStamp",
    "PluginLock",
    "default_cache_dir",
    "default_registry_path",
    "ensure_cached_artifact",
    "ensure_managed_plugin",
    "install_artifact",
    "install_stamp_path",
    "load_managed_stamp",
    "load_pinned_manifest",
    "load_plugin_lock",
    "load_plugin_registry",
    "migrate_legacy_stamp",
    "probe_in_current_process",
    "probe_installed_plugin",
    "select_plugins",
    "select_release_asset",
    "validate_install_stamp",
    "validate_release_manifest",
    "write_install_stamp",
]
