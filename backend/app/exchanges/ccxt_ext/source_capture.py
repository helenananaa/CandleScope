"""Public REST evidence before CCXT projection; request-local, never credentials."""

from __future__ import annotations

import copy
import time
from contextvars import ContextVar
from urllib.parse import urlsplit

REST_CAPTURE: ContextVar[list | None] = ContextVar(
    "ccxt_public_rest_capture", default=None
)
RAW_ONLY = "_candlescope_raw_only"


class RestSourceCaptureMixin:
    async def fetch(self, url, method="GET", headers=None, body=None):
        response = await super().fetch(url, method, headers, body)
        sink = REST_CAPTURE.get()
        if sink is not None:
            # Only the public market-data request scope enables this hook.
            # Neither credentials, headers nor signed query strings are stored.
            parsed = urlsplit(url)
            sink.append(
                {
                    "endpoint": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                    "received_at": int(time.time() * 1000),
                    "payload": copy.deepcopy(response),
                }
            )
        return response


def matches_public_frame(event, descriptor):
    if not event.payload.get(RAW_ONLY):
        return False
    symbol = descriptor.symbol.upper()
    if event.symbol != symbol:
        # OKX index tickers use BTC-USDT, while the subscription is BTC-USDT-SWAP.
        if not (
            symbol.endswith("-SWAP")
            and event.symbol == symbol[:-5]
            and event.channel == "index-tickers"
        ):
            return False
    channels = {
        "trade": {"trade", "aggTrade", "trades", "trades-all"},
        "depth": {"depth", "books", "books5", "books-l2-tbt", "books50-l2-tbt"},
        "ticker": {"24hrTicker", "tickers"},
        "mini_ticker": {"24hrTicker", "24hrMiniTicker", "tickers"},
        "mark_price": {
            "markPriceUpdate",
            "mark-price",
            "index-tickers",
            "funding-rate",
        },
        "index_price": {
            "markPriceUpdate",
            "mark-price",
            "index-tickers",
            "funding-rate",
        },
        "funding_rate": {"markPriceUpdate", "funding-rate"},
        "liquidation": {"forceOrder", "liquidation-orders"},
    }
    return event.channel in channels.get(descriptor.stream_type.name.lower(), set())
