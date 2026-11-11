from __future__ import annotations

import asyncio

import httpx
import pytest
from app.api.v1.external_providers import router
from app.data_engine.data_manager.core import DataManagerCore
from fastapi import FastAPI

from tests.test_external_provider_control import service


@pytest.mark.parametrize("peer,origin,enabled,code", [
    ("192.0.2.9", None, True, "PROVIDER_UNAUTHORIZED_WRITE"),
    ("127.0.0.1", "https://untrusted.invalid", True, "PROVIDER_UNAUTHORIZED_WRITE"),
    ("127.0.0.1", None, False, "FLAG_DISABLED"),
])
def test_peer_origin_and_default_off_fail_before_connection_store_creation(tmp_path, peer, origin, enabled, code):
    owner = service(tmp_path, enabled=enabled)
    app = FastAPI()
    app.include_router(router)
    app.state.backtest_service = owner

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(peer, 12345)), base_url="http://127.0.0.1") as client:
            return await client.get("/provider-connections", headers={"Origin": origin} if origin else {})

    try:
        response = asyncio.run(request())
        assert response.status_code == 400 and response.json()["error"]["code"] == code
        assert not owner.external.directory.exists()
    finally:
        owner.shutdown()


@pytest.mark.parametrize("closed,code", [(False, "FLAG_DISABLED"), (True, "STRATEGY_MANAGER_CLOSED")])
def test_configured_strategy_manager_does_not_fall_back_to_stale_service_alias(tmp_path, closed, code):
    owner = service(tmp_path, enabled=True)
    app = FastAPI()
    app.include_router(router)
    app.state.backtest_service = owner
    app.state.data_manager_core = DataManagerCore()
    if closed:
        app.state.data_manager_core.bind_strategy(owner).close()

    async def request():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            for suffix in ("", "/endpoint", "/example", "/runs/unknown/trace"):
                response = await client.get("/provider-connections" + suffix)
                assert response.status_code == 400 and response.json()["error"]["code"] == code
            for suffix in ("/revoke", "/connect", "/poll", "/reply"):
                response = await client.post("/provider-connections/epc_unused" + suffix, json={})
                assert response.status_code == 400 and response.json()["error"]["code"] == code

    try:
        asyncio.run(request())
        assert not owner.external.directory.exists()
    finally:
        owner.shutdown()
