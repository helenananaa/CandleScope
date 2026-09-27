"""HTTP snapshot surface for Partial Top-N order books."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.data_engine.market_data.order_book_projection import (
    cached_price_tick_size,
)
from app.data_engine.market_data.order_book_contract import (
    PROTOCOL, serialize_record, order_book_contract as resolve_order_book_contract,
)
from app.data_engine.market_data.models import MarketChannel, MarketStreamKey


router = APIRouter(prefix="/order-book", tags=["order-book"])
logger = logging.getLogger("api.order_book")


@router.get("/snapshot")
async def order_book_snapshot(
    request: Request,
    symbol: str = Query("BTCUSDT"),
    exchange: str = Query("binance"),
    market_type: str = Query("futures"),
    depth_levels: int = Query(default=20),
    update_interval_ms: int | None = Query(default=None),
    wait_ms: int = Query(default=5_000, ge=100, le=10_000),
) -> dict[str, Any]:
    """Return a fresh replaceable partial-book snapshot.

    A short-lived logical lease is used so the endpoint also works when no
    browser currently owns the physical stream.  It is always released after
    the first snapshot arrives (or the bounded wait expires).
    """

    dm = _data_manager(request)
    key = _key(
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        depth_levels=depth_levels,
        update_interval_ms=update_interval_ms,
    )
    consumer_id = f"http:order-book:{id(request)}"
    leased = False
    try:
        await dm.ensure_order_book_stream(key, consumer_id=consumer_id)
        leased = True
        record = await dm.wait_for_order_book_snapshot(
            key,
            timeout_seconds=wait_ms / 1000,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="order-book snapshot did not arrive before the bounded wait expired",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning("Order-book snapshot is unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="order-book snapshot is temporarily unavailable",
        ) from exc
    except Exception as exc:
        logger.warning("Order-book snapshot failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="order-book upstream is temporarily unavailable",
        ) from exc
    finally:
        if leased:
            with suppress(Exception):
                released = await dm.release_order_book_stream(
                    key,
                    consumer_id=consumer_id,
                )
                if not released:
                    logger.warning("Order-book HTTP lease could not be fully released")

    return {
        "type": "order_book.snapshot",
        "protocol": PROTOCOL,
        "delivery": "latest_snapshot",
        "full_depth": False,
        "backfillable": False,
        "persisted": False,
        "data": serialize_record(record, price_tick_size=cached_price_tick_size(key)),
    }


def _data_manager(request: Request) -> Any:
    dm = getattr(request.app.state, "data_manager", None)
    if dm is None:
        raise HTTPException(status_code=503, detail="DataManager not initialized")
    if not getattr(dm, "order_book_ready", False):
        raise HTTPException(status_code=503, detail="Order-book service is not initialized")
    return dm


def _key(
    *,
    exchange: str,
    market_type: str,
    symbol: str,
    depth_levels: int,
    update_interval_ms: int | None,
) -> MarketStreamKey:
    exchange_name = str(exchange).strip().lower()
    market = str(market_type).strip().lower()
    contract = order_book_contract(exchange_name, market)
    allowed_depth_levels = contract["depth_levels"]
    if depth_levels not in allowed_depth_levels:
        raise HTTPException(
            status_code=422,
            detail=(
                "depth_levels must be one of "
                f"{', '.join(str(value) for value in sorted(allowed_depth_levels))}"
            ),
        )
    resolved_interval_ms = (
        contract["default_update_interval_ms"]
        if update_interval_ms is None
        else update_interval_ms
    )
    allowed_intervals = contract["update_intervals_ms"]
    if resolved_interval_ms not in allowed_intervals:
        supported = ", ".join(str(value) for value in sorted(allowed_intervals))
        raise HTTPException(
            status_code=422,
            detail=(
                f"{exchange_name} {market} update_interval_ms must be one of "
                f"{supported}"
            ),
        )
    try:
        return MarketStreamKey.build(
            exchange_name,
            market,
            symbol,
            MarketChannel.DEPTH,
            params={
                "mode": "partial",
                "depth_levels": depth_levels,
                "update_interval_ms": resolved_interval_ms,
            },
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def order_book_contract(exchange: str, market_type: str) -> dict[str, Any]:
    try:
        return resolve_order_book_contract(exchange, market_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
