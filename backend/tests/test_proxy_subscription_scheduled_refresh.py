"""Scheduled subscription refresh follows chosen nodes only (#575 PL-11c)."""
import asyncio
from contextlib import contextmanager

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from app.api.v1 import settings
from app.core import config
from app.proxy_subscriptions import api, refresh, runtime
from app.proxy_subscriptions.refresh import Refresher, saved_sources
from app.proxy_subscriptions.source import SubscriptionError, parse_nodes
from app.proxy_subscriptions.store import REFERENCE, SnapshotStore

SOURCE = "https://example.invalid/subscription?token=private-test-token"
HOUR_MS = 3_600_000


def payload(*nodes):
    return ("proxies:\n" + "".join(f"  - {node}\n" for node in nodes)).encode()


FIRST = "{name: first, type: trojan, server: a.example.invalid, port: 443, password: one}"
SECOND = "{name: second, type: trojan, server: b.example.invalid, port: 443, password: two}"
THIRD = "{name: third, type: trojan, server: c.example.invalid, port: 443, password: three}"


class FakeCore:
    connection_sweep_due = False

    def __init__(self, nodes):
        self.alive = True
        self.reconfigure(nodes)

    def reconfigure(self, nodes):
        self.nodes = nodes
        self.endpoints = {key: f"http://127.0.0.1:{10000 + i}" for i, key in enumerate(nodes)}

    @contextmanager
    def stage_update(self, nodes):
        yield
        self.reconfigure(nodes)

    def sweep_retired_connections(self):
        pass

    def close(self):
        self.alive = False


