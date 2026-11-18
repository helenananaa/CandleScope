from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _BACKEND_ROOT / "scripts"
_BACKTEST_SDK = (
    _BACKEND_ROOT.parent / "packages" / "candlescope-backtest-sdk" / "src"
)
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from plugin_sdk_isolation import pin_in_repo_plugin_sdk

pin_in_repo_plugin_sdk(_BACKEND_ROOT, _BACKTEST_SDK)

# Tests must never use the developer's replay data: a stray
# backend/data/replay-history/progressive-index.sqlite3 once broke most replay
# tests. load_replay_settings derives every replay path from DATA_DIR with a
# "replay" prefix (replay.db*, replay-history, replay-agg-trades). The audit
# hook sees opens, SQLite connects and directory changes, not bare stat calls.
_DEVELOPER_DATA = os.path.normcase(str(_BACKEND_ROOT / "data")) + os.sep
_GUARDED_EVENTS = frozenset({
    "open", "sqlite3.connect", "os.mkdir", "os.listdir", "os.scandir",
    "os.remove", "os.rmdir", "os.rename", "os.truncate", "os.utime",
    "os.chmod", "shutil.copyfile", "shutil.rmtree",
})
_developer_replay_paths: list[str] = []


class DeveloperReplayDataAccess(AssertionError):
    """Raised when a test reaches replay data under the real backend/data."""


def _audited_path(value: object) -> str | None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    try:
        text = os.fsdecode(value)
    except TypeError:
        return None
    if text.startswith("file:"):
        text = url2pathname(urlsplit(text).path)
    return os.path.normcase(os.path.abspath(text)) if text else None


def _guard_developer_replay_data(event: str, args: tuple[object, ...]) -> None:
    if event not in _GUARDED_EVENTS or not args:
        return
    targets = args[:2] if event in {"os.rename", "shutil.copyfile"} else args[:1]
    for target in targets:
        path = _audited_path(target)
        if path is None or not path.startswith(_DEVELOPER_DATA):
            continue
        if not path[len(_DEVELOPER_DATA):].startswith("replay"):
            continue
        _developer_replay_paths.append(path)
        raise DeveloperReplayDataAccess(
            f"test reached the developer's replay data via {event}: {path}; "
            "build settings with service_fakes.replay_settings(tmp_path / ...)"
        )


sys.addaudithook(_guard_developer_replay_data)


@pytest.fixture(autouse=True)
def _forbid_developer_replay_data():
    """Fail tests whose replay-data access was raised and then swallowed."""
    yield
    touched = sorted(set(_developer_replay_paths))
    _developer_replay_paths.clear()
    if touched:
        pytest.fail(
            "test reached the developer's replay data under backend/data:\n"
            + "\n".join(touched),
            pytrace=False,
        )


@pytest.fixture
def anyio_backend() -> str:
    """Run anyio-marked tests on the asyncio backend used by the app."""
    return "asyncio"


@pytest.fixture(scope="session")
def _qualified_pine_runtime(tmp_path_factory):
    descriptor = os.environ.get("CANDLESCOPE_TEST_QUALIFIED_PINE_DESCRIPTOR")
    if not descriptor:
        pytest.fail("native Pine qualification requires the built unified package descriptor")

    import asyncio
    from concurrent.futures import Future, ThreadPoolExecutor
    from threading import Event
    from types import SimpleNamespace

    from app.plugin_lifecycle.pine import PINE_ID
    from app.plugin_lifecycle.runtime import UnifiedRuntime
    from app.plugin_lifecycle.script_runtime import pin_script
    from app.plugin_lifecycle.store import PackageStore

    runtime = UnifiedRuntime(
        SimpleNamespace(state=SimpleNamespace()),
        PackageStore(tmp_path_factory.mktemp("qualified-pine")),
    )
    ready = Future()
    stopped = Event()

    async def run_lifecycle():
        try:
            await runtime.prepare_startup(bundled={PINE_ID: Path(descriptor)})
            await runtime.start()
            pin_script(runtime, PINE_ID)
            ready.set_result(runtime)
            await asyncio.to_thread(stopped.wait)
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise
        finally:
            await runtime.stop()

    # The real sidecar transport keeps its event loop while synchronous Host
    # qualification tests launch pinned chart, strategy and replay processes.
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker = executor.submit(asyncio.run, run_lifecycle())
        try:
            yield ready.result(timeout=45)
        finally:
            stopped.set()
            worker.result(timeout=45)


@pytest.fixture
def qualified_pine_reference(monkeypatch, _qualified_pine_runtime):
    from app.plugin_lifecycle import pine

    monkeypatch.setattr(pine, "_strategy_runtime", _qualified_pine_runtime)
    monkeypatch.setattr(pine, "_strategy_required", False)


@pytest.fixture
def qualified_pine(monkeypatch, qualified_pine_reference):
    from app.plugin_lifecycle import pine

    monkeypatch.setattr(pine, "_strategy_required", True)


@pytest.fixture(autouse=True)
def _isolate_process_proxy_http_admission(monkeypatch):
    # Production admission deliberately spans event loops; test cases represent
    # separate app lifetimes and must not inherit a previous case's cooldowns.
    import weakref
    from app.core import proxy_pool
    monkeypatch.setattr(proxy_pool, "_SHARED_HTTP", proxy_pool._HttpState())
    monkeypatch.setattr(proxy_pool, "_POOLS", weakref.WeakKeyDictionary())
