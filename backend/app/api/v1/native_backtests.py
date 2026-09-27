"""Native engine endpoints; host-matching endpoints retain their own ledger."""
from __future__ import annotations

from app.backtest.native_contracts import (
    NativeRunRequest,
    ExternalRunRequest,
    ReplayCreate,
    ReplayCommand,
)

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from app.backtest.errors import BacktestError

router = APIRouter(prefix="/native", tags=["native-backtests"])
external_router = APIRouter(prefix="/external", tags=["external-backtests"])


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
