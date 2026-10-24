"""Isolated liquidation cannot spend another leg's or unallocated collateral."""

from dataclasses import replace
from decimal import Decimal

import pytest
from app.replay.training.models import ReplayV2CommandType

from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request
from tests.test_replay_hedge_fixed_funding import _place
from tests.test_replay_v2_training_phase5 import _acquire, _request
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


async def _isolated_case(service, root, *, victim, book_mode, insurance):
    other = "SHORT" if victim == "LONG" else "LONG"
    mark = "50" if victim == "LONG" else "150"
    request = replace(
        _sandbox_request(
            await _request(service), initial_equity="200", margin_mode="ISOLATED"
        ),
        market_type="futures",
    )
    request = await prepare_hedge_request(
        service,
        request,
        root=root,
        prefix="isolated-loss",
        mark_prices=["104"] + [mark] * 12,
        book_mode=book_mode,
        insurance_opening_balance=insurance,
        adl_candidates=[
            {
                "candidate_id": "profitable-counterparty",
                "symbol": "BTCUSDT",
                "position_side": other,
                "quantity": "100",
                "entry_price": "110" if other == "SHORT" else "90",
                "mark_price": "100",
                "initial_margin": "500",
                "margin_balance": "1000",
            }
        ],
    )
    created = await service.training.create_run(request)
    run, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
    await _acquire(service, run_id=run, selected_session_id=sid, command_id="acquire")
    for side in ("LONG", "SHORT"):
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="allocate-" + side,
            command_type=ReplayV2CommandType.ALLOCATE_ISOLATED_MARGIN,
            payload={"track_id": "track-1", "position_side": side, "amount": "70"},
        )
        await _place(
            service, run, sid, "open-" + side, side, "2" if side == victim else "0.4"
        )
    return run, sid, (await service.training.get_market_tracks(run))["portfolio"]


@pytest.mark.parametrize("victim", ["LONG", "SHORT"])
@pytest.mark.parametrize("book_mode", ["OFF", "BOOK_ASSISTED_REQUIRED"])
@pytest.mark.parametrize("insurance", ["1000000", "0"])
async def test_isolated_gap_loss_is_capped_and_deficit_recovers_once(
    tmp_path,
    victim,
    book_mode,
    insurance,
):
    database = tmp_path / "replay.db"
    service = await _risk_service(database)
    try:
        run, sid, _before = await _isolated_case(
            service, tmp_path, victim=victim, book_mode=book_mode, insurance=insurance
        )
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="crash",
            command_type=ReplayV2CommandType.STEP_BASE,
            payload={"count": 2},
        )
        after = (await service.training.get_market_tracks(run))["portfolio"]
        # The victim's entire allocation lifecycle is capped, including entry
        # fees and funding. Only the survivor's own fee/funding affects free cash.
        expected_cash = Decimal("129.98" if victim == "LONG" else "129.96")
        assert Decimal(after["cash_balance"]) == expected_cash
        survivor = "SHORT" if victim == "LONG" else "LONG"
        assert [p["position_side"] for p in after["positions"]] == [survivor]
        assert abs(Decimal(after["positions"][0]["position"]["quantity"])) == Decimal(
            "0.4"
        )
        assert after["isolated_allocations"] == {"track-1:" + survivor: "70"}
        assert after["status"] == "ACTIVE"
        steps = [s["step_type"] for s in after["liquidations"][0]["steps"]]
        assert "BANKRUPTCY_TRANSFER" in steps
        assert ("ADL" in steps) == (insurance == "0")
        postings = after["hedge_state"]["insurance_postings"]
        assert [p["reason"] for p in postings] == [
            "LIQUIDATION_FEE_INFLOW",
            "BANKRUPTCY_DEFICIT_DEBIT",
        ]
        assert all(Decimal(p["balance_after"]) >= 0 for p in postings)
        assert (await service.training.audit_account(run))["status"] == "PASS"
        saved = (await service.training.get_market_tracks(run))["portfolio"]
    finally:
        await service.shutdown(step_timeout=1)
    restored = await _risk_service(database)
    try:
        assert (await restored.training.get_market_tracks(run))["portfolio"] == saved
        assert (await restored.training.audit_account(run))["status"] == "PASS"
    finally:
        await restored.shutdown(step_timeout=1)