@pytest.fixture
async def world(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROXY_SETTINGS_PATH", tmp_path / "proxy.json")
    store = SnapshotStore(tmp_path / "private")
    cipher = Fernet(Fernet.generate_key())
    monkeypatch.setattr(store, "_cipher", lambda create: cipher)
    manager = runtime.ManagedRoutes(store)
    for module in (runtime, settings, api):
        monkeypatch.setattr(module, "managed", manager)
    monkeypatch.setattr(runtime, "Core", FakeCore)
    published = {"body": payload(FIRST, SECOND, THIRD), "calls": 0}

    async def fetch(url):
        assert url == SOURCE
        published["calls"] += 1
        if published.get("during"):
            await published.pop("during")()
        if isinstance(published["body"], Exception):
            raise published["body"]
        return parse_nodes(published["body"], url)

    clock = [1_000_000.0]
    refresher = Refresher(store, tmp_path / "refresh.json", fetch=fetch, clock=lambda: clock[0])
    monkeypatch.setattr(api, "refresher", refresher)
    app = FastAPI()
    app.include_router(settings.router)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1/settings/proxy") as cli:
        nodes, _ = parse_nodes(published["body"], SOURCE)
        chosen = {key: node for key, node in nodes.items() if node["name"] in ("first", "second")}
        rows = store.save(SOURCE, chosen)
        rows[0]["max_concurrency"] = 1
        manual = {"id": "manual", "name": "manual", "url": "http://127.0.0.1:7890", "egress_group": "shared", "enabled": True}
        saved = await cli.put("", json={"mode": "pool", "routes": [rows[0], manual, rows[1]]}, follow_redirects=True)
        assert saved.status_code == 200

        async def apply(replacements):
            return await settings.apply_refreshed_routes(app, replacements)

        yield {"cli": cli, "manager": manager, "refresher": refresher, "published": published,
               "clock": clock, "apply": apply, "store": store}
    manager.close()


def routes():
    return config.load_proxy_settings()["routes"]


def key_of(route):
    return REFERENCE.fullmatch(route["url"])[2]


@pytest.mark.anyio
async def test_changed_chosen_nodes_follow_the_provider_and_nothing_is_added(world):
    before = routes()
    core = world["manager"].active.core
    world["published"]["body"] = payload(FIRST.replace("password: one", "password: rotated"), THIRD)
    await world["refresher"].refresh_due(world["apply"])
    after = routes()
    assert [r["id"] for r in after] == [r["id"] for r in before]  # third is not added
    assert after[1] == before[1] and after[0]["max_concurrency"] == 1
    assert after[0]["url"] != before[0]["url"] and after[2]["url"] != before[2]["url"]
    assert world["manager"].active.core is core  # Staged in place: unchanged nodes keep connections.
    nodes = core.nodes
    assert nodes[key_of(after[0])]["password"] == "rotated"
    assert nodes[key_of(after[2])]["password"] == "two"  # Dropped by the provider: kept as it was.
    state = world["refresher"].status()["sources"][after[0]["id"][4:20]]
    assert state == {"last_attempt_ms": 1_000_000_000, "last_success_ms": 1_000_000_000,
                     "last_change_ms": 1_000_000_000, "updated": 1, "missing": 1, "error": None}
    assert "private-test-token" not in world["refresher"].path.read_text()


@pytest.mark.anyio
async def test_unchanged_nodes_change_nothing_and_wait_for_the_interval(world):
    before = routes()
    applied = []

    async def apply(replacements):
        applied.append(replacements)
        return True

    await world["refresher"].refresh_due(apply)
    assert applied == [] and routes() == before
    sid = before[0]["id"][4:20]
    assert world["refresher"].status()["sources"][sid]["last_success_ms"] == 1_000_000_000
    world["clock"][0] += 23 * 3600
    await world["refresher"].refresh_due(apply)
    assert world["published"]["calls"] == 1
    world["clock"][0] += 3600
    await world["refresher"].refresh_due(apply)
    assert world["published"]["calls"] == 2


@pytest.mark.anyio
async def test_a_failed_download_keeps_routes_and_retries_within_the_hour(world):
    before = routes()
    world["published"]["body"] = SubscriptionError("Subscription returned HTTP 503")
    await world["refresher"].refresh_due(world["apply"])
    sid = before[0]["id"][4:20]
    assert world["refresher"].status()["sources"][sid]["error"] == "Subscription returned HTTP 503"
    assert routes() == before and world["manager"].active.core.alive
    world["clock"][0] += 1800
    await world["refresher"].refresh_due(world["apply"])
    assert world["published"]["calls"] == 1
    world["clock"][0] += 1800
    world["published"]["body"] = payload(FIRST, SECOND)
    await world["refresher"].refresh_due(world["apply"])
    state = world["refresher"].status()["sources"][sid]
    assert world["published"]["calls"] == 2 and state["error"] is None and state["missing"] == 0


@pytest.mark.anyio
async def test_schedule_off_or_pool_off_never_downloads(world):
    world["refresher"].set_interval(0)
    await world["refresher"].refresh_due(world["apply"])
    assert world["published"]["calls"] == 0
    world["refresher"].set_interval(24)
    assert (await world["cli"].put("", json={"mode": "none"}, follow_redirects=True)).status_code == 200
    await world["refresher"].refresh_due(world["apply"])
    assert world["published"]["calls"] == 0


@pytest.mark.anyio
async def test_routes_the_user_changed_meanwhile_are_left_alone(world):
    before = routes()

    async def user_removes_first():
        response = await world["cli"].put("", json={"mode": "pool", "routes": before[1:]}, follow_redirects=True)
        assert response.status_code == 200

    world["published"]["during"] = user_removes_first
    world["published"]["body"] = payload(FIRST.replace("one", "rotated"), SECOND.replace("two", "rotated"))
    await world["refresher"].refresh_due(world["apply"])
    after = routes()
    assert [r["id"] for r in after] == [before[1]["id"], before[2]["id"]]  # first stays removed
    assert world["manager"].active.core.nodes[key_of(after[1])]["password"] == "rotated"


@pytest.mark.anyio
async def test_unreadable_snapshots_are_skipped_but_keep_their_history(world, monkeypatch):
    rows = routes()
    broken = dict(rows[0], url="mihomo://" + "0" * 64 + "/" + key_of(rows[0]))
    sources = saved_sources([broken, *rows], world["store"])
    assert list(sources) == [SOURCE] and len(sources[SOURCE].nodes) == 2
    await world["refresher"].refresh_due(world["apply"])
    sid = rows[0]["id"][4:20]
    gone = "f" * 16
    world["refresher"]._write({"interval_hours": 24, "sources": {**world["refresher"].status()["sources"], gone: {"last_attempt_ms": 1}}})

    def locked(revision):
        raise SubscriptionError("Saved subscription unavailable")

    monkeypatch.setattr(world["store"], "read", locked)
    world["clock"][0] += 25 * 3600
    await world["refresher"].refresh_due(world["apply"])
    assert list(world["refresher"].status()["sources"]) == [sid]  # kept: a route still uses it


@pytest.mark.anyio
async def test_schedule_api_is_local_only_and_accepts_listed_intervals(world):
    cli = world["cli"]
    assert (await cli.get("/subscriptions/refresh")).json() == {"interval_hours": 24, "sources": {}}
    assert (await cli.put("/subscriptions/refresh", json={"interval_hours": 6})).json()["interval_hours"] == 6
    assert (await cli.put("/subscriptions/refresh", json={"interval_hours": 5})).status_code == 422
    denied = await cli.get("/subscriptions/refresh", headers={"Origin": "https://untrusted.invalid"})
    assert denied.status_code == 403
    assert world["refresher"].status()["interval_hours"] == 6


@pytest.mark.anyio
async def test_the_loop_checks_again_when_the_schedule_changes(world, monkeypatch):
    checked = asyncio.Event()
    refresher = world["refresher"]

    async def refresh_due(apply):
        checked.set()

    monkeypatch.setattr(refresher, "refresh_due", refresh_due)
    task = asyncio.create_task(refresher.run(world["apply"]))
    try:
        await world["cli"].put("/subscriptions/refresh", json={"interval_hours": 12})
        await asyncio.wait_for(checked.wait(), timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert refresh.CHECK_SECONDS == 600
