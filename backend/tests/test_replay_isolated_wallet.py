"""Active isolated collateral includes only its own allocation lifecycle cashflows."""

import json
import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest
from app.replay.training.models import ReplayV2CommandType
from app.replay.training.persistence import isolated_wallets
from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request
from tests.test_replay_hedge_fixed_funding import _place
from tests.test_replay_v2_training_phase5 import _acquire, _request, _command
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


async def _open(service, root, rate):
    prepared = await prepare_hedge_request(
        service, replace(_sandbox_request(await _request(service), initial_equity="200",
                                          margin_mode="ISOLATED"), market_type="futures"),
        root=root, prefix="isolated-wallet", book_mode="OFF", mark_prices=["100"] * 13,
    )
    created = await service.training.create_run(replace(
        prepared, funding_mode="SANDBOX_FIXED", fixed_funding_rate=rate, funding_interval_ms=60_000))
    run, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
    await _acquire(service, run_id=run, selected_session_id=sid, command_id="acquire")
    for side in ("LONG", "SHORT"):
        await _allocate(service, run, sid, side, "70", "allocate-" + side)
        await _place(service, run, sid, "open-" + side, side, "1")
    return run, sid


async def _allocate(service, run, sid, side, amount, command_id):
    return await _send(service, run_id=run, session_id=sid, command_id=command_id,
                       command_type=ReplayV2CommandType.ALLOCATE_ISOLATED_MARGIN,
                       payload={"track_id": "track-1", "position_side": side, "amount": amount})


async def _portfolio(service, run):
    return (await service.training.get_market_tracks(run))["portfolio"]


@pytest.mark.parametrize("rate", ["1", "-1", "0.01", "-0.01"])
async def test_own_funding_controls_wallet_risk_and_restart(tmp_path, rate, monkeypatch):
    database = tmp_path / "replay.db"
    service = await _risk_service(database, bar_prices=["99.5"] * 20)
    try:
        run, sid = await _open(service, tmp_path, rate)
        before = await _portfolio(service, run)
        assert before["isolated_wallets"] == {"track-1:LONG": "69.95", "track-1:SHORT": "69.95"}
        assert Decimal(before["available_equity"]) == 60
        def no_history(*args, **kwargs):
            pytest.fail("ordinary advancement must not rebuild isolated wallet history")
        with monkeypatch.context() as patch:
            patch.setattr(isolated_wallets, "rebuild", no_history)
            advance = _command(run, "funding", ReplayV2CommandType.STEP_BASE,
                               await service.get_session(sid), {"count": 2})
            result = await service.training.command(run, advance)
            after = await _portfolio(service, run)
            assert await service.training.command(run, advance) == result
        victim = "LONG" if Decimal(rate) > 0 else "SHORT"
        survivor = "SHORT" if victim == "LONG" else "LONG"
        if abs(Decimal(rate)) == 1:
            assert [p["position_side"] for p in after["positions"]] == [survivor]
            assert after["isolated_wallets"] == {"track-1:" + survivor: "169.95"}
            assert Decimal(after["cash_balance"]) == Decimal("229.95")
            assert len(after["liquidations"]) == 1
        else:
            assert after["isolated_wallets"] == {"track-1:" + victim: "68.95", "track-1:" + survivor: "70.95"}
            assert after["liquidations"] == []
        assert Decimal(after["available_equity"]) == 60
        audit = await service.training.audit_account(run)
        assert audit["status"] == "PASS", audit["differences"]
        saved = await _portfolio(service, run)
    finally:
        await service.shutdown(step_timeout=1)
    restored = await _risk_service(database, bar_prices=["99.5"] * 20)
    try:
        assert await _portfolio(restored, run) == saved
        assert (await restored.training.audit_account(run))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1)


