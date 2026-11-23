"""Extend the isolated browser host with real saved/local/replay owners."""
import asyncio
from pathlib import Path
import time

from tests.synthetic_browser_server import app, _fixture_profile, shutdown as close_base
from tests.test_backtest_research_source import _runtime
from tests.test_synthetic_pinned import imported
from tests.test_replay_v2_training_history import _service, _create_run
from tests.test_replay_v2_training_phase5 import _acquire
from tests.test_replay_v2_training_phase6 import _send
from app.replay.training.models import ReplayV2CommandType

app.router.on_shutdown.remove(close_base)


@app.on_event("startup")
async def pinned_owners():
    profile = Path(_fixture_profile.name)
    runtime = _runtime(profile / "backtest")
    app.state.backtest_runtime = runtime
    app.state.local_data_service = runtime.local_data
    manifest = imported(runtime.local_data, profile / "input.csv")
    preview = runtime.preview_snapshot(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"],
        start_time_ms=0, end_time_ms=299999, interval="1m")
    record = runtime.service.create_run(dict(strategy_revision_id="builtin-sma-cross-v1",
        dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"], snapshot_hash=preview["snapshot_hash"],
        fidelity_mode="BAR_APPROX", start_time_ms=0, end_time_ms=299999, interval="1m",
        parameters={"fast": 2, "slow": 3}), idempotency_key="synthetic-browser")
    deadline = time.monotonic() + 15
    while record["state"] not in {"COMPLETED", "FAILED"} and time.monotonic() < deadline:
        await asyncio.sleep(.02)
        record = runtime.service.get_run(record["run_id"])
    assert record["state"] == "COMPLETED"
    app.state.pinned_saved = {"run": record, "report": runtime.service.get_report(record["run_id"]),
        "chart": runtime.chart_data(record["run_id"]), "manifest": manifest}
    replay, _ = await _service(profile / "replay.db")
    app.state.replay_service = replay
    created, snapshot = await _create_run(replay)
    app.state.pinned_replay_run = created["run"]["run_id"]
    app.state.pinned_replay_session = snapshot["session_id"]
    await _acquire(replay, run_id=app.state.pinned_replay_run, selected_session_id=snapshot["session_id"], command_id="browser-acquire")
    app.state.pinned_step = 0


async def captured_replay():
    replay, sid = app.state.replay_service, app.state.pinned_replay_session
    snapshot = (await replay.get_session(sid))["snapshot"]
    cursor = snapshot["cursor"]
    page = await replay.training.history_page(sid, track_id="track-1", data_epoch=snapshot["data_epoch"],
        revealed_boundary_ms=cursor["virtual_time_ms"], before_ms=cursor["virtual_time_ms"] + 1,
        history_epoch=None, display_interval="1m", limit=100)
    return {"origin": {"kind": "REPLAY", "session_id": sid, "track_id": "track-1", "data_epoch": snapshot["data_epoch"],
        "history_epoch": page["history_epoch"], "revealed_boundary_ms": cursor["virtual_time_ms"], "source_sequence": cursor["source_sequence"]},
        "rows": [{"time": row["open_time_ms"] // 1000,
            **{field: float(row[field]) for field in ("open", "high", "low", "close", "volume")},
            "is_closed": row["is_closed"]} for row in page["bars"]]}


@app.get("/api/v1/fixture/pinned")
async def pinned():
    return {"saved": app.state.pinned_saved, "replay": await captured_replay()}


@app.post("/api/v1/fixture/pinned/step")
async def step():
    app.state.pinned_step += 1
    await _acquire(app.state.replay_service, run_id=app.state.pinned_replay_run,
        selected_session_id=app.state.pinned_replay_session, command_id=f"browser-reacquire-{app.state.pinned_step}")
    await _send(app.state.replay_service, run_id=app.state.pinned_replay_run, session_id=app.state.pinned_replay_session,
        command_id=f"browser-step-{app.state.pinned_step}", command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
    return await captured_replay()


@app.on_event("shutdown")
async def close_pinned():
    await app.state.replay_service.shutdown()
    app.state.backtest_runtime.shutdown()
    await close_base()
