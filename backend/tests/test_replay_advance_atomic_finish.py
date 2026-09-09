from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.replay.training.models import ReplayV2CommandType
from app.replay.training.errors import TrainingRunError
from tests.test_replay_v2_training_phase15 import (
    _async_test, _bar_service, _create_acquired_bar_run, _v2_command, INTERVAL_MS,
)


@_async_test
@pytest.mark.parametrize("cancelled", [False, True])
async def test_terminal_intent_and_response_roll_back_and_commit_together(
    tmp_path: Path, cancelled: bool,
) -> None:
    service = await _bar_service(tmp_path / "atomic.db", optimized=True)
    try:
        store = service.training.store
        run_id, session_id = await _create_acquired_bar_run(service)
        before = await service.get_session(session_id)
        target = before["snapshot"]["cursor"]["virtual_time_ms"] + INTERVAL_MS
        command = _v2_command(run_id, "atomic-finish", ReplayV2CommandType.ADVANCE_TO,
                              before, {"virtual_time_ms": target})
        await store.begin_advance_intent(
            run_id=run_id, command_id=command.command_id, command=command.to_dict(),
            session_id=session_id, initial_cursor=command.expected_cursor.to_dict(),
            target_virtual_time_ms=target, plan={}, summary=None,
        )
        result = {"command_id": command.command_id, "cancelled": cancelled}
        await service.store.run_extension_write(lambda connection: connection.execute(
            "UPDATE replay_training_advance_intent SET status = 'FAILED' WHERE run_id = ?",
            (run_id,),
        ))
        with pytest.raises(TrainingRunError, match="failed advance intent"):
            await store.finish_advance_intent(run_id=run_id, command_id=command.command_id,
                                              result=result, cancelled=cancelled)
        assert await store.get_command_result(run_id, command.command_id, command.to_dict()) is None
        await service.store.run_extension_write(lambda connection: connection.execute(
            "UPDATE replay_training_advance_intent SET status = 'RUNNING' WHERE run_id = ?",
            (run_id,),
        ))
        await service.store.run_extension_write(lambda connection: connection.execute(
            "CREATE TRIGGER reject_terminal BEFORE UPDATE OF status ON "
            "replay_training_advance_intent BEGIN SELECT RAISE(FAIL, 'injected terminal failure'); END"
        ))
        with pytest.raises(sqlite3.IntegrityError, match="injected terminal failure"):
            await store.finish_advance_intent(run_id=run_id, command_id=command.command_id,
                                              result=result, cancelled=cancelled)
        assert await store.get_command_result(run_id, command.command_id, command.to_dict()) is None
        intent = await store.get_advance_intent(run_id=run_id, command_id=command.command_id,
                                                command=command.to_dict())
        assert intent["status"] == "RUNNING"
        await service.store.run_extension_write(lambda connection: connection.execute("DROP TRIGGER reject_terminal"))
        await store.finish_advance_intent(run_id=run_id, command_id=command.command_id,
                                          result=result, cancelled=cancelled)
        assert await store.get_command_result(run_id, command.command_id, command.to_dict()) == result
        with pytest.raises(TrainingRunError):
            await store.finish_advance_intent(run_id=run_id, command_id=command.command_id,
                                              result={"conflict": True}, cancelled=cancelled)
        # Older databases may have a terminal intent without its response row.
        await service.store.run_extension_write(lambda connection: connection.execute(
            "DELETE FROM replay_training_command WHERE run_id = ? AND command_id = ?",
            (run_id, command.command_id),
        ))
        await store.finish_advance_intent(run_id=run_id, command_id=command.command_id,
                                          result=result, cancelled=cancelled)
        assert await store.get_command_result(run_id, command.command_id, command.to_dict()) == result
    finally:
        await service.shutdown(step_timeout=1.0)


@_async_test
async def test_response_loss_after_atomic_finish_retries_without_advancing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "response-loss.db"
    service = await _bar_service(database, optimized=True)
    run_id, session_id = await _create_acquired_bar_run(service)
    before = await service.get_session(session_id)
    target = before["snapshot"]["cursor"]["virtual_time_ms"] + 15 * INTERVAL_MS
    command = _v2_command(run_id, "atomic-response-loss", ReplayV2CommandType.ADVANCE_TO,
                          before, {"virtual_time_ms": target})
    finish = service.training.store.finish_advance_intent
    saved = None

    async def lose_response(**kwargs):
        nonlocal saved
        await finish(**kwargs)
        saved = kwargs["result"]
        raise RuntimeError("injected post-commit response loss")

    monkeypatch.setattr(service.training.store, "finish_advance_intent", lose_response)
    try:
        with pytest.raises(RuntimeError, match="post-commit response loss"):
            await service.training.command(run_id, command)
        assert saved is not None
        assert await service.training.store.get_command_result(
            run_id, command.command_id, command.to_dict(),
        ) == saved
    finally:
        await service.shutdown(step_timeout=1.0)
    recovered = await _bar_service(database, optimized=True)
    try:
        assert await recovered.training.command(run_id, command) == saved
        snapshot = (await recovered.get_session(session_id))["snapshot"]
        assert snapshot["cursor"] == saved["cursor"]
        assert snapshot["state_hash"] == saved["state_hash"]
    finally:
        await recovered.shutdown(step_timeout=1.0)


@_async_test
async def test_target_scan_finishes_with_one_transaction_and_no_second_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = await _bar_service(tmp_path / "single-finish.db", optimized=True)
    try:
        run_id, session_id = await _create_acquired_bar_run(service)
        before = await service.get_session(session_id)
        target = before["snapshot"]["cursor"]["virtual_time_ms"] + 15 * INTERVAL_MS
        command = _v2_command(run_id, "single-finish", ReplayV2CommandType.ADVANCE_TO,
                              before, {"virtual_time_ms": target})
        finish = service.training.store.finish_advance_intent
        commits = []

        async def measured_finish(**kwargs):
            count = service.store._metrics["transactions"]
            await finish(**kwargs)
            commits.append(service.store._metrics["transactions"] - count)

        async def redundant_save(**kwargs):
            raise AssertionError("target scan must not issue a second result transaction")

        monkeypatch.setattr(service.training.store, "finish_advance_intent", measured_finish)
        monkeypatch.setattr(service.training.store, "save_command_result", redundant_save)
        result = await service.training.command(run_id, command)
        assert commits == [1]
        assert await service.training.command(run_id, command) == result
        assert result["cursor"]["virtual_time_ms"] == target
    finally:
        await service.shutdown(step_timeout=1.0)
