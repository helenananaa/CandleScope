"""Shared contracts for backend-hosted script runtimes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


PYNE_RUNTIME_ID = "pyne"
PINE_COMPAT_RUNTIME_ID = "pine-compat"
DEFAULT_SCRIPT_RUNTIME_ID = PYNE_RUNTIME_ID
SCRIPT_RUNTIME_HOST_CONTRACT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ScriptRuntimeContext:
    """Market/chart identity supplied by CandleScope to a hosted runtime.

    The first contract version deliberately carries identity only. Runtime-
    specific data providers, library sources, and forming-bar state belong in
    versioned dependency/session contracts instead of an untyped options bag.
    """

    exchange: str
    market_type: str
    symbol: str
    interval: str

    def to_dict(self) -> dict[str, str]:
        return {
            "exchange": self.exchange,
            "marketType": self.market_type,
            "symbol": self.symbol,
            "interval": self.interval,
        }


@dataclass(slots=True)
class ScriptRuntimeAnalysis:
    """Runtime-neutral source analysis consumed by API/editor clients."""

    runtime: str
    ok: bool
    native_executable: bool
    host_executable: bool
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    compatibility: dict[str, Any] = field(default_factory=dict)
    host_compatibility: dict[str, Any] = field(default_factory=dict)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCRIPT_RUNTIME_HOST_CONTRACT_VERSION,
            "runtime": self.runtime,
            "ok": self.ok,
            "nativeExecutable": self.native_executable,
            "executable": self.host_executable,
            "diagnostics": self.diagnostics,
            "inputs": self.inputs,
            "compatibility": self.compatibility,
            "hostCompatibility": self.host_compatibility,
            "dependencies": self.dependencies,
            "meta": self.meta,
        }

    @classmethod
    def failure(
        cls,
        *,
        runtime: str,
        code: str,
        message: str,
        hint: str | None = None,
        line: int | None = None,
        column: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> "ScriptRuntimeAnalysis":
        diagnostic: dict[str, Any] = {
            "code": code,
            "severity": "error",
            "message": message,
        }
        if line is not None or column is not None:
            diagnostic["span"] = {
                **({"line": line} if line is not None else {}),
                **({"column": column} if column is not None else {}),
            }
        if hint:
            diagnostic["hint"] = hint
        error = {
            "code": code,
            "message": message,
            **({"line": line} if line is not None else {}),
            **({"column": column} if column is not None else {}),
            **({"hint": hint} if hint else {}),
        }
        return cls(
            runtime=runtime,
            ok=False,
            native_executable=False,
            host_executable=False,
            diagnostics=[diagnostic],
            host_compatibility={"executable": False, "error": error},
            meta=meta or {},
        )


@dataclass(slots=True)
class ScriptRuntimeResult:
    """Runtime-neutral result consumed by CandleScope serialization."""

    ok: bool
    error: str | None = None
    code: str | None = None
    line: int | None = None
    column: int | None = None
    hint: str | None = None
    lines: list[dict[str, Any]] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    param_schema: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ScriptRuntimeResult":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value[key] for key in allowed if key in value})


@dataclass(frozen=True, slots=True)
class ScriptRuntimeDescriptor:
    id: str
    label: str
    language: str
    package: str
    available: bool
    version: str | None = None
    source_path: str | None = None
    reason: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "language": self.language,
            "package": self.package,
            "available": self.available,
            "version": self.version,
            "sourcePath": self.source_path,
            "reason": self.reason,
            "capabilities": self.capabilities,
        }


class ScriptRuntimeAdapter(Protocol):
    runtime_id: str

    def execute(
        self,
        *,
        script: str,
        ohlcv: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
        security_mode: str | None = None,
        render_hints: dict[str, Any] | None = None,
        context: ScriptRuntimeContext | None = None,
    ) -> Any: ...

    def analyze(
        self,
        *,
        script: str,
        security_mode: str | None = None,
        context: ScriptRuntimeContext | None = None,
    ) -> ScriptRuntimeAnalysis: ...

    def descriptor(self) -> ScriptRuntimeDescriptor: ...
