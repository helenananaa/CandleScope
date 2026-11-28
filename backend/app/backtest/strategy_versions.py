"""Content-addressed strategy versions (ADR-BACKTEST-015 §3.1, step P3b).

A version is the exact code a run executed: language, source, libraries and the
identity of the compiler/runtime/adapter that interpreted it. Its hash is the
canonical hash of those, so the same code on the same runtime is the same version
whichever run family executed it (a builtin is its id on an engine version).
Parameters are not part of a version: a run is a version with parameters.

Users never manage versions. Every run is linked to its version when it is
created (or, for runs created before this existed and forward runs, the first
time the run facade reads it). Naming a version only gives its hash a name.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .errors import BacktestError
from .strategy.protocol import canonical_hash

SCHEMA = "candlescope.strategy-version/1"
DRAFT_SCHEMA = "candlescope.strategy-version-draft/1"
MAX_DRAFT_SOURCE_BYTES = 2 * 1024 * 1024
VERSION_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
# A name is a path segment: no slash, no surrounding space, 1 to 120 characters.
NAME = re.compile(r"^[^\s/](?:[^/\n]{0,118}[^\s/])?$")
FAMILIES = frozenset({"host", "native", "external", "continuous"})
# Host revision languages, as the editor languages they are written in.
HOST_LANGUAGES = {"PINE_ENGINE": "pine", "PINE_SUBSET": "pine", "PYTHON_SOURCE": "python", "PYTHON_EDITOR": "python"}


def material(language: str, source: str, libraries: Mapping[str, Any], runtime: Mapping[str, Any]) -> dict[str, Any]:
    return {"language": str(language), "source": str(source), "libraries": dict(libraries), "runtime": dict(runtime)}


def version_hash(value: Mapping[str, Any]) -> str:
    return canonical_hash({"schema": SCHEMA, **material(value["language"], value["source"], value["libraries"],
                                                        value["runtime"])})


def host_material(repository, registry, run: Mapping[str, Any]) -> dict[str, Any]:
    """A host run's code: its compiled revision, or a registry strategy on its engine version."""
    revision_id = str(run["strategy_revision_id"])
    revision = repository.get_strategy_revision(revision_id)
    if revision is None:
        try:
            descriptor = registry.require(revision_id)
        except Exception:
            raise BacktestError("VERSION_UNAVAILABLE", f"strategy revision {revision_id} is unknown") from None
        config = json.loads(str(run["config_json"]))
        source = config.get("strategy_source") if descriptor.accepts_source else None
        language = "pine" if descriptor.provider_kind == "SCRIPT" else "builtin"
        runtime = {"engine_version": str(run["engine_version"])}
        if source:
            return material(language, str(source), {}, {**runtime, "registry_revision": revision_id})
        return material(language, revision_id, {}, runtime)
    libraries: Mapping[str, Any] = {}
    if revision["language"] == "PINE_ENGINE":
        execution = json.loads(json.loads(str(revision["compiled_json"]))["executionSource"])
        libraries = execution.get("libraries") or {}
    return material(HOST_LANGUAGES.get(str(revision["language"]), str(revision["language"]).lower()),
                    str(revision["source_text"]), libraries,
                    {"compiler": str(revision["language"]), "runtime_revision": str(revision["runtime_revision"]),
                     "dependency_hash": str(revision["dependency_hash"]),
                     "base_revision_id": str(revision["base_revision_id"])})


def native_material(record: Mapping[str, Any]) -> dict[str, Any]:
    """A native or CandleScope-matched run's code: its Pine source on the engine that ran it."""
    config = record.get("config") or {}
    if not isinstance(config, Mapping) or not config.get("source"):
        raise BacktestError("VERSION_UNAVAILABLE", "the run does not hold its source")
    return material(str(config.get("language") or "pine"), str(config["source"]), config.get("libraries") or {},
                    {"engine": record.get("runtime_identity") or {}})


