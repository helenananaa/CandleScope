from __future__ import annotations

import inspect
import sys
import time
from collections.abc import Callable, Mapping
from typing import Any

import aiohttp
import ccxt
from ccxt.pro.binanceusdm import binanceusdm as CcxtBinanceUSDM

from app.exchanges.rate_limits import (
    RateLimitManager,
    RateLimitPolicy,
)

from .models import CcxtLifecycleEvent, CcxtRawMarketEvent
from .tls import SharedSslContextMixin
from .admission import PublicCcxtAdmissionMixin

SUPPORTED_CCXT_VERSION = "4.5.60"

RawEventSink = Callable[[CcxtRawMarketEvent], None]
LifecycleSink = Callable[[CcxtLifecycleEvent], None]

class CcxtCompatibilityError(RuntimeError):
    """Raised when the installed CCXT build is outside the tested contract."""


class CandleScopeBinanceUSDM(PublicCcxtAdmissionMixin, SharedSslContextMixin, CcxtBinanceUSDM):
    """CCXT Binance USD-M extension that preserves CandleScope quality seams.

    This class deliberately does not replace CandleScope normalization,
    continuity, reconnect supervision, or full-order-book reconstruction.
    It exposes raw websocket payloads before CCXT projects them into unified
    structures and admits REST calls through the shared CandleScope IP budget.
    """

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        raw_event_sink: RawEventSink | None = None,
        lifecycle_sink: LifecycleSink | None = None,
        rate_limit_manager: RateLimitManager | None = None,
        rate_limit_policy: RateLimitPolicy | None = None,
        enforce_version: bool = True,
    ) -> None:
        if enforce_version and ccxt.__version__ != SUPPORTED_CCXT_VERSION:
            raise CcxtCompatibilityError(
                "CandleScope CCXT extension was tested with "
                f"ccxt=={SUPPORTED_CCXT_VERSION}, found {ccxt.__version__}",
            )
        super().__init__(dict(config or {}))
        self._candlescope_raw_event_sink = raw_event_sink
        self._candlescope_lifecycle_sink = lifecycle_sink
        self._candlescope_closing = False
        self._candlescope_rate_limit_manager = rate_limit_manager
        if rate_limit_policy is None:
            from app.exchanges.plugins.binance.plugin import BinancePlugin

            rate_limit_policy = BinancePlugin._rate_limit_policy()
        self._candlescope_rate_limit_policy = rate_limit_policy

    def open(self) -> None:
        """Open CCXT with the reliable Windows threaded DNS resolver.

        CCXT 4.5.60 installs ``aiodns``.  On the CandleScope Windows host its
        automatic resolver cannot reach the configured DNS servers, while the
        operating-system resolver succeeds.  Keep this workaround local to the
        pinned extension instead of mutating aiohttp's process-wide default.
        """

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
        """Close both CCXT Pro websocket clients and its owned REST session."""

        self._candlescope_closing = True
        try:
            await super().close(clean_instance_data)
        finally:
            self._candlescope_closing = False

    def set_raw_event_sink(self, sink: RawEventSink | None) -> None:
        self._candlescope_raw_event_sink = sink

    def set_lifecycle_sink(self, sink: LifecycleSink | None) -> None:
        self._candlescope_lifecycle_sink = sink

    def handle_ohlcv(self, client: Any, message: Any) -> Any:
        self._emit_raw("kline", message)
        return super().handle_ohlcv(client, message)

    def handle_trade(self, client: Any, message: Any) -> Any:
        channel = (
            str(message.get("e") or "trade") if isinstance(message, dict) else "trade"
        )
        self._emit_raw(channel, message)
        return super().handle_trade(client, message)

    def handle_order_book(self, client: Any, message: Any) -> Any:
        self._emit_raw("depth", message)
        return super().handle_order_book(client, message)

    def handle_mark_prices(self, client: Any, message: Any) -> Any:
        values = message if isinstance(message, list) else [message]
        for value in values:
            self._emit_raw("markPriceUpdate", value)
        return super().handle_mark_prices(client, message)

    def handle_liquidation(self, client: Any, message: Any) -> Any:
        self._emit_raw("forceOrder", message)
        return super().handle_liquidation(client, message)

    def on_connected(self, client: Any, message: Any = None) -> Any:
        self._emit_lifecycle("connected", client)
        return super().on_connected(client, message)

    def on_error(self, client: Any, error: BaseException) -> Any:
        self._emit_lifecycle("error", client, error)
        return super().on_error(client, error)

    def on_close(self, client: Any, error: BaseException | None) -> Any:
        if self._candlescope_closing:
            self._emit_lifecycle("closed", client)
        else:
            self._emit_lifecycle("disconnected", client, error)
        return super().on_close(client, error)

    def _emit_raw(self, channel: str, message: Any) -> None:
        sink = self._candlescope_raw_event_sink
        if sink is None or not isinstance(message, dict):
            return
        nested_kline = message.get("k") if isinstance(message.get("k"), dict) else {}
        symbol = message.get("s") or message.get("ps") or nested_kline.get("s")
        result = sink(
            CcxtRawMarketEvent(
                channel=channel,
                symbol=str(symbol) if symbol is not None else None,
                payload=dict(message),
                received_at_ms=int(time.time() * 1000),
            )
        )
        _require_synchronous_sink(result, "raw_event_sink")

    def _emit_lifecycle(
        self,
        state: str,
        client: Any,
        error: BaseException | None = None,
    ) -> None:
        sink = self._candlescope_lifecycle_sink
        if sink is None:
            return
        url = getattr(client, "url", None)
        result = sink(
            CcxtLifecycleEvent(
                state=state,
                url=str(url) if url is not None else None,
                observed_at_ms=int(time.time() * 1000),
                error=str(error) if error is not None else None,
            )
        )
        _require_synchronous_sink(result, "lifecycle_sink")


def _require_synchronous_sink(result: Any, name: str) -> None:
    if not inspect.isawaitable(result):
        return
    close = getattr(result, "close", None)
    if callable(close):
        close()
    raise TypeError(f"{name} must be synchronous and non-blocking")
