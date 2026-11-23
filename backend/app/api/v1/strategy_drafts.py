"""The strategy editor's drafts, stored in the backend (ADR-BACKTEST-015 P3a)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.backtest.errors import BacktestError

router = APIRouter(prefix="/strategy-drafts", tags=["strategy-drafts"])
MAX_SAVE_BYTES = 3 * 1024 * 1024
MAX_IMPORT_BYTES = 32 * 1024 * 1024
STATUS = {"DRAFT_NOT_FOUND": 404, "DRAFT_REVISION_CONFLICT": 409, "DRAFT_CAPACITY_EXCEEDED": 409,
          "REQUEST_TOO_LARGE": 413, "FLAG_DISABLED": 503, "STRATEGY_MANAGER_CLOSED": 503}


def _drafts(request: Request):
    strategy = getattr(getattr(request.app.state, "data_manager_core", None), "strategy", None)
    if strategy is None:
        raise BacktestError("FLAG_DISABLED", "strategy data manager is not started")
    return strategy.drafts()


def _reply(value, status: int = 200) -> JSONResponse:
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def _error(failure: BacktestError) -> JSONResponse:
    body = {"code": failure.code, "message": failure.message[:256]}
    if failure.details:
        body["details"] = dict(failure.details)
    return _reply({"error": body}, STATUS.get(failure.code, 400))


async def _body(request: Request, limit: int):
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise BacktestError("REQUEST_TOO_LARGE", "the request exceeds its byte budget")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise BacktestError("REQUEST_TOO_LARGE", "the request exceeds its byte budget")
    try:
        return json.loads(data)
    except (ValueError, UnicodeError):
        raise BacktestError("DRAFT_INVALID", "the request must be JSON") from None


@router.get("")
async def list_drafts(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    try:
        return _reply(await asyncio.to_thread(_drafts(request).list, limit))
    except BacktestError as failure:
        return _error(failure)


@router.post("/import")
async def import_drafts(request: Request):
    try:
        body = await _body(request, MAX_IMPORT_BYTES)
        return _reply(await asyncio.to_thread(_drafts(request).import_drafts, body))
    except BacktestError as failure:
        return _error(failure)


@router.get("/{draft_id}")
async def get_draft(request: Request, draft_id: str):
    try:
        return _reply(await asyncio.to_thread(_drafts(request).get, draft_id))
    except BacktestError as failure:
        return _error(failure)


@router.put("/{draft_id}")
async def save_draft(request: Request, draft_id: str):
    try:
        body = await _body(request, MAX_SAVE_BYTES)
        return _reply(await asyncio.to_thread(_drafts(request).save, draft_id, body))
    except BacktestError as failure:
        return _error(failure)


@router.delete("/{draft_id}")
async def remove_draft(request: Request, draft_id: str):
    try:
        return _reply(await asyncio.to_thread(_drafts(request).remove, draft_id))
    except BacktestError as failure:
        return _error(failure)
