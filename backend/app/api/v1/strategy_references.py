"""Small references the strategy pages keep (ADR-BACKTEST-015 P3c).

Keys travel in the body or the query string: a chart's reference key is its
JSON scope, which a path segment cannot carry safely.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.backtest.errors import BacktestError

router = APIRouter(prefix="/strategy-references", tags=["strategy-references"])
MAX_PUT_BYTES = 80 * 1024
MAX_IMPORT_BYTES = 8 * 1024 * 1024
STATUS = {"REFERENCE_NOT_FOUND": 404, "REFERENCE_CAPACITY_EXCEEDED": 409, "REQUEST_TOO_LARGE": 413,
          "FLAG_DISABLED": 503, "STRATEGY_MANAGER_CLOSED": 503}


def _references(request: Request):
    strategy = getattr(getattr(request.app.state, "data_manager_core", None), "strategy", None)
    if strategy is None:
        raise BacktestError("FLAG_DISABLED", "strategy data manager is not started")
    return strategy.references()


def _reply(value, status: int = 200) -> JSONResponse:
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def _error(failure: BacktestError) -> JSONResponse:
    return _reply({"error": {"code": failure.code, "message": failure.message[:256]}}, STATUS.get(failure.code, 400))


async def _body(request: Request, limit: int):
    data = await request.body()
    if len(data) > limit:
        raise BacktestError("REQUEST_TOO_LARGE", "the request exceeds its byte budget")
    try:
        return json.loads(data)
    except (ValueError, UnicodeError):
        raise BacktestError("REFERENCE_INVALID", "the request must be JSON") from None


@router.get("/{kind}")
async def list_references(request: Request, kind: str, prefix: str = Query(default="", max_length=512),
                          limit: int = Query(default=200, ge=1, le=512)):
    try:
        return _reply(await asyncio.to_thread(_references(request).list, kind, prefix, limit))
    except BacktestError as failure:
        return _error(failure)


@router.get("/{kind}/entry")
async def get_reference(request: Request, kind: str, key: str = Query(min_length=1, max_length=512)):
    try:
        return _reply(await asyncio.to_thread(_references(request).get, kind, key))
    except BacktestError as failure:
        return _error(failure)


@router.put("/{kind}/entry")
async def put_reference(request: Request, kind: str):
    try:
        body = await _body(request, MAX_PUT_BYTES)
        return _reply(await asyncio.to_thread(_references(request).put, kind, body))
    except BacktestError as failure:
        return _error(failure)


@router.delete("/{kind}/entry")
async def remove_reference(request: Request, kind: str, key: str = Query(min_length=1, max_length=512)):
    try:
        return _reply(await asyncio.to_thread(_references(request).remove, kind, key))
    except BacktestError as failure:
        return _error(failure)


@router.post("/{kind}/import")
async def import_references(request: Request, kind: str):
    try:
        body = await _body(request, MAX_IMPORT_BYTES)
        return _reply(await asyncio.to_thread(_references(request).import_entries, kind, body))
    except BacktestError as failure:
        return _error(failure)
