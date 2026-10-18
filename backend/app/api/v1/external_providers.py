"""Loopback connection delivery for independently run decision providers."""

from __future__ import annotations

import ipaddress
import time
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.backtest.errors import BacktestError
from app.backtest.external_provider.endpoint import ENDPOINT_SCHEMA, instance_id
from app.backtest.external_provider.requests import (
    ClientConnectRequest,
    ClientPollRequest,
    ClientReplyRequest,
    ConnectionCreateRequest,
    ConnectionSmokeRequest,
)
from app.backtest.external_provider.smoke import run_smoke, verify_snapshot
from app.backtest.external_provider.wire import MAX_MESSAGE_BYTES, decode
from app.backtest.strategy.protocol import StrategyProviderError
from app.core.operator_origin import is_trusted_operator_origin, origin_from

router = APIRouter(prefix="/provider-connections", tags=["external-decision-providers"])


def _error(exc: BacktestError | StrategyProviderError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": {"code": exc.code, "message": str(exc)}})


def _control(request: Request):
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local:
        raise StrategyProviderError("PROVIDER_UNAUTHORIZED_WRITE", "external connections require a loopback peer")
    origin = origin_from(request.headers)
    if origin is not None and not is_trusted_operator_origin(origin):
        raise StrategyProviderError("PROVIDER_UNAUTHORIZED_WRITE", "external connection origin is not a trusted operator")
    service = getattr(request.app.state, "backtest_service", None)
    if service is None:
        raise BacktestError("FLAG_DISABLED", "backtest control plane is not started")
    service.external.require_enabled()
    return service.external


def _runtime(request: Request):
    runtime = getattr(request.app.state, "backtest_runtime", None)
    if runtime is None:
        raise BacktestError("FLAG_DISABLED", "backtest runtime is not started")
    return runtime


def _token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or not 20 <= len(header[7:]) <= 256:
        raise StrategyProviderError("PROVIDER_UNAUTHORIZED_WRITE", "external connection credentials are invalid")
    return header[7:]


async def _body(request: Request, contract: type[BaseModel]) -> dict[str, Any]:
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > MAX_MESSAGE_BYTES:
            raise StrategyProviderError("BUDGET_EXCEEDED", "external JSON message exceeds its byte budget")
        chunks.extend(chunk)
    try:
        return contract.model_validate(decode(bytes(chunks))).model_dump()
    except ValidationError:
        # Never put a response's model state or Authorization header in a
        # framework validation error or exception chain.
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external connection request fields") from None


@router.post("")
def create_connection(request: Request, payload: ConnectionCreateRequest):
    try:
        control = _control(request)
        verify_snapshot(_runtime(request), payload.model_dump())
        return control.create(revision_id=payload.strategy_revision_id, dataset_id=payload.dataset_id,
                              data_epoch=payload.data_epoch, snapshot_hash=payload.snapshot_hash)
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.get("")
def list_connections(request: Request):
    try:
        return {"connections": _control(request).list()}
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.get("/endpoint")
def endpoint(request: Request):
    try:
        _control(request)
        return {"schema_version": ENDPOINT_SCHEMA, "instance_id": instance_id()}
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.get("/example")
def example(request: Request):
    try:
        return _control(request).example()
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.get("/runs/{run_id}/trace")
def trace(request: Request, run_id: str, after: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500)):
    try:
        control = _control(request)
        request.app.state.backtest_service.get_run(run_id)
        return control.trace(run_id, after=after, limit=limit)
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/revoke")
def revoke_connection(request: Request, connection_id: str):
    try:
        control = _control(request)
        control.revoke(connection_id)
        service = request.app.state.backtest_service
        for run_id in service.repository.active_provider_runs(connection_id):
            try:
                service.cancel_run(run_id)
            except BacktestError:
                if service.get_run(run_id)["state"] not in {"COMPLETED", "FAILED", "CANCELLED"}:
                    raise
        return {"connection_id": connection_id, "revoked": True}
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/smoke")
def smoke_connection(request: Request, connection_id: str, payload: ConnectionSmokeRequest):
    try:
        _control(request)
        return run_smoke(_runtime(request), {**payload.model_dump(), "external_connection_id": connection_id})
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/connect")
async def connect(request: Request, connection_id: str):
    try:
        control = _control(request)
        token = _token(request)
        payload = await _body(request, ClientConnectRequest)
        journal = control.journal(connection_id)
        if payload["manifest_hash"] != journal.manifest.identity()["manifest_hash"]:
            raise StrategyProviderError("IDENTITY_MUTATION", "external client manifest differs from the selected revision")
        return control.store.connect(connection_id, token=token, client_id=payload["client_id"], now_ms=int(time.time() * 1000))
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/poll")
async def poll(request: Request, connection_id: str):
    try:
        control = _control(request)
        token = _token(request)
        payload = await _body(request, ClientPollRequest)
        journal = control.journal(connection_id)
        packet = journal.poll(connection_id, token=token, now_ms=int(time.time() * 1000), **payload)
        return {"call": packet, "active_sessions": journal.live_sessions(connection_id)}
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/reply")
async def reply(request: Request, connection_id: str):
    try:
        control = _control(request)
        token = _token(request)
        payload = await _body(request, ClientReplyRequest)
        result = control.journal(connection_id).submit(connection_id, token=token, now_ms=int(time.time() * 1000), **payload)
        return {"call_id": result["call_id"], "reply_hash": result["reply_hash"], "committed": True}
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)
