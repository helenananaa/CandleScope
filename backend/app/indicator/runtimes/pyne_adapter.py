"""Adapter that exposes the existing Pyne package through the runtime registry."""
from __future__ import annotations

from typing import Any

from app.indicator.pyne.external_runtime import (
    RuntimeBackendSnapshot,
    analyze_pyne_script,
    execute_pyne_script,
)

from .base import (
    PYNE_RUNTIME_ID,
    SCRIPT_RUNTIME_HOST_CONTRACT_VERSION,
    ScriptRuntimeAnalysis,
    ScriptRuntimeContext,
    ScriptRuntimeDescriptor,
)


class PyneRuntimeAdapter:
    runtime_id = PYNE_RUNTIME_ID

    def execute(
        self,
        *,
        script: str,
        ohlcv: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
        security_mode: str | None = None,
        render_hints: dict[str, Any] | None = None,
        context: ScriptRuntimeContext | None = None,
    ) -> Any:
        del render_hints, context
        return execute_pyne_script(
            script=script,
            ohlcv=ohlcv,
            params=params or {},
            security_mode=security_mode,
        )

    def analyze(
        self,
        *,
        script: str,
        security_mode: str | None = None,
        context: ScriptRuntimeContext | None = None,
    ) -> ScriptRuntimeAnalysis:
        if not script.strip():
            return ScriptRuntimeAnalysis.failure(
                runtime=self.runtime_id,
                code="PYNE_SCRIPT_REQUIRED",
                message="Pyne script is required",
                meta={"context": context.to_dict() if context else None},
            )
        try:
            diagnostics = analyze_pyne_script(script=script, security_mode=security_mode)
        except Exception as exc:
            return ScriptRuntimeAnalysis.failure(
                runtime=self.runtime_id,
                code="PYNE_ANALYSIS_ERROR",
                message=str(exc) or exc.__class__.__name__,
                meta={"context": context.to_dict() if context else None},
            )

        normalized: list[dict[str, Any]] = []
        has_error = False
        for raw in diagnostics:
            item = dict(raw)
            severity = "warning" if item.get("code") == "PYNE_MIGRATION_HINT" else "error"
            item["severity"] = severity
            has_error = has_error or severity == "error"
            normalized.append(item)
        executable = not has_error
        return ScriptRuntimeAnalysis(
            runtime=self.runtime_id,
            ok=executable,
            native_executable=executable,
            host_executable=executable,
            diagnostics=normalized,
            host_compatibility={
                "executable": executable,
                "formingBar": True,
                "error": next((item for item in normalized if item["severity"] == "error"), None),
            },
            meta={
                "hostContractVersion": SCRIPT_RUNTIME_HOST_CONTRACT_VERSION,
                "context": context.to_dict() if context else None,
                "securityMode": security_mode,
            },
        )

    def descriptor(self) -> ScriptRuntimeDescriptor:
        snapshot = RuntimeBackendSnapshot.current()
        return ScriptRuntimeDescriptor(
            id=self.runtime_id,
            label="Pyne (Python)",
            language="python",
            package=snapshot.package,
            available=True,
            version=snapshot.version,
            source_path=snapshot.source_path,
            capabilities={
                "hostContractVersion": SCRIPT_RUNTIME_HOST_CONTRACT_VERSION,
                "analysis": True,
                "historical": True,
                "formingBar": True,
                "incremental": True,
                "securityModes": ["safe", "research", "unsafe"],
            },
        )
