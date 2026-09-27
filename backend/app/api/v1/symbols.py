"""HTTP adapter for the shared symbol catalog."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from app.exchanges import symbol_catalog as catalog

router = APIRouter(prefix="/symbols", tags=["symbols"])


def catalog_http_error(error: catalog.SymbolCatalogError) -> HTTPException:
    if error.code == "unsupported_exchange":
        return HTTPException(status_code=400, detail=error.message)
    status = 429 if error.code == "provider_rate_limited" else 503
    headers = (
        {"Retry-After": str(error.retry_after_seconds)}
        if error.retry_after_seconds is not None else None
    )
    return HTTPException(
        status_code=status,
        detail={"code": error.code, "message": error.message,
                "retryable": error.retryable, **error.details},
        headers=headers,
    )


@router.get("/exchange-info")
async def get_exchange_info(
    search: str = Query("", description="Filter by symbol or asset name (case-insensitive)"),
    quote_asset: str = Query("", description="Filter by quote asset, e.g. USDT, BTC"),
    market_type: str = Query("", description="Filter by market type: spot, futures, or empty for all"),
    exchange: str = Query("", description="Filter by exchange id, e.g. binance, okx"),
) -> dict:
    """Return cached trading pair list with optional filtering."""
    try:
        return await catalog.query_symbols(search=search, quote_asset=quote_asset, market_type=market_type, exchange=exchange)
    except catalog.SymbolCatalogError as exc:
        raise catalog_http_error(exc) from exc


@router.post("/exchange-info/refresh")
async def refresh_exchange_info(
    exchange: str = Query("", description="Optional exchange id"),
    market_type: str = Query("", description="Optional exact market type"),
) -> dict:
    """Manually re-fetch exchange metadata via the registry."""
    try:
        return await catalog.refresh_symbols(exchange=exchange, market_type=market_type)
    except catalog.SymbolCatalogError as exc:
        raise catalog_http_error(exc) from exc
