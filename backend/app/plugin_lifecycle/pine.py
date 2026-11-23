"""Bind the existing Pine chart and strategy consumers to the unified owner."""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path

from .paths import is_link
from .script_bundle import PINE_ID
from .script_runtime import pin_script
from .store import LifecycleError

INSTALLATION_SCHEMA = "candlescope.unified-pine-installation/1"
STRATEGY_MODULES = frozenset(
    {
        "native_strategy",
        "native_session",
        "external_strategy",
        "chart_strategy",
    }
)
_strategy_runtime = None
_strategy_required = False
_strategy_processes = {}
_process_lock = threading.Lock()


def import_pine_observations(storage, environ):
    """Copy a consistent legacy journal into private storage on first use."""
    target = storage / "observations-v1.sqlite3"
    if target.exists() or is_link(target):
        return
    explicit = environ.get("CANDLESCOPE_PINE_JOURNAL")
    if explicit:
        source = Path(explicit).expanduser().absolute()
    elif environ.get("CANDLESCOPE_DESKTOP_USER_DATA"):
        return
    else:
        root = Path(environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
        source = root / "CandleScope" / "pine" / target.name
    if not source.is_file():
        return

    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}")
    deadline = time.monotonic() + 5

    def check_progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise LifecycleError("Pine observation journal backup timed out")

    try:
        with (
            closing(
                sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=1)
            ) as old,
            closing(sqlite3.connect(temporary)) as new,
        ):
            page_size = old.execute("PRAGMA page_size").fetchone()[0]
            pages = old.execute("PRAGMA page_count").fetchone()[0]
            if page_size * pages > 512 * 1024 * 1024:
                raise LifecycleError(
                    "Pine observation journal exceeds the migration budget"
                )
            old.backup(new, pages=256, progress=check_progress, sleep=0.05)
        os.replace(temporary, target)
    except sqlite3.Error as exc:
        raise LifecycleError(
            f"Could not copy the previous Pine observation journal: {exc}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def bind_strategy_runtime(runtime, *, required):
    global _strategy_runtime, _strategy_required
    _strategy_runtime, _strategy_required = runtime, required


def strategy_launch():
    run = pin_script(_strategy_runtime, PINE_ID)
    return _launch(run, "native_strategy")


def _launch(run, module):
    return {
        "command": [
            sys.executable,
            "-I",
            "-B",
            "-u",
            "-c",
            "import runpy,sys;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];runpy.run_module(sys.argv[0],run_name='__main__')",
            str(run.executor.context.root),
            f"candlescope_plugin_pine_compat.{module}",
        ],
        "plugin_id": PINE_ID,
        "plugin_version": run.identity.plugin_version,
        "installation": {
            "schema": INSTALLATION_SCHEMA,
            "packageSha256": run.identity.package_sha256,
            "generation": run.identity.generation,
        },
        "instanceId": run.instance,
    }


def pin_strategy_launch(plugin, *, restore=False):
    installation = plugin.get("installation")
    unified = (
        isinstance(installation, dict)
        and installation.get("schema") == INSTALLATION_SCHEMA
    )
    if not unified:
        if _strategy_required and plugin.get("plugin_id") == PINE_ID:
            raise LifecycleError(
                "This Pine run uses a retired runtime. Rerun it with the unified package."
            )
        return plugin
    run = pin_script(_strategy_runtime, PINE_ID)
    if installation.get("packageSha256") != run.identity.package_sha256 or (
        not restore
        and (
            plugin.get("instanceId") != run.instance
            or installation.get("generation") != run.identity.generation
        )
    ):
        raise LifecycleError(
            "Pine activation changed; restore the pinned package or rerun"
        )
    module = plugin["command"][-1].removeprefix("candlescope_plugin_pine_compat.")
    if module not in STRATEGY_MODULES:
        raise LifecycleError("Invalid unified Pine strategy entry")
    return _launch(run, module)


def track_strategy_process(plugin, process):
    instance = plugin.get("instanceId")
    if instance is None:
        return
    with _process_lock:
        pin_strategy_launch(plugin)
        _strategy_processes.setdefault(instance, set()).add(process)


def untrack_strategy_process(plugin, process):
    instance = plugin.get("instanceId")
    with _process_lock:
        processes = _strategy_processes.get(instance)
        if processes is not None:
            processes.discard(process)
            if not processes:
                _strategy_processes.pop(instance, None)


def revoke_strategy_processes(instance):
    with _process_lock:
        processes = _strategy_processes.pop(instance, ())
    for process in processes:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait()
