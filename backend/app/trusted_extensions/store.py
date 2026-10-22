"""Content-addressed extension packages and explicit, digest-bound activation."""
from __future__ import annotations

import hashlib
import io
import os
import re
import secrets
import stat
import zipfile
from pathlib import Path
from typing import Any

from candlescope_plugin_sdk.platform_v2 import loads_strict
from app.plugin_security_v2.storage import atomic_write_json, read_json, security_lock

MAX_PACKAGE = 16 * 1024 * 1024
API_VERSION = 1
_ID = re.compile(r"[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
PAGE_SLOTS = {"topBar", "intervalSelector", "workspace", "featureSurfaces", "statusBar"}
WORKSPACE_SLOTS = {"toolbar", "chart", "bottomPanel", "rightRail", "exportOverlay"}
COLORS = {"bg-primary", "bg-secondary", "bg-tertiary", "bg-hover", "border-color",
          "text-primary", "text-secondary", "text-muted", "accent-blue", "accent-purple",
          "accent-cyan", "candle-up", "candle-down"}


def safe_path(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.\-/]{1,180}", value):
        raise ValueError("Invalid package path")
    for part in value.split("/"):
        if (part in {"", ".", ".."} or part.endswith(".")
                or re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", part)):
            raise ValueError("Unsafe package path")
    return value


def validate_manifest(raw: Any, files: dict[str, bytes]) -> dict[str, Any]:
    required = {"schema", "id", "name", "version", "apiVersion", "trust"}
    optional = {"description", "entries", "dependencies", "theme", "layout", "internalApiVersion"}
    if not isinstance(raw, dict) or not required <= raw.keys() or raw.keys() - required - optional:
        raise ValueError("Invalid extension manifest fields")
    if raw["schema"] != "candlescope.extension/1" or type(raw["apiVersion"]) is not int or raw["apiVersion"] != API_VERSION:
        raise ValueError("Unsupported extension API")
    if not isinstance(raw["id"], str) or not _ID.fullmatch(raw["id"]):
        raise ValueError("Invalid extension id")
    for key in ("name", "version", "description"):
        if key in raw and (not isinstance(raw[key], str) or not 1 <= len(raw[key]) <= 500):
            raise ValueError(f"Invalid {key}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", raw["version"]):
        raise ValueError("Version must have three numeric components")
    if raw["trust"] not in {"theme", "full-trust"}:
        raise ValueError("Explicit theme or full-trust declaration required")
    entries = raw.get("entries", {})
    if not isinstance(entries, dict) or entries.keys() - {"frontend", "backend", "desktop"}:
        raise ValueError("Unknown execution realm")
    if entries and raw["trust"] != "full-trust":
        raise ValueError("Executable entries require full-trust")
    for realm, entry in entries.items():
        safe_path(entry)
        if entry not in files or not entry.endswith(".py" if realm == "backend" else ".mjs"):
            raise ValueError(f"Missing or invalid {realm} entry")
    if "internalApiVersion" in raw and (type(raw["internalApiVersion"]) is not int or raw["internalApiVersion"] != 1 or raw["trust"] != "full-trust"):
        raise ValueError("Unsupported internal API")
    dependencies = raw.get("dependencies", {})
    if not isinstance(dependencies, dict) or len(dependencies) > 32:
        raise ValueError("Invalid dependencies")
    for key, version in dependencies.items():
        if not _ID.fullmatch(key) or key == raw["id"] or not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Dependencies require another extension's exact version")
    theme = raw.get("theme")
    if theme is not None:
        if not isinstance(theme, dict) or set(theme) != {"base", "tokens"} or theme["base"] not in {"dark", "light"}:
            raise ValueError("Invalid theme")
        tokens = theme["tokens"]
        if not isinstance(tokens, dict) or not tokens or tokens.keys() - COLORS - {"radius-sm", "radius-md", "font-sans", "font-mono", "control-height", "panel-gap", "panel-shadow"}:
            raise ValueError("Unknown theme token")
        for key, value in tokens.items():
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError("Invalid theme token")
            if key in COLORS and not re.fullmatch(r"#[a-fA-F0-9]{6}", value):
                raise ValueError("Theme colors must be six-digit hex values")
            if key in {"radius-sm", "radius-md", "control-height", "panel-gap"} and not re.fullmatch(r"(?:[0-9]|[1-6][0-9])px", value):
                raise ValueError("Invalid theme dimension")
            if key.startswith("font-") and not re.fullmatch(r"[A-Za-z0-9 ,'-]+", value):
                raise ValueError("Invalid theme font")
            if key == "panel-shadow" and not re.fullmatch(r"(?:none|[0-9px .-]+ #[a-fA-F0-9]{6})", value):
                raise ValueError("Invalid theme shadow")
    layout = raw.get("layout")
    if layout is not None:
        if raw["trust"] != "full-trust" or not isinstance(layout, dict) or set(layout) != {"page", "workspace"}:
            raise ValueError("Layout requires full-trust and both slot orders")
        for key, slots in (("page", PAGE_SLOTS), ("workspace", WORKSPACE_SLOTS)):
            order = layout[key]
            if not isinstance(order, list) or not all(isinstance(item, str) for item in order) or len(order) != len(slots) or set(order) != slots:
                raise ValueError("Layout must preserve each host slot exactly once")
    if not entries and theme is None and layout is None:
        raise ValueError("Empty extension")
    return raw


def unpack(data: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not 0 < len(data) <= MAX_PACKAGE:
        raise ValueError("Extension package exceeds 16 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            records = archive.infolist()
            if not 1 <= len(records) <= 256 or sum(item.file_size for item in records) > MAX_PACKAGE:
                raise ValueError("Too many files or expanded package too large")
            files: dict[str, bytes] = {}
            names: set[str] = set()
            for item in records:
                name = safe_path(item.orig_filename)
                if name != item.filename:
                    raise ValueError("Archive path was normalized by the ZIP reader")
                if name.casefold() in names or item.is_dir() or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise ValueError("Duplicate, directory, encrypted or symlink entry")
                names.add(name.casefold())
                files[name] = archive.read(item)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("Invalid extension archive") from exc
    if "extension.json" not in files:
        raise ValueError("extension.json is required")
    manifest = validate_manifest(loads_strict(files["extension.json"]), files)
    return manifest, files


class ExtensionStore:
    def __init__(self, root: Path):
        self.root = root / "trusted-extensions-v1"
        self.state_path = self.root / "state.json"
        self.lock_path = self.root / "state.lock"
        self.tickets: dict[str, tuple[str, str, int]] = {}

    @property
    def safe_mode(self) -> bool:
        return os.environ.get("CANDLESCOPE_EXTENSIONS_SAFE_MODE") == "1"

    def _state(self) -> dict:
        return read_json(self.state_path, "extension registry") if self.state_path.exists() else {
            "revision": 0, "plugins": {}, "theme": None, "layout": None}

    def _save(self, state: dict) -> None:
        state["revision"] += 1
        atomic_write_json(self.state_path, state)
        self.tickets = {ticket: identity for ticket, identity in self.tickets.items()
                        if state["plugins"].get(identity[0], {}).get("enabled")
                        and state["plugins"][identity[0]].get("digest") == identity[1]
                        and state["plugins"][identity[0]].get("generation") == identity[2]}

    def revision(self) -> int:
        with security_lock(self.lock_path):
            return self._state()["revision"]

    def _archive(self, digest: str) -> Path:
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError("Invalid package digest")
        return self.root / "packages" / f"{digest}.csext"

    def package(self, digest: str) -> tuple[dict, dict[str, bytes]]:
        path = self._archive(digest)
        self._check_links(path)
        if not path.is_file():
            raise ValueError("Extension package is unavailable")
        if path.stat().st_size > MAX_PACKAGE:
            raise ValueError("Extension package exceeds size limit")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Extension package integrity check failed")
        return unpack(data)

    def _check_links(self, path: Path) -> None:
        for parent in (path, *path.parents):
            if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                raise ValueError("Extension package path contains a link")
            if parent == self.root:
                break

    def stage(self, data: bytes) -> dict:
        manifest, _ = unpack(data)
        digest = hashlib.sha256(data).hexdigest()
        with security_lock(self.lock_path):
            path = self._archive(digest)
            self._check_links(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(data)
            self.package(digest)
        return {"digest": digest, "manifest": manifest, "signed": False}

    def change(self, action: str, extension_id: str, digest: str | None = None,
               acknowledgement: str | None = None) -> dict:
        with security_lock(self.lock_path):
            state = self._state()
            plugins = state["plugins"]
            if action == "activate":
                manifest, _ = self.package(digest)
                if manifest["id"] != extension_id or acknowledgement != f"{manifest['trust']}:{digest}":
                    raise ValueError("Approval must match the exact package and trust level")
                for dependency, version in manifest.get("dependencies", {}).items():
                    dependency_record = plugins.get(dependency)
                    if not dependency_record or not dependency_record["enabled"] or self.package(dependency_record["digest"])[0]["version"] != version:
                        raise ValueError(f"Enable dependency {dependency} {version} first")
                for other_id, other in plugins.items():
                    if other_id != extension_id and other["enabled"]:
                        required = self.package(other["digest"])[0].get("dependencies", {}).get(extension_id)
                        if required is not None and required != manifest["version"]:
                            raise ValueError(f"Disable dependent extension {other_id} before changing version")
                old = plugins.get(extension_id, {})
                history = list(dict.fromkeys([*old.get("history", []), *([old["digest"]] if old.get("digest") else [])]))
                plugins[extension_id] = {"digest": digest, "enabled": True, "history": history[-10:], "generation": state["revision"] + 1}
                visiting, visited = set(), set()

                def visit(key):
                    if key in visiting:
                        raise ValueError("Cyclic extension dependency")
                    if key in visited:
                        return
                    visiting.add(key)
                    candidate, _ = self.package(plugins[key]["digest"])
                    for dependency in candidate.get("dependencies", {}):
                        visit(dependency)
                    visiting.remove(key)
                    visited.add(key)
                visit(extension_id)
                for kind in ("theme", "layout"):
                    if state[kind] == extension_id and kind not in manifest:
                        state[kind] = None
            elif action in {"disable", "uninstall"}:
                for other_id, other in plugins.items():
                    if other["enabled"] and extension_id in self.package(other["digest"])[0].get("dependencies", {}):
                        raise ValueError(f"Disable dependent extension {other_id} first")
                if extension_id not in plugins:
                    raise ValueError("Extension not installed")
                if action == "uninstall":
                    del plugins[extension_id]
                else:
                    plugins[extension_id]["enabled"] = False
                for kind in ("theme", "layout"):
                    if state[kind] == extension_id:
                        state[kind] = None
            elif action in {"theme", "layout"}:
                if extension_id:
                    record = plugins.get(extension_id)
                    if not record or not record["enabled"] or action not in self.package(record["digest"])[0]:
                        raise ValueError("Selected contribution is unavailable")
                state[action] = extension_id or None
            elif action == "disable-all":
                for record in plugins.values():
                    record["enabled"] = False
                state["theme"] = state["layout"] = None
            else:
                raise ValueError("Unsupported extension operation")
            self._save(state)
        return self.catalog()

    def catalog(self) -> dict:
        with security_lock(self.lock_path):
            state = self._state()
            result = []
            for extension_id, record in sorted(state["plugins"].items()):
                try:
                    manifest, _ = self.package(record["digest"])
                    if manifest["id"] != extension_id:
                        raise ValueError("Registry identity mismatch")
                    result.append({**record, "manifest": manifest, "error": None})
                except Exception as exc:
                    result.append({**record, "manifest": {"id": extension_id, "name": extension_id}, "error": str(exc)})
            return {"revision": state["revision"], "plugins": result, "theme": state["theme"],
                    "layout": state["layout"], "safeMode": self.safe_mode}

    def plan(self) -> dict:
        catalog = self.catalog()
        active = {p["manifest"]["id"]: p for p in catalog["plugins"] if p["enabled"] and not p["error"]}
        ordered: list[dict] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        failed: set[str] = set()

        def visit(key: str) -> None:
            if key in failed:
                raise ValueError(f"Failed extension dependency: {key}")
            if key in visiting:
                raise ValueError("Cyclic extension dependency")
            if key in visited:
                return
            visiting.add(key)
            item = active[key]
            for dependency, version in item["manifest"].get("dependencies", {}).items():
                if dependency not in active or active[dependency]["manifest"]["version"] != version:
                    raise ValueError(f"Unavailable dependency: {dependency}")
                visit(dependency)
            visiting.remove(key)
            visited.add(key)
            ordered.append(item)

        if not catalog["safeMode"]:
            for key in active:
                try:
                    visit(key)
                except ValueError as exc:
                    failed.add(key)
                    visiting.clear()
                    active[key]["error"] = str(exc)
        for item in ordered:
            identity = (item["manifest"]["id"], item["digest"], item["generation"])
            ticket = next((key for key, value in self.tickets.items() if value == identity), None)
            if ticket is None:
                ticket = secrets.token_urlsafe(32)
                self.tickets[ticket] = identity
            item["assetBase"] = f"/api/v2/plugins/extension-assets/{ticket}/"
        return {**catalog, "active": ordered}

    def asset(self, ticket: str, path: str) -> bytes:
        identity = self.tickets.get(ticket)
        if identity is None or self.safe_mode:
            raise ValueError("Extension asset authorization expired")
        extension_id, digest, generation = identity
        state = self._state()
        record = state["plugins"].get(extension_id, {})
        if record.get("generation") != generation or not record.get("enabled") or record.get("digest") != digest:
            raise ValueError("Extension asset authorization expired")
        _, files = self.package(digest)
        path = safe_path(path)
        if path not in files:
            raise ValueError("Unknown extension asset")
        return files[path]

    def materialize(self, digest: str) -> Path:
        _, files = self.package(digest)
        root = self.root / "code" / digest
        self._check_links(root)
        root.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            target = root / name
            for parent in (target, *target.parents):
                if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                    raise ValueError("Extension code path contains a link")
                if parent == self.root:
                    break
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not target.is_file() or target.stat().st_size != len(data) or target.read_bytes() != data:
                    raise ValueError("Materialized extension integrity check failed")
            else:
                with target.open("xb") as stream:
                    stream.write(data)
        return root.resolve()
