import asyncio
from urllib.parse import parse_qs, urlsplit

from ccxt.pro.okx import okx as CcxtOkx

from app.readonly_accounts.okx import ReadOnlyOkx
from app.readonly_accounts.repository import AccountRepository
from app.readonly_accounts.sync import AccountSynchronizer


def test_authenticated_ccxt_market_bootstrap_uses_only_perpetual_public_metadata(tmp_path, monkeypatch):
    calls = []
    markets = [
        {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "ctType": "linear",
         "baseCcy": "BTC", "quoteCcy": "USDT", "settleCcy": "USDT",
         "ctValCcy": "BTC", "ctVal": "0.01", "lotSz": "0.01", "tickSz": "0.1"},
        {"instType": "SWAP", "instId": "BTC-USD-SWAP", "ctType": "inverse",
         "baseCcy": "BTC", "quoteCcy": "USD", "settleCcy": "BTC",
         "ctValCcy": "USD", "ctVal": "100", "lotSz": "1", "tickSz": "0.1"},
    ]

    async def transport(_client, url, method="GET", headers=None, body=None):
        # Intercept the final transport, retaining the real CCXT bootstrap,
        # signing and read-only guards. No request can reach the network.
        parsed = urlsplit(url)
        assert method == "GET" and body is None
        calls.append(parsed.path)
        if parsed.path == "/api/v5/account/config":
            return {"code": "0", "data": [{"uid": "123", "perm": "read_only", "posMode": "long_short_mode"}]}
        assert parsed.path == "/api/v5/public/instruments"
        assert parse_qs(parsed.query) == {"instType": ["SWAP"]}
        assert not any(key.upper().startswith("OK-ACCESS-") for key in (headers or {}))
        return {"code": "0", "data": markets}

    monkeypatch.setattr(CcxtOkx, "fetch", transport)

    async def run():
        # Nonempty credentials are essential: CCXT skips its private currency
        # request when public-only probes have no key, hiding this regression.
        client = ReadOnlyOkx({"apiKey": "fixture", "secret": "fixture", "password": "fixture"})
        try:
            repository = AccountRepository(tmp_path)
            sync = AccountSynchronizer(repository, client)
            await sync.initialize("123")
            assert set(sync.contracts) == {"BTC-USDT-SWAP", "BTC-USD-SWAP"}
            assert len(repository.snapshots()["contracts"]["data"]) == 2
            await client.load_markets(reload=True)
            assert calls == ["/api/v5/account/config", "/api/v5/public/instruments", "/api/v5/public/instruments"]
        finally:
            await client.close()
    asyncio.run(run())
