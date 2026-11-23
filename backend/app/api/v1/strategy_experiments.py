"""Experiments: one strategy run by a rule (ADR-BACKTEST-015 P5b, P5c3).

Members are submitted through the same functions as the strategy-preparation and run routes,
with this request: validation, idempotency and the trusted-origin rule for local Python are
exactly those of a direct submission. A robustness experiment's study is created as the study
route creates one, and its local Python trust is decided by this request's origin.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.backtest.errors import BacktestError
from app.core.bounded_executor import ExecutorBusyError

from .continuous_strategies import _decode

router = APIRouter(prefix="/strategy-experiments", tags=["strategy-experiments"])
WIRE_ERRORS = (BacktestError, ExecutorBusyError)
MAX_BYTES = 4 * 1024 * 1024
UNAVAILABLE = {"FLAG_DISABLED", "STRATEGY_MANAGER_CLOSED", "EXECUTOR_BUSY"}
CONFLICT = {"IDEMPOTENCY_CONFLICT", "EXPERIMENT_MEMBER_ACTIVE", "EXPERIMENT_CANCELLED", "EXPERIMENT_RULE_UNSUPPORTED"}


def _strategy(request: Request):
    strategy = getattr(getattr(request.app.state, "data_manager_core", None), "strategy", None)
    if strategy is None:
        raise BacktestError("FLAG_DISABLED", "strategy data manager is not started")
    return strategy


def _error(failure: Exception) -> JSONResponse:
    code = str(getattr(failure, "code", "EXPERIMENT_FAILED"))[:64]
    message = str(getattr(failure, "message", failure))[:256]
    if code.endswith("NOT_FOUND"):
        status = 404
    elif code in CONFLICT:
        status = 409
    elif code in UNAVAILABLE:
        status = 503
    elif code == "REQUEST_TOO_LARGE":
        status = 413
    else:
        status = 400
    return JSONResponse(status_code=status, headers={"Cache-Control": "no-store"},
                        content={"error": {"code": code, "message": message}})


def _reply(value: dict[str, Any]) -> JSONResponse:
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


async def _body(request: Request) -> object:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BYTES:
            raise BacktestError("REQUEST_TOO_LARGE", "the experiment request exceeds its byte budget")
        body.extend(chunk)
    try:
        return _decode(bytes(body))
    except ValueError as exc:
        raise BacktestError("EXPERIMENT_INVALID", str(exc)) from exc


def _http_failure(exc: HTTPException) -> BacktestError:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return BacktestError(str(detail.get("code") or f"HTTP_{exc.status_code}"), str(detail.get("message") or exc.detail))


class ServicesPort:
    """The backend services an experiment's members use, reached as this request reaches them."""

    def __init__(self, request: Request) -> None:
        self.request = request
        self.strategy = _strategy(request)

    def _preparations(self):
        service = getattr(self.request.app.state, "data_preparation_service", None)
        if service is None:
            raise BacktestError("PREPARATION_UNAVAILABLE", "Automatic history preparation is unavailable")
        return service

    async def submit_preparation(self, body: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        from .data_preparation import StrategyPreparationPayload, prepare_strategy
        try:
            payload = StrategyPreparationPayload.model_validate({**body, "idempotency_key": idempotency_key})
        except ValidationError as exc:
            raise BacktestError("EXPERIMENT_INVALID", f"a member's preparation is invalid: {exc.errors()[0]['msg']}") from exc
        try:
            return await prepare_strategy(self.request, payload)
        except HTTPException as exc:
            raise _http_failure(exc) from exc

    async def submit_run(self, body: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        from app.backtest.request_contracts import RunCreateRequest

        from .backtests import create_run
        try:
            payload = RunCreateRequest.model_validate(body)
        except ValidationError as exc:
            raise BacktestError("EXPERIMENT_INVALID", f"a member's run is invalid: {exc.errors()[0]['msg']}") from exc
        created = await asyncio.to_thread(create_run, self.request, payload, idempotency_key)
        if isinstance(created, JSONResponse):
            error = json.loads(bytes(created.body)).get("error") or {}
            raise BacktestError(str(error.get("code") or "RUN_REJECTED"), str(error.get("message") or "the run was rejected"))
        return created

    async def preparation(self, job_id: str) -> dict[str, Any] | None:
        from app.data_preparation.models import PreparationError
        service = self._preparations()
        try:
            return await service.storage(service.repository.get, job_id)
        except PreparationError:
            return None

    async def run(self, run_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.strategy.service.repository.get_run_by_id, run_id)

    async def cancel_preparation(self, job_id: str) -> None:
        from app.data_preparation.models import PreparationError
        service = self._preparations()
        try:
            await service.cancel(job_id)
        except PreparationError as exc:
            raise BacktestError(exc.code, str(exc)) from exc

    async def cancel_run(self, run_id: str) -> None:
        await self.strategy.runs().cancel(run_id)

    def listen_preparation(self, job_id: str, wake: Callable[[], None]) -> Callable[[], None]:
        return self._preparations().repository.updates.listen_commits(job_id, wake)

    def listen_run(self, run_id: str, wake: Callable[[], None]) -> Callable[[], None]:
        return self.strategy.service.repository.run_updates.listen_commits(run_id, wake)

    async def create_study(self, body: dict[str, Any]) -> dict[str, Any]:
        from app.backtest.request_contracts import StudyCreateRequest
        from app.core.operator_origin import is_trusted_operator_origin, origin_from
        python = {name: body.pop(name) for name in ("python_runtime_mode", "python_trusted_confirmed") if name in body}
        try:
            payload = StudyCreateRequest.model_validate(body).model_dump()
        except ValidationError as exc:
            error = exc.errors()[0]
            where = ".".join(str(part) for part in error.get("loc", ()))
            raise BacktestError("EXPERIMENT_INVALID", f"the study is invalid: {where} {error['msg']}".strip()) from exc
        trusted = is_trusted_operator_origin(origin_from(self.request.headers))
        return await asyncio.to_thread(self.strategy.service.create_study, {**payload, **python}, trusted=trusted)

    async def start_study(self, study_id: str) -> None:
        await asyncio.to_thread(self.strategy.service.start_study, study_id)

    async def study(self, study_id: str) -> dict[str, Any] | None:
        service = self.strategy.service

        def read() -> dict[str, Any] | None:
            try:
                study = service.get_study(study_id)
            except BacktestError:
                return None
            return {**study, "failure": service.repository.study_failure(study_id)}
        return await asyncio.to_thread(read)

    async def cancel_study(self, study_id: str) -> None:
        await asyncio.to_thread(self.strategy.service.cancel_study, study_id)

    async def reveal_holdout(self, study_id: str) -> None:
        await asyncio.to_thread(self.strategy.service.reveal_study_holdout, study_id)

    def listen_study(self, study_id: str, wake: Callable[[], None]) -> Callable[[], None]:
        return self.strategy.service.repository.study_updates.listen_commits(study_id, wake)


@router.post("")
async def create(request: Request):
    """Create an experiment and submit its members; the same idempotency key returns the same experiment."""
    try:
        body = await _body(request)
        port = ServicesPort(request)
        return _reply(await port.strategy.experiments().create(body, port))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.get("")
async def list_experiments(request: Request, limit: int = Query(20, ge=1, le=50)):
    try:
        port = ServicesPort(request)
        return _reply(await port.strategy.experiments().list(port, limit))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.post("/studies/{study_id}")
async def adopt_study(request: Request, study_id: str):
    """A study made by the research tool as a robustness experiment (its link opens in the workspace)."""
    try:
        port = ServicesPort(request)
        return _reply(await port.strategy.experiments().adopt_study(study_id, port))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.get("/{experiment_id}")
async def get_experiment(request: Request, experiment_id: str):
    try:
        port = ServicesPort(request)
        return _reply(await port.strategy.experiments().view(experiment_id, port))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.get("/{experiment_id}/events", response_model=None)
async def events(request: Request, experiment_id: str):
    """``candlescope.strategy-experiment-stream/1`` as NDJSON: a frame per committed change, ending when no member is active."""
    try:
        port = ServicesPort(request)
        watch = await port.strategy.experiments().watch(experiment_id, port)
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


@router.post("/{experiment_id}/cancel")
async def cancel(request: Request, experiment_id: str):
    try:
        port = ServicesPort(request)
        return _reply(await port.strategy.experiments().cancel(experiment_id, port))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.post("/{experiment_id}/reveal-holdout")
async def reveal_holdout(request: Request, experiment_id: str):
    """Open a robustness study's sealed holdout, once all its folds have selected a candidate."""
    try:
        port = ServicesPort(request)
        return _reply(await port.strategy.experiments().reveal_holdout(experiment_id, port))
    except WIRE_ERRORS as failure:
        return _error(failure)


@router.post("/{experiment_id}/members/{ordinal}/retry")
async def retry(request: Request, experiment_id: str, ordinal: int):
    try:
        port = ServicesPort(request)
        return _reply(await port.strategy.experiments().retry(experiment_id, ordinal, port))
    except WIRE_ERRORS as failure:
        return _error(failure)
