"""Verified index cache, artifact staging, updates, and revocation policy."""

from __future__ import annotations

from app.core.config import getenv as app_getenv

import asyncio
import hashlib
import http.client
import ipaddress
import os
import re
import socket
import ssl
import tempfile
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from candlescope_plugin_sdk.platform_v2 import (
    JsonLimits,
    PlatformContractError,
    canonical_sha256,
    loads_strict,
)

from app.plugin_installer_v2 import PlatformPluginInstaller
from app.plugin_installer_v2.bundle import (
    MAX_BUNDLE_BYTES,
    SBOM_PATH,
    VerifiedPlatformBundle,
    verify_platform_bundle,
)
from app.plugin_installer_v2.errors import PlatformInstallerBaseError
from app.plugin_installer_v2.registry import load_activation_registry
from app.plugin_lifecycle.bundle import PackageError, verify_package
from app.plugin_lifecycle.runtime import UnifiedRuntime
from app.plugin_lifecycle.store import (
    CHART_PERMISSION,
    LifecycleError,
    RevisionConflict,
)
from app.plugin_security_v2.grants import manifest_publisher_identity
from app.plugin_security_v2.sandbox import restricted_runtime_profile
from app.plugin_security_v2.storage import atomic_write_json, security_lock
from app.plugin_runtime_registry_v3.service import host_platform

from .errors import MarketplaceError
from .models import (
    MAX_INDEX_BYTES,
    UNIFIED_PACKAGE_FORMAT,
    MarketplaceRoot,
    PublisherRecord,
    ReleaseRecord,
    VerifiedMarketplaceIndex,
    verify_marketplace_index,
)
from .supply_chain import MultiRuntimeReleaseRecord, SignedArtifactRecord
from .telemetry import MarketplaceTelemetry


STATE_SCHEMA_VERSION = 1
CATALOG_SCHEMA_VERSION = "candlescope.marketplace-catalog/1"
STATUS_SCHEMA_VERSION = "candlescope.marketplace-status/1"
CATALOG_SCHEMA_VERSION_V2 = "candlescope.marketplace-catalog/2"
STATUS_SCHEMA_VERSION_V2 = "candlescope.marketplace-status/2"
MARKETPLACE_ROLLOUT_ENV = "CANDLESCOPE_PLUGIN_MARKETPLACE_ROLLOUT"
MARKETPLACE_TELEMETRY_ENV = "CANDLESCOPE_PLUGIN_MARKETPLACE_TELEMETRY_ENABLED"
ROLLOUT_STAGES = ("internal", "opted-in-local", "preview", "stable")
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_REMOTE_ARTIFACT_BYTES = min(MAX_BUNDLE_BYTES, 128 * 1024 * 1024)
DOWNLOAD_TIMEOUT_SECONDS = 30.0

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_STATE_LIMITS = JsonLimits(
    max_message_bytes=MAX_STATE_BYTES,
    max_depth=32,
    max_container_items=100_000,
    max_string_bytes=2 * 1024 * 1024,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _environment_bool(name: str, *, default: bool) -> bool:
    raw = app_getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise MarketplaceError(
        "PLUGIN_MARKETPLACE_CONFIGURATION_INVALID",
        f"{name} must be one of 0/1/false/true/no/yes/off/on",
    )


def _rollout_stage(value: str | None) -> str:
    result = value or app_getenv(MARKETPLACE_ROLLOUT_ENV, "stable")
    if result not in ROLLOUT_STAGES:
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_CONFIGURATION_INVALID",
            f"{MARKETPLACE_ROLLOUT_ENV} has an unsupported rollout stage",
        )
    return result


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return f"sha256:{digest.hexdigest()}", size


def _major(value: str) -> int:
    try:
        major = int(value.split(".", 1)[0])
    except (ValueError, IndexError) as exc:
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_VERSION_INVALID",
            "plugin version has no valid SemVer major",
        ) from exc
    return major


def _version_key(
    value: str,
) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    precedence = value.partition("+")[0]
    core, separator, prerelease = precedence.partition("-")
    parts = core.split(".")
    if len(parts) != 3:
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_VERSION_INVALID",
            "marketplace release version is invalid",
        )
    try:
        numbers = tuple(int(item) for item in parts)
    except ValueError as exc:
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_VERSION_INVALID",
            "marketplace release version is invalid",
        ) from exc
    prerelease_key = tuple(
        (0, int(item)) if item.isdigit() else (1, item)
        for item in prerelease.split(".")
        if item
    )
    return (
        numbers[0],
        numbers[1],
        numbers[2],
        0 if separator else 1,
        prerelease_key,
    )


def _strict_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schemaVersion": STATE_SCHEMA_VERSION,
            "revision": 0,
            "indexes": [],
            "localBundles": [],
            "candidates": [],
        }
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_STATE_INVALID",
            "marketplace state must be a bounded regular file",
        )
    try:
        value = loads_strict(path.read_bytes(), limits=_STATE_LIMITS)
    except (OSError, PlatformContractError) as exc:
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_STATE_INVALID",
            "marketplace state is not strict JSON",
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schemaVersion",
            "revision",
            "indexes",
            "localBundles",
            "candidates",
        }
        or value.get("schemaVersion") != STATE_SCHEMA_VERSION
        or isinstance(value.get("revision"), bool)
        or not isinstance(value.get("revision"), int)
        or value["revision"] < 0
        or not all(
            isinstance(value.get(key), list)
            for key in ("indexes", "localBundles", "candidates")
        )
    ):
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_STATE_INVALID",
            "marketplace state schema is invalid",
        )
    return value


def _state_string(value: Any, label: str, *, maximum: int = 2048) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or "\x00" in value
    ):
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_STATE_INVALID",
            f"{label} is invalid",
        )
    return value


def _validate_state(state: dict[str, Any]) -> None:
    indexes: list[tuple[str, int]] = []
    for index, raw in enumerate(state["indexes"]):
        label = f"marketplace state.indexes[{index}]"
        if not isinstance(raw, dict) or set(raw) != {
            "marketplaceId",
            "sequence",
            "indexSha256",
            "cacheFile",
            "importedAt",
        }:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_STATE_INVALID",
                f"{label} schema is invalid",
            )
        marketplace_id = _state_string(
            raw["marketplaceId"], f"{label}.marketplaceId", maximum=128
        )
        if _ID.fullmatch(marketplace_id) is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_STATE_INVALID",
                f"{label}.marketplaceId is invalid",
            )
        sequence = raw["sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_STATE_INVALID",
                f"{label}.sequence is invalid",
            )
        if (
            not isinstance(raw["indexSha256"], str)
            or _SHA256.fullmatch(raw["indexSha256"]) is None
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_STATE_INVALID",
                f"{label}.indexSha256 is invalid",
            )
        cache_file = _state_string(raw["cacheFile"], f"{label}.cacheFile", maximum=128)
        if cache_file != f"{raw['indexSha256'].removeprefix('sha256:')}.json":
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_STATE_INVALID",
                f"{label}.cacheFile is not content-addressed",
            )
        _state_string(raw["importedAt"], f"{label}.importedAt", maximum=64)
        indexes.append((marketplace_id, sequence))
    if indexes != sorted(indexes) or len({item[0] for item in indexes}) != len(indexes):
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_STATE_INVALID",
            "marketplace state indexes must be ID-sorted and unique",
        )
    local_keys: list[str] = []
    for index, raw in enumerate(state["localBundles"]):
        label = f"marketplace state.localBundles[{index}]"
        if not isinstance(raw, dict) or set(raw) != {
            "bundleSha256",
            "pluginId",
            "version",
            "publisher",
            "recordedAt",
        }:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_STATE_INVALID",
                f"{label} schema is invalid",
            )
        digest = _state_string(raw["bundleSha256"], f"{label}.bundleSha256", maximum=71)
        if _SHA256.fullmatch(digest) is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_STATE_INVALID",
                f"{label}.bundleSha256 is invalid",
            )
        for key, maximum in (
            ("pluginId", 128),
            ("version", 64),
            ("publisher", 128),
            ("recordedAt", 64),
        ):
            _state_string(raw[key], f"{label}.{key}", maximum=maximum)
        local_keys.append(digest)
    if local_keys != sorted(local_keys) or len(set(local_keys)) != len(local_keys):
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_STATE_INVALID",
            "local bundle evidence must be digest-sorted and unique",
        )
    candidate_keys: list[str] = []
    candidate_fields = {
        "pluginId",
        "version",
        "marketplaceId",
        "publisherId",
        "bundleSha256",
        "artifactFile",
        "phase",
        "preparedAt",
        "fromVersion",
        "permissionDiff",
        "compatibility",
        "migration",
        "observation",
    }
    for index, raw in enumerate(state["candidates"]):
        label = f"marketplace state.candidates[{index}]"
        if (
            not isinstance(raw, dict)
            or set(raw) - {"unifiedApproval"} != candidate_fields
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_STATE_INVALID",
                f"{label} schema is invalid",
            )
        plugin_id = _state_string(raw["pluginId"], f"{label}.pluginId", maximum=128)
        for key, maximum in (
            ("version", 64),
            ("marketplaceId", 128),
            ("publisherId", 128),
            ("bundleSha256", 71),
            ("artifactFile", 128),
            ("phase", 32),
            ("preparedAt", 64),
        ):
            _state_string(raw[key], f"{label}.{key}", maximum=maximum)
        if raw["fromVersion"] is not None:
            _state_string(raw["fromVersion"], f"{label}.fromVersion", maximum=64)
        if (
            _SHA256.fullmatch(raw["bundleSha256"]) is None
            or raw["artifactFile"]
            != f"{raw['bundleSha256'].removeprefix('sha256:')}.cspkg"
            or raw["phase"]
            not in {
                "verified-staged",
                "activation-staged",
                "observing",
                "active",
                "rolled-back",
                "failed",
                "quarantined",
            }
            or not isinstance(raw["permissionDiff"], dict)
            or not isinstance(raw["compatibility"], dict)
            or not isinstance(raw["migration"], dict)
            or not isinstance(raw["observation"], dict)
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_STATE_INVALID",
                f"{label} values are invalid",
            )
        if "unifiedApproval" in raw:
            approval = raw["unifiedApproval"]
            if (
                not isinstance(approval, dict)
                or set(approval) - {"legacy"}
                != {"packageSha256", "permissions", "previousGeneration"}
                or approval["packageSha256"] != raw["bundleSha256"]
                or approval["permissions"] not in ([], [CHART_PERMISSION])
                or (
                    approval["previousGeneration"] is not None
                    and (
                        type(approval["previousGeneration"]) is not int
                        or approval["previousGeneration"] <= 0
                    )
                )
            ):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_STATE_INVALID", f"{label} approval is invalid"
                )
            if "legacy" in approval:
                legacy = approval["legacy"]
                if (
                    not isinstance(legacy, dict)
                    or set(legacy)
                    != {"legacyActivationId", "legacyBundleSha256", "legacyGrantSha256"}
                    or not isinstance(legacy["legacyActivationId"], str)
                    or re.fullmatch(
                        r"activation-[a-f0-9]{32}", legacy["legacyActivationId"]
                    )
                    is None
                    or any(
                        not isinstance(legacy[key], str)
                        or _SHA256.fullmatch(legacy[key]) is None
                        for key in ("legacyBundleSha256", "legacyGrantSha256")
                    )
                ):
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_STATE_INVALID",
                        f"{label} migration approval is invalid",
                    )
        candidate_keys.append(plugin_id)
    if candidate_keys != sorted(candidate_keys) or len(set(candidate_keys)) != len(
        candidate_keys
    ):
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_STATE_INVALID",
            "marketplace candidates must be plugin-ID-sorted and unique",
        )


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise MarketplaceError(
            "PLUGIN_MARKETPLACE_CACHE_UNSAFE",
            "marketplace cache directory must not be a symlink",
        )
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.part"
    try:
        with temporary.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != value:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_IMMUTABILITY_VIOLATION",
                    "content-addressed marketplace cache entry changed",
                )
            temporary.unlink()
            return
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class MarketplaceFetcher(Protocol):
    def get(self, url: str, *, maximum: int) -> bytes: ...


