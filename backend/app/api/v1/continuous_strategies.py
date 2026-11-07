"""Bounded HTTP initial results and commit-resumable WebSocket delivery."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import math

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import ValidationError

from app.backtest.continuous_contracts import ContinuousCreate,ContinuousControl,CommittedIdentity,ResultQuery
from app.backtest.errors import BacktestError
from app.backtest.strategy.protocol import StrategyProviderError
from app.backtest.strategy.python_author_v1 import AUTHOR_CONTRACT
from app.backtest.continuous_provider import SCHEMA as PROVIDER_SCHEMA
from app.data_engine.data_manager.continuous_strategy import MAX_REQUESTS
from app.core.async_cleanup import finish_cleanup
from app.core.bounded_executor import ExecutorBusyError
from app.core.operator_origin import is_trusted_operator_origin,origin_from
from .stream_utils import send_text_with_timeout

router=APIRouter(prefix="/continuous",tags=["continuous-strategies"])
PROTOCOL="continuous.v1"
MAX_BYTES=1024*1024
WIRE_ERRORS=(BacktestError,StrategyProviderError,ExecutorBusyError)


def _access(connection):
    gate=getattr(getattr(connection.app.state,"data_manager_core",None),"strategy",None)
    if gate is None:raise BacktestError("CONTINUOUS_NOT_READY","StrategyDataManager is unavailable")
    # Views never create/adopt an execution owner. Application startup owns it.
    access=gate.continuous_access()
    access.controller()
    return access


def _encode(value):
    text=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(",",":"))
    if len(text.encode("utf-8"))>MAX_BYTES:raise BacktestError("BUDGET_EXCEEDED","Strategy response exceeds its byte budget")
    return text


def _reply(value,status=200):
    return Response(_encode(value),status_code=status,media_type="application/json",headers={"Cache-Control":"no-store"})


def _error(failure):
    code=str(getattr(failure,"code","CONTINUOUS_INPUT_INVALID"))[:64]
    if code.endswith("NOT_FOUND"):status=404
    elif code in {"CONTINUOUS_COMMIT_CONFLICT","CONTINUOUS_REPAIR_REQUIRED"}:status=409
    elif code in {"TRUSTED_ORIGIN_REQUIRED"}:status=403
    elif code in {"CONTINUOUS_NOT_READY","STRATEGY_MANAGER_CLOSED","EXECUTOR_BUSY"}:status=503
    elif code=="BUDGET_EXCEEDED":status=429
    elif code=="REQUEST_TOO_LARGE":status=413
    elif code=="REQUEST_FIELDS_INVALID":status=422
    else:status=400
    return _reply({"error":{"code":code,"message":str(failure)[:256]}},status)


def _decode(raw):
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError("Duplicate JSON field")
            value[key]=item
        return value
    def constant(_value):raise ValueError("Non-finite JSON")
    try:
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
        pending=[(value,0)];visited=0
        while pending:
            item,depth=pending.pop();visited+=1
            if depth>64 or visited>10000:raise ValueError("JSON structure budget exceeded")
            if isinstance(item,str):item.encode("utf-8")
            elif isinstance(item,float) and not math.isfinite(item):raise ValueError("Non-finite JSON")
            elif isinstance(item,dict):
                for key,child in item.items():key.encode("utf-8");pending.append((child,depth+1))
            elif isinstance(item,list):pending.extend((child,depth+1) for child in item)
        return value
    except (ValueError,UnicodeError,RecursionError):
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Request must contain finite unambiguous UTF-8 JSON") from None


def _validate(contract,value):
    try:return contract.model_validate(value)
    except (ValidationError,ValueError,TypeError):
        # Never echo editor source or arbitrary parameters in validation errors.
        raise BacktestError("REQUEST_FIELDS_INVALID","Invalid continuous strategy request fields") from None


async def _body(request,contract):
    length=request.headers.get("content-length")
    if length is not None:
        try:
            if not length.isascii() or not length.isdecimal() or len(length)>10:raise ValueError
            declared=int(length)
        except ValueError:raise BacktestError("CONTINUOUS_INPUT_INVALID","Invalid content length") from None
        if declared>MAX_BYTES:raise BacktestError("REQUEST_TOO_LARGE","Strategy request exceeds its byte budget")
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>MAX_BYTES:raise BacktestError("REQUEST_TOO_LARGE","Strategy request exceeds its byte budget")
        body.extend(chunk)
    return _validate(contract,_decode(body))


def _identity(raw):
    if raw is None:return None
    if len(raw.encode("utf-8"))>2048:raise BacktestError("REQUEST_TOO_LARGE","Committed cursor exceeds its byte budget")
    return _validate(CommittedIdentity,_decode(raw)).model_dump()


@router.get("/capabilities")
async def capabilities(request:Request):
    try:
        access=_access(request);controller=access.controller()
        return _reply({"available":True,"execution_enabled":controller.execution_enabled,
            "runtime_mode":controller.runtime_mode,"protocol":PROTOCOL,
            "modes":["HISTORY_LIVE","LIVE_ONLY"],"languages":["builtin","python"],
            "intervals":["1m"],"account_models":["SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V1"],
            "python_editor_authorized":is_trusted_operator_origin(origin_from(request.headers)),
            "provider_schema":PROVIDER_SCHEMA,"python_author_contract":AUTHOR_CONTRACT,
            "repair_available":False,"requires_strategy_revision":False,"initial_result_transport":"HTTP",
            "limits":{"requests":MAX_REQUESTS,"subscriptions":access.owner.max_subscriptions,
                "active_runs":controller.runtime.max_active_runs,"page_items":200,"message_bytes":MAX_BYTES}})
    except WIRE_ERRORS as failure:return _error(failure)


@router.post("/runs")
async def create(request:Request):
    try:
        payload=await _body(request,ContinuousCreate)
        keys=request.headers.getlist("idempotency-key")
        if len(keys)!=1 or not 1<=len(keys[0])<=128:
            raise BacktestError("REQUEST_FIELDS_INVALID","One bounded Idempotency-Key is required")
        if payload.provider.language=="python" and not is_trusted_operator_origin(origin_from(request.headers)):
            raise BacktestError("TRUSTED_ORIGIN_REQUIRED","Python editor requires a trusted local application origin")
        values=payload.model_dump(exclude_unset=True)
        values["provider"]=payload.provider.model_dump(exclude_unset=True,by_alias=True)
        values["series"]=payload.series.key()
        creation=await _access(request).create(keys[0],**values)
        return _reply({"creation":creation},202)
    except WIRE_ERRORS as failure:return _error(failure)


@router.get("/runs")
async def catalog(request:Request):
    try:return _reply(await _access(request).catalog())
    except WIRE_ERRORS as failure:return _error(failure)


@router.get("/runs/{run_id}")
async def status(request:Request,run_id:str):
    try:return _reply(await _access(request).status(run_id))
    except WIRE_ERRORS as failure:return _error(failure)


@router.get("/runs/{run_id}/initial")
async def initial(request:Request,run_id:str):
    tasks=[]
    async def disconnected():
        while True:
            packet=await request.receive()
            if packet["type"]=="http.disconnect":return
    try:
        result=asyncio.create_task(_access(request).initial(run_id))
        lost=asyncio.create_task(disconnected());tasks=[result,lost]
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        if result in done:return _reply(result.result())
        # Reclaim only the initial-result view. Durable creation/Actor continues.
        return Response(status_code=499)
    except WIRE_ERRORS as failure:return _error(failure)
    finally:
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await finish_cleanup(asyncio.gather(*tasks,return_exceptions=True))


@router.get("/requests/{request_key:path}")
async def request_status(request:Request,request_key:str):
    try:return _reply({"creation":await _access(request).request(request_key)})
    except WIRE_ERRORS as failure:return _error(failure)


@router.post("/requests/{request_key:path}/control")
async def control(request:Request,request_key:str):
    try:
        payload=await _body(request,ContinuousControl)
        return _reply(await _access(request).control(request_key,payload.action,revision=payload.revision,
            expected=None if payload.expected is None else payload.expected.model_dump(),refresh_input=payload.refresh_input))
    except WIRE_ERRORS as failure:return _error(failure)


@router.post("/runs/{run_id}/results/query")
async def results(request:Request,run_id:str):
    try:
        payload=await _body(request,ResultQuery)
        return _reply(await _access(request).read(run_id,**payload.model_dump()))
    except WIRE_ERRORS as failure:return _error(failure)


@router.websocket("/runs/{run_id}/stream")
async def stream(websocket:WebSocket,run_id:str):
    tasks=[];subscription=None;lock=asyncio.Lock()
    async def send(packet):
        async with lock:await send_text_with_timeout(websocket,_encode({"protocol":PROTOCOL,**packet}))
    try:
        await websocket.accept()
        if websocket.query_params.get("protocol")!=PROTOCOL:
            raise BacktestError("PROTOCOL_UNSUPPORTED","Select the continuous.v1 stream protocol")
        after=_identity(websocket.query_params.get("after"))
        access=_access(websocket)
        async def forward():
            nonlocal subscription
            subscription=await access.subscribe(run_id,after=after)
            async for packet in subscription.events():await send(packet)
        async def receive():
            while True:
                packet=await websocket.receive()
                if packet["type"]=="websocket.disconnect":return
                if packet.get("text")=="ping":await send({"type":"pong","terminal":False})
                else:raise BacktestError("CONTINUOUS_INPUT_INVALID","Stream accepts only ping; use HTTP for control")
        tasks=[asyncio.create_task(forward()),asyncio.create_task(receive())]
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled():
                failure=task.exception()
                if failure is not None:raise failure
    except WIRE_ERRORS as failure:
        with suppress(WebSocketDisconnect,RuntimeError,TimeoutError):
            await send({"type":"error","terminal":True,
                "error":{"code":str(failure.code)[:64],"message":str(failure)[:256]}})
    except (WebSocketDisconnect,RuntimeError,TimeoutError):pass
    finally:
        if subscription is not None:subscription.close()
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await finish_cleanup(asyncio.gather(*tasks,return_exceptions=True))
        with suppress(WebSocketDisconnect,RuntimeError,TimeoutError):
            await asyncio.wait_for(websocket.close(),2)
