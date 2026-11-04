"""Backtest namespace for shared committed-state wakeups."""
import threading
import weakref
from pathlib import Path
from app.core.committed_updates import CommittedUpdates, CommittedSubscription

RunUpdateSubscription = CommittedSubscription


class RunUpdates(CommittedUpdates):
    def diagnostics(self) -> dict[str, int]:
        values = super().diagnostics()
        return {"runs": values["resources"], "subscriptions": values["subscriptions"]}


_registry_lock = threading.Lock()
_registry: weakref.WeakValueDictionary[str, RunUpdates] = weakref.WeakValueDictionary()


def run_updates_for(path: Path) -> RunUpdates:
    # Separate SQLite in-memory connections never share committed state.
    if str(path) == ":memory:":
        return RunUpdates()
    key = str(path.resolve())
    with _registry_lock:
        updates = _registry.get(key)
        if updates is None:
            updates = RunUpdates()
            _registry[key] = updates
        return updates
