"""Storage owner for immutable packages and recoverable desired activation.

Validation and desired state updates never execute package code.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from candlescope_plugin_sdk.platform_v2 import JsonLimits, canonical_dumps, loads_strict
from candlescope_plugin_sdk.unified import (
    ActivationIdentity,
    Manifest,
    activation_order,
)
from candlescope_plugin_sdk.unified.manifest import identifier, version

from app.plugin_security_v2.storage import (
    _fsync_directory,
    atomic_write_json,
    security_lock,
)

from .appearance import APPEARANCE_KINDS, appearance_kind
from .bundle import CHUNK, MAX_PACKAGE_BYTES, VerifiedPackage, verify_package
from .paths import is_link

CHART_PERMISSION = "chart.compute/1"

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
    """Explicit-root, serialized storage for the unified lifecycle owner.

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
            if is_link(current):
                raise LifecycleError(
                    "store paths must not contain symlinks or reparse points"
                )
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
            or not {"schema", "revision", "generation", "plugins"} <= state.keys()
            or state.keys()
            - {
                "schema",
                "revision",
                "generation",
                "plugins",
                "appearance",
                "marketplaceTrial",
                "marketplacePackages",
            }
            or state["schema"] != REGISTRY_SCHEMA
            or not _safe_integer(state["revision"])
            or not _safe_integer(state["generation"])
            or not isinstance(state["plugins"], dict)
            or len(state["plugins"]) > 256
        ):
            raise LifecycleError("invalid unified registry")
        marketplace_packages = state.get("marketplacePackages", [])
        if (
            not isinstance(marketplace_packages, list)
            or len(marketplace_packages) > MAX_RETAINED_PACKAGES
            or any(not _sha256(digest) for digest in marketplace_packages)
            or marketplace_packages != sorted(set(marketplace_packages))
        ):
            raise LifecycleError("invalid marketplace package reservations")
        appearance = state.get("appearance", {})
        if (
            not isinstance(appearance, dict)
            or set(appearance) - set(APPEARANCE_KINDS)
            or any(
                value is not None
                and (not isinstance(value, str) or value not in state["plugins"])
                for value in appearance.values()
            )
        ):
            raise LifecycleError("invalid unified appearance selection")
        generations = set()
        for plugin_id, record in state["plugins"].items():
            identifier(plugin_id, "registry.pluginId")
            self._validate_record(record, state["generation"])
            if record["generation"] in generations:
                raise LifecycleError("reused activation generation")
            generations.add(record["generation"])
        trial = state.get("marketplaceTrial")
        if trial is not None:
            if not isinstance(trial, dict) or set(trial) != {"pluginId", "previous"}:
                raise LifecycleError("invalid marketplace observation record")
            plugin_id = identifier(trial["pluginId"], "marketplaceTrial.pluginId")
            record = state["plugins"].get(plugin_id, {})
            if not record.get("enabled") or "marketplace" not in record:
                raise LifecycleError("marketplace observation has no active target")
            if trial["previous"] is not None:
                self._validate_record(trial["previous"], record["generation"] - 1)
                if "marketplace" not in trial["previous"]:
                    raise LifecycleError("marketplace rollback has no approval")
        if state["revision"] != state["generation"]:
            raise LifecycleError("registry revision and generation allocator diverged")
        return state

    @staticmethod
    def _validate_record(record: dict, generation: int) -> None:
        fields = {
            "packageSha256",
            "version",
            "trust",
            "enabled",
            "generation",
            "history",
        }
        if (
            not isinstance(record, dict)
            or not fields <= record.keys()
            or record.keys() - fields - {"marketplace"}
            or not _sha256(record["packageSha256"])
            or type(record["enabled"]) is not bool
            or record["trust"] not in ("restricted", "full-trust")
            or not _safe_integer(record["generation"], minimum=1)
            or record["generation"] > generation
            or not isinstance(record["history"], list)
            or len(record["history"]) > 8
            or any(not _sha256(digest) for digest in record["history"])
            or len(set(record["history"])) != len(record["history"])
            or record["packageSha256"] in record["history"]
        ):
            raise LifecycleError("invalid unified activation record")
        version(record["version"], "registry.version")
        if "marketplace" in record:
            grant = record["marketplace"]
            if (
                record["trust"] != "restricted"
                or not isinstance(grant, dict)
                or set(grant)
                != {"marketplaceId", "publisherId", "publisherKeyId", "permissions"}
                or any(
                    not isinstance(grant[key], str) or not 0 < len(grant[key]) <= 128
                    for key in ("marketplaceId", "publisherId", "publisherKeyId")
                )
                or grant["permissions"] not in ([], [CHART_PERMISSION])
            ):
                raise LifecycleError("invalid marketplace approval")

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
        self._validate_plan(state)
        if state.get("marketplaceTrial") is not None:
            rollback = copy.deepcopy(state)
            self._restore_marketplace(rollback)
            self._validate_plan(rollback)

    def _validate_plan(self, state: dict) -> None:
        manifests = []
        for plugin_id, record in state["plugins"].items():
            if not record["enabled"]:
                continue
            manifest = self._package(record["packageSha256"]).manifest
            if (
                manifest.id != plugin_id
                or manifest.version != record["version"]
                or manifest.trust != record["trust"]
                or (
                    "marketplace" in record
                    and list(manifest.permissions)
                    != record["marketplace"]["permissions"]
                )
            ):
                raise LifecycleError(
                    "activation record does not match approved package metadata"
                )
            manifests.append(manifest)
        activation_order(manifests)
        enabled = {manifest.id: manifest for manifest in manifests}
        for kind, plugin_id in state.get("appearance", {}).items():
            if plugin_id is not None and (
                plugin_id not in enabled
                or not any(
                    appearance_kind(entry) == kind
                    for entry in enabled[plugin_id].entries
                )
            ):
                raise LifecycleError(
                    "appearance selection must reference an enabled contribution"
                )

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

    def stage(
        self, source: Path | str, *, marketplace_digest: str | None = None
    ) -> VerifiedPackage:
        verified = verify_package(source)
        if marketplace_digest is not None and marketplace_digest != verified.sha256:
            raise LifecycleError("archive does not match its signed marketplace digest")
        with self._locked() as before:
            self.packages.mkdir(exist_ok=True)
            destination = self._archive(verified.sha256)
            if destination.exists():
                staged = self._package(verified.sha256)
            else:
                staged = self._stage_archive(source, verified, destination)
            if marketplace_digest is not None and marketplace_digest not in before.get(
                "marketplacePackages", []
            ):
                after = self._next(before, before["revision"])
                reserved = after.setdefault("marketplacePackages", [])
                reserved.append(marketplace_digest)
                reserved.sort()
                self._commit(before, after)
            return staged

    def _stage_archive(self, source, verified, destination):
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
                        raise LifecycleError("staged input grew beyond its byte budget")
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            # Source replacement/modification between inspect and copy cannot
            # change the bytes recorded under the reviewed digest.
            staged = verify_package(temporary)
            if staged.sha256 != verified.sha256:
                raise LifecycleError("package changed while staging; inspect it again")
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

    def execution_plan(
        self,
    ) -> tuple[int, tuple[tuple[Manifest, ActivationIdentity], ...]]:
        """One verified snapshot for every executor, ordered by dependency."""
        with self._locked() as state:
            self._preflight(state)
            manifests = [
                self._package(record["packageSha256"]).manifest
                for record in state["plugins"].values()
                if record["enabled"]
            ]
            return state["revision"], tuple(
                (
                    manifest,
                    ActivationIdentity(
                        manifest.id,
                        manifest.version,
                        state["plugins"][manifest.id]["packageSha256"],
                        state["plugins"][manifest.id]["generation"],
                    ),
                )
                for manifest in activation_order(manifests)
            )

    def materialize(self, digest: str) -> tuple[Path, dict[str, str]]:
        """Create a private, complete execution tree from verified bytes, never extractall."""
        with self._locked():
            verified = self._package(digest)
            runs = self.root / "runs"
            self._check_path(runs)
            runs.mkdir(exist_ok=True)
            # Interrupted execution trees remain inert and count toward the budget.
            retained = 0
            for count, path in enumerate(runs.rglob("*"), 1):
                self._check_path(path)
                if count > 16384:
                    raise LifecycleError("execution tree path budget exhausted")
                if path.is_file():
                    retained += path.stat().st_size
            if retained + verified.size > MAX_RETAINED_PACKAGE_BYTES:
                raise LifecycleError("execution tree budget exhausted")
            root = runs / uuid.uuid4().hex
            root.mkdir()
            try:
                with zipfile.ZipFile(self._archive(digest)) as archive:
                    descriptor = loads_strict(archive.read("bundle.json"))
                    files = {}
                    for name, expected in descriptor["files"].items():
                        target = root / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        actual, size = hashlib.sha256(), 0
                        with archive.open(name) as source, target.open("xb") as output:
                            while block := source.read(CHUNK):
                                size += len(block)
                                if size > expected["size"]:
                                    raise LifecycleError(
                                        "execution asset grew while materializing"
                                    )
                                actual.update(block)
                                output.write(block)
                        if (
                            size != expected["size"]
                            or "sha256:" + actual.hexdigest() != expected["sha256"]
                        ):
                            raise LifecycleError("execution asset digest mismatch")
                        files[name] = actual.hexdigest()
                return root, files
            except BaseException:
                shutil.rmtree(root)
                raise

    def private_directory(self, plugin_id: str) -> Path:
        identifier(plugin_id, "pluginId")
        path = self.root / "private" / plugin_id
        self._check_path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def release_materialization(self, root: Path, files: dict[str, str]) -> None:
        """Remove unchanged pinned code, preserving user-created or modified files."""
        if root.parent != self.root / "runs" or is_link(root):
            raise LifecycleError("not an owned execution tree")
        for name, expected in files.items():
            target = root / name
            self._check_path(target)
            if not target.is_file():
                continue
            digest = hashlib.sha256()
            with target.open("rb") as content:
                while block := content.read(CHUNK):
                    digest.update(block)
            if digest.hexdigest() == expected:
                target.unlink()
        for path in sorted(
            {(root / name).parent for name in files},
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            while path.is_relative_to(root):
                try:
                    path.rmdir()
                except OSError:
                    break
                path = path.parent

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
            if digest in before.get(
                "marketplacePackages", []
            ) or "marketplace" in before["plugins"].get(manifest.id, {}):
                raise LifecycleError(
                    "marketplace-owned plugins require marketplace approval"
                )
            self._set_active(after, manifest, digest)
            self._commit(before, after)
            return copy.deepcopy(after)

    @staticmethod
    def _set_active(
        after: dict, manifest: Manifest, digest: str, *, marketplace=None
    ) -> None:
        previous = after["plugins"].get(manifest.id)
        history = (
            []
            if previous is None
            else list(dict.fromkeys([previous["packageSha256"], *previous["history"]]))
        )
        record = {
            "packageSha256": digest,
            "version": manifest.version,
            "trust": manifest.trust,
            "enabled": True,
            "generation": after["generation"],
            "history": [item for item in history if item != digest][:8],
        }
        if marketplace is not None:
            record["marketplace"] = copy.deepcopy(marketplace)
        after["plugins"][manifest.id] = record
        for kind, selected in after.get("appearance", {}).items():
            if selected == manifest.id and not any(
                appearance_kind(entry) == kind for entry in manifest.entries
            ):
                if marketplace is not None:
                    raise LifecycleError(
                        "marketplace trial must preserve selected appearance"
                    )
                after["appearance"][kind] = None

    def begin_marketplace(
        self, digest: str, grant: dict, *, previous_generation: int | None
    ) -> int:
        """Commit a reviewed release and its rollback target in the same transaction."""
        with self._locked() as before:
            if before.get("marketplaceTrial") is not None:
                raise RevisionConflict(
                    "a marketplace activation is already under observation"
                )
            if digest not in before.get("marketplacePackages", []):
                raise LifecycleError("marketplace package has not been staged")
            manifest = self._package(digest).manifest
            previous = before["plugins"].get(manifest.id)
            if previous_generation != (previous and previous["generation"]):
                raise RevisionConflict("marketplace activation changed since review")
            if previous is not None and any(
                previous.get("marketplace", {}).get(key) != grant[key]
                for key in ("marketplaceId", "publisherId", "publisherKeyId")
            ):
                raise LifecycleError(
                    "marketplace cannot take over a different activation owner"
                )
            after = self._next(before, before["revision"])
            self._set_active(after, manifest, digest, marketplace=grant)
            after["marketplaceTrial"] = {"pluginId": manifest.id, "previous": previous}
            self._commit(before, after)
            return after["generation"]

    @staticmethod
    def _restore_marketplace(state: dict) -> None:
        trial = state.pop("marketplaceTrial")
        plugin_id, previous = trial["pluginId"], trial["previous"]
        if previous is None:
            del state["plugins"][plugin_id]
        else:
            state["plugins"][plugin_id] = {
                **previous,
                "generation": state["generation"],
            }
        if previous is None or not previous["enabled"]:
            for kind, selected in state.get("appearance", {}).items():
                if selected == plugin_id:
                    state["appearance"][kind] = None

    def finish_marketplace(
        self, plugin_id: str, generation: int, *, healthy: bool
    ) -> bool:
        with self._locked() as before:
            if (before.get("marketplaceTrial") or {}).get(
                "pluginId"
            ) != plugin_id or before["plugins"][plugin_id]["generation"] != generation:
                return False
            after = self._next(before, before["revision"])
            if healthy:
                del after["marketplaceTrial"]
            else:
                self._restore_marketplace(after)
            self._commit(before, after)
            return True

    def recover_marketplace(self) -> None:
        state = self.snapshot()
        if trial := state.get("marketplaceTrial"):
            plugin_id = trial["pluginId"]
            self.finish_marketplace(
                plugin_id, state["plugins"][plugin_id]["generation"], healthy=False
            )

    def select_appearance(
        self, kind: str, plugin_id: str | None, *, expected_revision: int
    ) -> dict:
        if kind not in APPEARANCE_KINDS:
            raise LifecycleError("unsupported appearance kind")
        if plugin_id is not None:
            identifier(plugin_id, "pluginId")
        with self._locked() as before:
            after = self._next(before, expected_revision)
            if plugin_id is not None and not after["plugins"].get(plugin_id, {}).get(
                "enabled"
            ):
                raise LifecycleError("appearance provider must be enabled")
            trial = after.get("marketplaceTrial")
            if trial and plugin_id == trial["pluginId"]:
                raise LifecycleError(
                    "marketplace appearance must pass health observation first"
                )
            after.setdefault("appearance", {})[kind] = plugin_id
            self._commit(before, after)
            return copy.deepcopy(after)

    def disable(self, plugin_id: str, *, expected_revision: int) -> dict:
        return self._remove(plugin_id, expected_revision, uninstall=False)

    def recover_disable(self, plugin_id: str) -> tuple[str, ...]:
        """Disable an explicit recovery target and its enabled dependents atomically."""
        identifier(plugin_id, "pluginId")
        with self._locked() as before:
            record = before["plugins"].get(plugin_id)
            if record is None:
                raise LifecycleError("plugin is not installed")
            if not record["enabled"]:
                return ()
            dependencies = {
                key: self._package(record["packageSha256"]).manifest.dependencies
                for key, record in before["plugins"].items()
                if record["enabled"] and key != plugin_id
            }
            disabled = {plugin_id}
            while True:
                more = {
                    key
                    for key, deps in dependencies.items()
                    if key not in disabled and any(dep in disabled for dep, _ in deps)
                }
                if not more:
                    break
                disabled.update(more)
            after = self._next(before, before["revision"])
            if (after.get("marketplaceTrial") or {}).get("pluginId") in disabled:
                del after["marketplaceTrial"]
            for key in disabled:
                after["plugins"][key]["enabled"] = False
            # The disabled flag revokes every dependent. Each later activation
            # allocates a fresh generation through the normal approval flow.
            after["plugins"][plugin_id]["generation"] = after["generation"]
            for kind, selected in after.get("appearance", {}).items():
                if selected in disabled:
                    after["appearance"][kind] = None
            self._commit(before, after)
            return tuple(sorted(disabled))

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
            if (after.get("marketplaceTrial") or {}).get("pluginId") == plugin_id:
                del after["marketplaceTrial"]
            if uninstall:
                del after["plugins"][plugin_id]
            else:
                after["plugins"][plugin_id]["enabled"] = False
                after["plugins"][plugin_id]["generation"] = after["generation"]
            for kind, selected in after.get("appearance", {}).items():
                if selected == plugin_id:
                    after["appearance"][kind] = None
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
