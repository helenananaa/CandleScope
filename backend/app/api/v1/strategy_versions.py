"""Content-addressed strategy versions and their names (ADR-BACKTEST-015 P3b)."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.backtest.errors import BacktestError

router = APIRouter(prefix="/strategy-versions", tags=["strategy-versions"])
MAX_BODY_BYTES = 4096
STATUS = {"VERSION_NOT_FOUND": 404, "REQUEST_TOO_LARGE": 413, "FLAG_DISABLED": 503, "STRATEGY_MANAGER_CLOSED": 503}


def _versions(request: Request):
    strategy = getattr(getattr(request.app.state, "data_manager_core", None), "strategy", None)
    if strategy is None:
        raise BacktestError("FLAG_DISABLED", "strategy data manager is not started")
    return strategy.versions()


def _reply(value, status: int = 200) -> JSONResponse:
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def _error(failure: BacktestError) -> JSONResponse:
    return _reply({"error": {"code": failure.code, "message": failure.message[:256]}}, STATUS.get(failure.code, 400))


@router.get("/names")
async def list_names(request: Request):
    try:
        return _reply(await asyncio.to_thread(_versions(request).names))
    except BacktestError as failure:
        return _error(failure)


@router.put("/names/{name}")
async def name_version(request: Request, name: str):
    """Point a name at a version; naming again moves the name."""
    try:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise BacktestError("REQUEST_TOO_LARGE", "the request exceeds its byte budget")
        try:
            value = json.loads(body)
        except (ValueError, UnicodeError):
            raise BacktestError("VERSION_NAME_INVALID", "the request must be JSON") from None
        if not isinstance(value, dict) or set(value) != {"version_hash"}:
            raise BacktestError("VERSION_NAME_INVALID", "naming a version carries its version_hash")
        versions = _versions(request)
        return _reply(await asyncio.to_thread(
            lambda: versions.name(name, value["version_hash"], now_ms=int(time.time() * 1000))))
    except BacktestError as failure:
        return _error(failure)


@router.delete("/names/{name}")
async def remove_name(request: Request, name: str):
    try:
        return _reply(await asyncio.to_thread(_versions(request).unname, name))
    except BacktestError as failure:
        return _error(failure)


@router.get("/{version_hash}")
async def get_version(request: Request, version_hash: str):
    try:
        return _reply(await asyncio.to_thread(_versions(request).get, version_hash))
    except BacktestError as failure:
        return _error(failure)


@router.get("/{version_hash}/draft")
async def version_draft(request: Request, version_hash: str):
    """The version as editor text, to open as a new draft."""
    try:
        return _reply(await asyncio.to_thread(_versions(request).draft, version_hash))
    except BacktestError as failure:
        return _error(failure)


@router.get("/{version_hash}/runs")
async def version_runs(request: Request, version_hash: str, limit: int = Query(default=50, ge=1, le=200)):
    """The runs that executed this version, newest first."""
    try:
        return _reply(await asyncio.to_thread(_versions(request).runs, version_hash, limit))
    except BacktestError as failure:
        return _error(failure)
