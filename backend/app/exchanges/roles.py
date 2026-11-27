"""Named data roles a venue declares instead of consumers naming venues.

ADR-DATA-002 §5 / D3: a feature that needs more than the channel matrix asks
whether the series' venue declares a role for its market, and which contract
supplies it. It never compares the exchange id.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from .models import CapabilityRole

# Verified daily aggregate-trade archives with published checksums.
TRADES_HISTORY_ARCHIVE = "trades.history.archive"

# The one implementation of TRADES_HISTORY_ARCHIVE: data.binance.vision USD-M
# daily aggTrades zips with CHECKSUM files.
BINANCE_USDM_AGG_TRADES_ARCHIVE = "binance.public-data.um-agg-trades.daily/1"

_BUILTIN_VENUES = ("binance", "okx")


def venue_role(
    exchange: str,
    market_type: str,
    role: str,
    *,
    registry: Any | None = None,
) -> CapabilityRole | None:
    """The role the venue declares for this market, or None."""

    capabilities = _venue_capabilities(str(exchange or "").strip().lower(), registry)
    lookup = getattr(capabilities, "role", None)
    return lookup(role, market_type) if callable(lookup) else None


def venue_role_contract(
    exchange: str,
    market_type: str,
    role: str,
    *,
    registry: Any | None = None,
) -> str | None:
    found = venue_role(exchange, market_type, role, registry=registry)
    return found.contract if found is not None else None


def _venue_capabilities(exchange: str, registry: Any | None) -> Any | None:
    from .registry import get_exchange_registry, read_capabilities

    registry = get_exchange_registry() if registry is None else registry
    try:
        return read_capabilities(registry, exchange)
    except KeyError:
        # The application bootstraps every adapter at startup. Command-line
        # tools and tests may not, and bootstrapping CCXT costs seconds, so the
        # built-in venues answer from their static capability documents.
        return _builtin_capabilities(exchange)


@lru_cache(maxsize=len(_BUILTIN_VENUES))
def _builtin_capabilities(exchange: str) -> Any | None:
    if exchange == "binance":
        from .plugins.binance.adapter import BinanceExchangeAdapter

        return BinanceExchangeAdapter.capabilities(object.__new__(BinanceExchangeAdapter))
    if exchange == "okx":
        from .plugins.okx.adapter import OkxExchangeAdapter

        return OkxExchangeAdapter.capabilities(object.__new__(OkxExchangeAdapter))
    return None


__all__ = [
    "BINANCE_USDM_AGG_TRADES_ARCHIVE",
    "TRADES_HISTORY_ARCHIVE",
    "venue_role",
    "venue_role_contract",
]