class PinnedMarketplaceFetcher:
    """Pinned-DNS HTTPS-only fetcher with no redirects or ambient proxy."""

    def __init__(
        self,
        *,
        resolver: Callable[[str, int], tuple[str, ...]] | None = None,
        timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS,
    ) -> None:
        self.resolver = resolver or self._resolve_public_addresses
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
        try:
            values = socket.getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except OSError as exc:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_NETWORK_FAILED",
                "marketplace hostname resolution failed",
            ) from exc
        addresses = sorted({item[4][0].split("%", 1)[0] for item in values})
        if not addresses:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_NETWORK_FAILED",
                "marketplace hostname resolved to no address",
            )
        for value in addresses:
            try:
                address = ipaddress.ip_address(value)
            except ValueError as exc:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_NETWORK_FAILED",
                    "marketplace hostname resolved to an invalid address",
                ) from exc
            if not address.is_global:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_PRIVATE_ADDRESS_DENIED",
                    "marketplace hostname resolved to a non-public address",
                )
        return tuple(addresses)

    class _PinnedConnection(http.client.HTTPSConnection):
        def __init__(
            self,
            host: str,
            *,
            resolved_ip: str,
            timeout: float,
        ) -> None:
            super().__init__(
                host,
                443,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
            self._resolved_ip = resolved_ip

        def connect(self) -> None:
            raw = socket.create_connection(
                (self._resolved_ip, self.port),
                self.timeout,
            )
            try:
                self.sock = self._context.wrap_socket(
                    raw,
                    server_hostname=self.host,
                )
            except BaseException:
                raw.close()
                raise

    def get(self, url: str, *, maximum: int) -> bytes:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port not in {None, 443}
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_URL_INVALID",
                "marketplace fetch URL is not canonical HTTPS",
            )
        host = parsed.hostname.lower()
        addresses = self.resolver(host, 443)
        if not addresses:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_NETWORK_FAILED",
                "marketplace hostname resolved to no public address",
            )
        for value in addresses:
            try:
                address = ipaddress.ip_address(value.split("%", 1)[0])
            except ValueError as exc:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_NETWORK_FAILED",
                    "marketplace resolver returned an invalid address",
                ) from exc
            if not address.is_global:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_PRIVATE_ADDRESS_DENIED",
                    "marketplace resolver returned a non-public address",
                )
        connection = self._PinnedConnection(
            host,
            resolved_ip=addresses[0].split("%", 1)[0],
            timeout=self.timeout_seconds,
        )
        try:
            connection.request(
                "GET",
                parsed.path or "/",
                headers={
                    "Accept": "application/json, application/octet-stream",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "User-Agent": "CandleScope-Marketplace/1",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_NETWORK_FAILED",
                    "marketplace server returned a non-success response",
                    details={"status": response.status},
                )
            encoding = response.getheader("content-encoding")
            if encoding is not None and encoding.strip().lower() not in {
                "",
                "identity",
            }:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_CONTENT_ENCODING_DENIED",
                    "compressed marketplace responses are not accepted",
                )
            content_length = response.getheader("content-length")
            if content_length is not None:
                try:
                    declared = int(content_length)
                except ValueError as exc:
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_NETWORK_FAILED",
                        "marketplace Content-Length is invalid",
                    ) from exc
                if declared < 0 or declared > maximum:
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_LIMIT_EXCEEDED",
                        "marketplace response exceeds its byte limit",
                    )
            body = response.read(maximum + 1)
            if len(body) > maximum:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_LIMIT_EXCEEDED",
                    "marketplace response exceeds its byte limit",
                )
            return body
        except MarketplaceError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_NETWORK_FAILED",
                "marketplace HTTPS request failed",
            ) from exc
        finally:
            connection.close()


@dataclass(frozen=True, slots=True)
class BundleTrust:
    trust_level: str
    publisher_identity: str
    source: str
    marketplace_id: str | None
    release: ReleaseRecord | None

    def to_wire(self) -> dict[str, Any]:
        return {
            "trustLevel": self.trust_level,
            "publisherIdentity": self.publisher_identity,
            "source": self.source,
            "marketplaceId": self.marketplace_id,
            "releaseSha256": (
                self.release.artifact.sha256 if self.release is not None else None
            ),
        }


