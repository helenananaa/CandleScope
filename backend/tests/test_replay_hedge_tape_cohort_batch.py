import sqlite3
from dataclasses import replace

import pytest
from app.replay.training import control_rules
from app.replay.training.errors import TrainingRunError
from app.replay.training.models import ReplayV2CommandType

from tests import test_replay_v2_training_phase5 as fixtures
from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request
from tests.test_replay_v2_training_phase6 import _send

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("batch_size", [1, 3, 5])
async def test_hedge_batch_never_leaves_older_marks_behind_a_partial_trade_cohort(tmp_path, monkeypatch, batch_size):
    sources = fixtures._multi_trade_sources
    monkeypatch.setattr(fixtures, "_multi_trade_sources", lambda *args, **kwargs:
                        sources(*args, coalesce_trade_timestamps=True, **kwargs))
    monkeypatch.setattr(control_rules, "FINAL_STATE_EMPTY_ACCOUNT_INTERACTIVE_BATCH_UNITS", batch_size)
    service = await fixtures._trade_service(tmp_path / "cohort.db", archive_root=tmp_path / "tape", symbols=("BTCUSDT",))
    service.settings = replace(service.settings, replay_fast_forward_optimization_enabled=True)
    try:
        request = await prepare_hedge_request(
            service, replace(await fixtures._trade_request(service), integrity_mode="SANDBOX"),
            root=tmp_path, prefix="cohort", book_mode="OFF", funding_event_offset_bars=10,
        )
        created = await service.training.create_run(request)
        run_id, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await fixtures._acquire(service, run_id=run_id, selected_session_id=sid, command_id="cohort-acquire")
        advanced = await _send(service, run_id=run_id, session_id=sid, command_id="cohort-advance",
                               command_type=ReplayV2CommandType.ADVANCE,
                               payload={"basis": "BASE_BAR", "count": 3})
        assert advanced["cursor"]["virtual_time_ms"] == request.requested_start_ms + 3 * 60_000 - 1
        result = await service.training.get_market_tracks(run_id)
        assert result["portfolio"]["equity"] == "10000"
        assert result["portfolio"]["hedge_inputs"]["status"] == "ACTIVE"
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
        await _assert_complete_global_prefix(service, run_id)
    finally:
        await service.shutdown(step_timeout=1.0)


async def _assert_complete_global_prefix(service, run_id):
    events = await service.training.store.global_events(run_id)
    keys = [(e["actual_event_time_ms"], e["event_phase"], e["track_id"], e["source_sequence"]) for e in events]
    assert keys == sorted(set(keys))
    tracks = await service.training.store.get_market_track_heads(run_id)
    for track in tracks:
        source = [e["source_sequence"] for e in events if e["track_id"] == track["track_id"]]
        assert source == list(range(1, track["cursor"]["source_sequence"] + 1))