@pytest.mark.parametrize("close_price", ["99.5", "110", "90"])
async def test_partial_close_allocation_and_new_lifecycle_do_not_reuse_old_flows(tmp_path, close_price):
    service = await _risk_service(tmp_path / "replay.db", bar_prices=["99.5"] + [close_price] * 19)
    try:
        run, sid = await _open(service, tmp_path, "0.01")
        await _send(service, run_id=run, session_id=sid, command_id="funding",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 2})
        await _place(service, run, sid, "partial", "LONG", "0.5", close=True)
        after = await _portfolio(service, run)
        leg = next(x for x in after["hedge_state"]["position_legs"] if x["position_side"] == "LONG")
        expected = Decimal(70) - Decimal(1) - Decimal(leg["trading_fees"]) + Decimal(leg["realized_pnl"])
        assert Decimal(after["isolated_wallets"]["track-1:LONG"]) == expected
        await _allocate(service, run, sid, "LONG", "80", "increase")
        assert Decimal((await _portfolio(service, run))["isolated_wallets"]["track-1:LONG"]) == expected + 10
        await _allocate(service, run, sid, "LONG", "70", "decrease")
        await _place(service, run, sid, "close", "LONG", "0.5", close=True)
        closed = await _portfolio(service, run)
        assert "track-1:LONG" not in closed["isolated_wallets"]
        await _allocate(service, run, sid, "LONG", "40", "new-lifecycle")
        await _place(service, run, sid, "reopen", "LONG", "0.5")
        reopened = await _portfolio(service, run)
        assert Decimal(reopened["isolated_wallets"]["track-1:LONG"]) == Decimal("39.97")
        audit = await service.training.audit_account(run)
        assert audit["status"] == "PASS", audit["differences"]
        for index in range(2):
            await service.training.record_review_marker(run, command_id=f"marker-{index}", text="Wallet lifecycle")
            review = await service.training.start_review(run, event_id=None)
            child = await service.training.fork_run(run, event_id=review["selected_event_id"])
            run = child["run"]["run_id"]
            assert (await _portfolio(service, run))["isolated_wallets"] == reopened["isolated_wallets"]
            audit = await service.training.audit_account(run)
            assert audit["status"] == "PASS", audit["differences"]
    finally:
        await service.shutdown(step_timeout=1)


async def test_depleted_wallet_limits_orders_leverage_and_withdrawals(tmp_path):
    from app.replay.training.errors import TrainingRunError
    service = await _risk_service(tmp_path / "replay.db", bar_prices=["99.5"] * 20)
    try:
        run, sid = await _open(service, tmp_path, "0.2")
        await _send(service, run_id=run, session_id=sid, command_id="funding",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 2})
        before = await _portfolio(service, run)
        assert before["isolated_wallets"]["track-1:LONG"] == "49.95"
        tracks = await service.training.get_market_tracks(run)
        maximum = service.training._shared_order_capacity_quantity(
            adapter_max_quantity="100", reference_price="100",
            payload={"side": "BUY", "order_type": "MARKET", "reduce_only": False,
                     "position_side": "LONG", "leverage": "3"},
            selected_track=tracks["tracks"][0], portfolio=before,
            binding=await service.training.store.run_binding(run),
        )
        assert Decimal(0) < Decimal(maximum) < Decimal("0.51")
        with pytest.raises(TrainingRunError) as rejected:
            await _allocate(service, run, sid, "LONG", "40", "withdraw-too-much")
        assert rejected.value.code == "ISOLATED_MARGIN_IN_USE"
        with pytest.raises(TrainingRunError) as rejected:
            await _send(service, run_id=run, session_id=sid, command_id="lower-leverage",
                        command_type=ReplayV2CommandType.SET_POSITION_LEVERAGE,
                        payload={"position_side": "LONG", "leverage": "2"})
        assert rejected.value.code == "RUN_ACCOUNT_MARGIN_EXCEEDED"
        with pytest.raises(TrainingRunError) as rejected:
            await _place(service, run, sid, "over-capacity", "LONG", "0.51")
        assert rejected.value.code == "RUN_ACCOUNT_MARGIN_EXCEEDED"
        assert (await _portfolio(service, run))["isolated_wallets"] == before["isolated_wallets"]
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=1)


