from __future__ import annotations

import asyncio

import httpx
import pytest
from app.api.v1.external_providers import router
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
