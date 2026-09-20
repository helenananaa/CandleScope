"""Native engine endpoints; host-matching endpoints retain their own ledger."""
from __future__ import annotations

from typing import Any, Literal
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.backtest.errors import BacktestError

router = APIRouter(prefix="/native", tags=["native-backtests"])
external_router = APIRouter(prefix="/external", tags=["external-backtests"])


class FrozenNativeData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=80)
    data_epoch: str = Field(min_length=8, max_length=80)
    snapshot_hash: str = Field(min_length=8, max_length=80)
    start_time_ms: int
    end_time_ms: int
    interval: str = Field(min_length=1, max_length=16)
    exchange: str = Field(default="binance", max_length=40)
    market_type: str = Field(default="usdm", max_length=40)

    @model_validator(mode="after")
    def check_range(self):
        if self.end_time_ms <= self.start_time_ms:
            raise ValueError("end_time_ms must follow start_time_ms")
        return self


class NativeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=120)
    timeframe: str = Field(min_length=1, max_length=16)


class RequestedNativeData(FrozenNativeData):
    symbol: str = Field(min_length=1, max_length=120)
    timeframe: str = Field(min_length=1, max_length=16)


class NativeRunRequest(FrozenNativeData):
    language: Literal["pine", "pyne"]
    source: str = Field(min_length=1, max_length=500_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: NativeContext
    contexts: list[RequestedNativeData] = Field(default_factory=list, max_length=16)
    libraries: dict[str, str] = Field(default_factory=dict)
    magnifier: FrozenNativeData | None = None


def _native(request):
    from .backtests import _runtime
    return _runtime(request).native


def _call(action):
    try:
        return action()
    except BacktestError as exc:
        from .backtests import _error
        return _error(exc)
    except (ValueError, OSError) as exc:
        return JSONResponse(status_code=400, content={"error": {"code": "NATIVE_INPUT_ERROR", "message": str(exc)}})


@router.get("/capabilities")
def capabilities(request: Request):
    return _call(lambda: _native(request).capabilities())


@router.post("/runs")
def create(request: Request, payload: NativeRunRequest,
           idempotency_key: str = Header(min_length=1, max_length=128)):
    return _call(lambda: _native(request).create(payload.model_dump(), idempotency_key))


@router.get("/runs")
def list_runs(request: Request):
    return _call(lambda: {"runs": [run for run in _native(request).list() if run["execution_mode"] == "NATIVE"]})


class HostMatchingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    price_tick: float | None = Field(default=None, gt=0)
    initial_balance: float = Field(default=10000, gt=0)
    slippage_bps: float = Field(default=1, ge=0, le=1000)
    taker_fee_bps: float = Field(default=0, ge=0, le=1000)


class ExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_ms: int
    role: Literal["TRADES", "ORDER_BOOK"]
    payload: dict[str, Any]


class ExecutionData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=120)
    events: list[ExecutionEvent] = Field(min_length=1, max_length=500_000)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ExternalRunRequest(NativeRunRequest):
    execution_mode: Literal["CANDLESCOPE"] = "CANDLESCOPE"
    execution_fidelity: Literal["BAR_APPROX", "TRADE_TAPE", "BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"] = "BAR_APPROX"
    fill_recalculation: bool = False
    execution_data: ExecutionData | None = None
    host_settings: HostMatchingSettings = Field(default_factory=HostMatchingSettings)


@external_router.post("/runs")
def create_external(request: Request, payload: ExternalRunRequest, idempotency_key: str = Header(min_length=1, max_length=128)):
    return _call(lambda: _native(request).create(payload.model_dump(), idempotency_key))


@external_router.get("/runs")
def list_external(request: Request):
    return _call(lambda: {"runs": [run for run in _native(request).list() if run["execution_mode"] == "CANDLESCOPE"]})


@router.get("/runs/{run_id}")
@external_router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str):
    return _call(lambda: _native(request).get(run_id))


@router.post("/runs/{run_id}/cancel")
@external_router.post("/runs/{run_id}/cancel")
def cancel(request: Request, run_id: str):
    return _call(lambda: _native(request).cancel(run_id))


@router.get("/runs/{run_id}/export")
@external_router.get("/runs/{run_id}/export")
def export(request: Request, run_id: str):
    # Includes original source, frozen data identities, engine identity and full raw output.
    return _call(lambda: JSONResponse(_native(request).get(run_id), headers={
        "Content-Disposition": f'attachment; filename="{run_id}.json"'}))


class ReplayCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=80)


class ReplayCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    action: Literal["play", "pause", "step", "seek", "snapshot", "restore"]
    target: int | None = Field(default=None, ge=0)
    snapshot_id: str | None = Field(default=None, max_length=80)


@router.post("/replays")
def create_replay(request: Request, payload: ReplayCreate):
    return _call(lambda: _native(request).replay.create(payload.run_id))


@router.get("/replays")
def list_replays(request: Request):
    return _call(lambda: {"replays": _native(request).replay.list()})


@router.get("/replays/{replay_id}")
def get_replay(request: Request, replay_id: str):
    return _call(lambda: _native(request).replay.get(replay_id))


@router.get("/replays/{replay_id}/export")
def export_replay(request: Request, replay_id: str):
    return _call(lambda: JSONResponse(_native(request).replay.get(replay_id), headers={
        "Content-Disposition": f'attachment; filename="{replay_id}.json"'}))


@router.post("/replays/{replay_id}/commands")
def command_replay(request: Request, replay_id: str, payload: ReplayCommand):
    def execute():
        service = _native(request).replay
        if payload.action == "snapshot":
            return service.snapshot(replay_id, payload.revision)
        if payload.action == "restore":
            return service.restore(replay_id, payload.revision, payload.snapshot_id)
        return service.command(replay_id, payload.revision, payload.action, payload.target)
    return _call(execute)