@pytest.mark.parametrize("insurance", ["1000000", "0"])
async def test_isolated_credit_review_fork_preserves_parent_and_child(
    tmp_path, insurance
):
    service = await _risk_service(tmp_path / "replay.db")
    try:
        run, sid, _before = await _isolated_case(
            service,
            tmp_path,
            victim="LONG",
            book_mode="BOOK_ASSISTED_REQUIRED",
            insurance=insurance,
        )
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="crash",
            command_type=ReplayV2CommandType.STEP_BASE,
            payload={"count": 2},
        )
        await service.training.record_review_marker(
            run, command_id="settled", text="Isolated deficit settled"
        )
        review = await service.training.start_review(run, event_id=None)
        parent = await service.training.audit_account(run)
        child = await service.training.fork_run(
            run, event_id=review["selected_event_id"]
        )
        child_id = child["run"]["run_id"]
        child_portfolio = (await service.training.get_market_tracks(child_id))[
            "portfolio"
        ]
        assert Decimal(child_portfolio["cash_balance"]) == Decimal("129.98")
        assert child_portfolio["status"] == "ACTIVE"
        audit = await service.training.audit_account(child_id)
        assert audit["status"] == "PASS", audit["differences"]
        assert (await service.training.audit_account(run))["proof_hash"] == parent[
            "proof_hash"
        ]
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.parametrize("boundary", ["BEFORE_COMMIT", "AFTER_COMMIT"])
@pytest.mark.parametrize(
    "method_name",
    [
        "commit_liquidation_bankruptcy",
        "commit_liquidation_insurance",
        "commit_liquidation_adl",
    ],
)
async def test_isolated_credit_and_risk_steps_resume_without_double_credit(
    tmp_path, monkeypatch, boundary, method_name
):
    database = tmp_path / "replay.db"
    service = await _risk_service(database)
    try:
        run, sid, _before = await _isolated_case(
            service,
            tmp_path,
            victim="LONG",
            book_mode="BOOK_ASSISTED_REQUIRED",
            insurance="0",
        )

        async def defer(**_kwargs):
            return 0

        with monkeypatch.context() as patch:
            patch.setattr(
                service.training._ordered_playback, "_reconcile_liquidations", defer
            )
            await _send(
                service,
                run_id=run,
                session_id=sid,
                command_id="crash",
                command_type=ReplayV2CommandType.STEP_BASE,
                payload={"count": 2},
            )
        store = service.training.store
        original = getattr(store, method_name)

        async def interrupt(*args, **kwargs):
            if boundary == "BEFORE_COMMIT":
                raise RuntimeError("isolated pre-commit interruption")
            await original(*args, **kwargs)
            raise RuntimeError("isolated lost committed reply")

        with monkeypatch.context() as patch:
            patch.setattr(store, method_name, interrupt)
            with pytest.raises(RuntimeError, match="isolated"):
                await service.training._ordered_playback._reconcile_liquidations(
                    run_id=run, client_instance_id="phase5-browser", command_id="finish"
                )
    finally:
        await service.shutdown(step_timeout=1)
    restored = await _risk_service(database)
    try:
        await restored.training._ordered_playback._reconcile_liquidations(
            run_id=run, client_instance_id="phase5-browser", command_id="finish"
        )
        portfolio = (await restored.training.get_market_tracks(run))["portfolio"]
        assert Decimal(portfolio["cash_balance"]) == Decimal("129.98")
        assert portfolio["status"] == "ACTIVE"
        audit = await restored.training.audit_account(run)
        assert audit["status"] == "PASS", audit["differences"]
        import sqlite3

        with sqlite3.connect(database) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM replay_training_contract_ledger WHERE kind='ISOLATED_BANKRUPTCY_TRANSFER'"
                ).fetchone()[0]
                == 1
            )
    finally:
        await restored.shutdown(step_timeout=1)


async def test_audit_detects_uncapped_isolated_loss_even_with_consistent_ledger(
    tmp_path, monkeypatch
):
    from app.replay.training.persistence import isolated_loss

    service = await _risk_service(tmp_path / "replay.db")
    try:
        run, sid, _before = await _isolated_case(
            service,
            tmp_path,
            victim="LONG",
            book_mode="BOOK_ASSISTED_REQUIRED",
            insurance="1000000",
        )
        # Reproduce the old omission without corrupting ledger hashes: the
        # independent audit must not trust the reducer's planned zero deficit.
        with monkeypatch.context() as patch:
            patch.setattr(
                isolated_loss, "closed_scope_deficit", lambda *_args: Decimal(0)
            )
            await _send(
                service,
                run_id=run,
                session_id=sid,
                command_id="crash",
                command_type=ReplayV2CommandType.STEP_BASE,
                payload={"count": 2},
            )
        audit = await service.training.audit_account(run)
        assert audit["status"] == "FAIL"
        assert any(
            d["field"].startswith("isolated_loss[")
            and d["field"].endswith(".bankruptcy_step")
            for d in audit["differences"]
        )
    finally:
        await service.shutdown(step_timeout=1)


