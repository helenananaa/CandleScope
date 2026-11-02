"""Bounded wakeups for committed resource changes across local repositories.

The database remains authoritative. A wakeup contains no result data and may
coalesce several commits; subscribers read the latest committed resource identity.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import threading
import weakref
from pathlib import Path


class CommittedSubscription:
    def __init__(self, owner: CommittedUpdates, resource_id: str) -> None:
        self._owner = owner
        self.resource_id = resource_id
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


class CommittedUpdates:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, set[CommittedSubscription]] = {}
        self._commit_listeners: dict[str, set[Callable[[], None]]] = {}

    def listen_commits(self, resource_id: str, listener: Callable[[], None]) -> Callable[[], None]:
        """Install an owned process bridge; callbacks carry no result payload."""
        with self._lock:
            self._commit_listeners.setdefault(resource_id, set()).add(listener)

        def release() -> None:
            with self._lock:
                listeners = self._commit_listeners.get(resource_id)
                if listeners is not None:
                    listeners.discard(listener)
                    if not listeners:
                        self._commit_listeners.pop(resource_id, None)
        return release

    def subscribe(self, resource_id: str) -> CommittedSubscription:
        subscription = CommittedSubscription(self, resource_id)
        with self._lock:
            self._subscribers.setdefault(resource_id, set()).add(subscription)
        return subscription

    def remove(self, subscription: CommittedSubscription) -> None:
        with self._lock:
            subscribers = self._subscribers.get(subscription.resource_id)
            if subscribers is None:
                return
            subscribers.discard(subscription)
            if not subscribers:
                self._subscribers.pop(subscription.resource_id, None)

    def notify(self, resource_id: str) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(resource_id, ()))
            listeners = tuple(self._commit_listeners.get(resource_id, ()))
        for subscription in subscribers:
            subscription.notify()
        for listener in listeners:
            try:
                listener()
            except Exception:
                # Notification failure cannot turn an already committed write
                # into a reported transaction failure.
                logging.getLogger(__name__).exception("Committed state bridge failed for %s", resource_id)

    def diagnostics(self) -> dict[str, int]:
        with self._lock:
            return {"resources": len(self._subscribers), "subscriptions": sum(map(len, self._subscribers.values()))}


_registry_lock = threading.Lock()
_registry: weakref.WeakValueDictionary[tuple[str, str], CommittedUpdates] = weakref.WeakValueDictionary()


def committed_updates_for(path: Path, namespace: str) -> CommittedUpdates:
    if str(path) == ":memory:":
        return CommittedUpdates()
    key = (namespace, str(path.resolve()))
    with _registry_lock:
        updates = _registry.get(key)
        if updates is None:
            updates = CommittedUpdates()
            _registry[key] = updates
        return updates
