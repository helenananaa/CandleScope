"""Scheduled refresh of saved subscriptions (#575 PL-11c).

A refresh only follows the nodes the user already chose: when the provider changes
one of them, the route points at a new snapshot with the provider's current
parameters. New nodes are never added, and a node the provider dropped keeps its
last parameters until the user picks again. A failed download changes nothing and
is retried within the hour.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import tempfile
import time

from app.core.config import DATA_DIR, load_proxy_settings
from .runtime import managed
from .source import SubscriptionError, download, source_id
from .store import REFERENCE

INTERVALS = (0, 6, 12, 24)  # Hours; 0 turns the schedule off.
DEFAULT_HOURS = 24
RETRY_MS = 3_600_000
CHECK_SECONDS = 600
logger = logging.getLogger(__name__)


@dataclass
class Saved:
    """The chosen nodes of one subscription URL, and the route URLs that point at them."""
    nodes: dict = field(default_factory=dict)
    routes: dict = field(default_factory=dict)  # route url -> node key


def saved_sources(routes, store) -> dict[str, Saved]:
    sources, snapshots = {}, {}
    for route in routes:
        match = REFERENCE.fullmatch(route.get("url", ""))
        if not match:
            continue
        revision, key = match[1], match[2]
        try:
            snapshot = snapshots[revision] = snapshots.get(revision) or store.read(revision)
        except SubscriptionError:
            continue  # restore() reports unreadable snapshots; nothing to refresh here.
        if key in snapshot["nodes"]:
            saved = sources.setdefault(snapshot["url"], Saved())
            saved.nodes[key] = snapshot["nodes"][key]
            saved.routes[route["url"]] = key
    return sources


class Refresher:
    def __init__(self, store, path: Path, *, fetch=download, clock=time.time):
        self.store = store
        self.path = path
        self.fetch = fetch
        self.clock = clock
        self.wake = asyncio.Event()

    def status(self) -> dict:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
        hours = data.get("interval_hours")
        sources = data.get("sources")
        return {"interval_hours": hours if hours in INTERVALS else DEFAULT_HOURS,
                "sources": sources if isinstance(sources, dict) else {}}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as out:
                json.dump(data, out, sort_keys=True)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def set_interval(self, hours: int) -> dict:
        if hours not in INTERVALS:
            raise ValueError("Unsupported refresh interval")
        data = self.status()
        data["interval_hours"] = hours
        self._write(data)
        return data

    async def refresh_due(self, apply) -> None:
        """Refresh every source whose time has come. `apply(replacements)` repoints routes."""
        data = self.status()
        hours = data["interval_hours"]
        settings = load_proxy_settings()
        if not hours or settings.get("mode") != "pool":
            return
        routes = settings.get("routes", [])
        sources = await asyncio.to_thread(saved_sources, routes, self.store)
        # Route ids start with the source id, so a source keeps its history while a route
        # still uses it, even if its snapshot can't be read right now (keychain locked).
        current = {route["id"][4:20] for route in routes if REFERENCE.fullmatch(route.get("url", ""))}
        states = {sid: state for sid, state in data["sources"].items() if sid in current}
        for url, saved in sources.items():
            sid = source_id(url)
            state = states.get(sid) or {}
            wait = hours * 3_600_000 if not state.get("error") else min(hours * 3_600_000, RETRY_MS)
            now = int(self.clock() * 1000)
            if now < int(state.get("last_attempt_ms") or 0) + wait:
                continue
            states[sid] = await self._refresh(url, saved, dict(state, last_attempt_ms=now), apply)
            self._write({"interval_hours": hours, "sources": states})
        if states != data["sources"]:
            self._write({"interval_hours": hours, "sources": states})

    async def _refresh(self, url, saved, state, apply):
        try:
            latest, _ = await self.fetch(url)
            changed = sorted(k for k, node in saved.nodes.items() if k in latest and latest[k] != node)
            missing = sorted(k for k in saved.nodes if k not in latest)
            if changed:
                chosen = {k: latest.get(k, node) for k, node in saved.nodes.items()}
                rows = await asyncio.to_thread(self.store.save, url, chosen)
                urls = {REFERENCE.fullmatch(row["url"])[2]: row["url"] for row in rows}
                if await apply({old: urls[key] for old, key in saved.routes.items()}):
                    state["last_change_ms"] = state["last_attempt_ms"]
                    state["updated"] = len(changed)
            return dict(state, last_success_ms=state["last_attempt_ms"], missing=len(missing), error=None)
        except SubscriptionError as exc:
            return dict(state, error=str(exc))
        except Exception:
            logger.exception("Scheduled subscription refresh failed")
            return dict(state, error="Scheduled refresh failed")

    async def run(self, apply) -> None:
        delay = 60  # Let startup settle before the first check.
        while True:
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=delay)
            except TimeoutError:
                pass
            self.wake.clear()
            try:
                await self.refresh_due(apply)
            except Exception:
                logger.exception("Scheduled subscription refresh check failed")
            delay = CHECK_SECONDS


refresher = Refresher(managed.store, DATA_DIR / "proxy-subscription-refresh.json")
