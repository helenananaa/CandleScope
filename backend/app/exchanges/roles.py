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

# Captured historical order-book archives; the contract is the archive's
# recorded source.
BOOK_HISTORY = "book.history"
BINANCE_USDM_DIFF_DEPTH_CAPTURE = "BINANCE_USDM_DIFF_DEPTH_CAPTURE"

# Public rule, fee, mark/index and funding history that hedge-mode replay
# simulates against.
HEDGE_PUBLIC_HISTORY = "hedge.public_history"
BINANCE_USDM_HEDGE_PUBLIC_HISTORY = "binance.usdm.hedge-public-history/1"

# Native-interval kline archives that replay charts must use as they are.
HISTORY_NATIVE_ARCHIVE = "history.native_archive"
BINANCE_PUBLIC_KLINE_ARCHIVE = "binance-public-kline-v1"

# History pages from a start time return the earliest rows, so one page from
# time zero finds the first bar (a listing boundary without metadata).
HISTORY_EARLIEST_PAGE = "history.earliest_page"
BINANCE_KLINES_START_TIME_ASCENDING = "binance.klines.start-time-ascending/1"

# Futures contract rules continuous runs simulate: linear contracts quoted in
# base-unit quantity, one unit per contract.
CONTRACT_RULES = "contract_rules"
BINANCE_USDM_LINEAR_BASE_QUANTITY = "BINANCE_USDM_LINEAR_BASE_QUANTITY"

# Funding history between settlements rebuilt from the minute premium index
# with the venue's published funding formula.
FUNDING_HYBRID_HISTORY = "funding.hybrid_history"
BINANCE_PREMIUM_INDEX_CUMAVG = "binance-premium-index-cumavg-v2"

# Settled funding history on a regular settlement schedule, so a bounded page
# can prove which settlements it holds.
FUNDING_SETTLEMENT_HISTORY = "funding.settlement_history"
BINANCE_USDM_REGULAR_SETTLEMENT = "binance-usdm-regular-settlement-v1"

# Open-interest history on a fixed sample grid, so a bounded page can prove
# which samples are missing.
OPEN_INTEREST_NATIVE_GRID = "open_interest.native_grid"
BINANCE_OI_GRID = "binance-oi-grid-v2"
GATE_OI_GRID = "gate-oi-grid-v1"

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


def venue_market_calendar_id(
    exchange: str,
    market_type: str,
    *,
    registry: Any | None = None,
) -> str | None:
    """The calendar the venue declares for this market, or None."""

    capabilities = _venue_capabilities(str(exchange or "").strip().lower(), registry)
    market = str(market_type or "").strip().lower()
    return next((getattr(item, "calendar_id", None)
                 for item in (getattr(capabilities, "markets", ()) or ())
                 if getattr(item, "market_type", None) == market), None)


def venue_symbol_normalizer(exchange: str, *, registry: Any | None = None) -> Any:
    """The venue's symbol normalizer (naming, not a feature switch)."""

    from .plugin import DefaultSymbolNormalizer
    from .registry import get_exchange_registry

    venue = str(exchange or "").strip().lower()
    registry = get_exchange_registry() if registry is None else registry
    try:
        return registry.get_plugin(venue).symbol_normalizer()
    except KeyError:
        if venue == "binance":
            from .plugins.binance.symbols import BinanceSymbolNormalizer

            return BinanceSymbolNormalizer()
        return DefaultSymbolNormalizer()


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
    "BINANCE_KLINES_START_TIME_ASCENDING",
    "BINANCE_OI_GRID",
    "BINANCE_PREMIUM_INDEX_CUMAVG",
    "BINANCE_PUBLIC_KLINE_ARCHIVE",
    "BINANCE_USDM_AGG_TRADES_ARCHIVE",
    "BINANCE_USDM_DIFF_DEPTH_CAPTURE",
    "BINANCE_USDM_HEDGE_PUBLIC_HISTORY",
    "BINANCE_USDM_LINEAR_BASE_QUANTITY",
    "BINANCE_USDM_REGULAR_SETTLEMENT",
    "BOOK_HISTORY",
    "CONTRACT_RULES",
    "FUNDING_HYBRID_HISTORY",
    "FUNDING_SETTLEMENT_HISTORY",
    "GATE_OI_GRID",
    "HEDGE_PUBLIC_HISTORY",
    "HISTORY_EARLIEST_PAGE",
    "HISTORY_NATIVE_ARCHIVE",
    "OPEN_INTEREST_NATIVE_GRID",
    "TRADES_HISTORY_ARCHIVE",
    "venue_market_calendar_id",
    "venue_role",
    "venue_role_contract",
    "venue_symbol_normalizer",
]
