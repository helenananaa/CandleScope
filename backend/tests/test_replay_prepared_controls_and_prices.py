from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.replay.training.public_price_blocks import (
    prepare_price_blocks,
    read_price_blocks,
    _index_path,
)
from app.replay.training.models import ReplayV2CommandType as C
from tests.fixtures.replay.multi_interval_fakes import make_multi
from tests.fixtures.replay.shared_market_fakes import install_shared_market


def test_price_blocks_range_checksum_and_source_change(tmp_path):
    path = tmp_path / "prices.json"
    path.write_bytes(b"verified fixture")
    checksum = "sha256:" + sha256(path.read_bytes()).hexdigest()
    events = tuple(
        SimpleNamespace(
            event_time_ms=i * 60_000,
            event_phase=30,
            event_kind="MARK_INDEX",
            event_sequence=i + 1,
            payload={"mark_price": str(i + 1)},
        )
        for i in range(3000)
    )
    prepare_price_blocks(path, checksum, events)
    rows = read_price_blocks(path, checksum, 1000, 2050)
    assert len(rows) == 1050 and rows[0][-1] == "1001" and rows[-1][-1] == "2050"
    assert read_price_blocks(path, checksum, 0, 0) == []
    import sqlite3

    with sqlite3.connect(_index_path(path)) as connection:
        connection.execute("UPDATE blocks SET digest='wrong' WHERE id=1")
    with pytest.raises(ValueError, match="checksum"):
        read_price_blocks(path, checksum, 1024, 1025)
    path.write_bytes(b"different source")
    with pytest.raises(ValueError, match="source"):
        read_price_blocks(path, checksum, 0, 1)


@pytest.mark.anyio
async def test_preparation_acquires_all_without_advancing_and_renews_owned_leases(
    tmp_path, monkeypatch
):
    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(
        tmp_path / "run", tracks=8, horizon=100, warmup=200
    )
    try:
        await send("release", C.RELEASE_CONTROLLER, {})
        before = {
            sid: (await service.get_session_state(sid))["cursor"]
            for sid in service._sessions
        }
        builders = {
            sid: handle.actor._reducer._bar_builder.snapshot()
            for sid, handle in service._sessions.items()
        }
        result = await service.training.prepare_indexed_run(
            run, client_instance_id="new-browser"
        )
        assert result["controller_ready"]
        inputs = await service.training.hedge_inputs.runtime_snapshot(run)
        cached_ids = {
            id(event)
            for events in service.training.hedge_inputs._verified_event_cache.values()
            for event in events
        }
        assert all(id(event) in cached_ids for event in inputs[0])
        for sid in before:
            current = await service.get_session_state(sid)
            assert current["controller_client_id"] == "new-browser"
            assert current["cursor"] == before[sid]
            assert (
                service._sessions[sid].actor._reducer._bar_builder.snapshot()
                == builders[sid]
            )
            from copy import copy

            index = service._sessions[sid].actor._prepared_bar_interval
            cold = copy(index)
            cold._transport_origins = {}
            for end in (1, 8, 31):
                assert (
                    index.builder_at(end, tail_limit=16).snapshot()
                    == cold.builder_at(end, tail_limit=16).snapshot()
                )
        calls = []
        for sid, handle in service._sessions.items():
            original = handle.actor.heartbeat

            async def heartbeat(client, *, _sid=sid, _original=original):
                calls.append(_sid)
                return await _original(client)

            monkeypatch.setattr(handle.actor, "heartbeat", heartbeat)
        await service.heartbeat(session, "new-browser")
        assert set(calls) == set(before) and len(calls) == 8
        refused = await service.training.prepare_indexed_run(
            run, client_instance_id="other-browser"
        )
        assert not refused["controller_ready"]
        for sid in before:
            assert (await service.get_session_state(sid))[
                "controller_client_id"
            ] == "new-browser"
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_prepared_curve_does_not_reparse_public_archives(tmp_path, monkeypatch):
    import json
    from app.replay.training import hedge_inputs
    from app.replay.training.multi_interval_store import reconstruct_portfolio_interval

    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", horizon=100)
    try:
        await service.training.prepare_indexed_run(run)
        before = (await service.get_session_state(session))["cursor"]["virtual_time_ms"]
        await send(
            "advance",
            C.ADVANCE_TO,
            {"virtual_time_ms": before + 90 * 60000, "stop_on_event": False},
        )
        row = await service.store.run_extension_read(
            lambda c: c.execute(
                "SELECT basis_json,summary_json FROM replay_multi_bar_interval WHERE run_id=? ORDER BY end_time_ms-start_time_ms DESC LIMIT 1",
                (run,),
            ).fetchone()
        )

        def forbid(*args, **kwargs):
            raise AssertionError("prepared curve reparsed a complete archive")

        monkeypatch.setattr(hedge_inputs, "verify_hedge_public_history", forbid)
        monkeypatch.setattr(hedge_inputs, "_read_public_events", forbid)
        monkeypatch.setattr(hedge_inputs, "_read_verified_public_events", forbid)
        result = await service.store.run_worker(
            "curve-test",
            reconstruct_portfolio_interval,
            json.loads(row[0]),
            input_root=service.training.hedge_inputs.root,
            bucket_ms=60000,
        )
        assert {k: v for k, v in result.items() if k != "points"} == json.loads(row[1])
        assert result["points"]
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_controller_group_conflict_rolls_back_without_degrading_storage(
    tmp_path, monkeypatch
):
    from app.replay.multi_commit import commit_actor_commands
    from app.replay.models import ReplayCommand, CommandType, REPLAY_PROTOCOL
    from app.replay.errors import ReplayDomainError, ReplayErrorCode

    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", horizon=100)
    try:
        await send("release", C.RELEASE_CONTROLLER, {})
        commands = []
        for i, sid in enumerate(service._sessions):
            state = await service.get_session_state(sid)
            commands.append(
                (
                    sid,
                    ReplayCommand(
                        protocol=REPLAY_PROTOCOL,
                        command_id=f"conflict-{i}",
                        client_instance_id="new-browser",
                        expected_revision=state["revision"] - i,
                        type=CommandType.ACQUIRE_CONTROLLER,
                        payload={"takeover": False},
                    ),
                )
            )
        with pytest.raises(ReplayDomainError) as error:
            await commit_actor_commands(
                service, commands, before=lambda _: None, after=lambda _: None
            )
        assert error.value.code is ReplayErrorCode.REVISION_CONFLICT
        for sid, command in commands:
            state = await service.get_session_state(sid)
            assert state["controller_client_id"] is None
            assert state["state"] == "PAUSED"
            assert state.get("degraded_reason") is None
            assert await service.store.get_command(sid, command.command_id) is None
    finally:
        await service.shutdown(step_timeout=5)


