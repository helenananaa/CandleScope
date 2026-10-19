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
