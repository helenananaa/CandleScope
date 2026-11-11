"""Loopback connection delivery for independently run decision providers."""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.backtest.errors import BacktestError
from app.backtest.external_provider.access import ExternalProviderAccess
from app.backtest.external_provider.requests import (
    ClientConnectRequest,
    ClientPollRequest,
    ClientReplyRequest,
    ConnectionCreateRequest,
    ConnectionSmokeRequest,
)
from app.backtest.external_provider.wire import MAX_MESSAGE_BYTES, decode
from app.backtest.strategy.protocol import StrategyProviderError
from app.core.operator_origin import is_trusted_operator_origin, origin_from

router = APIRouter(prefix="/provider-connections", tags=["external-decision-providers"])


def _error(exc: BacktestError | StrategyProviderError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": {"code": exc.code, "message": str(exc)}})


def _access(request: Request) -> ExternalProviderAccess:
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local:
        raise StrategyProviderError("PROVIDER_UNAUTHORIZED_WRITE", "external connections require a loopback peer")
    origin = origin_from(request.headers)
    if origin is not None and not is_trusted_operator_origin(origin):
        raise StrategyProviderError("PROVIDER_UNAUTHORIZED_WRITE", "external connection origin is not a trusted operator")
    core = getattr(request.app.state, "data_manager_core", None)
    if core is not None:
        if core.strategy is None:
            raise BacktestError("FLAG_DISABLED", "strategy data manager is not started")
        return core.strategy.external_providers
    # Explicit standalone hosts still use the same operations without a live
    # market manager. A configured production root never falls through here.
    service = getattr(request.app.state, "backtest_service", None)
    if service is None:
        raise BacktestError("FLAG_DISABLED", "backtest control plane is not started")
    return ExternalProviderAccess(lambda: service, getattr(request.app.state, "backtest_runtime", None))


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
        return _access(request).create(payload.model_dump())
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.get("")
def list_connections(request: Request):
    try:
        return {"connections": _access(request).list()}
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.get("/endpoint")
def endpoint(request: Request):
    try:
        return _access(request).endpoint()
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.get("/example")
def example(request: Request):
    try:
        return _access(request).example()
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.get("/runs/{run_id}/trace")
def trace(request: Request, run_id: str, after: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500)):
    try:
        return _access(request).trace(run_id, after=after, limit=limit)
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/revoke")
def revoke_connection(request: Request, connection_id: str):
    try:
        return _access(request).revoke(connection_id)
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/smoke")
def smoke_connection(request: Request, connection_id: str, payload: ConnectionSmokeRequest):
    try:
        return _access(request).smoke(connection_id, payload.model_dump())
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/connect")
async def connect(request: Request, connection_id: str):
    try:
        access = _access(request)
        access.require_enabled()
        token = _token(request)
        payload = await _body(request, ClientConnectRequest)
        return access.connect(connection_id, token=token, client_id=payload["client_id"], manifest_hash=payload["manifest_hash"])
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/poll")
async def poll(request: Request, connection_id: str):
    try:
        access = _access(request)
        access.require_enabled()
        token = _token(request)
        payload = await _body(request, ClientPollRequest)
        return access.poll(connection_id, token=token, values=payload)
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)


@router.post("/{connection_id}/reply")
async def reply(request: Request, connection_id: str):
    try:
        access = _access(request)
        access.require_enabled()
        token = _token(request)
        payload = await _body(request, ClientReplyRequest)
        return access.reply(connection_id, token=token, values=payload)
    except (BacktestError, StrategyProviderError) as exc:
        return _error(exc)
