"""Chart FOLLOW runs for HOST strategies (ADR-BACKTEST-015 §3.4, step P4b).

A chart cell holds a FOLLOW run through a lease: ``POST`` creates or joins the
run for its input and holds it, ``PUT .../lease`` renews, ``DELETE .../lease``
lets go. A run no cell holds stops. Status, result and the status stream are
the run facade's: ``/strategy-runs/{follow_id}``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.backtest.errors import BacktestError
from app.backtest.strategy.protocol import StrategyProviderError
from app.core.bounded_executor import ExecutorBusyError
from app.core.operator_origin import is_trusted_operator_origin, origin_from

from .continuous_strategies import _decode

router = APIRouter(prefix="/strategy-follows", tags=["strategy-follows"])
WIRE_ERRORS = (BacktestError, StrategyProviderError, ExecutorBusyError)
MAX_BYTES = 1024 * 1024
UNAVAILABLE = {"FLAG_DISABLED", "STRATEGY_MANAGER_CLOSED", "FOLLOW_UNAVAILABLE", "EXECUTOR_BUSY"}


def _follows(request: Request):
    strategy = getattr(getattr(request.app.state, "data_manager_core", None), "strategy", None)
    if strategy is None:
        raise BacktestError("FLAG_DISABLED", "strategy data manager is not started")
    return strategy.follows()


def _error(failure: Exception) -> JSONResponse:
    code = str(getattr(failure, "code", "FOLLOW_FAILED"))[:64]
    message = str(getattr(failure, "message", failure))[:256]
    headers = {"Cache-Control": "no-store"}
    if code.endswith("NOT_FOUND"):
        status = 404
    elif code == "FOLLOW_CAPACITY_EXCEEDED":
        status, headers = 429, {**headers, "Retry-After": "5"}
    elif code == "TRUSTED_ORIGIN_REQUIRED":
        status = 403
    elif code in UNAVAILABLE:
        status = 503
    elif code in {"BUDGET_EXCEEDED", "REQUEST_TOO_LARGE"}:
        status = 413
    else:
        status = 400
    return JSONResponse(status_code=status, headers=headers, content={"error": {"code": code, "message": message}})


def _reply(value: dict[str, Any]) -> JSONResponse:
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


async def _body(request: Request) -> object:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BYTES:
            raise BacktestError("REQUEST_TOO_LARGE", "FOLLOW request exceeds its byte budget")
        body.extend(chunk)
    return _decode(bytes(body))


@router.post("")
async def hold(request: Request):
    """Create or join the FOLLOW run for this chart's input, and hold it for the calling cell."""
    try:
        body = await _body(request)
        trusted = is_trusted_operator_origin(origin_from(request.headers))
        return _reply(await _follows(request).open(body, trusted=trusted))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.put("/{follow_id}/lease")
async def renew(request: Request, follow_id: str):
    try:
        return _reply(await _follows(request).renew(follow_id, await _body(request)))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.delete("/{follow_id}/lease")
async def release(request: Request, follow_id: str, holder: str = Query(default="", max_length=200)):
    try:
        return _reply(await _follows(request).release(follow_id, holder))
    except WIRE_ERRORS as failure:
        return _error(failure)
