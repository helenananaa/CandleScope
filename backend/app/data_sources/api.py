"""Settings → Data sources. Desktop-session protected; keys go in, never out.

Every route needs the trusted desktop session (loopback, the desktop Origin and
the session token); changes also need the CSRF token and a user-action header,
as the read-only account routes do. Responses carry only masked hints.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from candlescope_plugin_sdk.platform_v2 import PlatformContractError, loads_strict
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.plugin_security_v2.management import LocalManagementGuard

from .credentials import DataSourceCredentialError, DataSourceCredentials
from .registry import DATA_SOURCES

router = APIRouter(prefix="/data-sources", tags=["data-sources"])
_MAX_BODY = 2048


async def _service(request: Request) -> DataSourceCredentials:
    guard = getattr(request.app.state, "plugin_platform_v2_management_guard", None)
    owner = getattr(request.app.state, "data_source_credentials", None)
    if not isinstance(guard, LocalManagementGuard) or not isinstance(owner, DataSourceCredentials):
        raise HTTPException(503, detail={"code": "DATA_SOURCES_UNAVAILABLE"})
    await guard(request)
    return owner


async def _body(request: Request) -> dict:
    raw = bytearray()
    try:
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > _MAX_BODY:
                raise DataSourceCredentialError("DATA_SOURCE_REQUEST_TOO_LARGE")
        value = loads_strict(bytes(raw or b"{}"))
        if not isinstance(value, dict):
            raise DataSourceCredentialError("DATA_SOURCE_REQUEST_INVALID")
        return value
    except DataSourceCredentialError:
        raise
    except (PlatformContractError, ValueError, UnicodeError, TypeError):
        raise DataSourceCredentialError("DATA_SOURCE_REQUEST_INVALID") from None
    finally:
        for index in range(len(raw)):
            raw[index] = 0


def _failure(code: str, *, status: int = 409, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, **extra}})


async def _check(source_id: str, values: dict[str, str]) -> dict:
    if source_id == "twelvedata":
        from app.exchanges.plugins.twelvedata.credential_check import check_twelve_data_key

        return await check_twelve_data_key(values["apiKey"])
    raise DataSourceCredentialError("DATA_SOURCE_CHECK_UNSUPPORTED")


@router.get("")
async def get_status(request: Request):
    owner = await _service(request)
    return owner.status()


@router.post("/{source_id}/credentials/{field_id}")
async def save_credential(request: Request, source_id: str, field_id: str):
    owner = await _service(request)
    try:
        payload = await _body(request)
        try:
            if set(payload) != {"value"}:
                raise DataSourceCredentialError("DATA_SOURCE_REQUEST_INVALID")
            await asyncio.to_thread(owner.save, source_id, field_id, payload["value"])
        finally:
            payload.clear()
        return owner.status()
    except DataSourceCredentialError as exc:
        return _failure(exc.code)
    except OSError:
        return _failure("CREDENTIAL_INDEX_WRITE_FAILED")


@router.post("/{source_id}/credentials/{field_id}/remove")
async def remove_credential(request: Request, source_id: str, field_id: str):
    owner = await _service(request)
    try:
        if await _body(request):
            raise DataSourceCredentialError("DATA_SOURCE_REQUEST_INVALID")
        await asyncio.to_thread(owner.remove, source_id, field_id)
        return owner.status()
    except DataSourceCredentialError as exc:
        return _failure(exc.code)
    except OSError:
        return _failure("CREDENTIAL_INDEX_WRITE_FAILED")


@router.post("/{source_id}/check")
async def check_source(request: Request, source_id: str):
    """Test the key CandleScope uses now (saved first, then the environment variable)."""
    owner = await _service(request)
    try:
        if await _body(request):
            raise DataSourceCredentialError("DATA_SOURCE_REQUEST_INVALID")
        source = DATA_SOURCES.get(source_id)
        if source is None:
            raise DataSourceCredentialError("DATA_SOURCE_FIELD_UNKNOWN")
        values, origins = {}, set()
        for field in source.fields:
            status = owner.field_status(source_id, field)
            value = owner.effective(source_id, field)
            if not value:
                raise DataSourceCredentialError("DATA_SOURCE_KEY_MISSING")
            values[field.id] = value
            origins.add(status["active"])
        try:
            usage = await _check(source_id, values)
        finally:
            values.clear()
        return {"ok": True, "source": origins.pop() if len(origins) == 1 else "mixed",
                "checkedAtMs": int(time.time() * 1000), "usage": usage}
    except DataSourceCredentialError as exc:
        return _failure(exc.code)
    except Exception as exc:
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code.startswith("DATA_SOURCE_"):
            retry = getattr(exc, "retry_after_seconds", None)
            return _failure(code, **({"retryAfterSeconds": retry} if retry else {}))
        return _failure("DATA_SOURCE_UNREACHABLE")
