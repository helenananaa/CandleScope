"""Raw-observable pinned CCXT Pro OKX clients."""

from __future__ import annotations

import sys

import aiohttp
from ccxt.pro.okx import okx as CcxtOkx

from .binance_usdm import SUPPORTED_CCXT_VERSION
from .hooks import build_hooked_exchange_class
from .tls import SharedSslContextMixin

_HookedOkx = build_hooked_exchange_class(
    CcxtOkx,
    exchange_id="okx",
    market_type="futures",
    supported_ccxt_version=SUPPORTED_CCXT_VERSION,
)
_HookedOkxSpot = build_hooked_exchange_class(
    CcxtOkx,
    exchange_id="okx",
    market_type="spot",
    supported_ccxt_version=SUPPORTED_CCXT_VERSION,
)


class OkxWebSocketProtocolMixin:
    def describe(self):
        description = super().describe()
        # OKX retires public-internet port 8443 on 2026-10-31. Keep the
        # upstream host/path and migrate both production and demo defaults.
        for environment in ("api", "test"):
            websocket = description["urls"][environment].get("ws")
            if isinstance(websocket, str):
                description["urls"][environment]["ws"] = websocket.replace(":8443/", "/")
        return description

    def handle_error_message(self, client, message):
        # The retirement notice leaves the socket open. Pinned CCXT treats
        # every nonzero code as an error and otherwise rejects all watches.
        if isinstance(message, dict) and message.get("event") == "notice" and str(message.get("code")) == "64010":
            return False
        return super().handle_error_message(client, message)


class _OwnedOkxSession(OkxWebSocketProtocolMixin, SharedSslContextMixin):
    def open(self) -> None:
        if sys.platform != "win32" or self.session is not None or not self.own_session:
            super().open()
            return

        self.own_session = False
        try:
            super().open()
        finally:
            self.own_session = True
        self.tcp_connector = aiohttp.TCPConnector(
            ssl=self.ssl_context,
            loop=self.asyncio_loop,
            resolver=aiohttp.ThreadedResolver(loop=self.asyncio_loop),
        )
        self.session = aiohttp.ClientSession(
            loop=self.asyncio_loop,
            connector=self.tcp_connector,
            trust_env=self.aiohttp_trust_env,
        )

    async def close(self, clean_instance_data: bool = True) -> None:
        await super().close(clean_instance_data)


class CandleScopeOkx(_OwnedOkxSession, _HookedOkx):  # type: ignore[misc, valid-type]
    """OKX Swap client used by production raw profiles and qualification."""


class CandleScopeOkxSpot(  # type: ignore[misc, valid-type]
    _OwnedOkxSession,
    _HookedOkxSpot,
):
    """OKX Spot client used by production raw profiles and qualification."""
