"""Bounded wakeups for committed run changes across local worker repositories.

The database remains authoritative. A wakeup contains no result data and may
coalesce several commits; subscribers read the latest committed run identity.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import threading
import weakref
from pathlib import Path


class RunUpdateSubscription:
    def __init__(self, owner: RunUpdates, run_id: str) -> None:
        self._owner = owner
        self.run_id = run_id
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()
        self._lock = threading.Lock()
        self._dirty = False
        self._closed = False

    def notify(self) -> None:
        with self._lock:
            if self._closed or self._dirty:
                return
            self._dirty = True
        try:
            self._loop.call_soon_threadsafe(self._deliver)
        except RuntimeError:
            self.close()

    def _deliver(self) -> None:
        with self._lock:
            if not self._closed and self._dirty:
                self._event.set()

    def clear_before_read(self) -> None:
        """On the event-loop thread, clear before reading the committed state.

        A commit during that read sets the event again, so a terminal update
        cannot be lost between observing state and waiting for its successor.
        """
        with self._lock:
            self._dirty = False
            self._event.clear()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    async def wait(self) -> bool:
        await self._event.wait()
        return not self.closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._owner.remove(self)
        try:
            self._loop.call_soon_threadsafe(self._event.set)
        except RuntimeError:
            pass


class RunUpdates:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, set[RunUpdateSubscription]] = {}
        self._commit_listeners: dict[str, set[Callable[[], None]]] = {}

    def listen_commits(self, run_id: str, listener: Callable[[], None]) -> Callable[[], None]:
        """Install an owned process bridge; callbacks carry no result payload."""
        with self._lock:
            self._commit_listeners.setdefault(run_id, set()).add(listener)

        def release() -> None:
            with self._lock:
                listeners = self._commit_listeners.get(run_id)
                if listeners is not None:
                    listeners.discard(listener)
                    if not listeners:
                        self._commit_listeners.pop(run_id, None)
        return release

    def subscribe(self, run_id: str) -> RunUpdateSubscription:
        subscription = RunUpdateSubscription(self, run_id)
        with self._lock:
            self._subscribers.setdefault(run_id, set()).add(subscription)
        return subscription

    def remove(self, subscription: RunUpdateSubscription) -> None:
        with self._lock:
            subscribers = self._subscribers.get(subscription.run_id)
            if subscribers is None:
                return
            subscribers.discard(subscription)
            if not subscribers:
                self._subscribers.pop(subscription.run_id, None)

    def notify(self, run_id: str) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(run_id, ()))
            listeners = tuple(self._commit_listeners.get(run_id, ()))
        for subscription in subscribers:
            subscription.notify()
        for listener in listeners:
            try:
                listener()
            except Exception:
                # Notification failure cannot turn an already committed write
                # into a reported transaction failure.
                logging.getLogger(__name__).exception("Run commit bridge failed for %s", run_id)

    def diagnostics(self) -> dict[str, int]:
        with self._lock:
            return {"runs": len(self._subscribers), "subscriptions": sum(map(len, self._subscribers.values()))}


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
