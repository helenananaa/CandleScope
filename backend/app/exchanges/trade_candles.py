"""Explicitly admitted public trade history contracts (not CCXT fetchTrades flags)."""
from __future__ import annotations

from dataclasses import dataclass

from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec

DAY_MS = 86_400_000


@dataclass(frozen=True, slots=True)
class TradeCandleProfile:
    markets: tuple[str, ...]
    retention_ms: int | None = None


# Market selections match the pinned CCXT catalog. Generic aliases are accepted
# only when that venue actually has the corresponding contract family.
TRADE_CANDLE_PROFILES = {
    "kraken": TradeCandleProfile(("spot",)),
    "bitfinex": TradeCandleProfile(("spot", "swap", "swap.linear")),
    "bitvavo": TradeCandleProfile(("spot",)),
    "cryptocom": TradeCandleProfile(("spot",), DAY_MS),
    "coinbaseexchange": TradeCandleProfile(("spot",)),
    "bitget": TradeCandleProfile(("spot", "swap", "swap.linear", "swap.inverse", "future", "future.linear", "future.inverse"), 90 * DAY_MS),
    "binanceusdm": TradeCandleProfile(("swap", "swap.linear", "future", "future.linear"), 2 * DAY_MS),
    "binancecoinm": TradeCandleProfile(("swap", "swap.inverse", "future", "future.inverse"), 2 * DAY_MS),
    # Current API only: older windows can silently return empty. Admit the
    # verified recent day; the separate delayed historical archive is not used.
    "deribit": TradeCandleProfile(("swap", "swap.linear", "swap.inverse", "future", "future.linear", "future.inverse"), DAY_MS),
    "krakenfutures": TradeCandleProfile(("swap", "swap.linear", "swap.inverse", "future", "future.linear", "future.inverse")),
}


def trade_candle_profile(exchange: str, market_type: str) -> TradeCandleProfile | None:
    profile = TRADE_CANDLE_PROFILES.get(exchange)
    return profile if profile is not None and market_type in profile.markets else None


def supports_trade_candles(exchange: str, market_type: str) -> bool:
    return trade_candle_profile(exchange, market_type) is not None


def uses_trade_candles(exchange: str, market_type: str, interval: str) -> bool:
    if not supports_trade_candles(exchange, market_type) or not parse_interval_spec(interval):
        return False
    from app.data_engine.interval_resolution import IntervalResolver, IntervalRouteKind
    return IntervalResolver().resolve(
        exchange=exchange, market_type=market_type, interval=interval, purpose="history",
    ).kind is IntervalRouteKind.TRADE


def fixed_trade_spec(interval: str):
    spec = parse_interval_spec(interval)
    if spec is None or spec.alignment is not IntervalAlignment.FIXED_EPOCH:
        raise ValueError("Trade candles require a fixed, whole-second interval")
    return spec
