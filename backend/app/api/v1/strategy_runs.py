"""One HTTP entry for every strategy run family (ADR-BACKTEST-015 step P2).

The family endpoints under ``/backtests`` remain as adapters; new callers use
these. Every route goes through the profile's StrategyDataManager.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.backtest.errors import BacktestError
from app.backtest.strategy.protocol import StrategyProviderError
from app.core.bounded_executor import ExecutorBusyError

router = APIRouter(prefix="/strategy-runs", tags=["strategy-runs"])
WIRE_ERRORS = (BacktestError, StrategyProviderError, ExecutorBusyError)
UNAVAILABLE = {"FLAG_DISABLED", "STRATEGY_MANAGER_CLOSED", "CONTINUOUS_NOT_READY", "EXECUTOR_BUSY"}


def _runs(request: Request):
    strategy = getattr(getattr(request.app.state, "data_manager_core", None), "strategy", None)
    if strategy is None:
        raise BacktestError("FLAG_DISABLED", "strategy data manager is not started")
    return strategy.runs()


def _error(failure: Exception) -> JSONResponse:
    code = str(getattr(failure, "code", "STRATEGY_RUN_FAILED"))[:64]
    message = str(getattr(failure, "message", failure))[:256]
    if code.endswith("NOT_FOUND"):
        status = 404
    elif code == "RUN_CAPACITY_EXCEEDED":
        return JSONResponse(status_code=429, headers={"Retry-After": "1"},
                            content={"error": {"code": code, "message": message}})
    elif code in UNAVAILABLE:
        status = 503
    elif code in {"RUN_CONTROL_UNSUPPORTED", "RUN_RESULT_NOT_READY"}:
        status = 409
    elif code == "BUDGET_EXCEEDED":
        status = 413
    else:
        status = 400
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}},
                        headers={"Cache-Control": "no-store"})


def _reply(value: dict[str, Any]) -> JSONResponse:
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


@router.get("/capabilities")
async def capabilities(request: Request):
    try:
        return _reply(await _runs(request).capabilities())
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.get("/{run_id}")
async def status(request: Request, run_id: str):
    try:
        return _reply(await _runs(request).status(run_id))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.get("/{run_id}/events", response_model=None)
async def events(request: Request, run_id: str):
    """``candlescope.strategy-run-stream/1`` as NDJSON: a status frame per committed change, ending at the terminal one."""
    try:
        watch = await _runs(request).watch(run_id)
    except WIRE_ERRORS as failure:
        return _error(failure)

    async def rows():
        try:
            async for frame in watch.events():
                yield json.dumps(frame, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        finally:
            watch.close()

    return StreamingResponse(rows(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Content-Encoding": "identity"})


@router.get("/{run_id}/result")
async def result(request: Request, run_id: str):
    """The completed run as ``candlescope.run-result/1``."""
    try:
        return _reply(await _runs(request).result(run_id))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.post("/{run_id}/cancel")
async def cancel(request: Request, run_id: str):
    try:
        return _reply(await _runs(request).cancel(run_id))
    except WIRE_ERRORS as failure:
        return _error(failure)
