from dataclasses import replace
from decimal import Decimal, ROUND_CEILING

import pytest

from app.replay.training.models import TrainingRunCreateRequest, ReplayV2CommandType
from tests.test_replay_v2_training_phase5 import _acquire, _request
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


def test_extension_cohorts_cover_both_bankrupt_sides_without_insurance_reset():
    from app.replay.training.hybrid_extensions import build_extension, validate_extension
    from app.replay.training.hedge_simulation_contract import select_adl_candidates
    from app.replay.canonical import canonical_json, canonical_sha256
    payload = build_extension(symbol="SOLUSDT", settlement_asset="USDT", base_manifest_id="original",
        base_checksum="original-hash", public_archive_id="public", public_checksum="public-hash",
        actual_time_ms=1000, virtual_time_ms=5000, end_time_ms=2000, price="120", leverage="3")
    restored = validate_extension({"payload_json": canonical_json(payload), "component_hash": canonical_sha256(payload)})
    assert restored["snapshot"]["effective_time_ms"] == 5000
    assert restored["snapshot"]["valid_until_ms"] == 6000
    assert "insurance" not in canonical_json(payload)
    for side in ("LONG", "SHORT"):
        assert select_adl_candidates(restored["snapshot"]["candidates"], bankrupt_position_side=side,
            takeover_quantity="0.5", quote_step="0.00000001")["status"] == "COMPLETED"


