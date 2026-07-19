"""Shared contracts for backend-hosted script runtimes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


PYNE_RUNTIME_ID = "pyne"
PINE_COMPAT_RUNTIME_ID = "pine-compat"
DEFAULT_SCRIPT_RUNTIME_ID = PYNE_RUNTIME_ID


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
    ) -> Any: ...

    def descriptor(self) -> ScriptRuntimeDescriptor: ...
