"""Explicit script-runtime registry.

Runtime selection is persisted and sent over the API. Source text is never
sniffed to decide which interpreter should execute it.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from .base import (
    DEFAULT_SCRIPT_RUNTIME_ID,
    PINE_COMPAT_RUNTIME_ID,
    PYNE_RUNTIME_ID,
    ScriptRuntimeAdapter,
)


_ALIASES = {
    "": DEFAULT_SCRIPT_RUNTIME_ID,
    "python": PYNE_RUNTIME_ID,
    "pyne-runtime": PYNE_RUNTIME_ID,
    "pine": PINE_COMPAT_RUNTIME_ID,
    "pine_compat": PINE_COMPAT_RUNTIME_ID,
    "pine-compat-runtime": PINE_COMPAT_RUNTIME_ID,
}


def normalize_runtime_id(value: Any, *, default: str = DEFAULT_SCRIPT_RUNTIME_ID) -> str:
    runtime_id = str(value or default).strip().lower()
    runtime_id = _ALIASES.get(runtime_id, runtime_id)
    if runtime_id not in {PYNE_RUNTIME_ID, PINE_COMPAT_RUNTIME_ID}:
        raise ValueError(f"Unknown script runtime: {value}")
    return runtime_id


@lru_cache(maxsize=2)
def get_script_runtime(value: Any = None) -> ScriptRuntimeAdapter:
    runtime_id = normalize_runtime_id(value)
    if runtime_id == PYNE_RUNTIME_ID:
        from .pyne_adapter import PyneRuntimeAdapter

        return PyneRuntimeAdapter()
    from .pine_compat_adapter import PineCompatRuntimeAdapter

    return PineCompatRuntimeAdapter()


def runtime_descriptors() -> list[dict[str, Any]]:
    return [
        get_script_runtime(runtime_id).descriptor().to_dict()
        for runtime_id in (PYNE_RUNTIME_ID, PINE_COMPAT_RUNTIME_ID)
    ]
