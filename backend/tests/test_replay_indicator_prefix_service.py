from __future__ import annotations

import asyncio
from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import pytest
from app.replay.bars.builder import ReplayDisplayBar

from tests.test_replay_indicator_prefix import lines, reference
from tests.test_replay_v2_training_api import _app, _request
from tests.test_replay_v2_training_history import _create_run, _service

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "disclosure,interval",
    [("NONE", "1m"), ("HIDE_ALL", "1m"), ("NONE", "2m"), ("HIDE_ALL", "3m")],
)
async def test_real_history_http_window_and_service_restart(
    tmp_path, disclosure, interval
):
    path = tmp_path / "real-prefix.db"
    service, _ = await _service(path)
    try:
        _, snapshot = await _create_run(
            service,
            disclosure=disclosure,
            history_mode="ALL_AVAILABLE",
            requested_start_index=12,
        )
        boundary = snapshot["cursor"]["virtual_time_ms"]
        page = await service.training.history_page(
            "adapter-1",
            track_id="track-1",
            before_ms=boundary + 1,
            revealed_boundary_ms=boundary,
            limit=100,
            data_epoch=snapshot["data_epoch"],
            history_epoch=None,
            display_interval=interval,
        )
        assert len(page["bars"]) >= 3
        payload = {
            "track_id": "track-1",
            "display_interval": interval,
            "revealed_boundary_ms": boundary,
            "data_epoch": snapshot["data_epoch"],
            "name": "EMA",
            "params": {"period": 2},
            "bars": page["bars"][-2:],
        }
        before = deepcopy((await service.get_session("adapter-1"))["snapshot"])
        response = await _request(
            _app(service),
            "POST",
            "/api/v1/replay/runs/session/adapter-1/indicator-compute",
            json=payload,
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "ready"
        expected = reference(
            "EMA",
            {"period": 2},
            [ReplayDisplayBar.from_dict(row) for row in page["bars"]],
        )
        first = payload["bars"][0]["open_time_ms"] // 1000
        assert lines(result["payload"]) == [
            (name, [point for point in points if point["time"] >= first])
            for name, points in lines(expected)
        ]
        assert result["prefix_rows_read"] == len(page["bars"]) - 2
        assert (await service.get_session("adapter-1"))["snapshot"] == before
        shorter = await service.training.canonical_indicator_compute(
            "adapter-1", **{**payload, "bars": page["bars"][-1:]}
        )
        assert shorter["seed"] == result["seed"]
        assert lines(shorter["payload"])[0][1] == lines(result["payload"])[0][1][-1:]
    finally:
        await service.shutdown(step_timeout=1.0)
    # New service, worker pool, repository and cache connections; no live math object.
    reopened, _ = await _service(path)
    try:
        recovered = deepcopy((await reopened.get_session("adapter-1"))["snapshot"])
        restored = await reopened.training.canonical_indicator_compute(
            "adapter-1", **payload
        )
        assert restored["payload"] == result["payload"]
        assert restored["seed"] == result["seed"]
        assert restored["prefix_rows_read"] == 0
        assert (await reopened.get_session("adapter-1"))["snapshot"] == recovered
        assert recovered["status_reason"] == "recovered_after_restart"
        assert recovered["checkpoint_count"] == before["checkpoint_count"] + 1
        metadata = {"status_reason", "checkpoint_count"}
        assert {k: v for k, v in recovered.items() if k not in metadata} == {
            k: v for k, v in before.items() if k not in metadata
        }
    finally:
        await reopened.shutdown(step_timeout=1.0)


async def test_http_bad_epoch_future_and_invalid_contract_leave_account_unchanged(
    tmp_path,
):
    service, _ = await _service(tmp_path / "invalid-prefix.db")
    try:
        _, snapshot = await _create_run(service)
        boundary = snapshot["cursor"]["virtual_time_ms"]
        page = await service.training.history_page(
            "adapter-1",
            track_id="track-1",
            before_ms=boundary + 1,
            revealed_boundary_ms=boundary,
            limit=10,
            data_epoch=snapshot["data_epoch"],
            history_epoch=None,
        )
        payload = {
            "track_id": "track-1",
            "display_interval": "1m",
            "revealed_boundary_ms": boundary,
            "data_epoch": snapshot["data_epoch"],
            "name": "EMA",
            "params": {"period": 2},
            "bars": page["bars"],
        }
        before = deepcopy((await service.get_session("adapter-1"))["snapshot"])
        app = _app(service)
        invalid = [
            {**payload, "data_epoch": "sha256:" + "f" * 64},
            {**payload, "revealed_boundary_ms": boundary + 60_000},
            {**payload, "name": "CUSTOM_SCRIPT"},
            {**payload, "params": {"period": 0}},
            {**payload, "params": {"unknown": 2}},
            {**payload, "bars": []},
            {**payload, "unexpected": True},
            {**payload, "bars": [{**page["bars"][-1], "close_time_ms": boundary + 1}]},
            {**payload, "bars": [{**page["bars"][-1], "close": "NaN"}]},
            {**payload, "bars": [{**page["bars"][-1], "volume": "-1"}]},
        ]
        for item in invalid:
            response = await _request(
                app,
                "POST",
                "/api/v1/replay/runs/session/adapter-1/indicator-compute",
                json=item,
            )
            assert response.status_code in (409, 422), response.text
        assert (await service.get_session("adapter-1"))["snapshot"] == before
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_prefix_worker_leaves_account_writer_and_event_loop_available(
    tmp_path, monkeypatch
):
    from app.replay.training.indicator_history import PinnedIndicatorHistory

    service, _ = await _service(tmp_path / "worker-prefix.db")
    started, release = Event(), Event()
    original = PinnedIndicatorHistory.read

    def paused(self, *args):
        started.set()
        assert release.wait(5), "indicator prefix blocked the event loop"
        return original(self, *args)

    monkeypatch.setattr(PinnedIndicatorHistory, "read", paused)
    query = follower = None
    try:
        _, snapshot = await _create_run(
            service, history_mode="ALL_AVAILABLE", requested_start_index=12
        )
        boundary = snapshot["cursor"]["virtual_time_ms"]
        page = await service.training.history_page(
            "adapter-1",
            track_id="track-1",
            before_ms=boundary + 1,
            revealed_boundary_ms=boundary,
            limit=1,
            data_epoch=snapshot["data_epoch"],
            history_epoch=None,
        )
        query = asyncio.create_task(
            service.training.canonical_indicator_compute(
                "adapter-1",
                track_id="track-1",
                display_interval="1m",
                revealed_boundary_ms=boundary,
                data_epoch=snapshot["data_epoch"],
                name="RSI",
                params={},
                bars=page["bars"],
            )
        )
        assert await asyncio.to_thread(started.wait, 5)
        follower = asyncio.create_task(
            service.training.canonical_indicator_compute(
                "adapter-1",
                track_id="track-1",
                display_interval="1m",
                revealed_boundary_ms=boundary,
                data_epoch=snapshot["data_epoch"],
                name="RSI",
                params={},
                bars=page["bars"],
            )
        )
        value = await asyncio.wait_for(
            service.store.run_extension_write(
                lambda conn: conn.execute("SELECT 42").fetchone()[0]
            ),
            2,
        )
        assert value == 42
    finally:
        release.set()
        if query is not None:
            first = await query
            assert first["status"] == "ready" and first["prefix_rows_read"] == 11
        if follower is not None:
            second = await follower
            assert (
                second["payload"] == first["payload"]
                and second["prefix_rows_read"] == 0
            )
        await service.shutdown(step_timeout=1.0)


async def test_indicator_http_size_budget_is_separate_from_commands():
    from app.api.v1.replay import MAX_REPLAY_INDICATOR_REQUEST_BYTES

    received = []

    async def compute(session_id, **kwargs):
        received.append((session_id, kwargs))
        return {"status": "ready"}

    app = _app(
        SimpleNamespace(training=SimpleNamespace(canonical_indicator_compute=compute))
    )
    payload = {
        "track_id": "track-1",
        "display_interval": "1m",
        "revealed_boundary_ms": 1,
        "data_epoch": "sha256:" + "a" * 64,
        "name": "RSI",
        "bars": [{"fixture": "a" * 100}] * 1000,
    }
    url = "/api/v1/replay/runs/session/adapter-1/indicator-compute"
    response = await _request(app, "POST", url, json=payload)
    assert response.status_code == 200 and len(received) == 1
    assert len(received[0][1]["bars"]) == 1000
    invalid = await _request(app, "POST", url, json={**payload, "bars": [{}] * 10001})
    assert invalid.status_code == 422 and len(received) == 1
    oversize = await _request(
        app, "POST", url, content=b" " * (MAX_REPLAY_INDICATOR_REQUEST_BYTES + 1)
    )
    assert oversize.status_code == 413 and len(received) == 1
    command = await _request(app, "POST", "/api/v1/replay/runs", json=payload)
    assert command.status_code == 413


async def test_real_two_market_tape_and_forming_volume_keep_account_state(tmp_path):
    from app.replay.training.models import ReplayV2CommandType

    from tests.test_replay_tape_phases import setup_tape
    from tests.test_replay_v2_training_phase6 import _send

    service, run_id, session_id = await setup_tape(tmp_path, held=True)
    try:
        state = await service.get_session_state(session_id)
        target = (state["cursor"]["virtual_time_ms"] // 60_000 + 2) * 60_000 + 1200
        await _send(
            service,
            run_id=run_id,
            session_id=session_id,
            command_id="indicator-tape-prefix",
            command_type=ReplayV2CommandType.ADVANCE_TO,
            payload={"virtual_time_ms": target},
        )
        seeds = []
        for number in (1, 2):
            sid = f"trade-adapter-{number}"
            snapshot = deepcopy((await service.get_session(sid))["snapshot"])
            rows = snapshot["components"]["bar_builder"]["public_projection"]["bars"]
            assert len(rows) >= 4 and not rows[-1]["is_closed"]
            for name, params in (("RSI", {"period": 2}), ("VOL", {})):
                args = {
                    "track_id": f"track-{number}",
                    "display_interval": "1m",
                    "revealed_boundary_ms": snapshot["cursor"]["virtual_time_ms"],
                    "data_epoch": snapshot["data_epoch"],
                    "name": name,
                    "params": params,
                    "bars": rows[-2:],
                }
                result = await service.training.canonical_indicator_compute(sid, **args)
                expected = reference(
                    name, params, [ReplayDisplayBar.from_dict(row) for row in rows]
                )
                first_time = rows[-2]["open_time_ms"] // 1000
                assert lines(result["payload"]) == [
                    (title, [p for p in points if p["time"] >= first_time])
                    for title, points in lines(expected)
                ]
                if name == "RSI":
                    seeds.append(result["seed"])
            assert (await service.get_session(sid))["snapshot"] == snapshot
        assert seeds[0]["identity"]["symbol"] != seeds[1]["identity"]["symbol"]
        assert seeds[0]["session_id"] != seeds[1]["session_id"]
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=3)
