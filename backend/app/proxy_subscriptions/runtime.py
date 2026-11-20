"""Translate persisted references into usable endpoints only while their core is live."""
from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass

from app.core.config import DATA_DIR, load_proxy_settings
from .core import Core
from .source import SubscriptionError
from .store import REFERENCE, SnapshotStore


@dataclass
class Generation:
    references: dict
    core: Core | None

    def resolve(self, url):
        if not url.startswith("mihomo://"):
            return url
        if self.core and self.core.alive:
            endpoint = self.core.endpoints.get(self.references.get(url))
            if endpoint:
                return endpoint
        raise SubscriptionError("Selected subscription node is unavailable")


class ManagedRoutes:
    def __init__(self, store):
        self.store = store
        self.active = Generation({}, None)
        self.lock = threading.RLock()
        self.restore_pending = False

    @contextmanager
    def candidate(self, routes):
        references = {}
        for route in routes:
            match = REFERENCE.fullmatch(route["url"])
            if match and route.get("enabled", True):
                references[route["url"]] = match[2]
        previous = self.active
        if references == previous.references and (not references or previous.core.alive):
            yield previous
            return
        nodes = {}
        snapshots = {}
        for ref, key in references.items():
            revision = REFERENCE.fullmatch(ref)[1]
            if revision not in snapshots:
                snapshots[revision] = self.store.read(revision)["nodes"]
            if key in nodes or key not in snapshots[revision]:
                raise SubscriptionError("Invalid or duplicate subscription node")
            nodes[key] = snapshots[revision][key]
        if nodes and previous.core and previous.core.alive:
            previous_nodes = previous.core.nodes
            changed = nodes != previous_nodes
            if changed:
                previous.core.reconfigure(nodes)
            try:
                yield Generation(references, previous.core)
            except BaseException:
                if changed:
                    previous.core.reconfigure(previous_nodes)
                raise
            return
        candidate = Generation(references, Core(nodes) if nodes else None)
        try:
            yield candidate
        finally:
            if candidate.core and self.active.core is not candidate.core:
                candidate.core.close()

    def activate(self, routes, persist=None):
        with self.lock, self.candidate(routes) as candidate:
            if persist:
                persist()
            previous = self.active
            self.active = candidate
            self.restore_pending = False
            if previous.core and previous.core is not candidate.core:
                previous.core.close()

    def restore(self):
        with self.lock:
            settings = load_proxy_settings()
            routes = settings.get("routes", []) if settings.get("mode") == "pool" else []
            self.restore_pending = any(r["enabled"] and REFERENCE.fullmatch(r["url"]) for r in routes)
            self.activate(routes)

    def recover(self):
        with self.lock:
            if self.restore_pending or (self.active.core and not self.active.core.alive):
                self.restore()

    async def supervise(self):
        delay = 2
        while True:
            await asyncio.sleep(delay)
            if not self.restore_pending and (not self.active.core or self.active.core.alive):
                delay = 2
                continue
            try:
                await asyncio.to_thread(self.recover)
                delay = 2
            except SubscriptionError as exc:
                logging.getLogger(__name__).warning("Subscription recovery pending: %s", exc)
                delay = min(60, delay * 2)

    def close(self):
        self.activate([])


managed = ManagedRoutes(SnapshotStore(DATA_DIR / "proxy-subscriptions"))


def resolve(url):
    return managed.active.resolve(url)
