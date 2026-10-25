"""Desktop-session protected account views; credential errors never echo inputs."""
from __future__ import annotations

import asyncio
import re
import time
import uuid

from candlescope_plugin_sdk.platform_v2 import PlatformContractError, loads_strict
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.plugin_security_v2.management import LocalManagementGuard
from .normalization import AccountDataError
from .service import ReadOnlyAccountService
from .sync import error_code

router = APIRouter(prefix="/readonly-accounts",tags=["read-only-accounts"])


async def service(request: Request) -> ReadOnlyAccountService:
    guard = getattr(request.app.state,"plugin_platform_v2_management_guard",None)
    owner = getattr(request.app.state,"readonly_account_service",None)
    if not isinstance(guard,LocalManagementGuard) or not isinstance(owner,ReadOnlyAccountService):
        raise HTTPException(503,detail={"code":"ACCOUNT_UNAVAILABLE"})
    await guard(request)
    return owner


async def body(request: Request, maximum: int = 4096) -> dict:
    raw = bytearray()
    try:
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > maximum:
                raise AccountDataError("ACCOUNT_REQUEST_TOO_LARGE")
        value = loads_strict(bytes(raw or b"{}"))
        if not isinstance(value,dict):
            raise AccountDataError("ACCOUNT_REQUEST_INVALID")
        return value
    except AccountDataError:
        raise
    except (PlatformContractError,ValueError,UnicodeError,TypeError):
        raise AccountDataError("ACCOUNT_REQUEST_INVALID") from None
    finally:
        for index in range(len(raw)):
            raw[index] = 0


def failure(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409,content={"error":{"code":error_code(exc)}})


@router.get("/status")
async def get_status(request: Request):
    owner = await service(request)
    return await owner.state()


@router.post("/connect")
async def connect(request: Request):
    owner = await service(request)
    try:
        payload = await body(request)
        try:
            await owner.connect(payload)
        finally:
            payload.clear()
        return {"connected":True}
    except Exception as exc:
        return failure(exc)


@router.post("/disconnect")
async def disconnect(request: Request):
    owner = await service(request)
    try:
        payload = await body(request)
        if set(payload)-{"forget"} or ("forget" in payload and type(payload["forget"]) is not bool):
            raise AccountDataError("ACCOUNT_REQUEST_INVALID")
        await owner.disconnect(forget=payload.get("forget",False))
        return {"disconnected":True}
    except Exception as exc:
        return failure(exc)


@router.post("/resync")
async def resync(request: Request):
    owner = await service(request)
    try:
        if await body(request):
            raise AccountDataError("ACCOUNT_REQUEST_INVALID")
        await owner.resume()
        return {"requested":True}
    except Exception as exc:
        return failure(exc)


@router.get("/facts/{kind}")
async def facts(request: Request,kind: str,before_time: int | None = None,
                before_id: str | None = None,limit: int = Query(100,ge=1,le=500)):
    owner = await service(request)
    try:
        if (before_time is None) != (before_id is None):
            raise AccountDataError("FACT_CURSOR_INVALID")
        rows = await asyncio.to_thread(owner.repository.facts,kind,
            before=None if before_time is None else (before_time,before_id),limit=limit)
        key = {"fills":"fillId","orders":"orderId","bills":"billId"}[kind]
        return {"items":rows,"next":None if len(rows)<limit else {"beforeTime":rows[-1]["eventTimeMs"],"beforeId":rows[-1][key]}}
    except Exception as exc:
        return failure(exc)


@router.get("/reconciliation")
async def reconciliation(request: Request):
    owner = await service(request)
    from .reconciliation import reconcile_account
    try:
        def compute():
            return reconcile_account(owner.repository.reconciliation_inputs())
        return await asyncio.to_thread(compute)
    except Exception as exc:
        return failure(exc)


@router.get("/journal")
async def journal(request: Request, before_recorded_ms: int | None = None,
                  before_note_id: str | None = None, before_version: int | None = None,
                  limit: int = Query(200,ge=1,le=500)):
    owner = await service(request)
    try:
        before = None
        if any(value is not None for value in [before_recorded_ms,before_note_id,before_version]):
            if (before_recorded_ms is None or before_recorded_ms < 0 or before_version is None or before_version < 1
                    or before_note_id is None or re.fullmatch(r"[0-9a-f]{32}",before_note_id) is None):
                raise AccountDataError("JOURNAL_CURSOR_INVALID")
            before = (before_recorded_ms,before_note_id,before_version)
        rows = await asyncio.to_thread(owner.repository.notes,before=before,limit=limit)
        last = rows[-1] if len(rows) == limit else None
        return {"versions":rows,"next":None if last is None else {
            "recordedMs":last["recordedMs"],"noteId":last["noteId"],"version":last["version"]}}
    except Exception as exc:
        return failure(exc)


@router.post("/journal")
async def save_journal(request: Request):
    owner = await service(request)
    try:
        value = await body(request,32*1024)
        if set(value)-{"noteId","baseVersion","text","tags","kind","eventMs","fillId"}:
            raise AccountDataError("JOURNAL_FIELDS_INVALID")
        note_id = value.get("noteId") or uuid.uuid4().hex
        base = value.get("baseVersion",0)
        text,tags,kind = value.get("text"),value.get("tags",[]),value.get("kind","note")
        event = value.get("eventMs",int(time.time()*1000))
        fill_id = value.get("fillId")
        if (not isinstance(note_id,str) or re.fullmatch(r"[0-9a-f]{32}",note_id) is None
                or type(base) is not int or base<0 or not isinstance(text,str) or not 1<=len(text.strip())<=8000
                or not isinstance(tags,list) or len(tags)>20 or any(not isinstance(tag,str) or not 1<=len(tag)<=40 for tag in tags)
                or kind not in {"plan","note","review"} or type(event) is not int or not 0<=event<2**53
                or (fill_id is not None and (not isinstance(fill_id,str) or len(fill_id)>128))):
            raise AccountDataError("JOURNAL_FIELDS_INVALID")
        return await asyncio.to_thread(owner.repository.save_note,note_id,base,
            {"text":text,"tags":tags,"kind":kind},event_ms=event,fill_id=fill_id)
    except Exception as exc:
        return failure(exc)
