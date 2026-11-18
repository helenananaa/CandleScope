"""Strict, immutable metadata shared by all unified plugin execution realms."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..platform_v2.json_codec import JsonLimits, loads_strict

MANIFEST_SCHEMA = "candlescope.unified-plugin/1"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ENTRIES = 32
MAX_DEPENDENCIES = 32
MAX_PERMISSIONS = 64
MAX_API_VERSION = 1

ID_PATTERN = r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?"
# Exact SemVer pins only. Ranges and dependency fetching belong to a future,
# separately specified resolver; install must never guess a compatible version.
VERSION_PATTERN = (
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
PATH_PATTERN = r"[A-Za-z0-9_./-]{1,180}"
KINDS = frozenset({"frontend", "backend", "desktop", "sandbox-view", "sidecar", "data"})
RUNTIMES = frozenset(
    {
        "python-module",
        "native-executable",
        "java-jar",
        "node-module",
        "wasm-component",
    }
)
_HOST_KINDS = frozenset({"frontend", "backend", "desktop"})
STARTUP_TARGETS = {
    "backend": frozenset({"data-engine", "replay", "alert-delivery", "indicator-range", "market-storage", "local-data"}),
    "frontend": frozenset({"shell"}),
}
_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", re.IGNORECASE)


class ManifestError(ValueError):
    """Metadata is unsupported; no import, migration or execution is permitted."""


def _object(value: Any, required: set[str], optional: set[str], label: str) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ManifestError(f"{label} must be an object with string keys")
    if set(value) - required - optional or required - set(value):
        raise ManifestError(f"{label} has missing or unsupported fields")
    return value


def _text(value: Any, label: str, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise ManifestError(f"{label} must be bounded text without control characters")
    return value


def identifier(value: Any, label: str) -> str:
    value = _text(value, label)
    if value == "candlescope.pyne":
        raise ManifestError("Pyne is retired and cannot be installed or activated")
    if re.fullmatch(ID_PATTERN, value) is None:
        raise ManifestError(f"{label} is not a plugin or entry identifier")
    return value


def version(value: Any, label: str) -> str:
    value = _text(value, label)
    if re.fullmatch(VERSION_PATTERN, value) is None:
        raise ManifestError(f"{label} must be an exact SemVer version")
    return value


def package_path(value: Any) -> str:
    value = _text(value, "entry.path", 180)
    if re.fullmatch(PATH_PATTERN, value) is None:
        raise ManifestError("entry.path must be a portable relative package path")
    for part in value.split("/"):
        if part in {"", ".", ".."} or part.endswith(".") or _DEVICE.fullmatch(part):
            raise ManifestError("entry.path contains an unsafe path component")
    return value


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    kind: str
    path: str
    runtime: str | None = None
    startup: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifier(self.id, "entry.id")
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise ManifestError("entry.kind is unsupported")
        package_path(self.path)
        allowed = STARTUP_TARGETS.get(self.kind, frozenset())
        if (
            not isinstance(self.startup, tuple)
            or any(not isinstance(target, str) or target not in allowed for target in self.startup)
            or len(set(self.startup)) != len(self.startup)
        ):
            raise ManifestError("unsupported or duplicate startup target")
        if self.path.casefold().endswith(".pyne"):
            raise ManifestError("Pyne is retired; legacy scripts cannot be plugin entrypoints")
        if self.kind == "sidecar":
            if isinstance(self.runtime, str) and self.runtime.casefold() in {
                "pyne",
                "candlescope.pyne",
            }:
                raise ManifestError("Pyne is retired; no runtime migration is supported")
            if not isinstance(self.runtime, str) or self.runtime not in RUNTIMES:
                raise ManifestError("sidecar requires an explicit supported runtime")
        elif self.runtime is not None:
            raise ManifestError("only sidecar entries declare a runtime")
        suffix = {
            "frontend": ".mjs",
            "desktop": ".mjs",
            "backend": ".py",
            "sandbox-view": ".html",
            "data": ".json",
        }.get(self.kind)
        if suffix and not self.path.endswith(suffix):
            raise ManifestError(f"{self.kind} entry requires a {suffix} path")

    @classmethod
    def from_wire(cls, raw: Any) -> Entry:
        data = _object(raw, {"id", "kind", "path"}, {"runtime", "startup"}, "entry")
        if "runtime" in data and data["runtime"] is None:
            raise ManifestError("entry.runtime cannot be null")
        startup = data.get("startup", [])
        if not isinstance(startup, list) or len(startup) > 6:
            raise ManifestError("entry.startup must be a bounded array of targets")
        return cls(data["id"], data["kind"], data["path"], data.get("runtime"), tuple(startup))

    def to_wire(self) -> dict[str, Any]:
        result = {"id": self.id, "kind": self.kind, "path": self.path}
        if self.runtime is not None:
            result["runtime"] = self.runtime
        if self.startup:
            result["startup"] = list(self.startup)
        return result


@dataclass(frozen=True, slots=True)
class Manifest:
    id: str
    name: str
    version: str
    trust: str
    entries: tuple[Entry, ...]
    dependencies: tuple[tuple[str, str], ...] = ()
    permissions: tuple[str, ...] = ()
    host_api_version: int = 1

    def __post_init__(self) -> None:
        identifier(self.id, "plugin.id")
        _text(self.name, "plugin.name", 200)
        version(self.version, "plugin.version")
        if not isinstance(self.trust, str) or self.trust not in {"restricted", "full-trust"}:
            raise ManifestError("trust must be restricted or full-trust")
        if type(self.host_api_version) is not int or self.host_api_version != MAX_API_VERSION:
            raise ManifestError("unsupported hostApiVersion")
        entries = tuple(self.entries)
        if not 1 <= len(entries) <= MAX_ENTRIES or any(not isinstance(e, Entry) for e in entries):
            raise ManifestError("entries must contain 1 to 32 validated entries")
        if len({e.id for e in entries}) != len(entries):
            raise ManifestError("duplicate entry id")
        if self.trust == "restricted" and any(e.kind in _HOST_KINDS for e in entries):
            raise ManifestError("in-process host entries require full-trust")
        dependencies = tuple(tuple(pair) for pair in self.dependencies)
        if len(dependencies) > MAX_DEPENDENCIES or any(len(pair) != 2 for pair in dependencies):
            raise ManifestError("dependencies must contain at most 32 exact pins")
        for dep_id, dep_version in dependencies:
            identifier(dep_id, "dependency.id")
            version(dep_version, "dependency.version")
            if dep_id == self.id:
                raise ManifestError("a plugin cannot depend on itself")
        if len({dep_id for dep_id, _ in dependencies}) != len(dependencies):
            raise ManifestError("duplicate dependency id")
        permissions = tuple(self.permissions)
        if len(permissions) > MAX_PERMISSIONS:
            raise ManifestError("at most 64 permission declarations are allowed")
        for permission in permissions:
            _text(permission, "permission", 128)
            if re.fullmatch(r"[a-z][a-z0-9.-]*/[1-9][0-9]*", permission) is None:
                raise ManifestError("permissions require explicit versioned capability ids")
        if len(set(permissions)) != len(permissions):
            raise ManifestError("duplicate permission declaration")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "dependencies", tuple(sorted(dependencies)))
        object.__setattr__(self, "permissions", tuple(sorted(permissions)))

    @classmethod
    def from_wire(cls, raw: Any) -> Manifest:
        if isinstance(raw, dict):
            language = raw.get("language")
            plugin = raw.get("plugin")
            if (
                isinstance(language, str)
                and language.casefold() in {"pyne", "pyne_chart_v1", "pyne_order_dsl"}
            ) or (isinstance(plugin, dict) and plugin.get("id") == "candlescope.pyne"):
                raise ManifestError(
                    "Pyne is retired; preserve the original script without executing it"
                )
            if raw.get("schema") != MANIFEST_SCHEMA:
                raise ManifestError(
                    "unsupported plugin schema; update the plugin package explicitly"
                )
        data = _object(
            raw,
            {"schema", "id", "name", "version", "hostApiVersion", "trust", "entries"},
            {"dependencies", "permissions"},
            "manifest",
        )
        entries, dependencies, permissions = (
            data["entries"],
            data.get("dependencies", {}),
            data.get("permissions", []),
        )
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
            raise ManifestError("entries must be a bounded array")
        if not isinstance(dependencies, dict) or len(dependencies) > MAX_DEPENDENCIES:
            raise ManifestError("dependencies must be a bounded object")
        if not isinstance(permissions, list) or len(permissions) > MAX_PERMISSIONS:
            raise ManifestError("permissions must be a bounded array")
        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            trust=data["trust"],
            entries=tuple(Entry.from_wire(entry) for entry in entries),
            dependencies=tuple(dependencies.items()),
            permissions=tuple(permissions),
            host_api_version=data["hostApiVersion"],
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> Manifest:
        return cls.from_wire(
            loads_strict(
                payload,
                limits=JsonLimits(
                    max_message_bytes=MAX_MANIFEST_BYTES,
                    max_depth=12,
                    max_container_items=1024,
                    max_string_bytes=4096,
                ),
            )
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "hostApiVersion": self.host_api_version,
            "trust": self.trust,
            "entries": [entry.to_wire() for entry in self.entries],
            "dependencies": dict(self.dependencies),
            "permissions": list(self.permissions),
        }
