import asyncio
import shutil
import ssl
import sys

import aiohttp
import certifi
import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.exchanges.ccxt_ext import tls
from app.exchanges.ccxt_ext.binance_spot import CandleScopeBinanceSpot
from app.exchanges.ccxt_ext.binance_usdm import CandleScopeBinanceUSDM
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.generic import _create_exchange
from app.exchanges.ccxt_ext.okx import CandleScopeOkx, CandleScopeOkxSpot
from app.exchanges.ccxt_ext.runtime import close_ccxt_exchange


@pytest.fixture
def context_builds(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    monkeypatch.setattr(tls, "_contexts", {})
    builds: list[str | None] = []
    create_default_context = ssl.create_default_context

    def counting(*, cafile=None):
        builds.append(cafile)
        return create_default_context(cafile=cafile)

    monkeypatch.setattr(tls.ssl, "create_default_context", counting)
    return builds


def _generic(exchange_id: str, market_type: str, *, websocket: bool = False):
    return _create_exchange(
        get_ccxt_catalog_entry(exchange_id),
        IngestionConfig(proxy_mode="none"),
        market_type=market_type,
        websocket=websocket,
    )


def test_every_ccxt_client_opens_with_one_shared_verifying_context(context_builds):
    async def run() -> None:
        clients = [
            _generic("binance", "spot"),
            _generic("okx", "swap.linear"),
            _generic("binance", "spot", websocket=True),
            CandleScopeBinanceSpot({}),
            CandleScopeBinanceUSDM({}),
            CandleScopeOkx({}),
            CandleScopeOkxSpot({}),
        ]
        try:
            for exchange in clients:
                exchange.open()
            context = clients[0].ssl_context
            assert isinstance(context, ssl.SSLContext)
            assert context.verify_mode == ssl.CERT_REQUIRED
            assert context.check_hostname is True
            for exchange in clients:
                assert exchange.ssl_context is context
                assert exchange.tcp_connector._ssl is context
                if sys.platform == "win32":
                    assert isinstance(exchange.tcp_connector._resolver, aiohttp.ThreadedResolver)
        finally:
            for exchange in clients:
                await close_ccxt_exchange(exchange)

    asyncio.run(run())
    assert context_builds == [certifi.where()]


def test_shared_context_honours_ccxt_verify_cafile_and_explicit_context(
    context_builds,
    tmp_path,
):
    cafile = str(tmp_path / "ca.pem")
    shutil.copyfile(certifi.where(), cafile)
    explicit = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    async def run() -> None:
        unverified = _generic("binance", "spot")
        unverified.verify = False
        custom = CandleScopeOkx({"cafile": cafile})
        preset = _generic("okx", "spot")
        preset.ssl_context = explicit
        clients = [unverified, custom, preset]
        try:
            for exchange in clients:
                exchange.open()
            assert unverified.ssl_context is False
            assert unverified.tcp_connector._ssl is False
            assert custom.ssl_context is tls.shared_ssl_context(cafile)
            assert preset.ssl_context is explicit
        finally:
            for exchange in clients:
                await close_ccxt_exchange(exchange)

    asyncio.run(run())
    assert context_builds == [cafile]


def test_warmup_builds_the_default_context_off_thread(context_builds):
    tls.start_shared_ssl_context_warmup().join(timeout=30)

    assert context_builds == [certifi.where()]
    assert tls.shared_ssl_context(certifi.where()) is tls._contexts[(certifi.where(), False)]
    assert context_builds == [certifi.where()]
