"""Upgrade persisted pre-fix summaries without changing financial history."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest
from app.replay.training.models import ReplayV2CommandType
from app.replay.training.persistence import account_marks

from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request
from tests.test_replay_hedge_dormant_account_inputs import _changing_inputs
from tests.test_replay_hedge_track_readmission import _dormant_run
from tests.test_replay_v2_training_phase5 import _acquire, _request
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("position_side", ["LONG", "SHORT"])
async def test_old_polluted_summary_is_correct_before_actor_recovery(tmp_path, monkeypatch, position_side):
    database = tmp_path / "legacy-summary.db"
    service = await _risk_service(database, symbols=("BTCUSDT",))
    request = await prepare_hedge_request(
        service, replace(_sandbox_request(await _request(service)), market_type="futures"),
        root=tmp_path, prefix="legacy-summary", mark_prices=["104"] * 13,
    )
    created = await service.training.create_run(request)
    run, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
    await _acquire(service, run_id=run, selected_session_id=sid, command_id="acquire")
    await _send(service, run_id=run, session_id=sid, command_id="open",
                command_type=ReplayV2CommandType.PLACE_ORDER, payload={
                    "client_order_id": "open", "position_side": position_side,
                    "side": "BUY" if position_side == "LONG" else "SELL",
                    "order_type": "MARKET", "quantity": "1", "reduce_only": False,
                    "limit_price": None, "stop_price": None})
    await _send(service, run_id=run, session_id=sid, command_id="step",
                command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
    expected = (await service.training.get_market_tracks(run))["portfolio"]
    # Reproduce the old exporter on shutdown: adapter trade marks overwrite
    # summary rows while committed relational HEDGE legs retain the pinned mark.
    with monkeypatch.context() as old:
        old.setattr(account_marks, "apply_hedge_mark_projection", lambda *args, **kwargs: None)
        await service.shutdown(step_timeout=1.0)
    restored = await _risk_service(database, symbols=("BTCUSDT",))
    try:
        async def saved_rows():
            return await restored.training.hedge_inputs.store.run_extension_read(lambda c: (
                tuple(c.execute("SELECT * FROM replay_training_run WHERE run_id=?", (run,)).fetchone()),
                [tuple(r) for r in c.execute("SELECT * FROM replay_training_market_track WHERE run_id=? ORDER BY track_id", (run,))],
            ))

        before_read = await saved_rows()
        assert (await restored.training.get_run(run))["equity"] == expected["equity"]
        listing = await restored.training.list_runs(limit=20, cursor=None, state=None, source_kind=None, compatibility=None)
        assert next(item for item in listing["items"] if item["run_id"] == run)["equity"] == expected["equity"]
        assert await saved_rows() == before_read
        assert (await restored.training.get_market_tracks(run))["portfolio"] == expected
    finally:
        await restored.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("kind,delta", [(ReplayV2CommandType.DEPOSIT, "10"), (ReplayV2CommandType.WITHDRAW, "-10")])
@pytest.mark.parametrize("held", [False, True])
async def test_shared_capital_change_matches_live_wallet_and_rest(tmp_path, monkeypatch, kind, delta, held):
    _changing_inputs(monkeypatch)
    service = await _risk_service(tmp_path / "capital.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run, _, selected = await _dormant_run(service, tmp_path, initial_count=0, other_count=0)
        if held:
            for side, quantity in (("LONG", "1"), ("SHORT", "2")):
                await _send(service, run_id=run, session_id=selected, command_id="open-" + side,
                            command_type=ReplayV2CommandType.PLACE_ORDER, payload={
                                "client_order_id": "open-" + side, "position_side": side,
                                "side": "BUY" if side == "LONG" else "SELL",
                                "order_type": "MARKET", "quantity": quantity, "reduce_only": False,
                                "limit_price": None, "stop_price": None})
            await _send(service, run_id=run, session_id=selected, command_id="funding-step",
                        command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 3})
        before = (await service.training.get_market_tracks(run))["portfolio"]
        if held:
            assert Decimal(before["funding_cashflow"]) != 0
        await _send(service, run_id=run, session_id=selected, command_id="capital",
                    command_type=kind, payload={"amount": "10", "reason": "capital reconciliation"})
        expected = Decimal(before["cash_balance"]) + Decimal(delta)
        rest = (await service.training.get_market_tracks(run))["portfolio"]
        live = (await service.training.get_live_market_tracks(run))["portfolio"]
        assert Decimal(rest["cash_balance"]) == expected
        assert Decimal(live["cash_balance"]) == expected
        assert live["equity"] == rest["equity"]
        assert (await service.training.get_run(run))["equity"] == rest["equity"]
        assert live["funding_cashflow"] == rest["funding_cashflow"]
        assert live["fees_paid"] == rest["fees_paid"]
        action = await service.training.hedge_inputs.store.run_extension_read(lambda c: c.execute(
            "SELECT old_value_json,new_value_json FROM replay_run_action_event WHERE run_id=? AND command_id='capital'",
            (run,),
        ).fetchone())
        assert json.loads(action[0])["equity"] == before["equity"]
        assert json.loads(action[1])["equity"] == rest["equity"]
        audit = await service.training.audit_account(run)
        assert audit["status"] == "PASS", audit
        # Audit metadata changes NOT_RUN→PASS; compare the parent after that
        # explicit audit, so a new child cannot hide financial/cursor mutations.
        rest = (await service.training.get_market_tracks(run))["portfolio"]
        review = await service.training.start_review(run, event_id=None)
        assert review["projection"]["domain"]["portfolio"]["equity"] == rest["equity"]
        forked = await service.training.fork_run(run, event_id=review["selected_event_id"])
        child = forked["run"]["run_id"]
        child_portfolio = (await service.training.get_market_tracks(child))["portfolio"]
        assert child_portfolio["cash_balance"] == rest["cash_balance"]
        assert child_portfolio["equity"] == rest["equity"]
        assert (await service.training.get_market_tracks(run))["portfolio"] == rest
    finally:
        await service.shutdown(step_timeout=1.0)
    restored = await _risk_service(tmp_path / "capital.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        for saved_run in (run, child):
            saved = (await restored.training.get_live_market_tracks(saved_run))["portfolio"]
            for field in ("cash_balance", "equity", "available_equity", "fees_paid", "funding_cashflow"):
                assert saved[field] == rest[field], field
            assert (await restored.training.get_run(saved_run))["equity"] == rest["equity"]
            audit = await restored.training.audit_account(saved_run)
            assert audit["status"] == "PASS", audit
    finally:
        await restored.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("kind,delta", [(ReplayV2CommandType.DEPOSIT, "10"), (ReplayV2CommandType.WITHDRAW, "-10")])
async def test_exact_one_way_capital_receipt_remains_auditable(tmp_path, kind, delta):
    from tests.test_replay_v2_training_phase16 import (
        ARCHIVE_END,
        REPLAY_START,
        _base_request,
        _exact_request,
        _import_and_plan,
        _service,
        build_account_history_archive,
    )

    archive = tmp_path / "source-account.sqlite3"
    build_account_history_archive(archive, range_start_ms=REPLAY_START, range_end_ms=ARCHIVE_END)
    service = await _service(tmp_path / "exact-capital.db")
    try:
        request, _ = await _import_and_plan(service, archive, _exact_request(await _base_request(service), funding=False))
        created = await service.training.create_run(_sandbox_request(request))
        run, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await _acquire(service, run_id=run, selected_session_id=sid, command_id="capital-control")
        before = (await service.training.get_market_tracks(run))["portfolio"]
        await _send(service, run_id=run, session_id=sid, command_id="exact-capital",
                    command_type=kind, payload={"amount": "10", "reason": "capital reconciliation"})
        rest = (await service.training.get_market_tracks(run))["portfolio"]
        assert Decimal(rest["cash_balance"]) == Decimal(before["cash_balance"]) + Decimal(delta)
        audit = await service.training.audit_account(run)
        assert audit["status"] == "PASS", audit
    finally:
        await service.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("select_primary", [False, True])
async def test_return_to_hub_keeps_shared_card_current_with_unequal_track_revisions(tmp_path, select_primary):
    service = await _risk_service(tmp_path / "hub-card.db", symbols=("BTCUSDT", "ETHUSDT"))
    try:
        run, primary, selected = await _dormant_run(service, tmp_path)
        if select_primary:
            await _send(service, run_id=run, session_id=selected, command_id="select-primary",
                        command_type=ReplayV2CommandType.SELECT_TRACK,
                        payload={"track_id": "track-1", "expected_viewer_revision": 1})
            selected = primary
        await _send(service, run_id=run, session_id=selected, command_id="held-hub",
                    command_type=ReplayV2CommandType.PLACE_ORDER, payload={
                        "client_order_id": "held-hub", "position_side": "LONG", "side": "BUY",
                        "order_type": "MARKET", "quantity": "0.001", "reduce_only": False,
                        "limit_price": None, "stop_price": None})
        before = await service.training.get_market_tracks(run)
        assert len({track["cursor"]["revision"] for track in before["tracks"]}) > 1
        await service.training.return_to_hub(run)
        card = await service.training.get_run(run)
        assert card["equity_status"] == "CURRENT"
        assert card["equity"] == before["portfolio"]["equity"]
        listing = await service.training.list_runs(limit=20, cursor=None, state=None,
                                                   source_kind=None, compatibility=None)
        assert next(item for item in listing["items"] if item["run_id"] == run) == card
        after = await service.training.get_market_tracks(run)
        for key in ("cash_balance", "equity", "available_equity", "fees_paid", "positions"):
            assert after["portfolio"][key] == before["portfolio"][key]
    finally:
        await service.shutdown(step_timeout=1.0)
