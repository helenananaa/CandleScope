"""Application composition hooks for the unified owner; legacy migration is separate."""

from __future__ import annotations

import os

from .runtime import UnifiedRuntime
from .store import PackageStore


def prepare_unified(app, *, store=None):
    from pathlib import Path

    if store is None:
        from app.plugin_core_v2.bootstrap import default_platform_root

        configured = os.environ.get("CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT")
        root = Path(configured) if configured else default_platform_root(os.environ)
        store = PackageStore(root / "unified")
    safe = (
        os.environ.get("CANDLESCOPE_EXTENSIONS_SAFE_MODE") == "1"
        or os.environ.get("CANDLESCOPE_PLUGIN_PLATFORM_V2_ENABLED", "1") == "0"
    )
    app.state.unified_plugin_runtime = UnifiedRuntime(app, store, safe_mode=safe)


async def activate_unified(app):
    runtime = getattr(app.state, "unified_plugin_runtime", None)
    if runtime:
        try:
            await runtime.start()
        except Exception as exc:  # noqa: BLE001 -- a plugin must not prevent recovery startup
            await runtime.stop()
            runtime.errors["runtime"] = str(exc)


async def stop_unified(app):
    runtime = getattr(app.state, "unified_plugin_runtime", None)
    if runtime:
        await runtime.stop()