@pytest.mark.parametrize("initial_bars,interrupt_write,time_policy", [
    (0, False, "NONE"), (0, True, "NONE"), (1, False, "NONE"), (1, True, "HIDE_ALL"),
])
async def test_legacy_partial_cohort_recovery_restores_exact_global_prefix(
        tmp_path, monkeypatch, initial_bars, interrupt_write, time_policy):
    sources = fixtures._multi_trade_sources
    monkeypatch.setattr(fixtures, "_multi_trade_sources", lambda *args, **kwargs:
                        sources(*args, coalesce_trade_timestamps=True, **kwargs))
    monkeypatch.setattr(control_rules, "FINAL_STATE_EMPTY_ACCOUNT_INTERACTIVE_BATCH_UNITS", 3)
    database, archive_root = tmp_path / "recovery.db", tmp_path / "tape"
    service = await fixtures._trade_service(database, archive_root=archive_root, symbols=("BTCUSDT",))
    service.settings = replace(service.settings, replay_fast_forward_optimization_enabled=True)
    try:
        request = await prepare_hedge_request(
            service, replace(await fixtures._trade_request(service), integrity_mode="SANDBOX",
                             time_disclosure_policy=time_policy),
            root=tmp_path, prefix="recover-cohort", book_mode="OFF", funding_event_offset_bars=10,
        )
        created = await service.training.create_run(request)
        run_id, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await fixtures._acquire(service, run_id=run_id, selected_session_id=sid, command_id="acquire")
        start = (await service.training.store.get_market_track_heads(run_id))[0]["cursor"]["virtual_time_ms"]
        if initial_bars:
            await _send(service, run_id=run_id, session_id=sid, command_id="first-complete",
                        command_type=ReplayV2CommandType.ADVANCE,
                        payload={"basis": "BASE_BAR", "count": initial_bars})
        original_plan = service.plan_source_chunk

        async def old_plan(*args, **kwargs):
            # Simulate the legacy caller accepting a truncated last timestamp.
            return {**await original_plan(*args, **kwargs), "has_more_before_target": False}

        with monkeypatch.context() as patch:
            patch.setattr(service, "plan_source_chunk", old_plan)
            with pytest.raises(TrainingRunError, match="input timeline") as failure:
                await _send(service, run_id=run_id, session_id=sid, command_id="legacy-fail",
                            command_type=ReplayV2CommandType.ADVANCE,
                            payload={"basis": "BASE_BAR", "count": 3-initial_bars})
        assert failure.value.code == "HEDGE_INPUT_CURSOR_BEHIND_MARKET"
        base = service.training.hedge_inputs.store

        def state(connection):
            return {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} WHERE run_id=?", (run_id,))]
                    for table in ("replay_training_global_event", "replay_training_global_checkpoint",
                                  "replay_hedge_mark_span", "replay_hedge_input_binding",
                                  "replay_hedge_track_public_binding", "replay_hedge_track_public_projection")}

        if interrupt_write:
            before = await base.run_extension_read(state)
            await base.run_extension_write(lambda connection: connection.execute(
                "CREATE TEMP TRIGGER fail_recovery BEFORE INSERT ON replay_training_global_event "
                "BEGIN SELECT RAISE(ABORT,'injected global recovery interruption'); END"))
            with pytest.raises(sqlite3.IntegrityError, match="injected global recovery interruption"):
                await _send(service, run_id=run_id, session_id=sid, command_id="interrupted",
                            command_type=ReplayV2CommandType.ADVANCE,
                            payload={"basis": "BASE_BAR", "count": 1})
            assert await base.run_extension_read(state) == before
            await base.run_extension_write(lambda connection: connection.execute("DROP TRIGGER fail_recovery"))
        advanced = await _send(service, run_id=run_id, session_id=sid, command_id="recover",
                               command_type=ReplayV2CommandType.ADVANCE,
                               payload={"basis": "BASE_BAR", "count": 2})
        assert advanced["cursor"]["virtual_time_ms"] == start + (3 + initial_bars) * 60_000 - 1
        result = await service.training.get_market_tracks(run_id)
        assert result["portfolio"]["equity"] == "10000"
        assert result["portfolio"]["hedge_inputs"]["status"] == "ACTIVE"
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
        await _assert_complete_global_prefix(service, run_id)
        events = await service.training.store.global_events(run_id)
    finally:
        await service.shutdown(step_timeout=1.0)
    restored = await fixtures._trade_service(database, archive_root=archive_root, symbols=("BTCUSDT",))
    try:
        await _assert_complete_global_prefix(restored, run_id)
        assert await restored.training.store.global_events(run_id) == events
        assert (await restored.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1.0)
    reference_root = tmp_path / "reference"
    reference_root.mkdir()
    reference = await fixtures._trade_service(
        reference_root / "reference.db", archive_root=reference_root / "tape", symbols=("BTCUSDT",),
    )
    try:
        reference_request = await prepare_hedge_request(
            reference, replace(await fixtures._trade_request(reference), integrity_mode="SANDBOX",
                               time_disclosure_policy=time_policy),
            root=reference_root, prefix="recover-cohort", book_mode="OFF", funding_event_offset_bars=10,
        )
        created = await reference.training.create_run(reference_request)
        reference_run, reference_sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await fixtures._acquire(reference, run_id=reference_run, selected_session_id=reference_sid,
                                command_id="reference-acquire")
        await _send(reference, run_id=reference_run, session_id=reference_sid, command_id="reference-advance",
                    command_type=ReplayV2CommandType.ADVANCE,
                    payload={"basis": "BASE_BAR", "count": 3 + initial_bars})
        reference_events = await reference.training.store.global_events(reference_run)

        def keys(items):
            return [(e["actual_event_time_ms"], e["event_phase"], e["track_id"], e["source_sequence"])
                    for e in items]

        assert keys(events) == keys(reference_events)
        reference_portfolio = (await reference.training.get_market_tracks(reference_run))["portfolio"]
        for field in ("equity", "positions", "orders", "fills"):
            assert result["portfolio"][field] == reference_portfolio[field]
    finally:
        await reference.shutdown(step_timeout=1.0)