def continuous_material(definition: Mapping[str, Any]) -> dict[str, Any]:
    """A forward run's code: its prepared provider on the engine version."""
    provider = definition.get("provider") or {}
    if not isinstance(provider, Mapping) or "language" not in provider:
        raise BacktestError("VERSION_UNAVAILABLE", "the forward run does not hold its provider")
    runtime = {"engine_version": str(definition.get("engine_version"))}
    builtin = provider.get("builtin_id")
    source = provider.get("source_text") or ""
    if builtin and not source:
        return material("builtin", str(builtin), {}, runtime)
    if provider["language"] == "external":
        # B-333c: the model runs outside the Host; its code is its revision's frozen manifest.
        binding = provider.get("external") or {}
        identity = binding.get("external_provider_identity") or {}
        return material("external", str(provider.get("strategy_revision_id")), {},
                        {**runtime, "provider_schema": str(provider.get("schema")),
                         "manifest_hash": str(identity.get("manifest_hash"))})
    pine = provider.get("pine") if isinstance(provider.get("pine"), Mapping) else None
    return material(str(provider["language"]), str(source), provider.get("libraries") or {},
                    {**runtime, "provider_schema": str(provider.get("schema")),
                     **({"builtin_id": str(builtin)} if builtin else {}),
                     # B-333b: a Pine forward run's compilation on the installed Pine runtime.
                     **({"dependency_hash": str(pine.get("dependency_hash"))} if pine else {})})


def check_hash(value: object) -> str:
    if not isinstance(value, str) or not VERSION_HASH.fullmatch(value):
        raise BacktestError("VERSION_NOT_FOUND", "unknown strategy version")
    return value


def check_name(value: object) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise BacktestError("VERSION_NAME_INVALID", "a version name is 1 to 120 characters, without a slash or surrounding space")
    return value


class StrategyVersions:
    """Versions, their names and which runs executed them, in the backtest database."""

    def __init__(self, repository) -> None:
        self.repository = repository

    def record(self, value: Mapping[str, Any], *, run_id: str | None = None, family: str | None = None,
               now_ms: int) -> str:
        """Store a version (idempotent) and link a run to it; returns its hash."""
        stored = material(value["language"], value["source"], value["libraries"], value["runtime"])
        digest = version_hash(stored)
        if run_id is not None and family not in FAMILIES:
            raise ValueError(f"unknown run family {family!r}")
        return self.repository.record_strategy_version(digest, stored, run_id=run_id, family=family, now_ms=now_ms)

    def for_run(self, run_id: str) -> str | None:
        return self.repository.strategy_version_for_run(run_id)

    def get(self, digest: str) -> dict[str, Any]:
        row = self.repository.get_strategy_version(check_hash(digest))
        if row is None:
            raise BacktestError("VERSION_NOT_FOUND", "unknown strategy version")
        return {"schema": SCHEMA, "version_hash": row["version_hash"], "language": row["language"],
                "source": row["source_text"], "libraries": json.loads(row["libraries_json"]),
                "runtime": json.loads(row["runtime_json"]), "created_at_ms": int(row["created_at_ms"]),
                "names": self.repository.strategy_version_names(row["version_hash"])}

    def draft(self, digest: str) -> dict[str, Any]:
        """A version as editor text, to edit as a new draft.

        Pine and forward-run Python hold their text; a chart or editor Python revision
        holds its bundle identity, and its text is that single-file editor bundle's
        ``strategy.py``. Builtins, external bundles and retired languages have no editor
        text and are refused, never relabelled.
        """
        version = self.get(digest)
        language, source, runtime = version["language"], version["source"], version["runtime"]
        if language == "python" and runtime.get("compiler") == "PYTHON_SOURCE":
            from .research_version import editor_bundle_source
            source, _ = editor_bundle_source(self.repository, source)
        elif not (language == "pine" or (language == "python" and "provider_schema" in runtime)):
            raise BacktestError("FIDELITY_UNSUPPORTED", "this strategy version has no editor text")
        if not source.strip() or len(source.encode("utf-8")) > MAX_DRAFT_SOURCE_BYTES:
            raise BacktestError("FIDELITY_UNSUPPORTED", "this strategy version exceeds the editor budget")
        return {"schema": DRAFT_SCHEMA, "version_hash": digest, "language": language, "source": source,
                "libraries": version["libraries"]}

    def runs(self, digest: str, limit: int = 50) -> dict[str, Any]:
        self.get(digest)
        return {"version_hash": digest, "runs": self.repository.strategy_version_runs(digest, limit)}

    def name(self, name: str, digest: str, *, now_ms: int) -> dict[str, Any]:
        """Point ``name`` at a version; naming again moves the name."""
        self.get(digest)
        self.repository.name_strategy_version(check_name(name), digest, now_ms=now_ms)
        return {"name": name, "version_hash": digest}

    def names(self) -> dict[str, Any]:
        return {"names": self.repository.list_strategy_version_names()}

    def unname(self, name: str) -> dict[str, Any]:
        return {"name": name, "removed": self.repository.delete_strategy_version_name(check_name(name))}
