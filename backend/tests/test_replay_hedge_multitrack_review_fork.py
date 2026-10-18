import json
import asyncio

import pytest

from app.replay.training.models import ReplayV2CommandType
from tests.test_replay_hedge_dormant_account_inputs import _changing_inputs, _rows
from tests.test_replay_hedge_track_readmission import _dormant_run
from tests.test_replay_v2_training_phase5 import _acquire
from tests.test_replay_v2_training_phase6 import _risk_service, _send

pytestmark = pytest.mark.anyio


def _assert_track_subscription_contract(tracks):
    for track in tracks["tracks"]:
        reasons = track["forced_full_reasons"]
        assert not reasons or track["subscription_tier"] == "FULL"
        assert ("VIEWED" in reasons) == (track["track_id"] == tracks["viewer_state"]["selected_track_id"])


async def _order(service, run_id, sid, key, position_side, close=False):
    return await _send(service, run_id=run_id, session_id=sid, command_id=key,
                       command_type=ReplayV2CommandType.PLACE_ORDER, payload={
                           "client_order_id": key, "position_side": position_side,
                           "side": ("SELL" if close else "BUY") if position_side == "LONG" else ("BUY" if close else "SELL"),
                           "order_type": "MARKET", "quantity": "1", "reduce_only": close,
                           "limit_price": None, "stop_price": None})


