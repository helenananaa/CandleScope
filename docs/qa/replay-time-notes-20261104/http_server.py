"""Real router/SQLite run with explicit fixture candles and no public network."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from app.local_data.network_guard import OfflineNetworkGuard

guard = OfflineNetworkGuard()
guard.install()

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.replay import router
from app.data_engine.data_manager.core import DataManagerCore
from app.replay.training.models import ReplayV2CommandType
from app.replay.training.errors import TrainingRunError
from tests.fixtures.replay.service_fakes import INTERVAL_MS
from tests.test_replay_v2_training_phase5 import _service, _request, _acquire, _command

root = Path(os.environ["CANDLESCOPE_NOTE_QA_ROOT"])
root.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app):
    service = await _service(root / "replay.db", controller_ttl_seconds=300)
    app.state.service = service
    core = DataManagerCore()
    core.bind_replay(service)
    app.state.data_manager_core = core
    def existing(db):
        return db.execute("SELECT run_id,adapter_session_id FROM replay_training_run ORDER BY created_at_ms,run_id LIMIT 1").fetchone()
    row = await service.store.run_extension_read(existing)
    if row is None:
        run = (await service.training.create_run(await _request(service)))["run"]
        run_id, session_id = run["run_id"], run["adapter_session_id"]
    else:
        run_id, session_id = row["run_id"], row["adapter_session_id"]
    app.state.run_id, app.state.session_id = run_id, session_id
    reviewing = await service.store.run_extension_read(lambda db: db.execute(
        "SELECT 1 FROM replay_review_session WHERE run_id=? LIMIT 1", (run_id,)).fetchone() is not None)
    if not reviewing:
        await _acquire(service, run_id=run_id, selected_session_id=session_id, command_id=f"notes-acquire-{os.getpid()}")
    (root / "ready.json").write_text(json.dumps({"pid": os.getpid(), "runId": run_id, "port": int(os.environ["CANDLESCOPE_NOTE_QA_PORT"])}))
    try:
        yield
    finally:
        await core.shutdown_replay(step_timeout=1)
        await service.shutdown(step_timeout=1)
        (root / f"exit-{os.getpid()}.json").write_text(json.dumps({"pid": os.getpid(), "network": guard.snapshot(), "manager": core.replay.diagnostics() if core.replay else None}))
        guard.uninstall()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api/v1")


@app.exception_handler(TrainingRunError)
async def domain_error(_request, error):
    return JSONResponse(error.to_payload(), status_code=error.status_code)


def training():
    return app.state.data_manager_core.replay.control_plane().training


@app.get("/fixture/state")
async def state():
    service = app.state.service
    tracks = await training().get_market_tracks(app.state.run_id)
    track = tracks["tracks"][0]["track_id"]
    notes = await training().notes(app.state.run_id, track)
    snapshot = (await service.get_session(app.state.session_id))["snapshot"]
    return {"pid": os.getpid(), "context": notes["context"], "snapshot": snapshot,
            "network": guard.snapshot(), "manager": app.state.data_manager_core.replay.diagnostics()}


@app.post("/fixture/advance")
async def advance():
    service = app.state.service
    current = await state()
    target = current["context"]["virtualTimeMs"] + 2 * INTERVAL_MS
    snapshot = await service.get_session(app.state.session_id)
    await training().command(app.state.run_id, _command(app.state.run_id, f"notes-advance-{target}",
        ReplayV2CommandType.ADVANCE_TO, snapshot, {"virtual_time_ms": target}))
    return await state()


@app.post("/fixture/buy")
async def buy():
    service = app.state.service
    snapshot = await service.get_session(app.state.session_id)
    await training().command(app.state.run_id, _command(app.state.run_id, f"notes-buy-{os.getpid()}",
        ReplayV2CommandType.PLACE_ORDER, snapshot, {"client_order_id": f"note-buy-{os.getpid()}",
        "side": "BUY", "order_type": "MARKET", "quantity": "0.1", "reduce_only": False,
        "limit_price": None, "stop_price": None}))
    return await state()


@app.post("/fixture/close")
async def close():
    service = app.state.service
    snapshot = await service.get_session(app.state.session_id)
    await training().command(app.state.run_id, _command(app.state.run_id, f"notes-close-{os.getpid()}",
        ReplayV2CommandType.PLACE_ORDER, snapshot, {"client_order_id": f"note-close-{os.getpid()}",
        "side": "SELL", "order_type": "MARKET", "quantity": "0.1", "reduce_only": True,
        "limit_price": None, "stop_price": None}))
    return await state()


@app.post("/fixture/marker")
async def marker():
    await training().record_review_marker(app.state.run_id, command_id=f"notes-marker-{os.getpid()}", text="same-time note event boundary")
    return await state()


@app.post("/fixture/review-first")
async def review_first():
    review = await training().start_review(app.state.run_id, event_id=None)
    await training().start_review(app.state.run_id, event_id=review["events"][0]["event_id"])
    return await state()


@app.post("/fixture/review-last")
async def review_last():
    review = await training().start_review(app.state.run_id, event_id=None)
    await training().start_review(app.state.run_id, event_id=review["events"][-1]["event_id"])
    return await state()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["CANDLESCOPE_NOTE_QA_PORT"]), log_level="info")