async def test_partial_then_full_liquidation_shares_one_allocation_budget(tmp_path):
    service = await _risk_service(tmp_path / "replay.db")
    try:
        request = replace(
            _sandbox_request(
                await _request(service), initial_equity="1000", margin_mode="ISOLATED"
            ),
            market_type="futures",
        )
        request = await prepare_hedge_request(
            service,
            request,
            root=tmp_path,
            prefix="two-stage",
            mark_prices=["104", "50"] + ["10"] * 11,
            maintenance_tiers=[
                {
                    "notional_cap": "100",
                    "maintenance_rate": "0.005",
                    "maintenance_deduction": "0",
                },
                {
                    "notional_cap": "1000000",
                    "maintenance_rate": "0.5",
                    "maintenance_deduction": "49.5",
                },
            ],
            book_level_quantities=["0.1", "0.1", "0.1", "0.1", "10"],
        )
        created = await service.training.create_run(request)
        run, sid = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await _acquire(
            service, run_id=run, selected_session_id=sid, command_id="acquire"
        )
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="allocate",
            command_type=ReplayV2CommandType.ALLOCATE_ISOLATED_MARGIN,
            payload={"track_id": "track-1", "position_side": "LONG", "amount": "140"},
        )
        await _place(service, run, sid, "open", "LONG", "2.4")
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="partial",
            command_type=ReplayV2CommandType.STEP_BASE,
            payload={"count": 2},
        )
        partial = (await service.training.get_market_tracks(run))["portfolio"]
        assert Decimal(partial["positions"][0]["position"]["quantity"]) == Decimal(2)
        assert Decimal(partial["cash_balance"]) == Decimal("977.12584")
        assert (await service.training.audit_account(run))["status"] == "PASS"
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="full",
            command_type=ReplayV2CommandType.STEP_BASE,
            payload={"count": 1},
        )
        final = (await service.training.get_market_tracks(run))["portfolio"]
        assert final["positions"] == []
        assert Decimal(final["cash_balance"]) == Decimal(860)
        assert len(final["liquidations"]) == 2
        audit = await service.training.audit_account(run)
        assert audit["status"] == "PASS", audit["differences"]
    finally:
        await service.shutdown(step_timeout=1)


async def test_isolated_child_liquidates_after_two_forks_and_reallocation(tmp_path):
    service = await _risk_service(tmp_path / "replay.db")
    try:
        run, sid, _before = await _isolated_case(
            service,
            tmp_path,
            victim="LONG",
            book_mode="BOOK_ASSISTED_REQUIRED",
            insurance="1000000",
        )
        original_run = run
        original = await service.training.audit_account(run)
        for index in range(2):
            await service.training.record_review_marker(
                run, command_id=f"fork-marker-{index}", text="Before gap"
            )
            review = await service.training.start_review(run, event_id=None)
            child = await service.training.fork_run(
                run, event_id=review["selected_event_id"]
            )
            run, sid = child["run"]["run_id"], child["run"]["adapter_session_id"]
        await _acquire(
            service, run_id=run, selected_session_id=sid, command_id="acquire-child"
        )
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="increase-budget",
            command_type=ReplayV2CommandType.ALLOCATE_ISOLATED_MARGIN,
            payload={"track_id": "track-1", "position_side": "LONG", "amount": "80"},
        )
        await _send(
            service,
            run_id=run,
            session_id=sid,
            command_id="crash-child",
            command_type=ReplayV2CommandType.STEP_BASE,
            payload={"count": 2},
        )
        final = (await service.training.get_market_tracks(run))["portfolio"]
        assert Decimal(final["cash_balance"]) == Decimal("119.98")
        audit = await service.training.audit_account(run)
        assert audit["status"] == "PASS", audit["differences"]
        assert (await service.training.audit_account(original_run))[
            "proof_hash"
        ] == original["proof_hash"]
    finally:
        await service.shutdown(step_timeout=1)