async def test_wallet_and_financial_receipt_rollback_together(tmp_path, monkeypatch):
    database = tmp_path / "replay.db"
    service = await _risk_service(database, bar_prices=["99.5"] * 20)
    try:
        run, sid = await _open(service, tmp_path, "0.01")
        before = await _portfolio(service, run)
        original = isolated_wallets.append
        def interrupt(connection, **kwargs):
            original(connection, **kwargs)
            if kwargs["kind"] == "FUNDING_SETTLEMENT":
                raise RuntimeError("interrupted after isolated wallet posting")
        with monkeypatch.context() as patch:
            patch.setattr(isolated_wallets, "append", interrupt)
            with pytest.raises(RuntimeError, match="isolated wallet posting"):
                await _send(service, run_id=run, session_id=sid, command_id="interrupted",
                            command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 2})
        after = await _portfolio(service, run)
        assert after["isolated_wallets"] == before["isolated_wallets"]
        assert after["cash_balance"] == before["cash_balance"]
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM replay_training_contract_ledger WHERE kind='FUNDING_SETTLEMENT'").fetchone()[0] == 0
    finally:
        await service.shutdown(step_timeout=1)
    restored = await _risk_service(database, bar_prices=["99.5"] * 20)
    try:
        assert (await _portfolio(restored, run))["isolated_wallets"] == before["isolated_wallets"]
        assert (await restored.training.audit_account(run))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1)


async def test_schema25_rebuilds_wallet_without_changing_financial_history(tmp_path):
    database = tmp_path / "replay.db"
    service = await _risk_service(database, bar_prices=["99.5"] * 20)
    try:
        run, sid = await _open(service, tmp_path, "0.01")
        await _send(service, run_id=run, session_id=sid, command_id="funding",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 2})
        expected = (await _portfolio(service, run))["isolated_wallets"]
    finally:
        await service.shutdown(step_timeout=1)
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT * FROM replay_training_contract_ledger ORDER BY ledger_sequence").fetchall()
        connection.execute("DROP TABLE replay_training_isolated_wallet")
        connection.execute("UPDATE replay_training_schema_version SET version=25")
        # Prior releases used principal for this current derived field.
        connection.execute("UPDATE replay_training_position_leg SET isolated_wallet='70'")
        connection.row_factory = sqlite3.Row
        from app.replay.canonical import canonical_sha256
        from app.replay.training.persistence.account_marks import position_leg_component
        for row in connection.execute("SELECT * FROM replay_training_position_leg").fetchall():
            component = position_leg_component(row, accumulated_funding=row["accumulated_funding"],
                                               trading_fees=row["trading_fees"], liquidation_fees=row["liquidation_fees"])
            connection.execute("UPDATE replay_training_position_leg SET component_hash=? WHERE run_id=? AND track_id=? AND position_side=?",
                               (canonical_sha256(component), run, row["track_id"], row["position_side"]))
    restored = await _risk_service(database, bar_prices=["99.5"] * 20)
    try:
        assert (await _portfolio(restored, run))["isolated_wallets"] == expected
        audit = await restored.training.audit_account(run)
        assert audit["status"] == "PASS", audit["differences"]
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT * FROM replay_training_contract_ledger ORDER BY ledger_sequence").fetchall() == before
    finally:
        await restored.shutdown(step_timeout=1)


async def test_independent_audit_detects_wallet_projection_disagreement(tmp_path):
    database = tmp_path / "replay.db"
    service = await _risk_service(database, bar_prices=["99.5"] * 20)
    try:
        run, sid = await _open(service, tmp_path, "0.01")
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE replay_training_isolated_wallet SET balances_json=? WHERE run_id=?",
                               (json.dumps({"track-1:LONG": "70", "track-1:SHORT": "69.95"}), run))
        audit = await service.training.audit_account(run)
        assert audit["status"] == "FAIL"
        assert any(d["field"] == "portfolio.isolated_wallets[track-1:LONG]" for d in audit["differences"])
    finally:
        await service.shutdown(step_timeout=1)
