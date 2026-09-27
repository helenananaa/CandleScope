"""Presentation-only price grouping for order-book snapshots."""

from __future__ import annotations

from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from itertools import islice
from typing import Any, Literal, Mapping, Sequence

from app.data_engine.market_data.order_book_auto import step_scores
from app.exchanges.symbol_catalog import get_cached_symbol_metadata
from app.data_engine.market_data.models import MarketStreamKey
from app.data_engine.market_data.full_order_book import FullOrderBookLevel


PriceGrouping = Literal["auto", "raw", "2", "5", "10", "20", "50", "100", "200", "500", "1000", "2000", "5000", "10000", "20000", "50000", "100000", "200000", "500000", "1000000", "2000000", "5000000", "10000000", "20000000", "50000000", "100000000", "200000000", "500000000", "1000000000"]
FULL_PRICE_GROUPINGS: tuple[PriceGrouping, ...] = ("auto", "raw", "2", "5", "10", "20", "50", "100", "200", "500", "1000", "2000", "5000", "10000", "20000", "50000", "100000", "200000", "500000", "1000000", "2000000", "5000000", "10000000", "20000000", "50000000", "100000000", "200000000", "500000000", "1000000000")
PARTIAL_PRICE_GROUPINGS = FULL_PRICE_GROUPINGS


@dataclass(frozen=True, slots=True)
class OrderBookProjection:
    bids: list[list[float]]
    asks: list[list[float]]
    price_tick_size: float | None
    price_step: float | None
    price_grouping: PriceGrouping
    aggregation_applied: bool
    source_bid_levels: int
    source_ask_levels: int
    bucket_bid_levels: int
    bucket_ask_levels: int
    price_window_bid_truncated: bool
    price_window_ask_truncated: bool
    incomplete_outer_bid_bucket_omitted: bool
    incomplete_outer_ask_bucket_omitted: bool
    incomplete_bid_prices: list[float]
    incomplete_ask_prices: list[float]
    coverage_bid_min: float | None
    coverage_ask_max: float | None


def normalize_price_grouping(
    value: object,
    *,
    allowed: Sequence[PriceGrouping] = FULL_PRICE_GROUPINGS,
) -> PriceGrouping:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        choices = ", ".join(allowed)
        raise ValueError(f"price_grouping must be one of {choices}")
    return normalized  # type: ignore[return-value]


def cached_price_tick_size(key: MarketStreamKey) -> Decimal | None:
    metadata = get_cached_symbol_metadata(key.exchange, key.market_type, key.symbol)
    if not metadata:
        return None
    return _positive_decimal(metadata.get("priceTickSize"))


def project_order_book_levels(
    data: Mapping[str, Any],
    *,
    price_grouping: PriceGrouping,
    price_tick_size: Decimal | None,
    limit: int | None = None,
    max_auto_multiplier: int = 1_000,
    source_levels_canonical: bool = False,
    target_rows: int = 12,
    range_bps: int = 0,
    resolved_step: Decimal | None = None,
) -> OrderBookProjection:
    price_step = resolved_step or _effective_price_step(
        data,
        price_grouping=price_grouping,
        price_tick_size=price_tick_size,
        max_auto_multiplier=max_auto_multiplier,
        target_rows=target_rows,
        range_bps=range_bps,
    )
    aggregation_applied = (
        price_tick_size is not None
        and price_step is not None
        and price_step > price_tick_size
    )
    raw_bids = data.get("bids")
    raw_asks = data.get("asks")
    source_bid_levels = _sequence_length(raw_bids, side="bids")
    source_ask_levels = _sequence_length(raw_asks, side="asks")
    bounded_canonical = (
        source_levels_canonical
        and not aggregation_applied
        and limit is not None
    )
    bids = _level_pairs(
        raw_bids,
        side="bids",
        max_items=limit if bounded_canonical else None,
    )
    asks = _level_pairs(
        raw_asks,
        side="asks",
        max_items=limit if bounded_canonical else None,
    )
    if aggregation_applied:
        bid_buckets = _aggregate_side(bids, price_step, side="bids")
        ask_buckets = _aggregate_side(asks, price_step, side="asks")
    else:
        bid_buckets = bids
        ask_buckets = asks

    all_bid_buckets = bid_buckets
    all_ask_buckets = ask_buckets
    bid_buckets = _price_window(all_bid_buckets, range_bps, side="bids")
    ask_buckets = _price_window(all_ask_buckets, range_bps, side="asks")
    if bounded_canonical:
        price_window_bid_truncated = len(bid_buckets) < source_bid_levels
        price_window_ask_truncated = len(ask_buckets) < source_ask_levels
    else:
        price_window_bid_truncated = len(bid_buckets) < len(all_bid_buckets)
        price_window_ask_truncated = len(ask_buckets) < len(all_ask_buckets)

    # Keep partial buckets visible: omitting the sole bucket of a wide grouping
    # would hide all known liquidity. Boundary provenance determines completeness.
    visible_bids = bid_buckets if limit is None else bid_buckets[:limit]
    visible_asks = ask_buckets if limit is None else ask_buckets[:limit]
    bid_boundary = _positive_decimal(data.get("coverage_bid_min"))
    ask_boundary = _positive_decimal(data.get("coverage_ask_max"))
    # A caller may project only part of a previously exhaustive/covered book.
    bid_cut = isinstance(data.get("book_bid_levels"), int) and data["book_bid_levels"] > source_bid_levels
    ask_cut = isinstance(data.get("book_ask_levels"), int) and data["book_ask_levels"] > source_ask_levels
    exhaustive = data.get("exchange_full_depth_exhaustive") is True
    if bid_cut and bids:
        bid_boundary = max(bid_boundary, bids[-1][0]) if bid_boundary is not None else (bids[-1][0] if exhaustive else None)
    if ask_cut and asks:
        ask_boundary = min(ask_boundary, asks[-1][0]) if ask_boundary is not None else (asks[-1][0] if exhaustive else None)
    incomplete_bids = [float(price) for price, _ in visible_bids if aggregation_applied
                       and not (exhaustive and not bid_cut) and (bid_boundary is None or price <= bid_boundary)]
    incomplete_asks = [float(price) for price, _ in visible_asks if aggregation_applied
                       and not (exhaustive and not ask_cut) and (ask_boundary is None or price >= ask_boundary)]
    return OrderBookProjection(
        bids=_float_levels(visible_bids),
        asks=_float_levels(visible_asks),
        price_tick_size=float(price_tick_size) if price_tick_size is not None else None,
        price_step=float(price_step) if price_step is not None else None,
        price_grouping=price_grouping,
        aggregation_applied=aggregation_applied,
        source_bid_levels=source_bid_levels,
        source_ask_levels=source_ask_levels,
        bucket_bid_levels=(
            source_bid_levels if bounded_canonical else len(all_bid_buckets)
        ),
        bucket_ask_levels=(
            source_ask_levels if bounded_canonical else len(all_ask_buckets)
        ),
        price_window_bid_truncated=price_window_bid_truncated,
        price_window_ask_truncated=price_window_ask_truncated,
        incomplete_outer_bid_bucket_omitted=False,
        incomplete_outer_ask_bucket_omitted=False,
        incomplete_bid_prices=incomplete_bids,
        incomplete_ask_prices=incomplete_asks,
        coverage_bid_min=float(bid_boundary) if bid_boundary is not None else None,
        coverage_ask_max=float(ask_boundary) if ask_boundary is not None else None,
    )


