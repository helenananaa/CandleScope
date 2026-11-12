"""Synthetic query/stream adapters. Computation and lifetime belong to DM."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.v1.stream_utils import send_json_with_timeout
from app.core.async_cleanup import finish_cleanup
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.synthetic_series.core import SyntheticConfig, SyntheticError
from app.data_engine.synthetic_series.service import SyntheticDefinition


router = APIRouter(prefix="/synthetic", tags=["synthetic"])


class SyntheticSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=128)
    interval: str = Field(min_length=1, max_length=32)
    exchange: str = Field(min_length=1, max_length=64)
    market_type: str = Field(min_length=1, max_length=64)
    provider_id: str | None = Field(default=None, max_length=64)
    venue: str | None = Field(default=None, max_length=64)
    asset_class: str = Field(default="crypto", max_length=64)
    series_variant: str = Field(default="native", max_length=64)
    price_adjustment: str = Field(default="raw", max_length=64)
    session_variant: str = Field(default="continuous", max_length=64)
    volume_semantics: str = Field(default="base_asset", max_length=64)


class SyntheticConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transform: str = Field(max_length=32)
    semantics: str = Field(default="display-window/1", max_length=32)
    mode: str = Field(default="traditional", max_length=32)
    box_size: float = Field(default=1, gt=0, allow_inf_nan=False)
    min_tick: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    atr_length: int = Field(default=14, ge=2, le=500)
    reversal_amount: float = Field(default=3, gt=0, allow_inf_nan=False)
    number_of_lines: int = Field(default=3, ge=1, le=50)


class SyntheticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: SyntheticSourceRequest
    config: SyntheticConfigRequest
    anchor: int = Field(ge=0, strict=True)
    through: int | None = Field(default=None, ge=0, strict=True)
    before: int | None = Field(default=None, ge=0, strict=True)
    limit: int = Field(default=5000, ge=1, le=5000)
    generation: str | None = Field(default=None, max_length=64)
    complete_window: bool = False

    def definition(self):
        return SyntheticDefinition(SeriesKey(**self.source.model_dump()),
            SyntheticConfig(**self.config.model_dump()), self.anchor, self.through)


def _service(scope):
    manager = getattr(scope.app.state, "data_manager", None)
    if manager is None:
        raise SyntheticError("market data unavailable")
    return manager.synthetic


@router.post("/query")
async def query_synthetic(request: Request, body: SyntheticRequest):
    lease = None
    try:
        lease = await _service(request).attach(body.definition())
        return await lease.snapshot(before=body.before, limit=body.limit, generation=body.generation)
    except SyntheticError as error:
        raise HTTPException(409, detail=str(error)) from error
    finally:
        if lease is not None:
            await finish_cleanup(lease.close())


@router.websocket("/stream")
async def stream_synthetic(websocket: WebSocket):
    await websocket.accept()
    lease = None
    tasks = []
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        if len(raw.encode()) > 8192:
            raise SyntheticError("synthetic request too large")
        body = SyntheticRequest.model_validate_json(raw)
        lease = await _service(websocket).attach(body.definition())
        async def send_snapshot():
            if body.complete_window:
                async for chunk in lease.snapshot_chunks(limit=body.limit):
                    await send_json_with_timeout(websocket, chunk)
            else:
                await send_json_with_timeout(websocket, await lease.snapshot(limit=body.limit))
        await send_snapshot()

        async def forward():
            while True:
                message = await lease.next()
                if message["type"] == "resync":
                    await send_snapshot()
                    continue
                await send_json_with_timeout(websocket, message)

        async def receive():
            while True:
                raw = await websocket.receive_text()
                if raw != "ping":
                    raise SyntheticError("subscription is immutable; reconnect to change it")
                await websocket.send_text("pong")

        tasks = [asyncio.create_task(forward()), asyncio.create_task(receive())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    except (SyntheticError, ValidationError, json.JSONDecodeError) as error:
        await send_json_with_timeout(websocket, {"type": "error", "status": "unavailable", "reason": str(error)})
        await websocket.close(code=1008)
    finally:
        async def cleanup():
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if lease is not None:
                await lease.close()
        await finish_cleanup(cleanup())