@pytest.mark.parametrize("disclosure", ["NONE", "HIDE_ALL"])
async def test_hybrid_added_market_preserves_account_and_original_simulation(tmp_path, disclosure, monkeypatch):
    database = tmp_path / "hybrid-markets.db"
    service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"), bar_prices=["100"] * 20)
    try:
        payload = replace(_sandbox_request(await _request(service)), market_type="futures").to_dict()
        payload.update(position_mode="HEDGE", account_data_mode="DETERMINISTIC_SIMULATION",
            time_disclosure_policy=disclosure,
            account_fidelity="PINNED_PUBLIC_INPUTS_DETERMINISTIC_SIMULATED_PRIVATE_STATE",
            insurance_adl_fidelity="DETERMINISTIC_SIMULATION_NOT_HISTORICAL_EXCHANGE_FACT")
        created = await service.training.create_run(TrainingRunCreateRequest.from_dict(payload))
        run_id = created["run"]["run_id"]
        session = created["run"]["adapter_session_id"]
        await _acquire(service, run_id=run_id, selected_session_id=session, command_id="hybrid-acquire")
        await _send(service, run_id=run_id, session_id=session, command_id="hybrid-step-before",
            command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 2})

        async def frozen_account():
            return await service.training.store.base_store.run_extension_read(lambda c: {
                "binding": dict(c.execute("SELECT * FROM replay_hedge_input_binding WHERE run_id=?", (run_id,)).fetchone()),
                "insurance": [dict(r) for r in c.execute("SELECT * FROM replay_training_insurance_fund WHERE run_id=?", (run_id,))],
            })

        before = await frozen_account()
        async def open_both(selected, prefix):
            for side, position_side in (("BUY", "LONG"), ("SELL", "SHORT")):
                await _send(service, run_id=run_id, session_id=selected, command_id=f"{prefix}-{side}",
                    command_type=ReplayV2CommandType.PLACE_ORDER, payload={"client_order_id": f"{prefix}-{side}",
                        "side": side, "position_side": position_side, "order_type": "MARKET", "quantity": "1",
                        "leverage": "3", "reduce_only": False, "limit_price": None, "stop_price": None})

        await open_both(session, "btc")
        # A pre-existing exact archive can sort before the freshly generated
        # hybrid input. Admission must pin the current seed/fee-policy receipt.
        import json
        from app.replay.training.hedge_inputs import build_hedge_public_history_archive
        inputs = service.training.hedge_inputs
        original_ensure = inputs.ensure_hybrid_inputs
        async def ensure_with_competing_archive(*args, **kwargs):
            receipt = await original_ensure(*args, **kwargs)
            if kwargs.get("public_only"):
                raw = json.loads((inputs.root / "generated" / f'{receipt["public"]["object_id"]}.json').read_text())
                competing = tmp_path / "other-public.json"
                build_hedge_public_history_archive(competing,
                    archive_id="aaa-other-public-source",
                    **{key: raw[key] for key in ("exchange", "market_type", "symbol", "settlement_asset",
                        "range_start_ms", "range_end_ms", "max_mark_gap_ms", "historical_l2_ref")},
                    source_identity="OTHER_OPERATOR_CAPTURE", capture_receipt="test-other-source",
                    events=[{key: event[key] for key in ("event_time_ms", "event_kind", "payload")}
                            for event in raw["events"]])
                await inputs.import_public(competing)
            return receipt
        monkeypatch.setattr(inputs, "ensure_hybrid_inputs", ensure_with_competing_archive)
        if disclosure == "NONE":
            from app.replay.training import hedge_inputs
            from app.replay.training.errors import TrainingRunError
            original_bind = hedge_inputs.bind_extension
            def interrupted_bind(*args, **kwargs):
                original_bind(*args, **kwargs)
                raise RuntimeError("injected admission failure after supplemental input insert")
            monkeypatch.setattr(hedge_inputs, "bind_extension", interrupted_bind)
            with pytest.raises(TrainingRunError, match="could not be prepared"):
                await _send(service, run_id=run_id, session_id=session, command_id="hybrid-interrupted-add",
                    command_type=ReplayV2CommandType.ADD_TRACK, payload={"exchange": "binance", "market_type": "futures",
                        "symbol": "ETHUSDT", "settlement_asset": "USDT", "subscription_tier": "FULL"})
            assert await frozen_account() == before
            assert len((await service.training.get_market_tracks(run_id))["tracks"]) == 1
            assert await service.store.run_extension_read(lambda c: c.execute(
                "SELECT COUNT(*) FROM replay_hedge_hybrid_extension WHERE run_id=?", (run_id,)).fetchone()[0]) == 0
            monkeypatch.setattr(hedge_inputs, "bind_extension", original_bind)
        await _send(service, run_id=run_id, session_id=session, command_id="hybrid-add-eth",
            command_type=ReplayV2CommandType.ADD_TRACK, payload={"exchange": "binance", "market_type": "futures",
                "symbol": "ETHUSDT", "settlement_asset": "USDT", "subscription_tier": "FULL"})
        tracks = await service.training.get_market_tracks(run_id)
        assert len(tracks["tracks"]) == 2
        assert {t["subscription_tier"] for t in tracks["tracks"]} == {"FULL"}
        assert await frozen_account() == before
        selected = await _send(service, run_id=run_id, session_id=session, command_id="hybrid-select-eth",
            command_type=ReplayV2CommandType.SELECT_TRACK, payload={"track_id": "track-2", "expected_viewer_revision": 0})
        secondary = selected["session_id"]
        await open_both(secondary, "eth")
        tracks = await service.training.get_market_tracks(run_id)
        assert len(tracks["portfolio"]["positions"]) == 4
        extension = tracks["portfolio"]["hedge_inputs"]["hybrid_extensions"][0]
        assert extension["track_id"] == "track-2"
        assert extension["time_domain"] == ("ACTUAL" if disclosure == "NONE" else "PUBLIC")
        assert "payload_json" not in extension
        assert (await service.training.hedge_inputs.audit_run(run_id))["status"] == "PASS"
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
        await _send(service, run_id=run_id, session_id=secondary, command_id="hybrid-step-after",
            command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert (await service.training.hedge_inputs.audit_run(run_id))["status"] == "PASS"
        tracks = await service.training.get_market_tracks(run_id)
        positions = tracks["portfolio"]["positions"]
        assert len({t["cursor"]["virtual_time_ms"] for t in tracks["tracks"]}) == 1
        await service.shutdown(step_timeout=1.0)
        service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"), bar_prices=["100"] * 20)
        # This fixture's counter-based IDs reset on restart; production uses UUIDs.
        import uuid
        service._session_id_factory = lambda: uuid.uuid4().hex
        service.training._run_id_factory = lambda: uuid.uuid4().hex
        recovered = await service.training.get_market_tracks(run_id)
        assert recovered["portfolio"]["positions"] == positions
        assert recovered["portfolio"]["hedge_inputs"]["hybrid_extensions"] == [extension]
        audit = await service.training.audit_account(run_id)
        assert audit["status"] == "PASS", audit
        assert await frozen_account() == before
        # make_bar(price=100) closes at 100.5. Compute independently of the broker.
        buy, sell = Decimal("100.5") * Decimal("1.0001"), Decimal("100.5") * Decimal("0.9999")
        pair_fee = sum((p * Decimal("0.0005")).quantize(Decimal("0.00000001"), rounding=ROUND_CEILING) for p in (buy, sell))
        pair_cost = buy - sell + pair_fee
        assert Decimal(recovered["portfolio"]["equity"]) == Decimal("10000") - 2 * pair_cost
        await _acquire(service, run_id=run_id, selected_session_id=secondary, command_id="hybrid-reacquire")
        for track_id, selected_session in (("track-2", secondary), ("track-1", session)):
            if track_id == "track-1":
                await _send(service, run_id=run_id, session_id=secondary, command_id="hybrid-select-btc",
                    command_type=ReplayV2CommandType.SELECT_TRACK,
                    payload={"track_id": track_id, "expected_viewer_revision": 1})
            for side in ("LONG", "SHORT"):
                await _send(service, run_id=run_id, session_id=selected_session, command_id=f"hybrid-close-{track_id}-{side}",
                    command_type=ReplayV2CommandType.CLOSE_POSITION,
                    payload={"position_side": side, "quantity": "1"})
        final = (await service.training.get_market_tracks(run_id))["portfolio"]
        assert final["positions"] == []
        assert Decimal(final["equity"]) == Decimal("10000") - 4 * pair_cost
        assert final["ledger"]["reconciliation_delta"] == "0"
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
        review = await service.training.start_review(run_id, event_id=None)
        forked = await service.training.fork_run(run_id, event_id=review["selected_event_id"])
        child_id = forked["run"]["run_id"]
        child_audit = await service.training.audit_account(child_id)
        assert child_audit["status"] == "PASS", child_audit
        assert (await service.training.get_market_tracks(run_id))["portfolio"]["equity"] == final["equity"]
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_hybrid_aggregate_trade_run_admits_second_market_and_advances(tmp_path):
    from tests.test_replay_v2_training_phase5 import _trade_request, _trade_service
    service = await _trade_service(tmp_path / "hybrid-trades.db", archive_root=tmp_path / "trades",
                                   symbols=("BTCUSDT", "ETHUSDT"), constant_prices=True)
    try:
        payload = (await _trade_request(service)).to_dict()
        payload.update(position_mode="HEDGE", account_data_mode="DETERMINISTIC_SIMULATION",
            account_fidelity="PINNED_PUBLIC_INPUTS_DETERMINISTIC_SIMULATED_PRIVATE_STATE",
            insurance_adl_fidelity="DETERMINISTIC_SIMULATION_NOT_HISTORICAL_EXCHANGE_FACT")
        created = await service.training.create_run(TrainingRunCreateRequest.from_dict(payload))
        run_id, session = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await _acquire(service, run_id=run_id, selected_session_id=session, command_id="tape-acquire")
        await _send(service, run_id=run_id, session_id=session, command_id="tape-before",
            command_type=ReplayV2CommandType.STEP_EVENT, payload={"count": 2})
        await _send(service, run_id=run_id, session_id=session, command_id="tape-add",
            command_type=ReplayV2CommandType.ADD_TRACK, payload={"exchange": "binance", "market_type": "futures",
                "symbol": "ETHUSDT", "settlement_asset": "USDT", "subscription_tier": "FULL"})
        await _send(service, run_id=run_id, session_id=session, command_id="tape-after",
            command_type=ReplayV2CommandType.STEP_EVENT, payload={"count": 2})
        tracks = await service.training.get_market_tracks(run_id)
        assert len(tracks["tracks"]) == 2
        assert len({t["cursor"]["virtual_time_ms"] for t in tracks["tracks"]}) == 1
        audit = await service.training.audit_account(run_id)
        assert audit["status"] == "PASS", audit
    finally:
        await service.shutdown(step_timeout=1.0)


@pytest.mark.parametrize("old_version", [23, 24, 25])
async def test_schema_upgrade_preserves_existing_runs_and_null_admission_cursors(tmp_path, old_version):
    import sqlite3
    database = tmp_path / "migration.db"
    service = await _risk_service(database)
    from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request
    request = await prepare_hedge_request(service,
        replace(_sandbox_request(await _request(service)), market_type="futures"),
        root=tmp_path, prefix="migration", mark_prices=["104"] * 13)
    created = await service.training.create_run(request)
    run_id = created["run"]["run_id"]
    before = await service.training.get_market_tracks(run_id)
    await service.shutdown(step_timeout=1.0)
    # Reconstruct the preceding schema in this disposable fixture only.
    with sqlite3.connect(database) as c:
        if old_version < 25:
            c.execute("DROP TABLE replay_hedge_track_input_admission")
        if old_version == 23:
            c.execute("DROP TABLE replay_hedge_hybrid_extension")
            c.execute("ALTER TABLE replay_hedge_track_public_binding DROP COLUMN initial_event_sequence")
        else:
            c.execute("UPDATE replay_hedge_track_public_binding SET initial_event_sequence=NULL")
        c.execute("UPDATE replay_training_schema_version SET version=?", (old_version,))
    service = await _risk_service(database)
    try:
        after = await service.training.get_market_tracks(run_id)
        assert after["portfolio"]["equity"] == before["portfolio"]["equity"]
        assert after["tracks"] == before["tracks"]
        assert await service.store.run_extension_read(lambda c: c.execute(
            "SELECT version FROM replay_training_schema_version").fetchone()[0]) == 25
        cursors = await service.store.run_extension_read(lambda c: c.execute(
            "SELECT initial_event_sequence FROM replay_hedge_track_public_binding WHERE run_id=?", (run_id,)).fetchall())
        assert cursors and all(row[0] is None for row in cursors)
        assert await service.store.run_extension_read(lambda c: c.execute(
            "SELECT COUNT(*) FROM replay_hedge_track_input_admission").fetchone()[0]) == 0
        assert await service.store.run_extension_read(lambda c: c.execute(
            "SELECT COUNT(*) FROM replay_hedge_hybrid_extension").fetchone()[0]) == 0
    finally:
        await service.shutdown(step_timeout=1.0)
