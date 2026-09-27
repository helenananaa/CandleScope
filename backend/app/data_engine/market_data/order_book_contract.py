"""Shared snapshot capabilities and projection for HTTP and plugin callers."""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from app.exchanges import bootstrap_default_adapters, get_exchange_registry
from app.exchanges.products import snapshot_order_book_mode, supports_snapshot_order_book
from .models import MarketChannel
from .order_book_projection import project_order_book_levels


PROTOCOL = "orderbook.v1"


ALLOWED_DEPTH_LEVELS = frozenset({5, 10, 20})


ALLOWED_UPDATE_INTERVALS_BY_MARKET = {
    "spot": frozenset({100, 1000}),
    "futures": frozenset({100, 250, 500}),
}


DEFAULT_UPDATE_INTERVAL_MS_BY_MARKET = {"spot": 1000, "futures": 250}


ALLOWED_UPDATE_INTERVALS_MS = frozenset().union(
    *ALLOWED_UPDATE_INTERVALS_BY_MARKET.values(),
    {2000, 3000},
)


def order_book_contract(exchange: str, market_type: str) -> dict[str, Any]:
    """Resolve bounded snapshot controls from the authoritative capability."""

    exchange_name = str(exchange).strip().lower()
    market = str(market_type).strip().lower()
    bootstrap_default_adapters()
    try:
        capabilities = get_exchange_registry().get_plugin(exchange_name).capabilities()
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    if not supports_snapshot_order_book(capabilities, market):
        raise ValueError(
            f"{exchange_name}:{market}:depth does not support the "
            "snapshot order-book product"
        )
    capability = capabilities.channel_capability(MarketChannel.DEPTH, market)
    assert capability is not None
    raw_levels = capability.params.get("depth_levels", ())
    declared_levels = frozenset(
        int(value)
        for value in raw_levels
        if isinstance(value, int) and not isinstance(value, bool)
    )
    levels = declared_levels & ALLOWED_DEPTH_LEVELS
    if not levels:
        levels = ALLOWED_DEPTH_LEVELS
    declared_intervals = frozenset(
        int(value)
        for value in capability.update_intervals_ms
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    )
    if not declared_intervals:
        strict_capability = capabilities.channel_capability(
            MarketChannel.FULL_DEPTH,
            market,
        )
        if strict_capability is not None:
            declared_intervals = frozenset(
                int(value)
                for value in strict_capability.update_intervals_ms
                if isinstance(value, int) and not isinstance(value, bool) and value > 0
            )
    # Unified CCXT books use provider-managed cadence.  1000ms is a stable
    # logical contract value; it is not presented as an exchange sequence or
    # guaranteed upstream sampling interval.
    intervals = declared_intervals or frozenset({1000})
    preferred = DEFAULT_UPDATE_INTERVAL_MS_BY_MARKET.get(market)
    default_interval = preferred if preferred in intervals else min(intervals)
    snapshot_mode = snapshot_order_book_mode(capabilities, market)
    return {
        "depth_levels": levels,
        "update_intervals_ms": intervals,
        "default_update_interval_ms": default_interval,
        "cadence_semantics": (
            "provider_rate_limited"
            if snapshot_mode == "polling_snapshot"
            else ("declared" if declared_intervals else "provider_managed")
        ),
    }


def serialize_record(
    record: Any,
    *,
    price_tick_size: Decimal | None = None,
) -> dict[str, Any]:
    to_dict = getattr(record, "to_dict", None)
    if not callable(to_dict):
        raise TypeError("order-book service returned an unsupported snapshot value")
    payload = dict(to_dict())
    data = payload.get("data")
    if isinstance(data, dict):
        projected = dict(data)
        projection = project_order_book_levels(
            projected,
            price_grouping="raw",
            price_tick_size=price_tick_size,
        )
        projected["bids"] = projection.bids
        projected["asks"] = projection.asks
        projected["price_tick_size"] = projection.price_tick_size
        projected["price_step"] = projection.price_step
        projected["price_grouping"] = "raw"
        projected["aggregation_applied"] = False
        payload["data"] = projected
    return payload
