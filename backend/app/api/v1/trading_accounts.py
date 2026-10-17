"""HTTP adapter for trading accounts, practice orders and the trade journal."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.core.executors import run_storage
from app.trading_accounts.models import TradingAccountError
from app.trading_accounts.service import TradingAccountService

router = APIRouter(prefix="/trading", tags=["trading-accounts"])


def _service(request: Request) -> TradingAccountService:
    service = getattr(request.app.state, "trading_accounts", None)
    if not isinstance(service, TradingAccountService):
        raise HTTPException(status_code=503, detail={
            "code": "TRADING_UNAVAILABLE",
            "message": "Trading accounts are unavailable",
        })
    return service


async def _call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return await run_storage(func, *args, **kwargs)
    except TradingAccountError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.to_dict()) from exc


def _body(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail={
            "code": "TRADING_INVALID", "message": "Request body must be an object",
        })
    return payload


# ── accounts ────────────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(request: Request) -> dict:
    return await _call(_service(request).list_accounts)


@router.post("/accounts")
async def create_account(request: Request, payload: Any = Body(...)) -> dict:
    return await _call(_service(request).create_account, _body(payload))


@router.patch("/accounts/{account_id}")
async def update_account(request: Request, account_id: str, payload: Any = Body(...)) -> dict:
    return await _call(_service(request).update_account, account_id, _body(payload))


@router.post("/accounts/{account_id}/reset")
async def reset_account(request: Request, account_id: str) -> dict:
    return await _call(_service(request).reset_practice, account_id)


@router.get("/accounts/{account_id}/summary")
async def account_summary(request: Request, account_id: str) -> dict:
    return await _call(_service(request).account_summary, account_id)


@router.get("/accounts/{account_id}/stats")
async def account_stats(
    request: Request,
    account_id: str,
    from_ms: int | None = Query(default=None, alias="fromMs", ge=0),
    to_ms: int | None = Query(default=None, alias="toMs", ge=0),
    tag: list[str] | None = Query(default=None),
) -> dict:
    return await _call(
        _service(request).account_stats, account_id, from_ms=from_ms, to_ms=to_ms, tags=tag,
    )


# ── trades ──────────────────────────────────────────────────────

@router.get("/accounts/{account_id}/trades")
async def list_trades(
    request: Request,
    account_id: str,
    status: str | None = Query(default=None, pattern="^(open|closed)$"),
) -> dict:
    return await _call(_service(request).list_trades, account_id, status=status)


@router.get("/accounts/{account_id}/trades/{trade_id}")
async def trade_detail(request: Request, account_id: str, trade_id: str) -> dict:
    return await _call(_service(request).trade_detail, account_id, trade_id)


@router.get("/accounts/{account_id}/trades/{trade_id}/excursion")
async def trade_excursion(request: Request, account_id: str, trade_id: str) -> dict:
    return await _call(_service(request).trade_excursion, account_id, trade_id)


# ── practice orders ─────────────────────────────────────────────

@router.get("/accounts/{account_id}/orders")
async def list_orders(
    request: Request,
    account_id: str,
    status: str | None = Query(default=None, pattern="^(working|filled|cancelled|rejected)$"),
) -> dict:
    return await _call(_service(request).list_orders, account_id, status=status)


@router.post("/accounts/{account_id}/orders")
async def place_order(request: Request, account_id: str, payload: Any = Body(...)) -> dict:
    return await _call(_service(request).place_order, account_id, _body(payload))


@router.post("/accounts/{account_id}/orders/{order_id}/cancel")
async def cancel_order(request: Request, account_id: str, order_id: str) -> dict:
    return await _call(_service(request).cancel_order, account_id, order_id)


# ── manual fills ────────────────────────────────────────────────

@router.get("/accounts/{account_id}/fills")
async def list_fills(request: Request, account_id: str) -> dict:
    return await _call(_service(request).list_fills, account_id)


@router.post("/accounts/{account_id}/fills")
async def add_fill(request: Request, account_id: str, payload: Any = Body(...)) -> dict:
    return await _call(_service(request).add_fill, account_id, _body(payload))


@router.delete("/accounts/{account_id}/fills/{fill_id}")
async def delete_fill(request: Request, account_id: str, fill_id: str) -> dict:
    return await _call(_service(request).delete_fill, account_id, fill_id)


# ── journal ─────────────────────────────────────────────────────

@router.get("/accounts/{account_id}/journal")
async def list_entries(
    request: Request,
    account_id: str,
    symbol: str | None = Query(default=None, max_length=40),
    unlinked: bool = Query(default=False),
) -> dict:
    return await _call(
        _service(request).list_entries, account_id, symbol=symbol, unlinked_only=unlinked,
    )


@router.post("/accounts/{account_id}/journal")
async def create_entry(request: Request, account_id: str, payload: Any = Body(...)) -> dict:
    return await _call(_service(request).create_entry, account_id, _body(payload))


@router.get("/journal/{entry_id}")
async def entry_detail(request: Request, entry_id: str) -> dict:
    return await _call(_service(request).entry_detail, entry_id)


@router.patch("/journal/{entry_id}")
async def save_entry(request: Request, entry_id: str, payload: Any = Body(...)) -> dict:
    return await _call(_service(request).save_entry, entry_id, _body(payload))


@router.put("/journal/{entry_id}/link")
async def link_entry(request: Request, entry_id: str, payload: Any = Body(...)) -> dict:
    trade_id = _body(payload).get("tradeId")
    return await _call(_service(request).link_entry, entry_id, str(trade_id) if trade_id else None)


@router.delete("/journal/{entry_id}")
async def delete_entry(request: Request, entry_id: str) -> dict:
    return await _call(_service(request).delete_entry, entry_id)


@router.get("/journal/{entry_id}/revisions")
async def entry_revisions(request: Request, entry_id: str) -> dict:
    return await _call(_service(request).entry_revisions, entry_id)


@router.post("/journal/{entry_id}/snapshots")
async def add_snapshot(request: Request, entry_id: str, payload: Any = Body(...)) -> dict:
    return await _call(_service(request).add_snapshot, entry_id, _body(payload))


@router.get("/snapshots/{snapshot_id}/image")
async def snapshot_image(request: Request, snapshot_id: str) -> FileResponse:
    path = await _call(_service(request).snapshot_image_path, snapshot_id)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})
