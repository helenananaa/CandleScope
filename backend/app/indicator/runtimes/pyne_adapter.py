"""Adapter that exposes the existing Pyne package through the runtime registry."""
from __future__ import annotations

from typing import Any

from app.indicator.pyne.external_runtime import RuntimeBackendSnapshot, execute_pyne_script

from .base import PYNE_RUNTIME_ID, ScriptRuntimeDescriptor


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
    ) -> Any:
        del render_hints
        return execute_pyne_script(
            script=script,
            ohlcv=ohlcv,
            params=params or {},
            security_mode=security_mode,
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
                "historical": True,
                "formingBar": True,
                "incremental": True,
                "securityModes": ["safe", "research", "unsafe"],
            },
        )
