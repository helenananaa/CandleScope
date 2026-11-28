"""Trusted-local import and refresh. Only opaque references leave the backend."""
import asyncio
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from app.core.config import load_proxy_settings
from app.core.proxy_pool import normalize_proxy_pool
from app.research_data.access import require_local_research_access
from .refresh import refresher
from .runtime import managed
from .source import SubscriptionError, download, source_id
from .store import REFERENCE

router = APIRouter(prefix="/proxy/subscriptions", dependencies=[Depends(require_local_research_access)])
_import_lock = asyncio.Lock()
_previews = {}


class Source(BaseModel):
    url: SecretStr | None = None
    saved_route_id: str | None = None


class RefreshSchedule(BaseModel):
    interval_hours: Literal[0, 6, 12, 24]


class Selection(BaseModel):
    preview: str = Field(max_length=80)
    nodes: list[str] = Field(min_length=1, max_length=16)


def _expire():
    now = time.monotonic()
    for token, (expiry, _, _) in list(_previews.items()):
        if now >= expiry:
            del _previews[token]


def _saved_url(route_id):
    for route in load_proxy_settings().get("routes", []):
        match = REFERENCE.fullmatch(route["url"])
        if route["id"] == route_id and match:
            return managed.store.read(match[1])["url"]
    raise SubscriptionError("Saved subscription route not found")


@router.post("/preview")
async def preview(body: Source):
    async with _import_lock:
        try:
            if bool(body.url) == bool(body.saved_route_id):
                raise SubscriptionError("Provide a subscription URL or a saved route")
            url = body.url.get_secret_value() if body.url else await asyncio.to_thread(_saved_url, body.saved_route_id)
            if len(url) > 8192:
                raise SubscriptionError("Subscription URL is too long")
            nodes, skipped = await download(url)
        except SubscriptionError as exc:
            raise HTTPException(400, str(exc)) from None
        _expire()
        if len(_previews) >= 4:
            del _previews[next(iter(_previews))]
        token = secrets.token_urlsafe(24)
        _previews[token] = (time.monotonic() + 300, url, nodes)
        asyncio.get_running_loop().call_later(300, _previews.pop, token, None)
        return {"preview": token, "source": source_id(url), "skipped": skipped, "nodes": [
            {"id": k, "name": n["name"], "protocol": n["type"]} for k, n in nodes.items()
        ]}


@router.post("/routes")
async def prepare_routes(body: Selection):
    async with _import_lock:
        _expire()
        item = _previews.get(body.preview)
        if not item:
            raise HTTPException(409, "Subscription preview expired")
        _, url, nodes = item
        if len(set(body.nodes)) != len(body.nodes) or not set(body.nodes) <= nodes.keys():
            raise HTTPException(400, "Invalid node selection")
        try:
            routes = await asyncio.to_thread(managed.store.save, url, {k: nodes[k] for k in body.nodes})
            return {"routes": normalize_proxy_pool(routes)[0]}
        except SubscriptionError as exc:
            raise HTTPException(400, str(exc)) from None


@router.get("/refresh")
async def refresh_status():
    """The automatic refresh interval and the last result per subscription (by source id)."""
    return await asyncio.to_thread(refresher.status)


@router.put("/refresh")
async def set_refresh_schedule(body: RefreshSchedule):
    data = await asyncio.to_thread(refresher.set_interval, body.interval_hours)
    refresher.wake.set()  # Re-check now; the event belongs to the event loop, not the worker thread.
    return data
