"""Admitted trade-to-candle sources; recent-trades support alone is insufficient.

Each profile must provide a complete, paginated time range before its output
may become final history. These capabilities are separate from native OHLCV.
"""
from __future__ import annotations

from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec


def supports_trade_candles(exchange: str, market_type: str) -> bool:
    return exchange == "kraken" and market_type == "spot"


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
