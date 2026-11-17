"""Single candidate owner of immutable packages and recoverable desired activation.

All code is inert metadata/storage until executors attach in the next delivery.
There is no fallback to any existing runtime registry or installer.
"""

from __future__ import annotations

import copy
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from candlescope_plugin_sdk.platform_v2 import JsonLimits, canonical_dumps, loads_strict
from candlescope_plugin_sdk.unified import ActivationIdentity, activation_order
from candlescope_plugin_sdk.unified.manifest import identifier, version

from app.plugin_security_v2.storage import (
    _fsync_directory,
    atomic_write_json,
    security_lock,
)

from .bundle import CHUNK, MAX_PACKAGE_BYTES, VerifiedPackage, verify_package

REGISTRY_SCHEMA = "candlescope.unified-registry/1"
TRANSACTION_SCHEMA = "candlescope.unified-transaction/1"
MAX_STATE_BYTES = 1024 * 1024
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_RETAINED_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
MAX_RETAINED_PACKAGES = 1024
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


class LifecycleError(ValueError):
    """Desired activation cannot be changed or safely recovered."""


class RevisionConflict(LifecycleError):
    """The review's registry revision is no longer current."""


def _empty() -> dict:
    return {"schema": REGISTRY_SCHEMA, "revision": 0, "generation": 0, "plugins": {}}


def _safe_integer(value, *, minimum=0) -> bool:
    return type(value) is int and minimum <= value <= MAX_SAFE_INTEGER


def _sha256(value) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