class PluginMarketplaceService:
    """Own signed metadata and updates without owning grants or activation policy."""

    def __init__(
        self,
        *,
        root: Path | str,
        installer: PlatformPluginInstaller,
        roots: tuple[MarketplaceRoot, ...] = (),
        enabled: bool = False,
        allow_legacy_execution: bool = True,
        fetcher: MarketplaceFetcher | None = None,
        managed_runtime_registry: Any | None = None,
        operating_system: str | None = None,
        architecture: str | None = None,
        rollout_stage: str | None = None,
        telemetry_enabled: bool | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        self.installer = installer
        self.roots = {item.marketplace_id: item for item in roots}
        self.enabled = enabled
        self.allow_legacy_execution = allow_legacy_execution
        self.fetcher = fetcher or PinnedMarketplaceFetcher()
        self.managed_runtime_registry = (
            managed_runtime_registry
            if managed_runtime_registry is not None
            else installer.managed_runtime_registry
        )
        detected_os, detected_arch = host_platform()
        self.operating_system = operating_system or detected_os
        self.architecture = architecture or detected_arch
        self._now = now_provider or (lambda: datetime.now(UTC))
        if self.operating_system not in {"windows", "linux", "macos"} or (
            self.architecture not in {"x86_64", "arm64"}
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_PLATFORM_UNAVAILABLE",
                "Marketplace Host platform is unsupported",
            )
        self.rollout_stage = _rollout_stage(rollout_stage)
        telemetry_opt_in = (
            _environment_bool(MARKETPLACE_TELEMETRY_ENV, default=False)
            if telemetry_enabled is None
            else telemetry_enabled
        )
        if not isinstance(telemetry_opt_in, bool):
            raise ValueError("telemetry_enabled must be a boolean")
        self.state_path = self.root / "marketplace-state-v1.json"
        self.lock_path = self.root / "marketplace-v1.lock"
        self.index_directory = self.root / "marketplace-v1" / "indexes"
        self.artifact_directory = self.root / "marketplace-v1" / "artifacts"
        self.quarantine_directory = self.root / "marketplace-v1" / "quarantine"
        self.telemetry = MarketplaceTelemetry(
            self.root / "marketplace-telemetry-v1.json",
            self.root / "marketplace-telemetry-v1.lock",
            telemetry_opt_in,
        )
        self._indexes: dict[str, VerifiedMarketplaceIndex] = {}
        self._known_indexes: dict[str, VerifiedMarketplaceIndex] = {}
        self._cache_errors: dict[str, str] = {}
        if enabled and not any(item.enabled for item in roots):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ROOT_REQUIRED",
                "enabling Marketplace requires at least one build-pinned root",
            )
        self.cutover_lock = asyncio.Lock()
        self.migration_ready: set[tuple[str, int]] = set()
        self.reload_cache()

    unified: UnifiedRuntime | None = None

    def bind_unified(self, runtime: UnifiedRuntime) -> None:
        self.unified = runtime
        self.migration_ready = {
            (plugin_id, item["generation"])
            for plugin_id, item in runtime.store.snapshot()
            .get("marketplaceMigrations", {})
            .items()
            if item["complete"]
        }
        runtime.marketplace_policy = self.unified_execution_allowed

    def legacy_fences(self) -> set[str]:
        if self.unified is None:
            return set()
        snapshot = self.unified.store.snapshot()
        return (
            set(snapshot.get("marketplaceMigrations", {}))
            | {
                plugin_id
                for plugin_id, item in snapshot["plugins"].items()
                if item["enabled"]
            }
            | set(self.unified.packages)
            | set(self.unified.quarantined)
        )

    def legacy_fenced(self, plugin_id: str) -> bool:
        return plugin_id in self.legacy_fences()

    def assert_legacy_inactive(self, plugin_id: str) -> None:
        if not self.allow_legacy_execution:
            return
        previous = self._active_record(plugin_id)
        if previous is not None and previous.enabled:
            raise LifecycleError(
                "Disable the existing Platform v2 plugin before activating a unified local package."
            )

    def _require_current_install_format(self, artifact) -> None:
        if (
            self.unified is not None or not self.allow_legacy_execution
        ) and not self._is_unified(artifact):
            raise MarketplaceError(
                "PLUGIN_PLATFORM_PACKAGE_UPDATE_REQUIRED",
                "The publisher must provide an updated unified marketplace package.",
                status_code=410,
            )

    def unified_execution_allowed(self, plugin_id: str, record: dict) -> bool:
        migration = (
            self.unified.store.snapshot()
            .get("marketplaceMigrations", {})
            .get(plugin_id)
        )
        return (
            migration is None
            or (plugin_id, migration["generation"]) in self.migration_ready
        ) and self.unified_release_current(plugin_id, record)

    def unified_release_current(self, plugin_id: str, record: dict) -> bool:
        grant = record["marketplace"]
        now = self._now()
        index = self._current_indexes(now=now).get(grant["marketplaceId"])
        if index is None:
            return False
        release = index.release_by_identity().get((plugin_id, record["version"]))
        publisher = index.publisher_by_id().get(grant["publisherId"])
        try:
            artifact = self._artifact_for_host(release) if release is not None else None
        except MarketplaceError:
            return False
        return bool(
            release is not None
            and publisher is not None
            and publisher.key_id == grant["publisherKeyId"]
            and release.publisher_id == grant["publisherId"]
            and self._is_unified(artifact)
            and artifact.sha256 == record["packageSha256"]
            and self._release_visible(release)
            and not index.is_revoked(release, now=now)
        )

    @staticmethod
    def _is_unified(artifact) -> bool:
        return getattr(artifact, "package_format", None) == UNIFIED_PACKAGE_FORMAT

    def _unified_owner(self, plugin_id, release, index, publisher):
        if self.unified is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_UNIFIED_UNAVAILABLE",
                "unified lifecycle is unavailable",
            )
        snapshot = self.unified.store.snapshot()
        current = snapshot["plugins"].get(plugin_id)
        legacy = self._active_record(plugin_id)
        migration = snapshot.get("marketplaceMigrations", {}).get(plugin_id)
        self._assert_migration_owner(migration, index, publisher)
        if legacy is not None:
            self._assert_legacy_successor(legacy, release, index, publisher)
            if (
                migration is not None
                and legacy.bundle_sha256 != migration["legacyBundleSha256"]
            ):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_MIGRATION_STALE",
                    "preserved legacy activation changed",
                )
        self._assert_unified_upgrade(current, release, index, publisher)
        return current

    @staticmethod
    def _assert_migration_owner(migration, index, publisher) -> None:
        if migration is not None and (
            migration["marketplaceId"],
            migration["publisherId"],
            migration["publisherKeyId"],
        ) != (index.marketplace_id, publisher.publisher_id, publisher.key_id):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ACTIVATION_OWNED",
                "migration storage is retained for its verified publisher",
            )

    def _assert_legacy_successor(self, legacy, release, index, publisher) -> None:
        if legacy.plugin_id == "candlescope.pyne":
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_RETIRED",
                "Pyne is retired and cannot be migrated or restored",
            )
        previous = index.release_by_digest().get(legacy.bundle_sha256)
        if (
            previous is None
            or previous.identity != (legacy.plugin_id, legacy.version)
            or previous.publisher_id != publisher.publisher_id
            or previous.signature["keyId"] != publisher.key_id
            or any(
                self._is_unified(item) and item.sha256 == legacy.bundle_sha256
                for item in previous.artifacts
            )
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ACTIVATION_OWNED",
                "unified migration requires a legacy release signed by the same marketplace publisher",
            )
        if _major(legacy.version) != _major(release.version) or _version_key(
            release.version
        ) <= _version_key(legacy.version):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_MIGRATION_REQUIRED",
                "unified successor must be a newer release of the same major version",
            )

    def _legacy_review(self, plugin_id, release, index, publisher, snapshot):
        migration = snapshot.get("marketplaceMigrations", {}).get(plugin_id)
        if migration is not None and migration["complete"]:
            return None, None
        captured = self.installer.capture_activation_state(plugin_id)
        record = captured.activation
        if record is None:
            return None, None
        self._assert_legacy_successor(record, release, index, publisher)
        if (
            captured.grant is None
            or captured.grant.publisher_identity != f"publisher-key:{publisher.key_id}"
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ACTIVATION_OWNED",
                "legacy activation has no matching signed publisher grant record",
            )
        return {
            "legacyActivationId": record.activation_id,
            "legacyBundleSha256": record.bundle_sha256,
            "legacyGrantSha256": captured.grant_sha256,
        }, record.version

    def migration_source(self, plugin_id: str, migration: dict, *, for_rollback=False):
        if plugin_id == "candlescope.pyne":
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_RETIRED",
                "Pyne is retired and cannot be migrated or restored",
            )
        captured = self.installer.capture_activation_state(plugin_id)
        record = captured.activation
        if (
            record is None
            or record.activation_id != migration["legacyActivationId"]
            or record.bundle_sha256 != migration["legacyBundleSha256"]
            or captured.grant_sha256 != migration["legacyGrantSha256"]
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_MIGRATION_STALE",
                "previous activation or permissions changed",
            )
        known = self._release_for_digest(record.bundle_sha256, include_expired=False)
        if known is None or known[1].identity != (record.plugin_id, record.version):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_MIGRATION_SOURCE_UNVERIFIED",
                "previous release is no longer verifiable",
            )
        index, release = known
        publisher = index.publisher_by_id()[release.publisher_id]
        self._assert_migration_owner(migration, index, publisher)
        if (
            captured.grant is None
            or captured.grant.publisher_identity != f"publisher-key:{publisher.key_id}"
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_MIGRATION_SOURCE_UNVERIFIED",
                "previous publisher grants are unavailable",
            )
        if for_rollback:
            if index.is_revoked(release, now=self._now()):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_RELEASE_REVOKED", "previous release was revoked"
                )
            bundle, _installation = self.installer.verify_activation_static(record)
            self._assert_bundle_release(bundle, release, publisher)
        return record, f"publisher-key:{publisher.key_id}"

    def release_migration(
        self, plugin_id: str, migration_generation: int, *, expected_revision: int
    ):
        with security_lock(self.lock_path):
            snapshot = self.unified.store.snapshot()
            migration = snapshot.get("marketplaceMigrations", {}).get(plugin_id)
            if migration is None or migration["generation"] != migration_generation:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_MIGRATION_STALE",
                    "migration rollback target changed",
                )
            record, _ = self.migration_source(plugin_id, migration, for_rollback=True)
            try:
                self.unified.store.release_marketplace_migration(
                    plugin_id,
                    expected_revision=expected_revision,
                    migration_generation=migration_generation,
                )
            except ValueError as exc:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_MIGRATION_STALE", str(exc)
                ) from exc
            self.migration_ready.discard((plugin_id, migration_generation))
            return record

    def recover_legacy_migrations(self) -> None:
        if self.unified is None or self.unified.safe_mode:
            return
        snapshot = self.unified.store.snapshot()
        for plugin_id, migration in snapshot.get("marketplaceMigrations", {}).items():
            if not migration["complete"] and plugin_id not in snapshot["plugins"]:
                try:
                    self.release_migration(
                        plugin_id,
                        migration["generation"],
                        expected_revision=self.unified.store.snapshot()["revision"],
                    )
                except (
                    MarketplaceError,
                    OSError,
                    ValueError,
                    PlatformInstallerBaseError,
                ):
                    # Keep ownership fenced if the preserved installation cannot be verified.
                    continue

    def _assert_unified_upgrade(self, current, release, index, publisher):
        if current is None:
            return
        if any(
            current.get("marketplace", {}).get(key) != expected
            for key, expected in {
                "marketplaceId": index.marketplace_id,
                "publisherId": release.publisher_id,
                "publisherKeyId": publisher.key_id,
            }.items()
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ACTIVATION_OWNED",
                "marketplace cannot replace a local activation or another publisher",
            )
        if _major(current["version"]) != _major(release.version):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_MIGRATION_REQUIRED",
                "major-version marketplace updates require a migration contract",
            )
        if (
            current["enabled"]
            or current["packageSha256"] != self._artifact_for_host(release).sha256
        ) and _version_key(release.version) <= _version_key(current["version"]):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_UPDATE_NOT_NEWER",
                "marketplace update must have a newer version",
            )

    def _verify_unified_artifact(self, path, release, artifact):
        try:
            package = verify_package(path)
            manifest = package.manifest
            with zipfile.ZipFile(path) as archive:
                raw_manifest = archive.read("manifest.json")
                with archive.open(SBOM_PATH) as stream:
                    raw_sbom = stream.read(MAX_STATE_BYTES + 1)
            if (
                (package.sha256, package.size) != (artifact.sha256, artifact.size)
                or (manifest.id, manifest.version) != release.identity
                or _sha256_bytes(raw_manifest) != artifact.manifest_sha256
                or _sha256_bytes(raw_sbom) != artifact.sbom_sha256
                or len(raw_sbom) > MAX_STATE_BYTES
            ):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_ARTIFACT_IDENTITY_MISMATCH",
                    "unified artifact, manifest or SBOM does not match the signed release",
                )
            if isinstance(artifact, SignedArtifactRecord):
                self._assert_unified_supply(path, manifest, release, artifact)
            self._assert_sbom_metadata(raw_sbom, release)
            if self.unified is None:
                raise LifecycleError("unified lifecycle is unavailable")
            self.unified.validate_marketplace(manifest)
            return manifest
        except (
            PackageError,
            LifecycleError,
            OSError,
            KeyError,
            zipfile.BadZipFile,
        ) as exc:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_UNIFIED_INVALID", str(exc)
            ) from exc

    def _assert_unified_supply(self, path, manifest, release, artifact):
        required = (
            [{"id": "chart.compute", "scope": {"data": "revealed-chart-bars"}}]
            if manifest.permissions
            else []
        )
        entries = {
            entry.id: entry for entry in manifest.entries if entry.kind == "sidecar"
        }
        bindings = {
            binding.entrypoint_id: binding for binding in artifact.runtime_bindings
        }
        inventory = {
            "plugin": release.license_expression,
            "dependencies": [item.to_wire() for item in release.dependencies],
            "runtimeLicenses": [],
        }
        if release.permissions != {"required": required, "optional": []}:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_PERMISSION_INVALID",
                "signed permissions do not match the unified manifest",
            )
        if artifact.license_inventory_sha256 != canonical_sha256(inventory):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_LICENSE_INVENTORY_MISMATCH",
                "signed license inventory does not match",
            )
        if entries.keys() != bindings.keys():
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_RUNTIME_INVALID",
                "signed runtime bindings do not cover every unified sidecar",
            )
        with zipfile.ZipFile(path) as archive:
            for entry_id, entry in entries.items():
                binding = bindings[entry_id]
                if (
                    entry.runtime not in {"native-executable", "python-module"}
                    or binding.runtime_kind != entry.runtime
                    or binding.runtime_id != entry.runtime
                    or binding.plugin_artifact_path != entry.path
                ):
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_RUNTIME_INVALID",
                        "signed runtime supplied for the sidecar is unsupported",
                    )
                with archive.open(entry.path) as member:
                    digest = (
                        "sha256:" + hashlib.file_digest(member, "sha256").hexdigest()
                    )
                if digest != binding.plugin_artifact_sha256:
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_RUNTIME_INVALID",
                        "signed sidecar entry digest does not match",
                    )

    def _verify_artifact(self, path, release, publisher, artifact):
        if self._is_unified(artifact):
            manifest = self._verify_unified_artifact(path, release, artifact)
            return {
                "manifest": manifest,
                "runtimeKinds": sorted(
                    {entry.runtime for entry in manifest.entries if entry.runtime}
                ),
                "runtimeRegistry": [],
                "sandboxAvailable": True,
            }
        bundle = verify_platform_bundle(
            path,
            expected_sha256=artifact.sha256,
            host_version=self.installer.host_version,
        )
        return self._assert_bundle_release(bundle, release, publisher, artifact)

    @staticmethod
    def _unified_permission_diff(manifest, digest, current):
        previous = current["marketplace"]["permissions"] if current else []
        requested = list(manifest.permissions)
        scope = {"data": "revealed-chart-bars"}
        return {
            "pluginId": manifest.id,
            "publisherIdentityChanged": False,
            "majorVersionChanged": False,
            "bundleChanged": current is None or current["packageSha256"] != digest,
            "requiresConfirmation": True,
            "authorizationIdentityChanged": True,
            "permissions": [
                {
                    "permissionId": permission,
                    "kind": "required" if permission in requested else None,
                    "previousKind": "required" if permission in previous else None,
                    "change": (
                        "unchanged"
                        if permission in requested and permission in previous
                        else "added"
                        if permission in requested
                        else "removed"
                    ),
                    "previousDecision": "granted" if permission in previous else None,
                    "requestedScope": scope if permission in requested else None,
                    "previousScope": scope if permission in previous else None,
                    "requiresConfirmation": permission in requested,
                }
                for permission in sorted(set(previous) | set(requested))
            ],
        }

    def _state(self) -> dict[str, Any]:
        state = _strict_state(self.state_path)
        _validate_state(state)
        return state

    def _commit_state(self, state: dict[str, Any]) -> None:
        state["revision"] += 1
        state["indexes"] = sorted(
            state["indexes"], key=lambda item: item["marketplaceId"]
        )
        state["localBundles"] = sorted(
            state["localBundles"], key=lambda item: item["bundleSha256"]
        )
        state["candidates"] = sorted(
            state["candidates"], key=lambda item: item["pluginId"]
        )
        _validate_state(state)
        atomic_write_json(self.state_path, state)

    def reload_cache(self) -> None:
        indexes: dict[str, VerifiedMarketplaceIndex] = {}
        known_indexes: dict[str, VerifiedMarketplaceIndex] = {}
        cache_errors: dict[str, str] = {}
        try:
            state = self._state()
            for item in state["indexes"]:
                marketplace_id = item["marketplaceId"]
                root = self.roots.get(marketplace_id)
                if root is None or not root.enabled:
                    cache_errors[marketplace_id] = "ROOT_UNAVAILABLE"
                    continue
                path = self.index_directory / marketplace_id / item["cacheFile"]
                try:
                    if path.is_symlink() or not path.is_file():
                        raise MarketplaceError(
                            "PLUGIN_MARKETPLACE_CACHE_INVALID",
                            "cached marketplace index is missing",
                        )
                    data = path.read_bytes()
                    if _sha256_bytes(data) != item["indexSha256"]:
                        raise MarketplaceError(
                            "PLUGIN_MARKETPLACE_CACHE_INVALID",
                            "cached marketplace index digest mismatch",
                        )
                    known = verify_marketplace_index(
                        data,
                        root=root,
                        allow_expired=True,
                        now=self._now(),
                    )
                    if (
                        known.sequence != item["sequence"]
                        or known.index_sha256 != item["indexSha256"]
                    ):
                        raise MarketplaceError(
                            "PLUGIN_MARKETPLACE_CACHE_INVALID",
                            "cached marketplace index does not match state",
                        )
                    known_indexes[marketplace_id] = known
                    indexes[marketplace_id] = verify_marketplace_index(
                        data,
                        root=root,
                        now=self._now(),
                    )
                except MarketplaceError as exc:
                    cache_errors[marketplace_id] = exc.code
        except BaseException:
            self._indexes = {}
            self._known_indexes = {}
            self._cache_errors = {}
            raise
        self._indexes = indexes
        self._known_indexes = known_indexes
        self._cache_errors = cache_errors

    def _release_for_digest(
        self,
        digest: str,
        *,
        include_expired: bool,
    ) -> tuple[VerifiedMarketplaceIndex, ReleaseRecord] | None:
        indexes = self._known_indexes if include_expired else self._current_indexes()
        matches = [
            (index, release)
            for index in indexes.values()
            for release in index.releases
            if any(artifact.sha256 == digest for artifact in release.artifacts)
        ]
        if len(matches) > 1:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_RELEASE_CONFLICT",
                "one artifact digest appears in multiple marketplace roots",
            )
        return matches[0] if matches else None

    def _current_indexes(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, VerifiedMarketplaceIndex]:
        current = now or self._now()
        return {
            marketplace_id: index
            for marketplace_id, index in self._indexes.items()
            if index.expires_datetime > current
        }

    def _current_cache_errors(
        self,
        current_indexes: Mapping[str, VerifiedMarketplaceIndex],
    ) -> dict[str, str]:
        errors = dict(self._cache_errors)
        for marketplace_id in self._indexes.keys() - current_indexes.keys():
            errors[marketplace_id] = "PLUGIN_MARKETPLACE_INDEX_EXPIRED"
        return errors

    def _release_visible(self, release: ReleaseRecord) -> bool:
        stage = getattr(release, "rollout_stage", "stable")
        minimum = ROLLOUT_STAGES.index(self.rollout_stage)
        return ROLLOUT_STAGES.index(stage) >= minimum

    def _artifact_for_host(self, release: ReleaseRecord) -> Any:
        return release.artifact_for_platform(
            self.operating_system,
            self.architecture,
        )

    def _release_available_on_host(self, release: ReleaseRecord) -> bool:
        if not self._release_visible(release):
            return False
        try:
            self._artifact_for_host(release)
            self._assert_minimum_host(release)
        except MarketplaceError:
            return False
        return True

    @staticmethod
    def _runtime_kind_label(artifact: Any) -> str:
        kinds = tuple(getattr(artifact, "runtime_kinds", ()))
        if not kinds:
            return "none"
        return kinds[0] if len(kinds) == 1 else "mixed"

    def _assert_minimum_host(self, release: ReleaseRecord) -> None:
        minimum = getattr(release, "minimum_host_version", None)
        if minimum is not None and _version_key(
            self.installer.host_version
        ) < _version_key(minimum):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_HOST_VERSION_UNSUPPORTED",
                "Marketplace release requires a newer CandleScope Host",
                details={
                    "hostVersion": self.installer.host_version,
                    "minimumHostVersion": minimum,
                },
            )

    def _assert_multi_runtime_release(
        self,
        bundle: VerifiedPlatformBundle,
        release: ReleaseRecord,
        artifact: Any,
    ) -> dict[str, Any]:
        if not isinstance(release, MultiRuntimeReleaseRecord) or not isinstance(
            artifact, SignedArtifactRecord
        ):
            return {
                "runtimeKinds": ["python-module"],
                "runtimeRegistry": [],
                "sandboxAvailable": self.operating_system == "windows",
            }
        self._assert_minimum_host(release)
        if bundle.manifest.permissions.to_wire() != release.permissions:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_PERMISSION_INVALID",
                "bundle permissions do not match the signed release scope",
            )
        declared = {
            entrypoint.id: entrypoint
            for entrypoint in bundle.manifest.normalized_entrypoints
        }
        bindings = {item.entrypoint_id: item for item in artifact.runtime_bindings}
        if set(declared) != set(bindings):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_RUNTIME_INVALID",
                "signed runtime bindings do not cover every manifest entrypoint",
            )
        contents = {item.path: item for item in bundle.envelope.contents}
        registry_evidence: list[dict[str, Any]] = []
        sandbox_available = True
        for entrypoint_id in sorted(declared):
            entrypoint = declared[entrypoint_id]
            runtime = entrypoint.runtime
            binding = bindings[entrypoint_id]
            expected_path = (
                bundle.wheels[0].path
                if runtime.kind == "python-module"
                else runtime.artifact
            )
            content = contents.get(expected_path)
            if (
                binding.runtime_kind != runtime.kind
                or binding.runtime_id != runtime.runtime_id
                or binding.plugin_artifact_path != expected_path
                or content is None
                or binding.plugin_artifact_sha256 != content.sha256
            ):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_RUNTIME_INVALID",
                    "signed runtime binding does not match the immutable bundle manifest",
                    details={"entrypointId": entrypoint_id},
                )
            profile = restricted_runtime_profile(runtime.kind)
            sandbox_available = sandbox_available and profile.supported(
                self.operating_system
            )
            if binding.host_runtime is not None:
                if self.managed_runtime_registry is None or not callable(
                    getattr(
                        self.managed_runtime_registry,
                        "verify_marketplace_binding",
                        None,
                    )
                ):
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_RUNTIME_REGISTRY_UNAVAILABLE",
                        "signed Marketplace runtime requires the managed Runtime Registry",
                    )
                runtime_kind = {
                    "java-jar": "java",
                    "node-module": "node",
                    "wasm-component": "wasm",
                }[binding.runtime_kind]
                evidence = binding.host_runtime
                try:
                    registry_evidence.append(
                        self.managed_runtime_registry.verify_marketplace_binding(
                            registry_id=evidence.registry_id,
                            registry_revision=evidence.registry_revision,
                            registry_sha256=evidence.registry_sha256,
                            runtime_id=binding.runtime_id,
                            runtime_kind=runtime_kind,
                            runtime_artifact_sha256=(evidence.runtime_artifact_sha256),
                            license_expression=evidence.license_expression,
                            operating_system=self.operating_system,
                            architecture=self.architecture,
                        )
                    )
                except MarketplaceError:
                    raise
                except Exception as exc:
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_RUNTIME_BINDING_INVALID",
                        "signed Marketplace runtime evidence does not match the active Registry chain",
                        details={
                            "entrypointId": entrypoint_id,
                            "errorType": type(exc).__name__,
                        },
                    ) from exc
        expected_license_inventory = canonical_sha256(
            {
                "plugin": release.license_expression,
                "dependencies": [item.to_wire() for item in release.dependencies],
                "runtimeLicenses": sorted(
                    {
                        item.host_runtime.license_expression
                        for item in artifact.runtime_bindings
                        if item.host_runtime is not None
                    }
                ),
            }
        )
        if artifact.license_inventory_sha256 != expected_license_inventory:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_LICENSE_INVENTORY_MISMATCH",
                "signed Marketplace license inventory does not cover plugin, dependencies, and runtimes",
            )
        if not sandbox_available:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SANDBOX_UNAVAILABLE",
                "Marketplace release has no supported Host sandbox for this runtime target",
                details={
                    "os": self.operating_system,
                    "runtimeKinds": list(artifact.runtime_kinds),
                },
            )
        return {
            "runtimeKinds": list(artifact.runtime_kinds),
            "runtimeRegistry": registry_evidence,
            "sandboxAvailable": sandbox_available,
        }

    def _assert_bundle_release(
        self,
        bundle: VerifiedPlatformBundle,
        release: ReleaseRecord,
        publisher: PublisherRecord,
        artifact: Any | None = None,
    ) -> dict[str, Any]:
        artifact = artifact or next(
            (item for item in release.artifacts if item.sha256 == bundle.sha256),
            None,
        )
        if artifact is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ARTIFACT_IDENTITY_MISMATCH",
                "bundle digest is not one of the independently signed release artifacts",
            )
        mismatches: dict[str, Any] = {}
        expected = {
            "bundleSha256": artifact.sha256,
            "bundleSize": artifact.size,
            "manifestSha256": artifact.manifest_sha256,
            "pluginId": release.plugin_id,
            "version": release.version,
            "publisher": release.publisher_id,
            "publisherKeyId": publisher.key_id,
            "sbomSha256": artifact.sbom_sha256,
        }
        actual = {
            "bundleSha256": bundle.sha256,
            "bundleSize": bundle.size,
            "manifestSha256": bundle.manifest_sha256,
            "pluginId": bundle.manifest.plugin.id,
            "version": bundle.manifest.plugin.version,
            "publisher": bundle.manifest.plugin.publisher,
            "publisherKeyId": publisher.key_id,
            "sbomSha256": next(
                (
                    item.sha256
                    for item in bundle.envelope.contents
                    if item.path == SBOM_PATH
                ),
                None,
            ),
        }
        for key, expected_value in expected.items():
            if actual[key] != expected_value:
                mismatches[key] = {"expected": expected_value, "actual": actual[key]}
        if mismatches:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ARTIFACT_IDENTITY_MISMATCH",
                "bundle identity does not match its signed release",
                details=mismatches,
            )
        PluginMarketplaceService._assert_sbom_release(bundle, release)
        return self._assert_multi_runtime_release(bundle, release, artifact)

    @staticmethod
    def _license_expression(value: Any, label: str) -> str:
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_LICENSE_MISSING",
                f"{label} must contain exactly one license expression",
            )
        item = value[0]
        if set(item) == {"expression"} and isinstance(item["expression"], str):
            result = item["expression"]
        elif (
            set(item) == {"license"}
            and isinstance(item["license"], dict)
            and set(item["license"]) == {"id"}
            and isinstance(item["license"]["id"], str)
        ):
            result = item["license"]["id"]
        else:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_LICENSE_MISSING",
                f"{label} license expression is invalid",
            )
        if not result or len(result) > 256:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_LICENSE_MISSING",
                f"{label} license expression is invalid",
            )
        return result

    @staticmethod
    def _assert_sbom_release(
        bundle: VerifiedPlatformBundle, release: ReleaseRecord
    ) -> None:
        try:
            with zipfile.ZipFile(bundle.path, "r") as archive:
                raw = archive.read(SBOM_PATH)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_INVALID", "signed release SBOM cannot be read"
            ) from exc
        PluginMarketplaceService._assert_sbom_metadata(raw, release)
        wheel_dependencies = sorted(
            (re.sub(r"[-_.]+", "-", item.package).lower(), item.version)
            for item in bundle.wheels
        )
        signed_dependencies = [
            (item.name, item.version) for item in release.dependencies
        ]
        missing_wheels = sorted(set(wheel_dependencies) - set(signed_dependencies))
        if missing_wheels:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_DEPENDENCY_MISMATCH",
                "signed dependencies do not cover every bundled wheel",
                details={"missingWheels": missing_wheels},
            )

    @staticmethod
    def _assert_sbom_metadata(raw: bytes, release: ReleaseRecord) -> None:
        try:
            value = loads_strict(raw)
        except PlatformContractError as exc:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_INVALID", "signed release SBOM cannot be read"
            ) from exc
        if not isinstance(value, dict):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_INVALID",
                "signed release SBOM must be an object",
            )
        metadata = value.get("metadata")
        component = metadata.get("component") if isinstance(metadata, dict) else None
        if (
            not isinstance(component, dict)
            or component.get("name") != release.plugin_id
            or component.get("version") != release.version
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_IDENTITY_MISMATCH",
                "SBOM application identity does not match the signed release",
            )
        plugin_license = PluginMarketplaceService._license_expression(
            component.get("licenses"),
            "SBOM metadata.component",
        )
        if plugin_license != release.license_expression:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_LICENSE_MISMATCH",
                "SBOM plugin license does not match signed release metadata",
            )
        components = value.get("components")
        if not isinstance(components, list):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_INVALID",
                "SBOM components must be an array",
            )
        declared: list[dict[str, str]] = []
        for index, item in enumerate(components):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not isinstance(item.get("version"), str)
            ):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_SBOM_INVALID",
                    f"SBOM component {index} is invalid",
                )
            name = re.sub(r"[-_.]+", "-", item["name"]).lower()
            declared.append(
                {
                    "name": name,
                    "version": item["version"],
                    "licenseExpression": PluginMarketplaceService._license_expression(
                        item.get("licenses"),
                        f"SBOM components[{index}]",
                    ),
                }
            )
        declared.sort(key=lambda item: (item["name"], item["version"]))
        expected = [item.to_wire() for item in release.dependencies]
        if declared != expected:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_SBOM_DEPENDENCY_MISMATCH",
                "SBOM dependencies or licenses do not match signed release metadata",
                details={"expected": expected, "actual": declared},
            )

    def bundle_trust(
        self,
        bundle: VerifiedPlatformBundle,
        *,
        fallback_trust_level: str,
    ) -> BundleTrust:
        known = self._release_for_digest(bundle.sha256, include_expired=True)
        if known is not None:
            known_index, known_release = known
            current_indexes = self._current_indexes()
            valid_index = current_indexes.get(known_index.marketplace_id)
            if valid_index is None:
                cache_errors = self._current_cache_errors(current_indexes)
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_OFFLINE_CACHE_INVALID",
                    "verified publisher activation has no current valid offline index",
                    details={
                        "marketplaceId": known_index.marketplace_id,
                        "reason": cache_errors.get(
                            known_index.marketplace_id,
                            "CACHE_UNAVAILABLE",
                        ),
                    },
                )
            release = valid_index.release_by_digest()[bundle.sha256]
            publisher = valid_index.publisher_by_id()[release.publisher_id]
            if valid_index.is_revoked(release, now=self._now()):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_RELEASE_REVOKED",
                    "verified publisher release is revoked",
                    details={
                        "marketplaceId": valid_index.marketplace_id,
                        "pluginId": release.plugin_id,
                    },
                )
            self._assert_bundle_release(bundle, release, publisher)
            return BundleTrust(
                "verified-publisher",
                f"publisher-key:{publisher.key_id}",
                "signed-marketplace",
                valid_index.marketplace_id,
                release,
            )
        state = self._state()
        candidate = next(
            (
                item
                for item in state["candidates"]
                if item["bundleSha256"] == bundle.sha256
            ),
            None,
        )
        if candidate is not None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_OFFLINE_CACHE_INVALID",
                "signed marketplace candidate has no current verified index",
                details={
                    "marketplaceId": candidate["marketplaceId"],
                    "pluginId": candidate["pluginId"],
                    "reason": self._cache_errors.get(
                        candidate["marketplaceId"],
                        "CACHE_UNAVAILABLE",
                    ),
                },
            )
        local = next(
            (
                item
                for item in state["localBundles"]
                if item["bundleSha256"] == bundle.sha256
            ),
            None,
        )
        if local is not None:
            expected = {
                "pluginId": bundle.manifest.plugin.id,
                "version": bundle.manifest.plugin.version,
                "publisher": bundle.manifest.plugin.publisher,
            }
            if any(local[key] != value for key, value in expected.items()):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_LOCAL_EVIDENCE_INVALID",
                    "local bundle evidence does not match the immutable bundle",
                )
            return BundleTrust(
                "local-developer",
                manifest_publisher_identity(bundle.manifest),
                "local-file",
                None,
                None,
            )
        return BundleTrust(
            fallback_trust_level,
            manifest_publisher_identity(bundle.manifest),
            "legacy-or-first-party-bootstrap",
            None,
            None,
        )

    def record_local_bundle(self, bundle: VerifiedPlatformBundle) -> None:
        if self._release_for_digest(bundle.sha256, include_expired=True) is not None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_TRUST_DOWNGRADE_DENIED",
                "signed marketplace artifact cannot be relabeled as local",
            )
        with security_lock(self.lock_path):
            state = self._state()
            current = next(
                (
                    item
                    for item in state["localBundles"]
                    if item["bundleSha256"] == bundle.sha256
                ),
                None,
            )
            record = {
                "bundleSha256": bundle.sha256,
                "pluginId": bundle.manifest.plugin.id,
                "version": bundle.manifest.plugin.version,
                "publisher": bundle.manifest.plugin.publisher,
                "recordedAt": _utc_now(),
            }
            if current is not None:
                comparable = {
                    key: current[key] for key in record if key != "recordedAt"
                }
                expected = {key: record[key] for key in record if key != "recordedAt"}
                if comparable != expected:
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_LOCAL_EVIDENCE_INVALID",
                        "local bundle digest was rebound to another identity",
                    )
                return
            state["localBundles"].append(record)
            self._commit_state(state)

    def _cache_index(
        self,
        verified: VerifiedMarketplaceIndex,
    ) -> None:
        path = (
            self.index_directory
            / verified.marketplace_id
            / f"{verified.index_sha256.removeprefix('sha256:')}.json"
        )
        _write_bytes(path, verified.canonical_bytes)

    @staticmethod
    def _assert_index_update(
        current: VerifiedMarketplaceIndex | None,
        candidate: VerifiedMarketplaceIndex,
    ) -> None:
        if current is None:
            if candidate.sequence != 1 or candidate.previous_index_sha256 is not None:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_INDEX_CHAIN_INVALID",
                    "first observed marketplace index must start at sequence 1",
                )
            return
        if candidate.sequence == current.sequence:
            if candidate.index_sha256 != current.index_sha256:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_IMMUTABILITY_VIOLATION",
                    "marketplace index sequence was replaced in place",
                )
            return
        if (
            candidate.sequence != current.sequence + 1
            or candidate.previous_index_sha256 != current.index_sha256
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_INDEX_CHAIN_INVALID",
                "marketplace index sequence or previous digest is invalid",
            )
        if (
            len(candidate.releases) < len(current.releases)
            or candidate.releases[: len(current.releases)] != current.releases
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_IMMUTABILITY_VIOLATION",
                "published releases cannot be removed or replaced",
            )
        old = {
            (item.scope, item.subject, item.reason_code, item.effective_at)
            for item in current.revocations
        }
        new = {
            (item.scope, item.subject, item.reason_code, item.effective_at)
            for item in candidate.revocations
        }
        if not old.issubset(new):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_REVOCATION_ROLLBACK",
                "marketplace revocations are append-only",
            )

    def import_index(
        self,
        data: bytes,
        *,
        marketplace_id: str,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_DISABLED",
                "signed Marketplace is disabled",
                status_code=404,
            )
        root = self.roots.get(marketplace_id)
        if root is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ROOT_NOT_FOUND",
                "marketplace root is not build-pinned",
                status_code=404,
            )
        verified = verify_marketplace_index(data, root=root, now=self._now())
        with security_lock(self.lock_path):
            self.reload_cache()
            current = self._known_indexes.get(marketplace_id)
            self._assert_index_update(current, verified)
            if current is not None and current.index_sha256 == verified.index_sha256:
                return {
                    "changed": False,
                    "marketplaceId": marketplace_id,
                    "sequence": current.sequence,
                    "indexSha256": current.index_sha256,
                }
            self._cache_index(verified)
            state = self._state()
            replacement = {
                "marketplaceId": marketplace_id,
                "sequence": verified.sequence,
                "indexSha256": verified.index_sha256,
                "cacheFile": f"{verified.index_sha256.removeprefix('sha256:')}.json",
                "importedAt": _utc_now(),
            }
            state["indexes"] = [
                item
                for item in state["indexes"]
                if item["marketplaceId"] != marketplace_id
            ]
            state["indexes"].append(replacement)
            self._commit_state(state)
            self.reload_cache()
        return {
            "changed": True,
            "marketplaceId": marketplace_id,
            "sequence": verified.sequence,
            "indexSha256": verified.index_sha256,
            "releaseCount": len(verified.releases),
            "revocationCount": len(verified.revocations),
        }

    def refresh(self, marketplace_id: str) -> dict[str, Any]:
        root = self.roots.get(marketplace_id)
        if not self.enabled or root is None or not root.enabled:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ROOT_NOT_FOUND",
                "marketplace root is unavailable",
                status_code=404,
            )
        try:
            data = self.fetcher.get(root.index_url, maximum=MAX_INDEX_BYTES)
            result = self.import_index(data, marketplace_id=marketplace_id)
        except Exception:
            self.telemetry.record("none", "refresh", "failure")
            raise
        self.telemetry.record("none", "refresh", "success")
        return result

    def _active_record(self, plugin_id: str) -> Any | None:
        return (
            load_activation_registry(self.installer.registry_path)
            .by_id()
            .get(plugin_id)
        )

    def _candidate(
        self, state: Mapping[str, Any], plugin_id: str
    ) -> dict[str, Any] | None:
        return next(
            (item for item in state["candidates"] if item["pluginId"] == plugin_id),
            None,
        )

    def _release(
        self,
        plugin_id: str,
        version: str | None = None,
    ) -> tuple[VerifiedMarketplaceIndex, ReleaseRecord, PublisherRecord]:
        matches = [
            (index, release)
            for index in self._current_indexes().values()
            for release in index.releases
            if release.plugin_id == plugin_id
            and (version is None or release.version == version)
            and not index.is_revoked(release, now=self._now())
            and self._release_available_on_host(release)
        ]
        if not matches:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_RELEASE_NOT_FOUND",
                "marketplace release is unavailable",
                status_code=404,
            )
        if version is None:
            maximum = max(_version_key(release.version) for _index, release in matches)
            matches = [
                item for item in matches if _version_key(item[1].version) == maximum
            ]
        if len(matches) != 1:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_RELEASE_CONFLICT",
                "marketplace release identity is ambiguous",
            )
        index, release = matches[0]
        return index, release, index.publisher_by_id()[release.publisher_id]

    def _assert_ownership(
        self,
        plugin_id: str,
        release: ReleaseRecord,
        marketplace_id: str,
    ) -> Any | None:
        if self.unified is not None and (
            plugin_id in self.unified.store.snapshot()["plugins"]
            or self.legacy_fenced(plugin_id)
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ACTIVATION_OWNED",
                "a unified activation already owns this plugin ID",
            )
        current = self._active_record(plugin_id)
        if current is None:
            return None
        trust = self._release_for_digest(
            current.bundle_sha256,
            include_expired=True,
        )
        if trust is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ACTIVATION_OWNED",
                "marketplace cannot override a local or first-party activation",
                details={"pluginId": plugin_id},
            )
        current_index, current_release = trust
        if (
            current_index.marketplace_id != marketplace_id
            or current_release.publisher_id != release.publisher_id
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ACTIVATION_OWNED",
                "marketplace cannot replace another source or publisher",
                details={"pluginId": plugin_id},
            )
        if _major(current.version) != _major(release.version):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_MIGRATION_REQUIRED",
                "major-version marketplace updates require a future explicit migration contract",
                details={
                    "fromVersion": current.version,
                    "toVersion": release.version,
                },
            )
        if _version_key(release.version) <= _version_key(current.version):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_UPDATE_NOT_NEWER",
                "marketplace update must have a newer version",
            )
        return current

    def _artifact_path(self, digest: str) -> Path:
        if _SHA256.fullmatch(digest) is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ARTIFACT_INVALID",
                "artifact digest is invalid",
            )
        return self.artifact_directory / f"{digest.removeprefix('sha256:')}.cspkg"

    def _quarantine_cached_artifact(
        self,
        *,
        release: ReleaseRecord,
        artifact: Any,
        reason: str,
    ) -> dict[str, Any]:
        source = self._artifact_path(artifact.sha256)
        self.quarantine_directory.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        payload_name = f"{artifact.sha256.removeprefix('sha256:')}-{token}.cspkg"
        destination = self.quarantine_directory / payload_name
        moved = False
        if source.exists() or source.is_symlink():
            os.replace(source, destination)
            moved = True
        receipt = {
            "schemaVersion": "candlescope.marketplace-quarantine/1",
            "pluginId": release.plugin_id,
            "version": release.version,
            "bundleSha256": artifact.sha256,
            "reason": reason[:128],
            "quarantinedAt": _utc_now(),
            "artifactFile": payload_name if moved else None,
            "payloadMoved": moved,
        }
        atomic_write_json(
            self.quarantine_directory / f"receipt-{token}.json",
            receipt,
        )
        return receipt

    def _quarantine_receipts(self) -> list[dict[str, Any]]:
        if not self.quarantine_directory.exists():
            return []
        receipts: list[dict[str, Any]] = []
        for path in sorted(self.quarantine_directory.glob("receipt-*.json")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_384:
                continue
            try:
                value = loads_strict(path.read_bytes())
            except (OSError, PlatformContractError):
                continue
            if (
                isinstance(value, dict)
                and set(value)
                == {
                    "schemaVersion",
                    "pluginId",
                    "version",
                    "bundleSha256",
                    "reason",
                    "quarantinedAt",
                    "artifactFile",
                    "payloadMoved",
                }
                and value.get("schemaVersion") == "candlescope.marketplace-quarantine/1"
            ):
                receipts.append(value)
        return receipts

    def prepare(
        self,
        plugin_id: str,
        *,
        version: str | None = None,
        artifact_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        index, release, publisher = self._release(plugin_id, version)
        artifact = self._artifact_for_host(release)
        self._require_current_install_format(artifact)
        self._assert_minimum_host(release)
        unified = self._is_unified(artifact)
        if unified:
            self._unified_owner(plugin_id, release, index, publisher)
        else:
            self._assert_ownership(plugin_id, release, index.marketplace_id)
        destination = self._artifact_path(artifact.sha256)
        cache_reused = False
        if artifact_bytes is None:
            if (
                destination.is_file()
                and not destination.is_symlink()
                and _hash_file(destination) == (artifact.sha256, artifact.size)
            ):
                artifact_bytes = destination.read_bytes()
                cache_reused = True
                self.telemetry.record(
                    self._runtime_kind_label(artifact), "cache-reuse", "success"
                )
            elif destination.exists() or destination.is_symlink():
                self._quarantine_cached_artifact(
                    release=release,
                    artifact=artifact,
                    reason="CACHE_CORRUPT",
                )
            if artifact_bytes is None and artifact.size > MAX_REMOTE_ARTIFACT_BYTES:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_REMOTE_ARTIFACT_TOO_LARGE",
                    "remote marketplace artifacts exceed the bounded download limit",
                    details={"maximum": MAX_REMOTE_ARTIFACT_BYTES},
                )
            if artifact_bytes is None:
                artifact_bytes = self.fetcher.get(
                    artifact.url,
                    maximum=artifact.size,
                )
        if (
            len(artifact_bytes) != artifact.size
            or _sha256_bytes(artifact_bytes) != artifact.sha256
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_ARTIFACT_DIGEST_MISMATCH",
                "downloaded artifact does not match signed size and digest",
            )
        self.artifact_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="marketplace-",
            suffix=".cspkg",
            dir=self.artifact_directory,
            delete=False,
        ) as temporary:
            temporary.write(artifact_bytes)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            compatibility = self._verify_artifact(
                temporary_path, release, publisher, artifact
            )
            _write_bytes(destination, artifact_bytes)
        finally:
            temporary_path.unlink(missing_ok=True)
        with security_lock(self.lock_path):
            current_index, current_release, current_publisher = self._release(
                plugin_id,
                release.version,
            )
            if (
                current_index.marketplace_id != index.marketplace_id
                or current_release != release
                or current_publisher != publisher
            ):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_CANDIDATE_STALE",
                    "marketplace release changed while its artifact was being verified",
                )
            if unified:
                manifest = compatibility["manifest"]
                current = self._unified_owner(plugin_id, release, index, publisher)
                permission_diff = self._unified_permission_diff(
                    manifest, artifact.sha256, current
                )
                legacy_review, legacy_version = self._legacy_review(
                    plugin_id, release, index, publisher, self.unified.store.snapshot()
                )
                from_version = current["version"] if current else legacy_version
            else:
                current = self._assert_ownership(
                    plugin_id, release, index.marketplace_id
                )
                permission_diff = self.installer.preview_permission_diff(
                    destination, expected_sha256=artifact.sha256
                ).to_wire()
                from_version = current.version if current is not None else None
            candidate = {
                "pluginId": plugin_id,
                "version": release.version,
                "marketplaceId": index.marketplace_id,
                "publisherId": release.publisher_id,
                "bundleSha256": artifact.sha256,
                "artifactFile": (f"{artifact.sha256.removeprefix('sha256:')}.cspkg"),
                "phase": "verified-staged",
                "preparedAt": _utc_now(),
                "fromVersion": from_version,
                "permissionDiff": permission_diff,
                "compatibility": {
                    "hostVersion": self.installer.host_version,
                    "verified": True,
                    "marketplaceSchema": index.schema_version,
                    "platform": {
                        "os": self.operating_system,
                        "arch": self.architecture,
                        "artifactId": getattr(artifact, "artifact_id", "legacy"),
                    },
                    "runtimeKinds": compatibility["runtimeKinds"],
                    "runtimeRegistry": compatibility["runtimeRegistry"],
                    "sandboxAvailable": compatibility["sandboxAvailable"],
                    "cacheReuse": cache_reused,
                    "rolloutStage": getattr(release, "rollout_stage", "stable"),
                },
                "migration": {
                    "required": False,
                    "supported": True,
                    "policy": "same-major-only",
                },
                "observation": {
                    "status": "not-started",
                    "observedAt": None,
                    "detail": None,
                },
            }
            if unified:
                candidate["unifiedApproval"] = {
                    "packageSha256": artifact.sha256,
                    "permissions": list(manifest.permissions),
                    "previousGeneration": current["generation"] if current else None,
                    **({"legacy": legacy_review} if legacy_review else {}),
                }
            state = self._state()
            existing = self._candidate(state, plugin_id)
            if existing and self._candidate_status(existing)["phase"] == "observing":
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_OBSERVATION_PENDING",
                    "a marketplace release is still under observation",
                )
            state["candidates"] = [
                item for item in state["candidates"] if item["pluginId"] != plugin_id
            ]
            state["candidates"].append(candidate)
            self._commit_state(state)
        self.telemetry.record(self._runtime_kind_label(artifact), "prepare", "success")
        return dict(candidate)

    def _verified_candidate(
        self,
        plugin_id: str,
    ) -> tuple[dict[str, Any], ReleaseRecord, PublisherRecord, Path]:
        state = self._state()
        candidate = self._candidate(state, plugin_id)
        if candidate is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_CANDIDATE_NOT_FOUND",
                "plugin has no verified marketplace candidate",
                status_code=404,
            )
        index, release, publisher = self._release(plugin_id, candidate["version"])
        artifact = self._artifact_for_host(release)
        self._require_current_install_format(artifact)
        if (
            index.marketplace_id != candidate["marketplaceId"]
            or release.publisher_id != candidate["publisherId"]
            or artifact.sha256 != candidate["bundleSha256"]
            or self._is_unified(artifact) != ("unifiedApproval" in candidate)
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_CANDIDATE_STALE",
                "marketplace candidate no longer matches the verified index",
            )
        if "unifiedApproval" in candidate:
            self._unified_owner(plugin_id, release, index, publisher)
        else:
            if self.legacy_fenced(plugin_id):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_ACTIVATION_OWNED",
                    "plugin already migrated to the unified lifecycle",
                )
            current = self._active_record(plugin_id)
            if current is None or current.bundle_sha256 != artifact.sha256:
                self._assert_ownership(plugin_id, release, index.marketplace_id)
        path = self.artifact_directory / candidate["artifactFile"]
        if (
            path.is_symlink()
            or not path.is_file()
            or _hash_file(path)
            != (
                artifact.sha256,
                artifact.size,
            )
        ):
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_CACHE_INVALID",
                "staged marketplace artifact failed its content-addressed check",
            )
        self._verify_artifact(path, release, publisher, artifact)
        return dict(candidate), release, publisher, path

    def _replace_candidate_in_state(
        self,
        state: dict[str, Any],
        replacement: dict[str, Any],
    ) -> None:
        if self._candidate(state, replacement["pluginId"]) is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_CANDIDATE_NOT_FOUND",
                "plugin has no marketplace candidate",
            )
        state["candidates"] = [
            item
            for item in state["candidates"]
            if item["pluginId"] != replacement["pluginId"]
        ]
        state["candidates"].append(replacement)
        self._commit_state(state)

    def _replace_candidate(self, replacement: dict[str, Any]) -> None:
        with security_lock(self.lock_path):
            self._replace_candidate_in_state(self._state(), replacement)

    def apply(self, plugin_id: str) -> dict[str, Any]:
        with security_lock(self.lock_path):
            candidate, release, _publisher, path = self._verified_candidate(plugin_id)
            if "unifiedApproval" in candidate:
                if candidate["phase"] not in {"verified-staged", "activation-staged"}:
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_ACTIVATION_STATE_INVALID",
                        "prepare the unified marketplace release before staging it",
                    )
                try:
                    package = self.unified.store.stage(
                        path, marketplace_digest=candidate["bundleSha256"]
                    )
                except (PackageError, LifecycleError) as exc:
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_CACHE_INVALID", str(exc)
                    ) from exc
                candidate["phase"] = "activation-staged"
                self._replace_candidate_in_state(self._state(), candidate)
                return {
                    "candidate": candidate,
                    "installation": {**package.review(), "publisherVerified": True},
                }
            activation_savepoint = self.installer.capture_activation_state(plugin_id)
            result = self.installer.install(
                path,
                expected_sha256=candidate["bundleSha256"],
                enabled=False,
                force_staged=True,
            )
            candidate["phase"] = "activation-staged"
            candidate["permissionDiff"] = result.permission_diff
            try:
                self._replace_candidate_in_state(self._state(), candidate)
            except BaseException as state_error:
                if result.changed:
                    try:
                        self.installer.restore_activation_state(
                            activation_savepoint,
                            expected_activation_id=result.activation_id,
                            expected_grant_record_sha256=(result.grant_record_sha256),
                        )
                    except BaseException as compensation_error:
                        raise MarketplaceError(
                            "PLUGIN_MARKETPLACE_APPLY_COMPENSATION_FAILED",
                            "marketplace candidate commit failed and activation rollback did not complete",
                            details={
                                "pluginId": plugin_id,
                                "activationId": result.activation_id,
                                "stateError": (
                                    f"{type(state_error).__name__}: {state_error}"
                                )[:1024],
                                "compensationError": (
                                    f"{type(compensation_error).__name__}: "
                                    f"{compensation_error}"
                                )[:1024],
                            },
                        ) from compensation_error
                raise
        self.telemetry.record(
            self._runtime_kind_label(self._artifact_for_host(release)),
            "apply",
            "success",
        )
        return {
            "candidate": candidate,
            "installation": result.to_wire(),
        }

    def is_unified_candidate(self, plugin_id: str) -> bool:
        candidate = self._candidate(self._state(), plugin_id)
        return candidate is not None and "unifiedApproval" in candidate

    def _candidate_status(self, candidate, snapshot=None):
        if (
            self.unified is None
            or "unifiedApproval" not in candidate
            or candidate["phase"] not in {"observing", "active"}
        ):
            return candidate
        snapshot = self.unified.store.snapshot() if snapshot is None else snapshot
        plugin_id = candidate["pluginId"]
        record = snapshot["plugins"].get(plugin_id, {})
        owns_release = (
            record.get("enabled")
            and "marketplace" in record
            and record["packageSha256"] == candidate["bundleSha256"]
            and record["generation"]
            != candidate["unifiedApproval"]["previousGeneration"]
        )
        if candidate["phase"] == "active":
            if (
                owns_release
                or plugin_id in snapshot.get("marketplaceMigrations", {})
                or self._active_record(plugin_id) is None
            ):
                return candidate
            return {
                **candidate,
                "phase": "rolled-back",
                "observation": {
                    "status": "failed",
                    "observedAt": None,
                    "detail": "the verified Platform v2 activation was restored",
                },
            }
        if (
            owns_release
            and (snapshot.get("marketplaceTrial") or {}).get("pluginId") == plugin_id
        ):
            return candidate
        return {
            **candidate,
            "phase": "active" if owns_release else "rolled-back",
            "observation": {
                "status": "passed" if owns_release else "failed",
                "observedAt": None,
                "detail": (
                    "unified activation was committed"
                    if owns_release
                    else "unified activation was recovered or superseded"
                ),
            },
        }

    def begin_unified_activation(
        self, plugin_id: str, approval: dict
    ) -> dict[str, Any]:
        with security_lock(self.lock_path):
            candidate, release, publisher, _path = self._verified_candidate(plugin_id)
            expected = candidate.get("unifiedApproval")
            if (
                self.unified is None
                or expected is None
                or candidate["phase"] != "activation-staged"
                or not self.unified.ready
                or self.unified.safe_mode
            ):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_ACTIVATION_STATE_INVALID",
                    "unified candidate is not staged for activation",
                )
            if canonical_sha256(approval) != canonical_sha256(expected):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_APPROVAL_MISMATCH",
                    "approve the reviewed package digest, permissions and activation generation",
                    status_code=409,
                )
            index = self._current_indexes().get(candidate["marketplaceId"])
            if index is None:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_CANDIDATE_STALE",
                    "signed index expired during review",
                )
            migration, _ = self._legacy_review(
                plugin_id, release, index, publisher, self.unified.store.snapshot()
            )
            if migration != expected.get("legacy"):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_MIGRATION_STALE",
                    "legacy activation or its permissions changed since review",
                )
            digest = expected["packageSha256"]
            grant = {
                "marketplaceId": candidate["marketplaceId"],
                "publisherId": release.publisher_id,
                "publisherKeyId": publisher.key_id,
                "permissions": expected["permissions"],
            }
            try:
                generation = self.unified.store.begin_marketplace(
                    digest,
                    grant,
                    previous_generation=expected["previousGeneration"],
                    migration=migration,
                )
            except ValueError as exc:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_ACTIVATION_CONFLICT"
                    if isinstance(exc, RevisionConflict)
                    else "PLUGIN_MARKETPLACE_ACTIVATION_STATE_INVALID",
                    str(exc),
                    status_code=409,
                ) from exc
            try:
                candidate["phase"] = "observing"
                candidate["observation"] = {
                    "status": "observing",
                    "observedAt": None,
                    "detail": None,
                }
                self._replace_candidate_in_state(self._state(), candidate)
            except BaseException:
                self.unified.store.finish_marketplace(
                    plugin_id, generation, healthy=False
                )
                raise
            return {
                "candidate": candidate,
                "generation": generation,
                "migration": self.unified.store.snapshot()["marketplaceMigrations"][
                    plugin_id
                ]
                if migration
                else None,
            }

    def finish_unified_activation(self, plugin_id, generation, *, healthy, detail):
        with security_lock(self.lock_path):
            state = self._state()
            candidate = self._candidate(state, plugin_id)
            snapshot = self.unified.store.snapshot()
            record = snapshot["plugins"].get(plugin_id, {})
            current = bool(
                "marketplace" in record
                and record["generation"] == generation
                and self.unified_release_current(plugin_id, record)
            )
            healthy = healthy and current
            changed = self.unified.store.finish_marketplace(
                plugin_id, generation, healthy=healthy
            )
            if not changed:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_ACTIVATION_CONFLICT",
                    "unified activation changed while under observation",
                    status_code=409,
                )
            if not current:
                detail = "signed marketplace release is unavailable or revoked"
            phase = "active" if healthy else "rolled-back"
            if (
                candidate is not None
                and candidate["phase"] == "observing"
                and candidate["bundleSha256"] == record.get("packageSha256")
            ):
                candidate["phase"] = phase
                candidate["observation"] = {
                    "status": "passed" if healthy else "failed",
                    "observedAt": _utc_now(),
                    "detail": detail[:1024],
                }
                self._replace_candidate_in_state(state, candidate)
            before = (snapshot.get("marketplaceTrial") or {}).get("previous")
            return {
                "candidate": candidate,
                "healthy": healthy,
                "detail": detail[:1024],
                "restoredVersion": before["version"]
                if not healthy and before
                else None,
            }

    def begin_activation(self, plugin_id: str) -> dict[str, Any]:
        with security_lock(self.lock_path):
            candidate, release, _publisher, _path = self._verified_candidate(plugin_id)
            if "unifiedApproval" in candidate:
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_APPROVAL_REQUIRED",
                    "unified marketplace releases require explicit approval",
                    status_code=409,
                )
            current = self._active_record(plugin_id)
            artifact = self._artifact_for_host(release)
            if (
                current is None
                or current.bundle_sha256 != artifact.sha256
                or candidate["phase"] not in {"activation-staged", "observing"}
            ):
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_ACTIVATION_STATE_INVALID",
                    "marketplace candidate is not the current staged activation",
                )
            result = self.installer.enable(plugin_id)
            candidate["phase"] = "observing"
            candidate["observation"] = {
                "status": "observing",
                "observedAt": None,
                "detail": None,
            }
            try:
                self._replace_candidate_in_state(self._state(), candidate)
            except BaseException:
                self.installer.disable(plugin_id)
                raise
        self.telemetry.record(
            self._runtime_kind_label(self._artifact_for_host(release)),
            "activate",
            "success",
        )
        return {"candidate": candidate, "stateChange": result.to_wire()}

    def finish_observation(
        self,
        plugin_id: str,
        *,
        healthy: bool,
        detail: str,
    ) -> dict[str, Any]:
        observed_release: ReleaseRecord | None = None
        with security_lock(self.lock_path):
            state = self._state()
            candidate = self._candidate(state, plugin_id)
            if candidate is None or candidate["phase"] != "observing":
                raise MarketplaceError(
                    "PLUGIN_MARKETPLACE_OBSERVATION_INVALID",
                    "marketplace candidate is not under health observation",
                )
            if healthy:
                _verified, release, _publisher, _path = self._verified_candidate(
                    plugin_id
                )
                observed_release = release
                current = self._active_record(plugin_id)
                if (
                    current is None
                    or current.state != "active"
                    or current.bundle_sha256 != self._artifact_for_host(release).sha256
                ):
                    raise MarketplaceError(
                        "PLUGIN_MARKETPLACE_OBSERVATION_INVALID",
                        "marketplace candidate lost its active verified activation",
                    )
            replacement = dict(candidate)
            replacement["phase"] = "active" if healthy else "failed"
            replacement["observation"] = {
                "status": "passed" if healthy else "failed",
                "observedAt": _utc_now(),
                "detail": detail[:512],
            }
            self._replace_candidate_in_state(state, replacement)
        if observed_release is None:
            _index, observed_release, _publisher = self._release(
                plugin_id,
                candidate["version"],
            )
        self.telemetry.record(
            self._runtime_kind_label(self._artifact_for_host(observed_release)),
            "observation",
            "success" if healthy else "failure",
        )
        return replacement

    def mark_rolled_back(self, plugin_id: str, *, detail: str) -> None:
        with security_lock(self.lock_path):
            state = self._state()
            candidate = self._candidate(state, plugin_id)
            if candidate is None:
                return
            replacement = dict(candidate)
            replacement["phase"] = "rolled-back"
            replacement["observation"] = {
                "status": "rolled-back",
                "observedAt": _utc_now(),
                "detail": detail[:512],
            }
            self._replace_candidate_in_state(state, replacement)
        try:
            _index, release, _publisher = self._release(
                plugin_id,
                candidate["version"],
            )
        except MarketplaceError:
            return
        self.telemetry.record(
            self._runtime_kind_label(self._artifact_for_host(release)),
            "rollback",
            "success",
        )

    def enforce_trust_policy(self) -> tuple[str, ...]:
        changed: list[str] = []
        quarantined_digests: set[str] = set()
        with security_lock(self.lock_path):
            state = self._state()
            state_changed = False
            current_indexes = self._current_indexes()
            legacy_records = (
                load_activation_registry(self.installer.registry_path).plugins
                if self.allow_legacy_execution
                else ()
            )
            fenced = self.legacy_fences() if legacy_records else set()
            for record in legacy_records:
                if record.state != "active" or record.plugin_id in fenced:
                    continue
                known = self._release_for_digest(
                    record.bundle_sha256,
                    include_expired=True,
                )
                if known is None:
                    candidate = next(
                        (
                            item
                            for item in state["candidates"]
                            if item["bundleSha256"] == record.bundle_sha256
                        ),
                        None,
                    )
                    if candidate is None:
                        continue
                    result = self.installer.disable(record.plugin_id)
                    if result.changed:
                        changed.append(record.plugin_id)
                    continue
                index, release = known
                valid = current_indexes.get(index.marketplace_id)
                blocked = valid is None or valid.is_revoked(release, now=self._now())
                if blocked:
                    result = self.installer.disable(record.plugin_id)
                    if result.changed:
                        changed.append(record.plugin_id)
                    if valid is not None and valid.is_revoked(release, now=self._now()):
                        artifact = next(
                            item
                            for item in release.artifacts
                            if item.sha256 == record.bundle_sha256
                        )
                        if self._artifact_path(artifact.sha256).exists():
                            self._quarantine_cached_artifact(
                                release=release,
                                artifact=artifact,
                                reason="SIGNED_REVOCATION",
                            )
                            quarantined_digests.add(artifact.sha256)
            for candidate in state["candidates"]:
                known = self._release_for_digest(
                    candidate["bundleSha256"],
                    include_expired=True,
                )
                if known is None:
                    continue
                index, release = known
                valid = current_indexes.get(index.marketplace_id)
                if valid is None or not valid.is_revoked(release, now=self._now()):
                    continue
                artifact = next(
                    item
                    for item in release.artifacts
                    if item.sha256 == candidate["bundleSha256"]
                )
                if (
                    artifact.sha256 not in quarantined_digests
                    and self._artifact_path(artifact.sha256).exists()
                ):
                    self._quarantine_cached_artifact(
                        release=release,
                        artifact=artifact,
                        reason="SIGNED_REVOCATION",
                    )
                    quarantined_digests.add(artifact.sha256)
                if candidate["phase"] != "quarantined":
                    candidate["phase"] = "quarantined"
                    candidate["observation"] = {
                        "status": "failed",
                        "observedAt": _utc_now(),
                        "detail": "SIGNED_REVOCATION",
                    }
                    state_changed = True
            if state_changed:
                self._commit_state(state)
        for digest in quarantined_digests:
            known = self._release_for_digest(digest, include_expired=True)
            if known is not None:
                _index, release = known
                artifact = next(
                    item for item in release.artifacts if item.sha256 == digest
                )
                self.telemetry.record(
                    self._runtime_kind_label(artifact),
                    "revocation-quarantine",
                    "quarantined",
                )
        return tuple(changed)

    def _update_for_record(self, record: Any) -> dict[str, Any]:
        state = self._state()
        candidate = self._candidate(state, record.plugin_id)
        known = self._release_for_digest(record.bundle_sha256, include_expired=True)
        if known is None:
            conflicts = any(
                release.plugin_id == record.plugin_id
                for index in self._current_indexes().values()
                for release in index.releases
            )
            return {
                "policy": "signed-marketplace-or-local-artifact",
                "automatic": False,
                "available": False,
                "ownership": "local-or-first-party",
                "reason": (
                    "MARKETPLACE_CANNOT_OVERRIDE_LOCAL_ACTIVATION"
                    if conflicts
                    else "NO_SIGNED_UPDATE"
                ),
                "candidate": candidate,
                "latest": None,
            }
        current_index, current_release = known
        matches = [
            (index, release)
            for index in self._current_indexes().values()
            for release in index.releases
            if release.plugin_id == record.plugin_id
            and release.publisher_id == current_release.publisher_id
            and index.marketplace_id == current_index.marketplace_id
            and not index.is_revoked(release, now=self._now())
            and self._release_available_on_host(release)
            and _major(release.version) == _major(record.version)
            and _version_key(release.version) > _version_key(record.version)
        ]
        latest = (
            max(matches, key=lambda item: _version_key(item[1].version))[1]
            if matches
            else None
        )
        return {
            "policy": "signed-marketplace-or-local-artifact",
            "automatic": False,
            "available": latest is not None,
            "ownership": "signed-marketplace",
            "reason": None if latest is not None else "NO_NEWER_SIGNED_RELEASE",
            "candidate": candidate,
            "latest": (
                latest.to_public_wire(
                    revoked=False,
                )
                if latest is not None
                else None
            ),
        }

    def update_status(self, plugin_id: str) -> dict[str, Any]:
        record = self._active_record(plugin_id)
        if record is None:
            raise MarketplaceError(
                "PLUGIN_MARKETPLACE_PLUGIN_NOT_FOUND",
                "plugin is not installed",
                status_code=404,
            )
        return self._update_for_record(record)

    def _catalog_assurances(
        self,
        release: ReleaseRecord,
        publisher: PublisherRecord,
    ) -> dict[str, Any]:
        try:
            artifact = self._artifact_for_host(release)
        except MarketplaceError:
            artifact = None
        runtime_kinds = (
            list(getattr(artifact, "runtime_kinds", ())) if artifact is not None else []
        )
        profiles = [
            restricted_runtime_profile(kind).to_wire(
                platform_name=self.operating_system
            )
            for kind in runtime_kinds
        ]
        sandbox_available = (bool(profiles) or self._is_unified(artifact)) and all(
            item["sandboxSupported"] for item in profiles
        )
        if not isinstance(release, MultiRuntimeReleaseRecord):
            runtime_kinds = ["python-module"]
            profiles = [
                restricted_runtime_profile("python-module").to_wire(
                    platform_name=self.operating_system
                )
            ]
            sandbox_available = profiles[0]["sandboxSupported"]
        return {
            "publisherVerified": publisher.verification_tier
            in {"verified", "official"},
            "officialMaintained": getattr(
                release,
                "official_maintained",
                False,
            ),
            "sandbox": {
                "available": sandbox_available,
                "runtimeKinds": runtime_kinds,
                "profiles": profiles,
            },
            "permissions": getattr(
                release,
                "permissions",
                {"required": [], "optional": []},
            ),
            "rolloutStage": getattr(release, "rollout_stage", "stable"),
            "minimumHostVersion": getattr(
                release,
                "minimum_host_version",
                None,
            ),
            "platform": {
                "os": self.operating_system,
                "arch": self.architecture,
                "available": artifact is not None,
                "artifactId": (
                    getattr(artifact, "artifact_id", "legacy")
                    if artifact is not None
                    else None
                ),
            },
        }

    def public_catalog(self) -> dict[str, Any]:
        current_indexes = self._current_indexes()
        schema_v2 = any(
            index.schema_version.endswith("/2") for index in current_indexes.values()
        )
        cache_errors = self._current_cache_errors(current_indexes)
        plugins: dict[str, list[tuple[VerifiedMarketplaceIndex, ReleaseRecord]]] = {}
        for index in current_indexes.values():
            for release in index.releases:
                if self._release_visible(release):
                    plugins.setdefault(release.plugin_id, []).append((index, release))
        entries = []
        installed = load_activation_registry(self.installer.registry_path).by_id()
        unified_snapshot = (
            self.unified.store.snapshot() if self.unified is not None else {}
        )
        unified = unified_snapshot.get("plugins", {})
        migrations = unified_snapshot.get("marketplaceMigrations", {})
        for plugin_id in sorted(plugins):
            releases = sorted(
                plugins[plugin_id],
                key=lambda item: _version_key(item[1].version),
                reverse=True,
            )
            installable_release = next(
                (
                    (index, release)
                    for index, release in releases
                    if not index.is_revoked(release, now=self._now())
                    and self._release_available_on_host(release)
                    and (
                        (self.unified is None and self.allow_legacy_execution)
                        or self._is_unified(self._artifact_for_host(release))
                    )
                ),
                None,
            )
            latest_index, latest = installable_release or releases[0]
            publisher = latest_index.publisher_by_id()[latest.publisher_id]
            assurances = self._catalog_assurances(latest, publisher)
            try:
                host_artifact = self._artifact_for_host(latest)
            except MarketplaceError:
                host_artifact = None
            unified_artifact = self._is_unified(host_artifact)
            unified_installable = False
            if (
                installable_release is not None
                and unified_artifact
                and self.unified is not None
                and (
                    not isinstance(latest, MultiRuntimeReleaseRecord)
                    or assurances["sandbox"]["available"]
                )
            ):
                try:
                    self._assert_migration_owner(
                        migrations.get(plugin_id), latest_index, publisher
                    )
                    if plugin_id in installed and plugin_id not in migrations:
                        self._assert_legacy_successor(
                            installed[plugin_id], latest, latest_index, publisher
                        )
                    self._assert_unified_upgrade(
                        unified.get(plugin_id), latest, latest_index, publisher
                    )
                except MarketplaceError:
                    pass
                else:
                    unified_installable = True
            publisher_wire = publisher.to_public_wire()
            if not isinstance(latest, MultiRuntimeReleaseRecord):
                publisher_wire.pop("verificationTier", None)
            entry = {
                "pluginId": plugin_id,
                "publisher": publisher_wire,
                "latest": latest.to_public_wire(
                    revoked=latest_index.is_revoked(latest, now=self._now())
                ),
                "releaseCount": len(releases),
                "installedVersion": (
                    unified[plugin_id]["version"]
                    if plugin_id in unified
                    else installed[plugin_id].version
                    if plugin_id in installed
                    else None
                ),
                "installable": (
                    installable_release is not None
                    and host_artifact is not None
                    and host_artifact.size <= MAX_REMOTE_ARTIFACT_BYTES
                    and self._release_available_on_host(latest)
                    and (
                        unified_installable
                        if unified_artifact
                        else (
                            plugin_id not in unified
                            and plugin_id not in migrations
                            and assurances["sandbox"]["available"]
                            and (
                                plugin_id not in installed
                                or self._release_for_digest(
                                    installed[plugin_id].bundle_sha256,
                                    include_expired=True,
                                )
                                is not None
                            )
                        )
                    )
                ),
            }
            if plugin_id in migrations and plugin_id in installed:
                entry["legacyRollback"] = {
                    "version": installed[plugin_id].version,
                    "migrationGeneration": migrations[plugin_id]["generation"],
                    "registryRevision": unified_snapshot["revision"],
                }
            if isinstance(latest, MultiRuntimeReleaseRecord):
                entry["assurances"] = assurances
            entries.append(entry)
        result = {
            "schemaVersion": (
                CATALOG_SCHEMA_VERSION_V2 if schema_v2 else CATALOG_SCHEMA_VERSION
            ),
            "enabled": self.enabled,
            "marketplaces": [
                {
                    **root.to_public_wire(),
                    "cache": (
                        {
                            "status": "valid",
                            "sequence": current_indexes[root.marketplace_id].sequence,
                            "expiresAt": current_indexes[
                                root.marketplace_id
                            ].expires_at,
                        }
                        if root.marketplace_id in current_indexes
                        else {
                            "status": "invalid-or-empty",
                            "reason": cache_errors.get(root.marketplace_id),
                        }
                    ),
                }
                for root in sorted(
                    self.roots.values(), key=lambda item: item.marketplace_id
                )
            ],
            "plugins": entries,
        }
        if schema_v2:
            result["rollout"] = {
                "channel": self.rollout_stage,
                "stages": list(ROLLOUT_STAGES),
            }
        return result

    def status(self) -> dict[str, Any]:
        state = self._state()
        registry = load_activation_registry(self.installer.registry_path)
        current_indexes = self._current_indexes()
        cache_errors = self._current_cache_errors(current_indexes)
        schema_v2 = any(
            index.schema_version.endswith("/2") for index in current_indexes.values()
        )
        unified_snapshot = (
            self.unified.store.snapshot() if self.unified is not None else None
        )
        result = {
            "schemaVersion": (
                STATUS_SCHEMA_VERSION_V2 if schema_v2 else STATUS_SCHEMA_VERSION
            ),
            "enabled": self.enabled,
            "automaticUpdates": False,
            "rootCount": len(self.roots),
            "validCacheCount": len(current_indexes),
            "cacheErrors": dict(sorted(cache_errors.items())),
            "candidates": [
                self._candidate_status(candidate, unified_snapshot)
                for candidate in state["candidates"]
            ],
            "updates": [
                {
                    "pluginId": record.plugin_id,
                    **self._update_for_record(record),
                }
                for record in registry.plugins
            ],
        }
        if schema_v2:
            result.update(
                {
                    "rollout": {
                        "channel": self.rollout_stage,
                        "stages": list(ROLLOUT_STAGES),
                    },
                    "telemetry": self.telemetry.public_status(),
                    "quarantine": self._quarantine_receipts(),
                }
            )
        return result