def _effective_price_step(
    data: Mapping[str, Any],
    *,
    price_grouping: PriceGrouping,
    price_tick_size: Decimal | None,
    max_auto_multiplier: int,
    target_rows: int = 12,
    range_bps: int = 0,
) -> Decimal | None:
    if price_tick_size is None:
        return None
    if price_grouping == "raw":
        return price_tick_size
    if price_grouping != "auto":
        return price_tick_size * Decimal(int(price_grouping))

    scores = step_scores(data, price_tick_size, target_rows, range_bps, max_auto_multiplier)
    return min(scores, key=lambda step: (scores[step], step))


def _sequence_length(value: object, *, side: str) -> int:
    if not isinstance(value, SequenceABC) or isinstance(value, (str, bytes)):
        raise TypeError(f"order-book {side} must be a sequence")
    return len(value)


def _level_pairs(
    value: object,
    *,
    side: str,
    max_items: int | None = None,
) -> list[tuple[Decimal, Decimal]]:
    length = _sequence_length(value, side=side)
    parsed: list[tuple[Decimal, Decimal]] = []
    assert isinstance(value, SequenceABC)
    bounded_length = length if max_items is None else min(length, max_items)
    for index, raw in enumerate(islice(value, bounded_length)):
        if type(raw) is FullOrderBookLevel:
            # Constructor-validated and immutable; shared revisions keep the
            # same objects, so do not stringify/reparse unchanged levels.
            parsed.append(raw.decimal_pair())
            continue
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            raw_price, raw_quantity = raw
        elif hasattr(raw, "price") and hasattr(raw, "quantity"):
            raw_price = getattr(raw, "price")
            raw_quantity = getattr(raw, "quantity")
        else:
            raise TypeError(
                f"order-book {side}[{index}] must be a price/quantity pair",
            )
        price = _positive_decimal(raw_price)
        quantity = _positive_decimal(raw_quantity)
        if price is None or quantity is None:
            raise ValueError(f"order-book {side}[{index}] must contain positive values")
        parsed.append((price, quantity))
    if len(parsed) != bounded_length:
        raise ValueError(f"order-book {side} ended before its declared length")
    return parsed


def _aggregate_side(
    levels: Sequence[tuple[Decimal, Decimal]],
    price_step: Decimal,
    *,
    side: Literal["bids", "asks"],
) -> list[tuple[Decimal, Decimal]]:
    rounding = ROUND_FLOOR if side == "bids" else ROUND_CEILING
    buckets: dict[Decimal, Decimal] = {}
    zero = Decimal(0)
    for price, quantity in levels:
        bucket = (price / price_step).to_integral_value(rounding=rounding) * price_step
        buckets[bucket] = buckets.get(bucket, zero) + quantity
    return sorted(buckets.items(), key=lambda item: item[0], reverse=side == "bids")


def _price_window(
    levels: Sequence[tuple[Decimal, Decimal]],
    range_bps: int,
    *,
    side: Literal["bids", "asks"],
) -> list[tuple[Decimal, Decimal]]:
    if not range_bps or not levels:
        return list(levels)
    near_price = levels[0][0]
    max_distance = near_price * Decimal(range_bps) / 10000
    if side == "bids":
        boundary = near_price - max_distance
        return [level for level in levels if level[0] >= boundary]
    boundary = near_price + max_distance
    return [level for level in levels if level[0] <= boundary]


def _float_levels(levels: Sequence[tuple[Decimal, Decimal]]) -> list[list[float]]:
    return [[float(price), float(quantity)] for price, quantity in levels]


def _positive_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


__all__ = [
    "FULL_PRICE_GROUPINGS",
    "PARTIAL_PRICE_GROUPINGS",
    "OrderBookProjection",
    "PriceGrouping",
    "cached_price_tick_size",
    "normalize_price_grouping",
    "project_order_book_levels",
]