@pytest.mark.parametrize("time_policy", ["NONE", "HIDE_ALL"])
@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
async def test_multitrack_funding_fork_uses_selected_history_and_survives_restart(tmp_path, monkeypatch, time_policy, closed, legacy):
    if legacy:
        from app.replay.training.persistence import hedge_review_fork
        original_snapshot = hedge_review_fork.input_snapshot
        monkeypatch.setattr(hedge_review_fork, "input_snapshot", lambda *_: None)
    _changing_inputs(monkeypatch)
    database = tmp_path / "fork.db"
    service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run, primary, secondary = await _dormant_run(service, tmp_path, initial_count=0,
                                                    other_count=0, time_disclosure_policy=time_policy)
        for side in ("LONG", "SHORT"):
            await _order(service, run, secondary, f"secondary-{side}", side)
        await _send(service, run_id=run, session_id=secondary, command_id="select-primary",
                    command_type=ReplayV2CommandType.SELECT_TRACK,
                    payload={"track_id": "track-1", "expected_viewer_revision": 1})
        for side in ("LONG", "SHORT"):
            await _order(service, run, primary, f"primary-{side}", side)
        await _send(service, run_id=run, session_id=primary, command_id="funding-step",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 3})
        if closed:
            for index, sid in enumerate((primary, secondary)):
                if index:
                    await _send(service, run_id=run, session_id=primary, command_id="close-select-secondary",
                                command_type=ReplayV2CommandType.SELECT_TRACK,
                                payload={"track_id": "track-2", "expected_viewer_revision": 2})
                for side in ("LONG", "SHORT"):
                    await _order(service, run, sid, f"close-{index}-{side}", side, close=True)
            await _send(service, run_id=run, session_id=secondary, command_id="close-return-primary",
                        command_type=ReplayV2CommandType.SELECT_TRACK,
                        payload={"track_id": "track-1", "expected_viewer_revision": 3})
        await service.training.record_review_marker(run, command_id="fork-at-three", text="Fork at the current three-minute boundary")
        assert (await service.training.audit_account(run))["status"] == "PASS"
        before = await service.training.get_market_tracks(run)
        public_before = await _rows(service, run, "replay_hedge_track_public_projection")
        funding_before = await _rows(service, run, "replay_training_hedge_funding_settlement")
        review = await service.training.start_review(run, event_id=None)
        for key in ("equity", "available_equity", "unrealized_pnl", "margin_used", "reserved_margin"):
            assert review["projection"]["domain"]["portfolio"][key] == before["portfolio"][key], key
        await _send(service, run_id=run, session_id=primary, command_id="parent-future",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 3})
        if legacy:
            monkeypatch.setattr(hedge_review_fork, "input_snapshot", original_snapshot)
            # Migrated primary bindings predate the per-track initial cursor.
            await service.training.hedge_inputs.store.run_extension_write(lambda c: c.execute(
                "UPDATE replay_hedge_track_public_binding SET initial_event_sequence=NULL WHERE run_id=? AND track_id='track-1'",
                (run,),
            ))
        forked = await service.training.fork_run(run, event_id=review["selected_event_id"])
        child = forked["run"]["run_id"]
        after = await service.training.get_market_tracks(child)
        _assert_track_subscription_contract(after)
        for field in ("equity", "cash_balance", "realized_pnl", "unrealized_pnl", "fees_paid", "funding_cashflow"):
            assert after["portfolio"][field] == before["portfolio"][field], field
        assert len(after["portfolio"]["positions"]) == (0 if closed else 4)
        assert after["portfolio"]["active_fee_policy"]["taker_fee_bps"] == "3"
        funding_after = await _rows(service, child, "replay_training_hedge_funding_settlement")
        fields = ("track_id", "position_side", "settlement_time_ms", "cash_delta", "pre_settlement_signed_quantity")
        assert sorted(tuple(r[f] for f in fields) for r in funding_after) == sorted(tuple(r[f] for f in fields) for r in funding_before)
        assert [(r["track_id"], r["last_event_sequence"], r["state_json"]) for r in await _rows(service, child, "replay_hedge_track_public_projection")] == [
            (r["track_id"], r["last_event_sequence"], r["state_json"]) for r in public_before]
        sid = forked["run"]["adapter_session_id"]
        await _acquire(service, run_id=child, selected_session_id=sid, command_id="child-acquire")
        await _order(service, child, sid, "child-order", "LONG", close=not closed)
        await _send(service, run_id=child, session_id=sid, command_id="child-next",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert (await service.training.audit_account(child))["status"] == "PASS"
        await service.training.record_review_marker(child, command_id="grandchild-point", text="Fork after child trade")
        child_review = await service.training.start_review(child, event_id=None)
        grandchild = await service.training.fork_run(child, event_id=child_review["selected_event_id"])
        assert (await service.training.audit_account(grandchild["run"]["run_id"]))["status"] == "PASS"
        saved = (await service.training.get_market_tracks(child))["portfolio"]
    finally:
        await service.shutdown(step_timeout=1.0)
    restored = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        assert (await restored.training.get_market_tracks(child))["portfolio"] == saved
        _assert_track_subscription_contract(await restored.training.get_market_tracks(child))
        assert (await restored.training.audit_account(child))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("primary_held", [False, True])
async def test_secondary_selected_fork_restores_subscription_contract_and_repairs_old_default(tmp_path, primary_held):
    database = tmp_path / "secondary-selected.db"
    service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run, primary, secondary = await _dormant_run(service, tmp_path, initial_count=0, other_count=0)
        if primary_held:
            await _send(service, run_id=run, session_id=secondary, command_id="select-primary-held",
                        command_type=ReplayV2CommandType.SELECT_TRACK,
                        payload={"track_id": "track-1", "expected_viewer_revision": 1})
            await _order(service, run, primary, "primary-long", "LONG")
            await _send(service, run_id=run, session_id=primary, command_id="select-secondary-held",
                        command_type=ReplayV2CommandType.SELECT_TRACK,
                        payload={"track_id": "track-2", "expected_viewer_revision": 2})
        await service.training.record_review_marker(run, command_id="secondary-point", text="Review secondary")
        review = await service.training.start_review(run, event_id=None)
        forked = await service.training.fork_run(run, event_id=review["selected_event_id"])
        child = forked["run"]["run_id"]
        tracks = await service.training.get_market_tracks(child)
        _assert_track_subscription_contract(tracks)
        expected_reasons = ["LIQUIDATION_RISK", "OPEN_POSITION"] if primary_held else []
        assert tracks["tracks"][0]["forced_full_reasons"] == expected_reasons
        assert tracks["tracks"][0]["subscription_tier"] == ("FULL" if primary_held else "WARM")
        saved = tracks["portfolio"]
    finally:
        await service.shutdown(step_timeout=1.0)
    # Reproduce v57 persisted metadata after shutdown; startup must repair it
    # without account/cursor mutations or manual editing of a user's archive.
    import sqlite3
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE replay_training_market_track SET forced_full_reasons_json=? WHERE run_id=? AND track_id='track-1'",
                           (json.dumps([*expected_reasons, "VIEWED"]), child))
    for _ in range(2):
        restored = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
        try:
            tracks = await restored.training.get_market_tracks(child)
            _assert_track_subscription_contract(tracks)
            assert tracks["portfolio"] == saved
            assert tracks["tracks"][0]["forced_full_reasons"] == expected_reasons
            assert (await restored.training.audit_account(child))["status"] == "PASS"
        finally:
            await restored.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("anchor_timing", ["prior", "later", "missing"])