class PackageStore:
    """Explicit-root, serialized storage for the eventual unified lifecycle owner.

    Callers must authenticate management actions before invoking mutations. The
    acknowledgement binds reviewed bytes/trust; it is not an authentication token.
    No default path, environment toggle, production API or executable is installed.
    """

    def __init__(self, root: Path | str):
        configured = Path(root).absolute()
        self.root = configured.parent.resolve() / configured.name
        self.packages = self.root / "packages"
        self.registry = self.root / "registry.json"
        self.journal = self.root / "transaction.json"
        self.lock = self.root / "owner.lock"

    def _check_path(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise LifecycleError("store path escapes configured root") from exc
        current = self.root
        for part in (None, *relative.parts):
            if part is not None:
                current = current / part
            if current.is_symlink():
                raise LifecycleError("store paths must not contain symlinks")
            if current != path and current.exists() and not current.is_dir():
                raise LifecycleError("store path parent is not a directory")

    @contextmanager
    def _locked(self):
        for path in (self.packages, self.registry, self.journal, self.lock):
            self._check_path(path)
        self.root.mkdir(parents=True, exist_ok=True)
        with security_lock(self.lock):
            for path in (self.packages, self.registry, self.journal):
                self._check_path(path)
            self._recover()
            yield self._state()

    def _read(self, path: Path) -> dict:
        self._check_path(path)
        with path.open("rb") as stream:
            data = stream.read(MAX_STATE_BYTES + 1)
        value = loads_strict(
            data,
            limits=JsonLimits(
                max_message_bytes=MAX_STATE_BYTES,
                max_depth=12,
                max_container_items=4096,
                max_string_bytes=4096,
            ),
        )
        if not isinstance(value, dict):
            raise LifecycleError("store state must be an object")
        return value

    def _validate(self, state: dict) -> dict:
        if (
            not isinstance(state, dict)
            or set(state) != {"schema", "revision", "generation", "plugins"}
            or state["schema"] != REGISTRY_SCHEMA
            or not _safe_integer(state["revision"])
            or not _safe_integer(state["generation"])
            or not isinstance(state["plugins"], dict)
            or len(state["plugins"]) > 256
        ):
            raise LifecycleError("invalid unified registry")
        generations = set()
        for plugin_id, record in state["plugins"].items():
            identifier(plugin_id, "registry.pluginId")
            if (
                not isinstance(record, dict)
                or set(record)
                != {
                    "packageSha256",
                    "version",
                    "trust",
                    "enabled",
                    "generation",
                    "history",
                }
                or not _sha256(record["packageSha256"])
                or type(record["enabled"]) is not bool
                or record["trust"] not in ("restricted", "full-trust")
                or not _safe_integer(record["generation"], minimum=1)
                or record["generation"] > state["generation"]
                or not isinstance(record["history"], list)
                or len(record["history"]) > 8
                or any(not _sha256(digest) for digest in record["history"])
            ):
                raise LifecycleError("invalid unified activation record")
            version(record["version"], "registry.version")
            if (
                record["generation"] in generations
                or len(set(record["history"])) != len(record["history"])
                or record["packageSha256"] in record["history"]
            ):
                raise LifecycleError("reused generation or ambiguous package history")
            generations.add(record["generation"])
        if state["revision"] != state["generation"]:
            raise LifecycleError("registry revision and generation allocator diverged")
        return state

    def _state(self) -> dict:
        return (
            self._validate(self._read(self.registry))
            if self.registry.exists()
            else _empty()
        )

    def _archive(self, digest: str) -> Path:
        if not _sha256(digest):
            raise LifecycleError("invalid package sha256")
        path = self.packages / (digest.removeprefix("sha256:") + ".cspkg")
        self._check_path(path)
        return path

    def _package(self, digest: str) -> VerifiedPackage:
        package = verify_package(self._archive(digest))
        if package.sha256 != digest:
            raise LifecycleError(
                "immutable package bytes no longer match their approved digest"
            )
        return package

    def _preflight(self, state: dict) -> None:
        manifests = []
        for plugin_id, record in state["plugins"].items():
            if not record["enabled"]:
                continue
            manifest = self._package(record["packageSha256"]).manifest
            if (
                manifest.id != plugin_id
                or manifest.version != record["version"]
                or manifest.trust != record["trust"]
            ):
                raise LifecycleError(
                    "activation record does not match approved package metadata"
                )
            manifests.append(manifest)
        activation_order(manifests)

    def _recover(self) -> None:
        if not self.journal.exists():
            return
        intent = self._read(self.journal)
        if (
            not isinstance(intent, dict)
            or set(intent) != {"schema", "before", "after"}
            or intent["schema"] != TRANSACTION_SCHEMA
        ):
            raise LifecycleError(
                "invalid lifecycle recovery journal; preserve it for recovery"
            )
        before, after = (
            self._validate(intent["before"]),
            self._validate(intent["after"]),
        )
        if after["revision"] != before["revision"] + 1:
            raise LifecycleError("invalid lifecycle transaction revision")
        current = self._state()
        if current == after:
            self._preflight(after)
        elif current != before:
            raise LifecycleError(
                "recovery journal does not match current registry; manual recovery required"
            )
        # Atomic registry replacement is the commit point. Before it, abort;
        # after it, preserve the committed desired state. Never replay imports.
        self.journal.unlink()
        _fsync_directory(self.root)

    def _commit(self, before: dict, after: dict) -> None:
        self._validate(after)
        self._preflight(after)
        if (
            len(canonical_dumps({"before": before, "after": after}).encode())
            > MAX_STATE_BYTES - 1024
        ):
            raise LifecycleError("lifecycle transaction exceeds its byte budget")
        atomic_write_json(
            self.journal,
            {"schema": TRANSACTION_SCHEMA, "before": before, "after": after},
        )
        atomic_write_json(self.registry, after)
        self.journal.unlink()
        _fsync_directory(self.root)

    @staticmethod
    def _next(state: dict, expected_revision: int) -> dict:
        if (
            not _safe_integer(expected_revision)
            or expected_revision != state["revision"]
        ):
            raise RevisionConflict(
                "registry changed since review; refresh before retrying"
            )
        if state["generation"] == MAX_SAFE_INTEGER:
            raise LifecycleError("activation generation budget exhausted")
        result = copy.deepcopy(state)
        result["revision"] += 1
        result["generation"] += 1
        return result

    def stage(self, source: Path | str) -> VerifiedPackage:
        verified = verify_package(source)
        with self._locked():
            self.packages.mkdir(exist_ok=True)
            destination = self._archive(verified.sha256)
            if destination.exists():
                return self._package(verified.sha256)
            retained_bytes = 0
            for retained_count, existing in enumerate(self.packages.iterdir(), 1):
                self._check_path(existing)
                if not existing.is_file():
                    raise LifecycleError("package store contains a non-file artifact")
                retained_bytes += existing.stat().st_size
                if (
                    retained_count >= MAX_RETAINED_PACKAGES
                    or retained_bytes + verified.size > MAX_RETAINED_PACKAGE_BYTES
                ):
                    raise LifecycleError(
                        "retained package budget exhausted; no archives were removed"
                    )
            if verified.size > MAX_RETAINED_PACKAGE_BYTES:
                raise LifecycleError("package exceeds the retained byte budget")
            descriptor, temporary = tempfile.mkstemp(
                prefix=".stage-", suffix=".cspkg", dir=self.packages
            )
            temporary = Path(temporary)
            try:
                with (
                    os.fdopen(descriptor, "wb") as output,
                    Path(source).open("rb") as incoming,
                ):
                    size = 0
                    while block := incoming.read(CHUNK):
                        size += len(block)
                        if size > MAX_PACKAGE_BYTES:
                            raise LifecycleError(
                                "staged input grew beyond its byte budget"
                            )
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
                # Source replacement/modification between inspect and copy cannot
                # change the bytes recorded under the reviewed digest.
                staged = verify_package(temporary)
                if staged.sha256 != verified.sha256:
                    raise LifecycleError(
                        "package changed while staging; inspect it again"
                    )
                os.replace(temporary, destination)
                _fsync_directory(self.packages)
            finally:
                temporary.unlink(missing_ok=True)
            return staged

    def review(self, digest: str) -> dict:
        with self._locked() as state:
            return {
                **self._package(digest).review(),
                "registryRevision": state["revision"],
            }

    def snapshot(self) -> dict:
        with self._locked() as state:
            return {**copy.deepcopy(state), "executorsAttached": False}

    def activate(
        self, digest: str, *, expected_revision: int, acknowledgement: str
    ) -> dict:
        with self._locked() as before:
            after = self._next(before, expected_revision)
            manifest = self._package(digest).manifest
            if acknowledgement != f"{manifest.trust}:{digest}":
                raise LifecycleError(
                    "explicit approval must match reviewed package bytes and trust"
                )
            previous = after["plugins"].get(manifest.id)
            history = (
                []
                if previous is None
                else list(
                    dict.fromkeys([previous["packageSha256"], *previous["history"]])
                )
            )
            after["plugins"][manifest.id] = {
                "packageSha256": digest,
                "version": manifest.version,
                "trust": manifest.trust,
                "enabled": True,
                "generation": after["generation"],
                "history": [item for item in history if item != digest][:8],
            }
            self._commit(before, after)
            return copy.deepcopy(after)

    def disable(self, plugin_id: str, *, expected_revision: int) -> dict:
        return self._remove(plugin_id, expected_revision, uninstall=False)

    def uninstall(self, plugin_id: str, *, expected_revision: int) -> dict:
        return self._remove(plugin_id, expected_revision, uninstall=True)

    def _remove(
        self, plugin_id: str, expected_revision: int, *, uninstall: bool
    ) -> dict:
        identifier(plugin_id, "pluginId")
        with self._locked() as before:
            after = self._next(before, expected_revision)
            if plugin_id not in after["plugins"]:
                raise LifecycleError("plugin is not installed")
            if uninstall:
                del after["plugins"][plugin_id]
            else:
                after["plugins"][plugin_id]["enabled"] = False
                after["plugins"][plugin_id]["generation"] = after["generation"]
            self._commit(before, after)
            return copy.deepcopy(after)

    def identity(self, plugin_id: str) -> ActivationIdentity | None:
        with self._locked() as state:
            self._preflight(state)
            record = state["plugins"].get(plugin_id)
            if record is None or not record["enabled"]:
                return None
            return ActivationIdentity(
                plugin_id,
                record["version"],
                record["packageSha256"],
                record["generation"],
            )