@pytest.mark.anyio
async def test_final_ack_is_atomic_and_unobserved_tracks_require_snapshot(
    tmp_path, monkeypatch
):
    import json
    from app.replay.constants import ReplayEventType

    install_shared_market(monkeypatch, tmp_path / "market")
    service, run, session, send = await make_multi(tmp_path / "run", horizon=100)
    actor, subscription = await service.subscribe(
        session, after_sequence=None, data_epoch=None
    )
    try:
        before = {
            sid: (await service.get_session_state(sid))["sequence"]
            for sid in service._sessions
        }
        at = (await service.get_session_state(session))["cursor"]["virtual_time_ms"]

        def count_intervals(c):
            return c.execute(
                "SELECT COUNT(*) FROM replay_multi_bar_interval WHERE run_id=? AND basis_json LIKE '%multi-bar-interval.v1%'",
                (run,),
            ).fetchone()[0]

        count = await service.store.run_extension_read(count_intervals)
        writes = service.store._metrics["transactions"]

        async def no_separate_ack(**kwargs):
            raise AssertionError("terminal ACK used another transaction")

        monkeypatch.setattr(
            service.training.store, "finish_advance_intent", no_separate_ack
        )
        result = await send(
            "atomic-ack",
            C.ADVANCE_TO,
            {"virtual_time_ms": at + 90 * 60000, "stop_on_event": False},
        )
        assert (
            service.store._metrics["transactions"] - writes
            == await service.store.run_extension_read(count_intervals) - count
        )
        stored = await service.store.run_extension_read(
            lambda c: c.execute(
                "SELECT status,result_json FROM replay_training_advance_intent WHERE run_id=? AND command_id='atomic-ack'",
                (run,),
            ).fetchone()
        )
        assert stored[0] == "COMPLETED"
        assert json.loads(stored[1])["data"] == result["data"]
        for sid, handle in service._sessions.items():
            events = handle.actor._events.after(before[sid])
            expected = (
                ReplayEventType.FINAL_STATE
                if sid == session
                else ReplayEventType.RESYNC_REQUIRED
            )
            assert events and all(event.type is expected for event in events)
            if sid != session:
                late_actor, late = await service.subscribe(
                    sid, after_sequence=before[sid], data_epoch=None
                )
                assert any(
                    event.type is ReplayEventType.RESYNC_REQUIRED
                    for event in late.initial_events
                )
                await late_actor.unsubscribe(late.token)
                _, fresh = await service.subscribe(
                    sid, after_sequence=None, data_epoch=None
                )
                assert (
                    fresh.initial_events[0].data["snapshot"]["cursor"][
                        "source_sequence"
                    ]
                    == result["cursor"]["source_sequence"]
                )
                await late_actor.unsubscribe(fresh.token)
    finally:
        await actor.unsubscribe(subscription.token)
        await service.shutdown(step_timeout=5)