async def test_legacy_latest_fork_restores_unlinked_warm_anchor(tmp_path, monkeypatch, anchor_timing):
    from app.replay.training import review as review_module
    from app.replay.training.persistence import hedge_review_fork
    from app.replay.training.errors import TrainingRunError

    database = tmp_path / "legacy-review.db"
    service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    original_load = review_module._AnchorBatch.load

    def legacy_batch(connection, run_id):
        batch = original_load(connection, run_id)
        batch.tracks = {sid: row for sid, row in batch.tracks.items() if row["subscription_tier"] == "FULL"}
        return batch

    try:
        with monkeypatch.context() as old:
            old.setattr(review_module._AnchorBatch, "load", legacy_batch)
            old.setattr(hedge_review_fork, "input_snapshot", lambda *_: None)
            run, primary, secondary = await _dormant_run(service, tmp_path, initial_count=0)
            await _send(service, run_id=run, session_id=secondary, command_id="legacy-select-primary",
                        command_type=ReplayV2CommandType.SELECT_TRACK,
                        payload={"track_id": "track-1", "expected_viewer_revision": 1})
            await service.training.record_review_marker(run, command_id="legacy-point", text="Legacy current fork")
        review = await service.training.start_review(run, event_id=None)
        before = await service.training.get_market_tracks(run)
        base = service.training.hedge_inputs.store
        selected = await service.training.store.checkpoint_for_event(run, review["selected_event_id"])
        warm = next(t for t in selected["projection"]["tracks"] if t["track_id"] == "track-2")
        # Model a legacy archive whose unchanged dormant actor was first saved
        # after this event. Neither save time nor a later parent cursor should
        # change the state selected for the child.
        if anchor_timing != "prior":
            def adjust_anchor(connection):
                event_time = connection.execute(
                    "SELECT created_at_ms FROM replay_review_timeline_event WHERE run_id=? AND event_id=?",
                    (run, review["selected_event_id"]),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE replay_review_actor_anchor SET created_at_ms=?, state_hash=? "
                    "WHERE run_id=? AND track_id='track-2' AND state_hash=?",
                    (event_time + 1000, warm["state_hash"] if anchor_timing == "later" else "sha256:" + "0" * 64,
                     run, warm["state_hash"]),
                )
            await base.run_extension_write(adjust_anchor)
        if anchor_timing == "missing":
            with pytest.raises(TrainingRunError) as failure:
                await service.training.fork_run(run, event_id=review["selected_event_id"])
            assert failure.value.code == "REVIEW_ANCHOR_UNAVAILABLE"
            assert await service.training.get_market_tracks(run) == before
            return
        await _send(service, run_id=run, session_id=primary, command_id="legacy-parent-future",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        parent_future = await service.training.get_market_tracks(run)
        forked = await service.training.fork_run(run, event_id=review["selected_event_id"])
        child = forked["run"]["run_id"]
        tracks = await service.training.get_market_tracks(child)
        assert len(tracks["tracks"]) == 2
        assert tracks["tracks"][1]["subscription_tier"] == "WARM"
        for restored, original in zip(tracks["tracks"], before["tracks"], strict=True):
            assert restored["cursor"]["source_sequence"] == original["cursor"]["source_sequence"]
            assert restored["cursor"]["virtual_time_ms"] == original["cursor"]["virtual_time_ms"]
        for field in ("equity", "cash_balance", "realized_pnl", "unrealized_pnl", "fees_paid", "funding_cashflow"):
            assert tracks["portfolio"][field] == before["portfolio"][field], field
        assert await service.training.get_market_tracks(run) == parent_future
        assert (await service.training.audit_account(child))["status"] == "PASS"
        saved = tracks["portfolio"]
    finally:
        await service.shutdown(step_timeout=1.0)
    restored_service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        assert (await restored_service.training.get_market_tracks(child))["portfolio"] == saved
        assert (await restored_service.training.audit_account(child))["status"] == "PASS"
    finally:
        await restored_service.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_secondary_fork_failure_leaves_no_partial_run_or_adapter(tmp_path, monkeypatch, error_type):
    service = await _risk_service(tmp_path / "failure.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run, primary, secondary = await _dormant_run(service, tmp_path, initial_count=0)
        review = await service.training.start_review(run, event_id=None)
        base = service.training.hedge_inputs.store

        async def inventory():
            return await base.run_extension_read(lambda c: (
                c.execute("SELECT run_id FROM replay_training_run ORDER BY run_id").fetchall(),
                c.execute("SELECT session_id FROM replay_session ORDER BY session_id").fetchall(),
            ))

        before = await inventory()
        original = service.fork_session_from_checkpoint_blob
        calls = 0

        async def fail_secondary(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise error_type("injected secondary fork interruption")
            return await original(*args, **kwargs)

        with monkeypatch.context() as failing:
            failing.setattr(service, "fork_session_from_checkpoint_blob", fail_secondary)
            with pytest.raises(error_type, match="injected secondary"):
                await service.training.fork_run(run, event_id=review["selected_event_id"])
        assert await inventory() == before
        retried = await service.training.fork_run(run, event_id=review["selected_event_id"])
        assert (await service.training.audit_account(retried["run"]["run_id"]))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("missing_valuation", [False, True])
async def test_legacy_fork_valuation_drift_is_rejected_and_child_is_removed(tmp_path, monkeypatch, missing_valuation):
    """Old frozen frames can carry a broker mark instead of the pinned mark.

    Model that saved derived valuation without altering cash or positions. An
    internally consistent child audit alone must not certify an exact fork.
    """
    from app.replay.training import review_account
    from app.replay.training.errors import TrainingRunError

    service = await _risk_service(tmp_path / "legacy-valuation.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run, primary, _ = await _dormant_run(service, tmp_path, initial_count=0)
        secondary = (await service.training.get_market_tracks(run))["tracks"][1]["adapter_session_id"]
        await _send(service, run_id=run, session_id=secondary, command_id="valuation-select-primary",
                    command_type=ReplayV2CommandType.SELECT_TRACK,
                    payload={"track_id": "track-1", "expected_viewer_revision": 1})
        await _order(service, run, primary, "held-for-valuation", "SHORT")
        capture = review_account.capture_account

        def legacy_valuation(connection, run_id):
            from decimal import Decimal
            result = capture(connection, run_id)
            if missing_valuation:
                return {**result, "status": "LEGACY_PARTIAL", "margin_used": None}
            return {**result, "equity": str(Decimal(result["equity"]) - 8),
                    "unrealized_pnl": str(Decimal(result["unrealized_pnl"]) - 8),
                    "available_equity": str(Decimal(result["available_equity"]) - 8)}

        with monkeypatch.context() as legacy:
            legacy.setattr(review_account, "capture_account", legacy_valuation)
            await service.training.record_review_marker(run, command_id="old-valuation", text="Legacy broker mark")
        selected = await service.training.start_review(run, event_id=None)
        before = await service.training.get_market_tracks(run)
        base = service.training.hedge_inputs.store

        async def inventory():
            return await base.run_extension_read(lambda c: (
                c.execute("SELECT run_id FROM replay_training_run ORDER BY run_id").fetchall(),
                c.execute("SELECT session_id FROM replay_session ORDER BY session_id").fetchall(),
            ))

        rows = await inventory()
        with pytest.raises(TrainingRunError) as failure:
            await service.training.fork_run(run, event_id=selected["selected_event_id"])
        assert failure.value.code == ("REVIEW_FORK_VALUATION_UNAVAILABLE" if missing_valuation else "REVIEW_FORK_VALUATION_MISMATCH")
        assert failure.value.details["fallback_applied"] is False
        if not missing_valuation:
            assert "equity" in failure.value.details["differences"]
        assert await inventory() == rows
        assert await service.training.get_market_tracks(run) == before
    finally:
        await service.shutdown(step_timeout=1.0)
