from dataclasses import replace
import sqlite3
from unittest.mock import patch

import pytest

from app.replay.training.models import ReplayV2CommandType
from app.replay.training.errors import TrainingRunError
from app.replay.training import hedge_track_readmission
from app.replay.training.hedge_timeline import IndexedHedgeSnapshot
from tests.fixtures.replay.hedge_input_fakes import (
    import_hedge_track_public_inputs,
    prepare_hedge_request,
)
from tests.test_replay_v2_training_phase5 import _acquire, _request
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


async def _dormant_run(service, root, initial_count=2, time_disclosure_policy="NONE", legacy=False, other_count=3):
    request = await prepare_hedge_request(
        service, replace(_sandbox_request(await _request(service)), market_type="futures",
                         time_disclosure_policy=time_disclosure_policy),
        root=root, prefix="readmit", book_mode="OFF",
        required_symbols=["BTCUSDT", "ETHUSDT"],
        mark_prices=[str(100 + n) for n in range(13)],
    )
    await import_hedge_track_public_inputs(
        service, request, root=root, prefix="readmit", symbol="ETHUSDT",
        mark_prices=[str(200 + n) for n in range(13)],
    )
    created = await service.training.create_run(request)
    run_id, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
    await _acquire(service, run_id=run_id, selected_session_id=sid, command_id="acquire")
    if initial_count:
        await _send(service, run_id=run_id, session_id=sid, command_id="initial-step",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": initial_count})
    added = await _send(service, run_id=run_id, session_id=sid, command_id="add",
                       command_type=ReplayV2CommandType.ADD_TRACK, payload={
                           "exchange": "binance", "market_type": "futures", "symbol": "ETHUSDT",
                           "settlement_asset": "USDT", "subscription_tier": "FULL"})
    other = added["data"]["track"]
    selected = await _send(service, run_id=run_id, session_id=sid, command_id="select-other",
                          command_type=ReplayV2CommandType.SELECT_TRACK,
                          payload={"track_id": other["track_id"], "expected_viewer_revision": 0})
    current_runtime = service.training.hedge_inputs._runtime_events

    async def previous_runtime(run):
        snapshot = await current_runtime(run)
        tracks = await service.training.store.get_market_track_heads(run)
        full = {t["track_id"] for t in tracks if t["subscription_tier"] == "FULL"}
        return IndexedHedgeSnapshot(tuple(e for e in snapshot[0] if e.track_id in full), snapshot[1])

    with patch.object(service.training.hedge_inputs, "_runtime_events", previous_runtime if legacy else current_runtime):
        if other_count:
            await _send(service, run_id=run_id, session_id=selected["session_id"], command_id="other-step",
                        command_type=ReplayV2CommandType.STEP_BASE, payload={"count": other_count})
    return run_id, sid, selected["session_id"]


@pytest.mark.parametrize("time_disclosure_policy", ["NONE", "HIDE_ALL"])
async def test_warm_hedge_track_readmission_then_step_preserves_cash_and_audit(tmp_path, time_disclosure_policy):
    service = await _risk_service(tmp_path / "readmit.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, primary, other = await _dormant_run(service, tmp_path, time_disclosure_policy=time_disclosure_policy)
        before = await service.training.get_market_tracks(run_id)
        selected = await _send(service, run_id=run_id, session_id=other, command_id="return-primary",
                              command_type=ReplayV2CommandType.SELECT_TRACK,
                              payload={"track_id": "track-1", "expected_viewer_revision": 1})
        after = await service.training.get_market_tracks(run_id)
        assert after["portfolio"]["equity"] == before["portfolio"]["equity"]
        assert after["portfolio"]["positions"] == []
        assert selected["cursor"]["virtual_time_ms"] == before["tracks"][1]["cursor"]["virtual_time_ms"]
        advanced = await _send(service, run_id=run_id, session_id=primary, command_id="returned-step",
                               command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert advanced["cursor"]["virtual_time_ms"] > selected["cursor"]["virtual_time_ms"]
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
        # The secondary lane also fell behind while WARM; both directions matter.
        selected_other = await _send(service, run_id=run_id, session_id=primary, command_id="return-other",
                                     command_type=ReplayV2CommandType.SELECT_TRACK,
                                     payload={"track_id": "track-2", "expected_viewer_revision": 2})
        await _send(service, run_id=run_id, session_id=selected_other["session_id"], command_id="other-next",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=1.0)


async def _legacy_reactivate(service, run_id, other, monkeypatch):
    async def old_no_catchup(**_kwargs):
        pass

    with monkeypatch.context() as patch:
        patch.setattr(hedge_track_readmission, "catch_up_public_marks", old_no_catchup)
        return await _send(service, run_id=run_id, session_id=other, command_id="legacy-select",
                           command_type=ReplayV2CommandType.SELECT_TRACK,
                           payload={"track_id": "track-1", "expected_viewer_revision": 1})


async def test_legacy_failure_recovers_on_next_command_and_survives_restart(tmp_path, monkeypatch):
    database = tmp_path / "legacy.db"
    service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, primary, other = await _dormant_run(service, tmp_path, legacy=True)
        selected = await _legacy_reactivate(service, run_id, other, monkeypatch)
        with pytest.raises(TrainingRunError) as failure:
            await _send(service, run_id=run_id, session_id=primary, command_id="legacy-fail",
                        command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert failure.value.code == "HEDGE_INPUT_CURSOR_BEHIND_MARKET"
        card = await service.training.get_run(run_id)
        assert card["compatibility"] == "UNAVAILABLE"
        assert card["resume_action"] == "OPEN_ADAPTER"
        assert card["status"]["code"] == "HEDGE_INPUT_RECOVERY_REQUIRED"
        cards = await service.training.list_runs(limit=50, cursor=None, state=None,
                                                  source_kind=None, compatibility="UNAVAILABLE")
        assert next(item for item in cards["items"] if item["run_id"] == run_id) == card
        before = await service.training.get_market_tracks(run_id)
        recovered = await _send(service, run_id=run_id, session_id=primary, command_id="recover",
                                command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        after = await service.training.get_market_tracks(run_id)
        assert recovered["cursor"]["virtual_time_ms"] > selected["cursor"]["virtual_time_ms"]
        assert after["portfolio"]["equity"] == before["portfolio"]["equity"]
        assert after["portfolio"]["hedge_inputs"]["status"] == "ACTIVE"
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
        after = await service.training.get_market_tracks(run_id)
    finally:
        await service.shutdown(step_timeout=1.0)
    restored = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        assert (await restored.training.get_market_tracks(run_id))["portfolio"] == after["portfolio"]
        assert (await restored.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("close_again", [False, True])
async def test_recovery_refuses_current_or_historical_exposure(tmp_path, monkeypatch, close_again):
    service = await _risk_service(tmp_path / "exposure.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, primary, other = await _dormant_run(service, tmp_path, legacy=True)
        await _legacy_reactivate(service, run_id, other, monkeypatch)
        for index, side in enumerate(["BUY", "SELL"] if close_again else ["BUY"]):
            await _send(service, run_id=run_id, session_id=primary, command_id=f"trade-{index}",
                        command_type=ReplayV2CommandType.PLACE_ORDER, payload={
                            "client_order_id": f"trade-{index}", "side": side, "position_side": "LONG",
                            "order_type": "MARKET", "quantity": "1", "reduce_only": index == 1,
                            "limit_price": None, "stop_price": None})
        await service.training.hedge_inputs.pause_run(run_id, reason=hedge_track_readmission.CURSOR_BEHIND)
        await service.training.audit_account(run_id)
        before = await service.training.get_market_tracks(run_id)
        with pytest.raises(TrainingRunError) as failure:
            await _send(service, run_id=run_id, session_id=primary, command_id="unsafe-recover",
                        command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert failure.value.code == "HEDGE_TRACK_READMISSION_REQUIRES_REVIEW"
        assert (await service.training.get_market_tracks(run_id))["portfolio"] == before["portfolio"]
    finally:
        await service.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("legacy", [False, True])
async def test_readmission_settles_dormant_funding_without_changing_cash(tmp_path, legacy):
    service = await _risk_service(tmp_path / "funding.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, primary, other = await _dormant_run(service, tmp_path, initial_count=0, legacy=legacy)
        before = await service.training.get_market_tracks(run_id)
        selected = await _send(service, run_id=run_id, session_id=other, command_id="funding-readmit",
                              command_type=ReplayV2CommandType.SELECT_TRACK,
                              payload={"track_id": "track-1", "expected_viewer_revision": 1})
        after = await service.training.get_market_tracks(run_id)
        assert after["portfolio"]["equity"] == before["portfolio"]["equity"]
        assert selected["cursor"]["virtual_time_ms"] == before["tracks"][1]["cursor"]["virtual_time_ms"]
        rows = await service.training.hedge_inputs.store.run_extension_read(lambda c: c.execute(
            "SELECT * FROM replay_training_hedge_funding_settlement WHERE run_id=? AND track_id='track-1'", (run_id,),
        ).fetchall())
        assert len(rows) == 2
        assert {r["position_side"] for r in rows} == {"LONG", "SHORT"}
        assert all(r["pre_settlement_absolute_quantity"] == "0" and r["cash_delta"] == "0" for r in rows)
        await _send(service, run_id=run_id, session_id=primary, command_id="funding-next",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_recovery_write_failure_rolls_back_mark_span_and_every_binding(tmp_path, monkeypatch):
    service = await _risk_service(tmp_path / "rollback.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, primary, other = await _dormant_run(service, tmp_path, legacy=True)
        await _legacy_reactivate(service, run_id, other, monkeypatch)
        await service.training.hedge_inputs.pause_run(run_id, reason=hedge_track_readmission.CURSOR_BEHIND)
        base = service.training.hedge_inputs.store

        def state(connection):
            return {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} WHERE run_id=?", (run_id,))]
                    for table in ("replay_hedge_track_public_projection", "replay_hedge_input_projection",
                                  "replay_hedge_mark_span", "replay_hedge_input_binding",
                                  "replay_hedge_track_public_binding")}

        before = await base.run_extension_read(state)
        await base.run_extension_write(lambda connection: connection.execute(
            "CREATE TEMP TRIGGER fail_recovery BEFORE UPDATE OF status ON replay_hedge_input_binding "
            "WHEN NEW.status='ACTIVE' BEGIN SELECT RAISE(ABORT,'injected recovery interruption'); END"))
        with pytest.raises(sqlite3.IntegrityError, match="injected recovery interruption"):
            await _send(service, run_id=run_id, session_id=primary, command_id="interrupted",
                        command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert await base.run_extension_read(state) == before
        await base.run_extension_write(lambda connection: connection.execute("DROP TRIGGER fail_recovery"))
        await _send(service, run_id=run_id, session_id=primary, command_id="after-interruption",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_other_input_pause_does_not_get_a_recovery_entry(tmp_path):
    service = await _risk_service(tmp_path / "other-pause.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run_id, _, _ = await _dormant_run(service, tmp_path)
        await service.training.hedge_inputs.pause_run(run_id, reason="PINNED_ARCHIVE_CHANGED")
        card = await service.training.get_run(run_id)
        assert card["resume_action"] == "UNAVAILABLE"
        assert card["status"]["code"] == "UNAVAILABLE"
    finally:
        await service.shutdown(step_timeout=1.0)
