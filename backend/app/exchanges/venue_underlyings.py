"""What a crypto-venue contract tracks, when it tracks a traditional market.

Binance USD-M lists ``TRADIFI_PERPETUAL`` contracts (gold, crude oil, US/HK/KR
stocks, ...). They trade around the clock on the same endpoints, streams and
archives as crypto perpetuals, so they stay ordinary crypto-venue series
(ADR-DATA-002 Q1). Their ``underlyingType`` only says what the contract
tracks, which the symbol search uses for grouping and the "contract price"
label. Both the native catalog and the CCXT catalog classify through here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger("candlescope.exchange.underlyings")

BINANCE_TRADFI_CONTRACT_TYPE = "TRADIFI_PERPETUAL"

# CCXT lists the same USD-M contracts under both "binance" and "binanceusdm".
_BINANCE_USDM_SOURCES = frozenset({"binance", "binanceusdm"})

_BINANCE_TRADFI_UNDERLYINGS: dict[str, tuple[str, str]] = {
    "EQUITY": ("stock", "us"),
    "HK_EQUITY": ("stock", "hk"),
    "KR_EQUITY": ("stock", "kr"),
    "CN_EQUITY": ("stock", "cn"),
    # Pre-IPO company contracts: no listed share or region to point at.
    "PREMARKET": ("stock", ""),
    "COMMODITY": ("commodity", ""),
    "FX": ("forex", ""),
}

# Commodity contracts use exchange codes as base assets; a name makes "gold" or
# "crude" findable. Stocks already use their ticker.
_COMMODITY_NAMES = {
    "XAU": "Gold",
    "XAG": "Silver",
    "XPT": "Platinum",
    "XPD": "Palladium",
    "COPPER": "Copper",
    "CL": "WTI Crude Oil",
    "BZ": "Brent Crude Oil",
    "NATGAS": "Natural Gas",
}


def binance_futures_underlying(info: Mapping[str, Any]) -> dict[str, str] | None:
    """SymbolInfo fields for one Binance USD-M ``exchangeInfo`` row.

    Returns ``{}`` for a crypto contract, the underlying fields for a known
    TradFi contract, and ``None`` for a TradFi contract whose underlyingType is
    unknown: such a row is left out rather than shown as crypto.
    """
    if info.get("contractType") != BINANCE_TRADFI_CONTRACT_TYPE:
        return {}
    underlying = _BINANCE_TRADFI_UNDERLYINGS.get(
        str(info.get("underlyingType") or "").upper()
    )
    if underlying is None:
        return None
    underlying_class, region = underlying
    base = str(info.get("baseAsset") or "").strip().upper()
    fields = {
        "underlying_class": underlying_class,
        "underlying_region": region,
        "underlying_symbol": base,
    }
    if underlying_class == "commodity" and base in _COMMODITY_NAMES:
        fields["display_name"] = _COMMODITY_NAMES[base]
    return fields


def venue_contract_underlying(
    exchange_id: str,
    market_type: str,
    info: Any,
) -> dict[str, str] | None:
    """Underlying fields for a venue's raw market row; see ``binance_futures_underlying``."""
    if (
        exchange_id in _BINANCE_USDM_SOURCES
        and market_type in {"futures", "swap.linear"}
        and isinstance(info, Mapping)
    ):
        return binance_futures_underlying(info)
    return {}


def warn_unknown_underlyings(exchange_id: str, unknown: set[str]) -> None:
    if unknown:
        logger.warning(
            "%s catalog left out TradFi contracts with unknown underlyingType: %s",
            exchange_id,
            ", ".join(sorted(unknown)),
        )


__all__ = [
    "BINANCE_TRADFI_CONTRACT_TYPE",
    "binance_futures_underlying",
    "venue_contract_underlying",
    "warn_unknown_underlyings",
]
