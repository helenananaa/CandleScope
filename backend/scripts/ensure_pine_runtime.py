#!/usr/bin/env python3
"""Install CandleScope's pinned Pine-compatible binary wheel.

The installer deliberately separates application startup from native builds:
it accepts only a release manifest pinned by CANDLESCOPE_RUNTIME.json, verifies
both manifest and wheel SHA-256 digests, and installs into this interpreter.
"""
from __future__ import annotations

import argparse
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


LOCK_SCHEMA_VERSION = 2
RELEASE_MANIFEST_SCHEMA_VERSION = 1
INSTALL_STAMP_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_WHEEL_BYTES = 200 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class InstallerError(RuntimeError):
    """A fail-closed installer error with an actionable user message."""


@dataclass(frozen=True, slots=True)
class ReleaseLock:
    path: Path
    package: str
    module: str
    version: str
    upstream: str
    source_commit: str
    analysis_schema_version: int
    runtime_schema_version: int
    tag: str
    release_commit: str
    manifest_url: str
    manifest_sha256: str
    asset_base_url: str


def _default_lock_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "pine-compat-runtime"
        / "CANDLESCOPE_RUNTIME.json"
    )


def default_cache_dir() -> Path:
    override = os.environ.get("CANDLESCOPE_RUNTIME_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "CandleScope" / "runtime-cache"
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base_path = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return base_path / "candlescope" / "runtime-cache"


def install_stamp_path(prefix: Path | None = None) -> Path:
    environment_prefix = prefix or Path(sys.prefix)
    return environment_prefix / ".candlescope" / "pine-runtime-install.json"


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


def load_release_lock(path: Path | str = _default_lock_path()) -> ReleaseLock:
    lock_path = Path(path).expanduser().resolve()
    try:
        raw = lock_path.read_bytes()
    except OSError as exc:
        raise InstallerError(f"Unable to read Pine runtime lock {lock_path}: {exc}") from exc
    root = _decode_json(raw, "runtime lock")
    if root.get("schemaVersion") != LOCK_SCHEMA_VERSION:
        raise InstallerError(
            f"Unsupported runtime lock schema: {root.get('schemaVersion')!r}; "
            f"expected {LOCK_SCHEMA_VERSION}"
        )

    package = _require_string(root, "package", "runtime lock")
    module = _require_string(root, "pythonModule", "runtime lock")
    version = _require_string(root, "version", "runtime lock")
    upstream = _require_string(root, "upstream", "runtime lock").rstrip("/")
    source_commit = _require_string(root, "commit", "runtime lock").lower()
    if not _HEX_40.fullmatch(source_commit):
        raise InstallerError("runtime lock.commit must be a 40-character Git SHA")
    analysis_schema = _require_positive_int(root, "analysisSchemaVersion", "runtime lock")
    runtime_schema = _require_positive_int(root, "runtimeSchemaVersion", "runtime lock")

    release = _require_mapping(root.get("release"), "runtime lock.release")
    tag = _require_string(release, "tag", "runtime lock.release")
    release_commit = _require_string(release, "commit", "runtime lock.release").lower()
    manifest_url = _require_string(release, "manifestUrl", "runtime lock.release")
    manifest_sha256 = _require_string(
        release, "manifestSha256", "runtime lock.release"
    ).lower()
    asset_base_url = _require_string(
        release, "assetBaseUrl", "runtime lock.release"
    ).rstrip("/")

    if tag != f"v{version}":
        raise InstallerError(
            f"runtime lock release tag {tag!r} does not match package version {version!r}"
        )
    if not _HEX_40.fullmatch(release_commit):
        raise InstallerError("runtime lock.release.commit must be a 40-character Git SHA")
    if not _HEX_64.fullmatch(manifest_sha256):
        raise InstallerError("runtime lock.release.manifestSha256 must be a SHA-256 digest")
    _validate_https_url(upstream, "runtime lock.upstream")
    _validate_https_url(manifest_url, "runtime lock.release.manifestUrl")
    _validate_https_url(asset_base_url, "runtime lock.release.assetBaseUrl")
    expected_prefix = f"{upstream}/releases/download/{tag}"
    if manifest_url != f"{expected_prefix}/manifest.json":
        raise InstallerError("runtime lock manifest URL is outside the pinned GitHub release")
    if asset_base_url != expected_prefix:
        raise InstallerError("runtime lock asset base URL is outside the pinned GitHub release")

    return ReleaseLock(
        path=lock_path,
        package=package,
        module=module,
        version=version,
        upstream=upstream,
        source_commit=source_commit,
        analysis_schema_version=analysis_schema,
        runtime_schema_version=runtime_schema,
        tag=tag,
        release_commit=release_commit,
        manifest_url=manifest_url,
        manifest_sha256=manifest_sha256,
        asset_base_url=asset_base_url,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_matches(path: Path, expected_sha256: str, expected_size: int | None = None) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    if not path.is_file() or (expected_size is not None and stat.st_size != expected_size):
        return False
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_sha256


def validate_release_manifest(data: bytes, lock: ReleaseLock) -> Mapping[str, Any]:
    actual_digest = _sha256_bytes(data)
    if actual_digest != lock.manifest_sha256:
        raise InstallerError(
            "Pine release manifest SHA-256 mismatch: "
            f"expected {lock.manifest_sha256}, got {actual_digest}"
        )
    manifest = _decode_json(data, "release manifest")
    expected_fields = {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "channel": "stable",
        "distribution": lock.package,
        "module": lock.module,
        "version": lock.version,
        "tag": lock.tag,
        "commit": lock.release_commit,
        "python_requires": ">=3.10",
    }
    for key, expected in expected_fields.items():
        if manifest.get(key) != expected:
            raise InstallerError(
                f"release manifest {key!r} mismatch: "
                f"expected {expected!r}, got {manifest.get(key)!r}"
            )

    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise InstallerError("release manifest.assets must be a non-empty list")
    seen_names: set[str] = set()
    for index, raw_asset in enumerate(assets):
        label = f"release manifest.assets[{index}]"
        asset = _require_mapping(raw_asset, label)
        filename = _require_string(asset, "filename", label)
        if filename != Path(filename).name or filename in {".", ".."}:
            raise InstallerError(f"{label}.filename must be a plain file name")
        expected_prefix = (
            f"{lock.package.replace('-', '_')}-{lock.version}-cp310-abi3-"
        )
        if not filename.startswith(expected_prefix) or not filename.endswith(".whl"):
            raise InstallerError(f"{label}.filename does not match the pinned wheel identity")
        if filename in seen_names:
            raise InstallerError(f"release manifest contains duplicate asset {filename!r}")
        seen_names.add(filename)
        if _require_string(asset, "python_tag", label) != "cp310":
            raise InstallerError(f"{label} does not target the pinned cp310 ABI floor")
        if _require_string(asset, "abi_tag", label) != "abi3":
            raise InstallerError(f"{label} is not an abi3 wheel")
        _require_string(asset, "platform_tag", label)
        digest = _require_string(asset, "sha256", label).lower()
        if not _HEX_64.fullmatch(digest):
            raise InstallerError(f"{label}.sha256 must be a SHA-256 digest")
        size = _require_positive_int(asset, "size", label)
        if size > MAX_WHEEL_BYTES:
            raise InstallerError(f"{label}.size exceeds the installer safety limit")
    return manifest


def select_release_asset(
    manifest: Mapping[str, Any],
    *,
    sys_platform: str | None = None,
    machine: str | None = None,
    python_implementation: str | None = None,
    python_version: tuple[int, int] | None = None,
    gil_disabled: bool | None = None,
) -> Mapping[str, Any]:
    current_platform = sys_platform or sys.platform
    current_machine = (machine or platform.machine()).strip().lower().replace("-", "_")
    implementation = python_implementation or platform.python_implementation()
    version = python_version or (sys.version_info.major, sys.version_info.minor)
    if gil_disabled is None:
        gil_disabled = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))

    if implementation != "CPython":
        raise InstallerError(f"Pine binary wheels require CPython, found {implementation}")
    if version < (3, 10):
        raise InstallerError(
            f"Pine binary wheels require CPython 3.10+, found {version[0]}.{version[1]}"
        )
    if gil_disabled:
        raise InstallerError("Free-threaded CPython is not supported by the abi3 release wheel")
    if current_machine not in {"amd64", "x86_64"}:
        raise InstallerError(
            f"No Pine release wheel for architecture {current_machine or 'unknown'}"
        )

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise InstallerError("release manifest.assets is invalid")
    if current_platform == "win32":
        candidates = [asset for asset in assets if asset.get("platform_tag") == "win_amd64"]
    elif current_platform.startswith("linux"):
        candidates = [
            asset
            for asset in assets
            if str(asset.get("platform_tag") or "").startswith("manylinux")
            and str(asset.get("platform_tag") or "").endswith("_x86_64")
        ]
    else:
        raise InstallerError(f"No Pine release wheel for platform {current_platform!r}")
    if len(candidates) != 1:
        raise InstallerError(
            f"Expected exactly one compatible Pine wheel, found {len(candidates)}"
        )
    return _require_mapping(candidates[0], "selected release asset")


