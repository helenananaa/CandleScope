"""The live host must retain both account products after branch integration."""
import asyncio

import httpx

from app.main import app
from app.plugin_security_v2.management import LocalManagementGuard
from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore
from tests.test_readonly_account_service import fixture_service


def test_live_host_keeps_trading_routes_and_readonly_session_guard(tmp_path, monkeypatch):
    async def run():
        readonly, _, _, _ = fixture_service(tmp_path / "readonly")
        store = TradingStore(tmp_path / "trading.sqlite3")
        trading = TradingAccountService(store, snapshot_dir=tmp_path / "snapshots")
        guard = LocalManagementGuard(["http://127.0.0.1:61234"])
        monkeypatch.setattr(app.state, "readonly_account_service", readonly, raising=False)
        monkeypatch.setattr(app.state, "trading_accounts", trading, raising=False)
        monkeypatch.setattr(app.state, "plugin_platform_v2_management_guard", guard, raising=False)
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 61235))
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
                local = await api.get("/api/v1/trading/accounts")
                assert local.status_code == 200
                assert local.json() == trading.list_accounts()
                assert (await api.get("/api/v1/readonly-accounts/status")).status_code == 403
                observed = await api.get("/api/v1/readonly-accounts/status", headers=guard.trusted_headers())
                assert observed.status_code == 200
                assert observed.json()["historyMonths"] == 3
        finally:
            await readonly.close()
            store.close()

    asyncio.run(run())
