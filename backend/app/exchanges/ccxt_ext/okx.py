"""Raw-observable pinned CCXT Pro OKX clients."""

from __future__ import annotations

import sys
from typing import Any

import aiohttp
from ccxt.pro.okx import okx as CcxtOkx

from .binance_usdm import SUPPORTED_CCXT_VERSION
from .hooks import build_hooked_exchange_class
from .tls import SharedSslContextMixin
from .admission import PublicCcxtAdmissionMixin
from app.exchanges.okx_intervals import OKX_UTC_INTERVALS, okx_utc_interval

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


class _OwnedOkxSession(PublicCcxtAdmissionMixin, SharedSslContextMixin):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # CCXT Pro uses this same table for subscribe, unsubscribe, reverse
        # lookup and its OHLCV cache. Do not only override the outgoing channel.
        self.timeframes = {**self.timeframes, **OKX_UTC_INTERVALS}

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1m", since: int | None = None,
        limit: int | None = None, params: dict | None = None,
    ) -> Any:
        # Pinned CCXT REST adds "utc" to its timeframe value. Supply the final
        # protocol parameter explicitly so the UTC table cannot yield "utcutc".
        values = {**(params or {}), "bar": okx_utc_interval(timeframe)}
        return await super().fetch_ohlcv(symbol, timeframe, since, limit, values)

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
