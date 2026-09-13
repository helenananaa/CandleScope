import json
import asyncio
import threading

import pytest

from app.replay.training.models import ReplayV2CommandType as C
from tests.fixtures.replay.multi_interval_fakes import make_multi
from tests.fixtures.replay.shared_market_fakes import install_shared_market


@pytest.mark.anyio
async def test_unsupported_atomic_pair_fails_without_waiting_for_builders():
    from app.replay.multi_phase_commit import commit_actor_phases
    from app.replay.models import ReplayCommand
    from app.replay.constants import CommandType, REPLAY_PROTOCOL

    with pytest.raises(ValueError):
        await commit_actor_phases(None, [])
    command = ReplayCommand(
        protocol=REPLAY_PROTOCOL, command_id="invalid-pair", client_instance_id="client",
        expected_revision=0, type=CommandType.ACQUIRE_CONTROLLER, payload={"takeover": False},
    )
    with pytest.raises(ValueError):
        await commit_actor_phases(None, [{"commands": [("session", command)]}]*2)


@pytest.mark.anyio
@pytest.mark.parametrize("fail", [False, True, "second_builder"])
async def test_lowpoint_and_endpoint_commit_together(tmp_path, monkeypatch, fail):
    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(
        tmp_path / "run", tracks=8, horizon=50, initial_equity="10000",
        marks=["100"]*5 + ["80"] + ["110"]*45,
    )
    try:
        current = await service.get_session_state(session)
        await service.training.prepare_indexed_run(run, client_instance_id=current["controller_client_id"])
        before = {sid: await service.get_session_state(sid) for sid in service._sessions}
        latency_counts = {
            sid: handle.actor._command_ack_latency.snapshot()["samples"]
            for sid, handle in service._sessions.items()
        }
        writes = service.store._metrics["transactions"]
        if fail == "second_builder":
            from app.replay.broker.shared_prepared import SharedPreparedInterval
            original_apply = SharedPreparedInterval.apply
            applies = []

            def broken(index, *args, **kwargs):
                applies.append(index)
                if len(applies) == 10:
                    raise RuntimeError("injected failure in second phase builder")
                return original_apply(index, *args, **kwargs)

            monkeypatch.setattr(SharedPreparedInterval, "apply", broken)
        original = service.store.commit_command_phases
        captured = []
        command_results = {}
        original_command = service.command

        async def record_command(sid, command, **kwargs):
            result = await original_command(sid, command, **kwargs)
            command_results[command.command_id] = result
            return result

        monkeypatch.setattr(service, "command", record_command)

        async def observe(phases):
            captured.extend(phases)
            assert len(phases) == 2
            assert all(len(rows) == 8 for rows, _, _ in phases)
            for sid, state in before.items():
                assert not service._sessions[sid].actor._events.after(state["sequence"])
            if fail:
                rows, pre, post = phases[0]

                def failure(connection):
                    post(connection)
                    raise RuntimeError("injected failure after durable-prefix construction")

                phases = [(rows, pre, failure), phases[1]]
            return await original(phases)

        monkeypatch.setattr(service.store, "commit_command_phases", observe)
        target = current["cursor"]["virtual_time_ms"] + 30*60000
        if fail:
            with pytest.raises(Exception):
                await send("batched", C.ADVANCE_TO, dict(virtual_time_ms=target, stop_on_event=False))
            for sid, prior in before.items():
                after = await service.get_session_state(sid)
                assert after["cursor"] == prior["cursor"]
                assert after["state_hash"] == prior["state_hash"]
            assert service.store._metrics["transactions"] == writes
        else:
            result = await send("batched", C.ADVANCE_TO, dict(virtual_time_ms=target, stop_on_event=False))
            assert result["cursor"]["virtual_time_ms"] == target
            assert service.store._metrics["transactions"] - writes == 1
            rows = await service.store.run_extension_read(lambda c: c.execute(
                "SELECT start_time_ms,end_time_ms,summary_json FROM replay_multi_bar_interval WHERE command_id LIKE 'batched:multi:%' ORDER BY start_time_ms"
            ).fetchall())
            assert len(rows) == 2
            assert rows[0][1] == rows[1][0]
            assert json.loads(rows[0][2])["last"] == json.loads(rows[0][2])["trough"]
            for prefix in captured[0][0]:
                command_id = prefix["command"]["command_id"]
                assert command_results[command_id]["command_id"] == command_id
                assert command_results[command_id]["cursor"] == prefix["result"]["cursor"]
                checkpoint = await service.store.run_extension_read(lambda c: c.execute(
                    "SELECT 1 FROM replay_checkpoint WHERE session_id=? AND state_hash=?",
                    (prefix["session_id"], prefix["session_state"]["state_hash"]),
                ).fetchone())
                assert checkpoint is not None, "lowpoint must retain its actual actor checkpoint"
            assert (await service.training.audit_account(run))["status"] == "PASS"
        assert len(captured) == (0 if fail == "second_builder" else 2)
        for sid, count in latency_counts.items():
            assert service._sessions[sid].actor._command_ack_latency.snapshot()["samples"] == count + 1
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_mark_lowpoint_before_next_bar_keeps_exact_fallback(tmp_path, monkeypatch):
    install_shared_market(monkeypatch, tmp_path / "market")
    outcomes = []
    for enabled in (True, False):
        service, run, session, send = await make_multi(
            tmp_path / str(enabled), enabled=enabled, horizon=30,
            marks=["100", "100", "80"] + ["110"]*28,
        )
        try:
            before = await service.get_session_state(session)
            await send("low-between-bars", C.ADVANCE_TO, dict(
                virtual_time_ms=before["cursor"]["virtual_time_ms"]+10*60000,
                stop_on_event=False,
            ))
            tracks = await service.training.store.get_market_track_heads(run)
            outcomes.append([(t["cursor"], t["position"], t["account"]) for t in tracks])
            assert (await service.training.audit_account(run))["status"] == "PASS"
        finally:
            await service.shutdown(step_timeout=5)
    assert outcomes[0] == outcomes[1]


@pytest.mark.anyio
async def test_cancelled_request_drains_atomic_phase_commit(tmp_path, monkeypatch):
    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(
        tmp_path / "run", horizon=40, marks=["100"]*5+["80"]+["110"]*35,
    )
    release = threading.Event()
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    task = None
    try:
        before = await service.training.store.get_market_track_heads(run)
        state = await service.get_session_state(session)
        original = service.store.commit_command_phases

        async def paused(phases):
            rows, pre, post = phases[0]

            def pause(connection):
                post(connection)
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(10):
                    raise TimeoutError("test commit was not released")

            return await original([(rows, pre, pause), phases[1]])

        monkeypatch.setattr(service.store, "commit_command_phases", paused)
        target = state["cursor"]["virtual_time_ms"]+30*60000
        task = asyncio.create_task(send("cancel-request", C.ADVANCE_TO, dict(
            virtual_time_ms=target, stop_on_event=False,
        )))
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        visible = await service.training.store.get_market_track_heads(run)
        assert [t["cursor"] for t in visible] == [t["cursor"] for t in before]
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        after = await service.training.store.get_market_track_heads(run)
        assert all(t["cursor"]["virtual_time_ms"] == target for t in after)
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await service.shutdown(step_timeout=5)
