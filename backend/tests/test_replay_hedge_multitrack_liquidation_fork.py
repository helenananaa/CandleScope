"""A review fork preserves risk events belonging only to a secondary market."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.replay.training.models import ReplayV2CommandType
from app.replay.training.errors import TrainingRunError
from tests.fixtures.replay.hedge_input_fakes import (
    import_hedge_track_public_inputs,
    prepare_hedge_request,
)
from tests.test_replay_v2_training_phase5 import _acquire, _request
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


async def _assert_risk_equity(service, run_id, portfolio):
    from app.replay.training.persistence.liquidation import liquidation_risk_state
    equity = await service.training.hedge_inputs.store.run_extension_read(
        lambda connection: liquidation_risk_state(connection, run_id=run_id)["equity"])
    assert equity == Decimal(portfolio["equity"])


@pytest.mark.parametrize("insurance", ["1000000", "0"])
@pytest.mark.parametrize("future_credit", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("fail_audit", [False, True])
async def test_secondary_only_liquidation_fork_preserves_risk_history(tmp_path, monkeypatch, insurance, future_credit, legacy, fail_audit):
    if future_credit:
        from tests.fixtures.replay import hedge_input_fakes
        original = hedge_input_fakes.build_hedge_simulation_manifest

        def with_credit(*args, **kwargs):
            kwargs["insurance_events"].append({
                "effective_time_ms": kwargs["range_start_ms"] + 3 * 60_000,
                "kind": "CREDIT", "amount": "123",
            })
            return original(*args, **kwargs)

        monkeypatch.setattr(hedge_input_fakes, "build_hedge_simulation_manifest", with_credit)
    database = tmp_path / "secondary-risk.db"
    service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        request = await prepare_hedge_request(
            service,
            replace(_sandbox_request(await _request(service), initial_equity="100"), market_type="futures"),
            root=tmp_path, prefix="secondary-risk", required_symbols=["BTCUSDT", "ETHUSDT"],
            mark_prices=["104"] * 13, insurance_opening_balance=insurance,
        )
        await import_hedge_track_public_inputs(
            service, request, root=tmp_path, prefix="secondary-risk", symbol="ETHUSDT",
            mark_prices=["104", "50"] + ["50"] * 11,
        )
        created = await service.training.create_run(request)
        run = created["run"]["run_id"]
        primary = created["run"]["adapter_session_id"]
        await _acquire(service, run_id=run, selected_session_id=primary, command_id="acquire")
        await _send(service, run_id=run, session_id=primary, command_id="add-secondary",
                    command_type=ReplayV2CommandType.ADD_TRACK, payload={
                        "exchange": "binance", "market_type": "futures", "symbol": "ETHUSDT",
                        "settlement_asset": "USDT", "subscription_tier": "FULL"})
        selected = await _send(service, run_id=run, session_id=primary, command_id="select-secondary",
                               command_type=ReplayV2CommandType.SELECT_TRACK,
                               payload={"track_id": "track-2", "expected_viewer_revision": 0})
        secondary = selected["session_id"]
        for side, leg, quantity in [("BUY", "LONG", "2.4"), ("SELL", "SHORT", "0.4")]:
            await _send(service, run_id=run, session_id=secondary, command_id=f"open-{leg}",
                        command_type=ReplayV2CommandType.PLACE_ORDER, payload={
                            "client_order_id": f"open-{leg}", "position_side": leg, "side": side,
                            "order_type": "MARKET", "quantity": quantity, "reduce_only": False,
                            "limit_price": None, "stop_price": None})
        await _send(service, run_id=run, session_id=secondary, command_id="select-primary",
                    command_type=ReplayV2CommandType.SELECT_TRACK,
                    payload={"track_id": "track-1", "expected_viewer_revision": 1})
        await _send(service, run_id=run, session_id=primary, command_id="crash-secondary",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 2})
        before = await service.training.get_market_tracks(run)
        await _assert_risk_equity(service, run, before["portfolio"])
        assert len(before["portfolio"]["liquidations"]) == 1
        assert {leg["track_id"] for leg in before["portfolio"]["liquidations"][0]["legs"]} == {"track-2"}
        assert (await service.training.audit_account(run))["status"] == "PASS"
        with monkeypatch.context() as old:
            if legacy:
                from app.replay.training.persistence import hedge_review_fork
                old.setattr(hedge_review_fork, "input_snapshot", lambda *_: None)
            await service.training.record_review_marker(run, command_id="risk-point", text="Secondary risk settled")
        review = await service.training.start_review(run, event_id=None)
        if future_credit:
            await _send(service, run_id=run, session_id=primary, command_id="future-credit",
                        command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 2})
        if fail_audit:
            original_audit = service.training.audit_account

            async def reject_child(run_id):
                if run_id != run:
                    raise TrainingRunError("TEST_CHILD_AUDIT_FAILURE", "injected child audit failure", status_code=409)
                return await original_audit(run_id)

            with monkeypatch.context() as failure:
                failure.setattr(service.training, "audit_account", reject_child)
                with pytest.raises(TrainingRunError, match="injected child audit failure"):
                    await service.training.fork_run(run, event_id=review["selected_event_id"])
            remaining = await service.training.hedge_inputs.store.run_extension_read(lambda c: c.execute(
                "SELECT run_id FROM replay_training_run ORDER BY run_id",
            ).fetchall())
            assert [row[0] for row in remaining] == [run]
            return
        fork = await service.training.fork_run(run, event_id=review["selected_event_id"])
        child = fork["run"]["run_id"]
        after = await service.training.get_market_tracks(child)
        assert len(after["portfolio"]["liquidations"]) == 1
        for key in ("equity", "cash_balance", "fees_paid", "liquidation_fees_paid", "realized_pnl"):
            assert after["portfolio"][key] == before["portfolio"][key], key
        for key in ("insurance_postings", "adl_events", "adl_selections", "adl_counterparty_ledger"):
            assert len(after["portfolio"]["hedge_state"][key]) == len(before["portfolio"]["hedge_state"][key]), key
        assert [f["current_balance"] for f in after["portfolio"]["hedge_state"]["insurance_funds"]] == [
            f["current_balance"] for f in before["portfolio"]["hedge_state"]["insurance_funds"]]
        assert (await service.training.audit_account(child))["status"] == "PASS"
        sid = fork["run"]["adapter_session_id"]
        await _acquire(service, run_id=child, selected_session_id=sid, command_id="child-acquire")
        await _send(service, run_id=child, session_id=sid, command_id="child-next",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 2})
        assert (await service.training.audit_account(child))["status"] == "PASS"
        saved = (await service.training.get_market_tracks(child))["portfolio"]
        parent_audit = await service.training.audit_account(run)
        assert parent_audit["status"] == "PASS", parent_audit["differences"]
    finally:
        await service.shutdown(step_timeout=1.0)
    restored = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    try:
        assert (await restored.training.get_market_tracks(child))["portfolio"] == saved
        assert (await restored.training.audit_account(child))["status"] == "PASS"
        await restored.training.delete_run(child)
        assert (await restored.training.audit_account(run))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("transition", [
    "commit_liquidation_cancellation", "commit_liquidation_recheck",
    "commit_liquidation_execution", "commit_liquidation_bankruptcy",
    "commit_liquidation_insurance", "commit_liquidation_adl",
    "commit_liquidation_complete",
])
async def test_fork_restores_selected_pending_liquidation_before_parent_completes(tmp_path, monkeypatch, transition):
    from tests.test_replay_v2_training_hedge_phase5 import _create_bankrupt_hedge_run, _trigger_crash

    async def finish(run_id, command_id):
        for _ in range(4):
            await service.training._ordered_playback._reconcile_liquidations(
                run_id=run_id, client_instance_id="phase5-browser", command_id=command_id)
            if not await service.training.store.pending_liquidations(run_id):
                break
        return await service.training.get_market_tracks(run_id)

    database = tmp_path / "pending-risk.db"
    service = await _risk_service(database)
    try:
        run, sid = await _create_bankrupt_hedge_run(
            service, root=tmp_path, prefix="pending", insurance_opening_balance="0")

        async def defer(**kwargs):
            return 0

        with monkeypatch.context() as preparation:
            preparation.setattr(service.training._ordered_playback, "_reconcile_liquidations", defer)
            await _trigger_crash(service, run_id=run, session_id=sid, prefix="pending")

        original_transition = getattr(service.training.store, transition)

        async def stop_after(**kwargs):
            # Publish the relational step together with its actor result before
            # taking a user-visible review point. The pre-commit actor response
            # is an internal recovery boundary, covered by phase8 restart tests.
            await original_transition(**kwargs)
            raise RuntimeError("selected historical risk boundary")

        with monkeypatch.context() as interruption:
            interruption.setattr(service.training.store, transition, stop_after)
            with pytest.raises(RuntimeError, match="selected historical risk boundary"):
                await finish(run, "risk-boundary")
        before = await service.training.get_market_tracks(run)
        await _assert_risk_equity(service, run, before["portfolio"])
        await service.training.record_review_marker(run, command_id="pending-point", text="Pending liquidation")
        review = await service.training.start_review(run, event_id=None)
        completed = await finish(run, "risk-parent-finish")
        try:
            fork = await service.training.fork_run(run, event_id=review["selected_event_id"])
        except TrainingRunError as exc:
            pytest.fail(f"{exc.code}: {exc.details}")
        child = fork["run"]["run_id"]
        after = await service.training.get_market_tracks(child)
        for key in ("equity", "fees_paid", "liquidation_fees_paid", "realized_pnl", "positions"):
            if after["portfolio"][key] != before["portfolio"][key]:
                import json
                (tmp_path / "difference.json").write_text(json.dumps({"before": before, "after": after, "review": review}, indent=2))
            assert after["portfolio"][key] == before["portfolio"][key], key
        assert [{**case, "run_id": run} for case in after["portfolio"]["liquidations"]] == before["portfolio"]["liquidations"]
        parent_saved = (await service.training.get_market_tracks(run))["portfolio"]
        child_completed = await finish(child, "risk-child-finish")
        for key in ("equity", "fees_paid", "liquidation_fees_paid", "realized_pnl", "positions"):
            assert child_completed["portfolio"][key] == completed["portfolio"][key], key
        assert (await service.training.audit_account(child))["status"] == "PASS"
        assert (await service.training.get_market_tracks(run))["portfolio"] == parent_saved
        saved = (await service.training.get_market_tracks(child))["portfolio"]
    finally:
        await service.shutdown(step_timeout=1.0)
    restored = await _risk_service(database)
    try:
        assert (await restored.training.get_market_tracks(child))["portfolio"] == saved
        assert (await restored.training.audit_account(child))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1.0)