def _request(url: str) -> urllib.request.Request:
    _validate_https_url(url, "download URL")
    return urllib.request.Request(
        url,
        headers={"User-Agent": "CandleScope-Pine-Runtime-Installer/1"},
        method="GET",
    )


def _read_url_limited(url: str, *, timeout: float, limit: int) -> bytes:
    try:
        with urllib.request.urlopen(_request(url), timeout=timeout) as response:
            data = response.read(limit + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise InstallerError(f"Unable to download {url}: {exc}") from exc
    if len(data) > limit:
        raise InstallerError(f"Download from {url} exceeds the {limit}-byte safety limit")
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
    lock: ReleaseLock,
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
        raise InstallerError(f"Offline mode requires cached manifest {manifest_path}")

    data = _read_url_limited(lock.manifest_url, timeout=timeout, limit=MAX_MANIFEST_BYTES)
    manifest = validate_release_manifest(data, lock)
    _atomic_write(manifest_path, data)
    return manifest


def _download_wheel(
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
            raise InstallerError(f"Unable to download {url}: {exc}") from exc
        with response, temporary.open("wb") as handle:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > expected_size or size > MAX_WHEEL_BYTES:
                    raise InstallerError("Downloaded wheel exceeds its pinned size")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size != expected_size:
            raise InstallerError(
                f"Downloaded wheel size mismatch: expected {expected_size}, got {size}"
            )
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise InstallerError(
                "Downloaded wheel SHA-256 mismatch: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def ensure_cached_wheel(
    lock: ReleaseLock,
    asset: Mapping[str, Any],
    *,
    cache_dir: Path,
    offline: bool,
    timeout: float,
) -> Path:
    filename = _require_string(asset, "filename", "selected release asset")
    expected_sha256 = _require_string(asset, "sha256", "selected release asset").lower()
    expected_size = _require_positive_int(asset, "size", "selected release asset")
    wheel_path = cache_dir / lock.package / lock.tag / filename
    if _file_matches(wheel_path, expected_sha256, expected_size):
        return wheel_path
    if offline:
        raise InstallerError(
            f"Offline mode requires a verified cached wheel at {wheel_path}"
        )
    asset_url = f"{lock.asset_base_url}/{urllib.parse.quote(filename)}"
    _download_wheel(
        asset_url,
        wheel_path,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
        timeout=timeout,
    )
    if not _file_matches(wheel_path, expected_sha256, expected_size):
        raise InstallerError("Cached wheel failed verification after download")
    return wheel_path


def validate_install_stamp(
    lock: ReleaseLock,
    *,
    path: Path | None = None,
) -> Mapping[str, Any]:
    stamp_path = path or install_stamp_path()
    try:
        stamp = _decode_json(stamp_path.read_bytes(), "Pine runtime install stamp")
    except OSError as exc:
        raise InstallerError(f"managed install stamp is missing: {stamp_path}") from exc
    expected = {
        "schemaVersion": INSTALL_STAMP_SCHEMA_VERSION,
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
    filename = stamp.get("wheelFilename")
    digest = stamp.get("wheelSha256")
    if not isinstance(filename, str) or filename != Path(filename).name:
        raise InstallerError("managed install stamp has an invalid wheel filename")
    if not isinstance(digest, str) or not _HEX_64.fullmatch(digest):
        raise InstallerError("managed install stamp has an invalid wheel SHA-256")
    return stamp


def write_install_stamp(
    lock: ReleaseLock,
    asset: Mapping[str, Any],
    *,
    path: Path | None = None,
) -> Path:
    stamp_path = path or install_stamp_path()
    stamp = {
        "schemaVersion": INSTALL_STAMP_SCHEMA_VERSION,
        "package": lock.package,
        "version": lock.version,
        "tag": lock.tag,
        "releaseCommit": lock.release_commit,
        "manifestSha256": lock.manifest_sha256,
        "wheelFilename": _require_string(asset, "filename", "selected release asset"),
        "wheelSha256": _require_string(asset, "sha256", "selected release asset").lower(),
    }
    data = (json.dumps(stamp, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(stamp_path, data)
    return stamp_path


def _probe_in_current_process(
    lock: ReleaseLock,
    *,
    require_stamp: bool = True,
) -> dict[str, Any]:
    try:
        stamp = validate_install_stamp(lock) if require_stamp else None
        installed_version = importlib.metadata.version(lock.package)
        if installed_version != lock.version:
            raise InstallerError(
                f"installed version is {installed_version}, expected {lock.version}"
            )
        module = importlib.import_module(lock.module)
        source = (
            '//@version=5\nindicator("CandleScope install probe", overlay=true)\n'
            'plot(ta.sma(close, 2), "SMA")\n'
        )
        analysis = dict(module.analyze_script(source))
        if analysis.get("schemaVersion") != lock.analysis_schema_version:
            raise InstallerError(
                "analysis schema mismatch: "
                f"expected {lock.analysis_schema_version}, "
                f"got {analysis.get('schemaVersion')!r}"
            )
        bars = [
            {"time": 1_700_000_000_000, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 100.0},
            {"time": 1_700_000_060_000, "open": 10.0, "high": 12.0, "low": 9.5, "close": 11.0, "volume": 110.0},
            {"time": 1_700_000_120_000, "open": 11.0, "high": 13.0, "low": 10.5, "close": 12.0, "volume": 120.0},
        ]
        runtime = dict(module.run_script(source, bars))
        if runtime.get("schemaVersion") != lock.runtime_schema_version:
            raise InstallerError(
                "runtime schema mismatch: "
                f"expected {lock.runtime_schema_version}, "
                f"got {runtime.get('schemaVersion')!r}"
            )
        plots = runtime.get("plots")
        if not isinstance(plots, list) or not plots:
            raise InstallerError("runtime smoke did not produce the expected plot output")
        return {
            "ok": True,
            "package": lock.package,
            "version": installed_version,
            "module": lock.module,
            "sourcePath": str(getattr(module, "__file__", "") or ""),
            "analysisSchemaVersion": analysis.get("schemaVersion"),
            "runtimeSchemaVersion": runtime.get("schemaVersion"),
            "managedRelease": dict(stamp) if stamp is not None else None,
        }
    except BaseException as exc:
        return {
            "ok": False,
            "package": lock.package,
            "version": None,
            "reason": str(exc) or exc.__class__.__name__,
        }


def probe_installed_runtime(
    lock: ReleaseLock,
    *,
    require_stamp: bool = True,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_probe",
        "--lock-file",
        str(lock.path),
    ]
    if not require_stamp:
        command.append("--_probe-without-stamp")
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
            "reason": completed.stderr.strip()
            or f"runtime probe exited with code {completed.returncode}",
        }
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"ok": False, "reason": f"invalid runtime probe output: {lines[-1]}"}
    if not isinstance(result, dict):
        return {"ok": False, "reason": "runtime probe returned a non-object result"}
    return result


def _inside_virtual_environment() -> bool:
    return bool(
        getattr(sys, "real_prefix", None)
        or getattr(sys, "base_prefix", sys.prefix) != sys.prefix
    )


def install_wheel(wheel_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-index",
        "--no-deps",
        "--force-reinstall",
        str(wheel_path),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise InstallerError(f"pip failed to install {wheel_path.name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify or install CandleScope's pinned Pine-compatible runtime wheel."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check the current interpreter without downloading or installing",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="install only from an already verified local cache",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="override the per-user runtime wheel cache",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=_default_lock_path(),
        help="path to CANDLESCOPE_RUNTIME.json",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="network timeout in seconds",
    )
    parser.add_argument(
        "--allow-system-python",
        action="store_true",
        help="allow installation outside a virtual environment",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress success messages")
    parser.add_argument("--_probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_probe-without-stamp", action="store_true", help=argparse.SUPPRESS)
    return parser


def _print(message: str, *, quiet: bool = False, error: bool = False) -> None:
    if quiet and not error:
        return
    stream = sys.stderr if error else sys.stdout
    print(f"[pine-runtime] {message}", file=stream, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        lock = load_release_lock(args.lock_file)
        if args._probe:
            print(
                json.dumps(
                    _probe_in_current_process(
                        lock,
                        require_stamp=not args._probe_without_stamp,
                    ),
                    ensure_ascii=False,
                )
            )
            return 0

        probe = probe_installed_runtime(lock)
        if probe.get("ok") is True:
            _print(
                f"{lock.package} {lock.version} is ready "
                f"({probe.get('sourcePath') or 'unknown path'})",
                quiet=args.quiet,
            )
            return 0
        if args.check:
            _print(
                f"{lock.package} is not ready: {probe.get('reason') or 'unknown reason'}",
                error=True,
            )
            return 1
        if not args.allow_system_python and not _inside_virtual_environment():
            raise InstallerError(
                "refusing to install into a system/base Python; run backend/setup.ps1, "
                "backend/setup.sh, or pass --allow-system-python explicitly"
            )
        if args.timeout <= 0:
            raise InstallerError("--timeout must be greater than zero")

        cache_dir = (args.cache_dir or default_cache_dir()).expanduser().resolve()
        manifest = load_pinned_manifest(
            lock,
            cache_dir=cache_dir,
            offline=args.offline,
            timeout=args.timeout,
        )
        asset = select_release_asset(manifest)
        wheel_path = ensure_cached_wheel(
            lock,
            asset,
            cache_dir=cache_dir,
            offline=args.offline,
            timeout=args.timeout,
        )
        _print(f"installing verified wheel {wheel_path.name}", quiet=args.quiet)
        install_wheel(wheel_path)
        verified = probe_installed_runtime(lock, require_stamp=False)
        if verified.get("ok") is not True:
            raise InstallerError(
                "installed Pine runtime failed its schema/SMA smoke: "
                f"{verified.get('reason') or 'unknown reason'}"
            )
        write_install_stamp(lock, asset)
        managed_probe = probe_installed_runtime(lock)
        if managed_probe.get("ok") is not True:
            raise InstallerError(
                "installed Pine runtime did not retain its managed Release identity: "
                f"{managed_probe.get('reason') or 'unknown reason'}"
            )
        _print(
            f"installed {lock.package} {lock.version} and passed the runtime smoke",
            quiet=args.quiet,
        )
        return 0
    except InstallerError as exc:
        _print(str(exc), error=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
