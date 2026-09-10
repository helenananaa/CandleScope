from types import SimpleNamespace
from decimal import Decimal
import sqlite3
import json

import pytest

from app.replay.errors import ReplayDomainError
from app.replay.training.models import ReplayV2CommandType
from app.replay.training.storage import TrainingRunStore
from app.replay.training.review import ReviewRecorder
from app.replay.actor import ReplaySessionActor
from app.replay.training import storage as training_storage
from app.replay.canonical import canonical_json_bytes
from tests.test_replay_hedge_wave_commit import seed, copy_store
from tests.test_replay_v2_training_phase6 import _send, _risk_service
from tests.test_replay_interval_advance import (
    test_waiting_order_skips_safe_prefix_and_stops_at_first_fill as run_case,
)


def test_ledger_tail_lookup_uses_bounded_work_with_large_history():
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE replay_training_contract_account(run_id TEXT PRIMARY KEY, ledger_tail_hash TEXT);
            CREATE TABLE replay_training_contract_ledger(run_id TEXT, ledger_sequence INTEGER,
                                                        PRIMARY KEY(run_id,ledger_sequence));
            INSERT INTO replay_training_contract_account VALUES ('run','tail');
        """)
        empty = TrainingRunStore._contract_ledger_append_state(connection, run_id="run")
        assert (empty.next_sequence, empty.tail_hash) == (1, "tail")
        connection.executemany(
            "INSERT INTO replay_training_contract_ledger VALUES ('run',?)",
            ((i,) for i in range(1, 10001)),
        )
        steps = 0

        def progress():
            nonlocal steps
            steps += 1
            return 0

        connection.set_progress_handler(progress, 1)
        state = TrainingRunStore._contract_ledger_append_state(connection, run_id="run")
        connection.set_progress_handler(None, 0)
        assert (state.next_sequence, state.tail_hash) == (10001, "tail")
        assert steps < 100


def test_owned_snapshot_encoding_does_not_alias_mutable_views(monkeypatch):
    from tests.fixtures.replay.broker_fakes import make_broker, bar

    broker = make_broker()
    for index in range(10):
        broker.apply_bar(bar(index, 100 + index))
    first = broker.snapshot()
    close = first["bar_builder"]["closed_bars"][0]["close"]
    first["bar_builder"]["closed_bars"][0]["close"] = "99999"
    current, encoded = broker._owned_snapshot_with_encoding()
    assert current["bar_builder"]["closed_bars"][0]["close"] == close
    assert encoded == canonical_json_bytes(current)
    broker.restore(current)
    restored, encoded = broker._owned_snapshot_with_encoding()
    assert restored == current and encoded == canonical_json_bytes(restored)
    monkeypatch.setattr(broker, "snapshot", lambda: {"custom": True})
    assert broker._owned_snapshot_with_encoding() == ({"custom": True}, None)


@pytest.mark.anyio
async def test_recorded_review_descriptor_matches_uncached_history(
    tmp_path, monkeypatch
):
    original = ReviewRecorder._descriptor_domain
    checked = 0

    def compare(self, connection, *, run_id):
        nonlocal checked
        result = original(self, connection, run_id=run_id)
        if getattr(self.owner, "_recorded_review_frame", None) is not None:
            assert result == self._uncached_descriptor_domain(connection, run_id=run_id)
            checked += 1
        return result

    monkeypatch.setattr(ReviewRecorder, "_descriptor_domain", compare)
    await run_case(tmp_path, monkeypatch, False, 0, True, "SHORT", "CROSS", True)
    assert checked > 64


@pytest.mark.anyio
async def test_recorded_owned_encoding_matches_full_state_hash(tmp_path, monkeypatch):
    original = ReplaySessionActor._compute_state_hash
    checked = 0

    def compare(self, *, component_state=None):
        nonlocal checked
        result = original(self, component_state=component_state)
        if component_state is None:
            assert result == original(self, component_state=self._component_state())
            checked += 1
        return result

    monkeypatch.setattr(ReplaySessionActor, "_compute_state_hash", compare)
    await run_case(tmp_path, monkeypatch, False, 0, True, "LONG", "CROSS", True)
    assert checked > 200


@pytest.mark.anyio
async def test_recorded_retention_matches_per_event_pruning(tmp_path, monkeypatch):
    monkeypatch.setattr(
        training_storage,
        "_EQUITY_RESOLUTIONS",
        tuple(
            (name, bucket, 4)
            for name, bucket, _ in training_storage._EQUITY_RESOLUTIONS
        ),
    )
    await run_case(tmp_path, monkeypatch, False, 0, True, "SHORT", "CROSS", True)


@pytest.mark.anyio
async def test_recorded_middle_review_anchor_can_fork(tmp_path, monkeypatch):
    await run_case(tmp_path, monkeypatch, False, 0, True, "SHORT", "CROSS", True, True)


@pytest.mark.anyio
async def test_recorded_cross_envelope_includes_open_order_reservations(tmp_path):
    service, run_id, session_id = await seed(
        tmp_path / "reserved.db", initial_equity="100", quantity="0.9"
    )
    try:
        await _send(
            service,
            run_id=run_id,
            session_id=session_id,
            command_id="prime",
            command_type=ReplayV2CommandType.ADVANCE,
            payload={"basis": "BASE_BAR", "count": 3},
        )
        store = service.training.store
        assert await store.recorded_interval_certificate(
            run_id, low=Decimal("50"), high=Decimal("110")
        )
        await _send(
            service,
            run_id=run_id,
            session_id=session_id,
            command_id="reserve",
            command_type=ReplayV2CommandType.PLACE_ORDER,
            payload={
                "client_order_id": "reserve",
                "side": "BUY",
                "position_side": "LONG",
                "order_type": "LIMIT",
                "quantity": "2",
                "reduce_only": False,
                "limit_price": "20",
                "stop_price": None,
            },
        )
        await store.finalize_hedge_inputs(run_id)
        row = await service.store.run_extension_read(
            lambda c: dict(
                c.execute(
                    "SELECT position_json,open_orders_json,current_equity FROM replay_training_market_track JOIN replay_training_run USING(run_id) WHERE run_id=?",
                    (run_id,),
                ).fetchone()
            )
        )
        leg = json.loads(row["position_json"])["long"]
        orders = json.loads(row["open_orders_json"])
        actual_orders = (await service.get_session(session_id))["snapshot"][
            "components"
        ]["orders"]
        assert len(orders) == 1 and orders[0]["status"] == "OPEN", [
            (o["status"], o.get("status_reason"), o.get("limit_price"))
            for o in actual_orders
        ]
        reserved = sum(
            (Decimal(order["reserved_margin"]) for order in orders), Decimal(0)
        )
        cash = Decimal(row["current_equity"]) - Decimal(leg["unrealized_pnl"])
        scoped_equity = reserved * Decimal("0.8")
        low = Decimal(leg["entry_price"]) + (scoped_equity - cash) / Decimal(
            leg["quantity"]
        )
        assert low > 0 and scoped_equity > Decimal("0.1")
        assert (
            await store.recorded_interval_certificate(
                run_id, low=low, high=Decimal("110")
            )
            is None
        )
        assert await store.recorded_interval_certificate(
            run_id, low=Decimal("100"), high=Decimal("110")
        )
        assert not await store.pending_liquidations(run_id)
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
@pytest.mark.parametrize("policy", ["HIDE_ALL", "HIDE_DAY"])
async def test_recorded_interval_preserves_disclosed_time_domain(
    tmp_path, monkeypatch, policy
):
    await run_case(
        tmp_path,
        monkeypatch,
        False,
        0,
        True,
        "SHORT",
        "CROSS",
        True,
        time_disclosure_policy=policy,
    )


@pytest.mark.anyio
async def test_recorded_committed_prefix_recovers_and_continues(tmp_path):
    path = tmp_path / "resume.db"
    service, run_id, session_id = await seed(path)
    try:
        await _send(
            service,
            run_id=run_id,
            session_id=session_id,
            command_id="prime",
            command_type=ReplayV2CommandType.ADVANCE,
            payload={"basis": "BASE_BAR", "count": 3},
        )
        snapshot = (await service.get_session(session_id))["snapshot"]
        result = await service.training._try_recorded_interval(
            command=SimpleNamespace(
                run_id=run_id,
                command_id="committed-prefix",
                client_instance_id=snapshot["controller_client_id"],
            ),
            binding=await service.training.store.run_binding(run_id),
            tracks=tuple(await service.training.store.get_market_track_heads(run_id)),
            snapshot=snapshot,
            target=snapshot["cursor"]["virtual_time_ms"] + 4 * 60000,
            runtime_snapshot=await service.training.hedge_inputs.runtime_snapshot(
                run_id
            ),
        )
        assert result is not None
        committed = await service.get_session_state(session_id)
        assert (
            committed["cursor"]["source_sequence"]
            > snapshot["cursor"]["source_sequence"] + 1
        )
        await service.shutdown(step_timeout=1)
        service = await _risk_service(path)
        assert (await service.get_session_state(session_id))["state_hash"] == committed[
            "state_hash"
        ]
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
        from tests.test_replay_v2_training_phase5 import _acquire

        await _acquire(
            service,
            run_id=run_id,
            selected_session_id=session_id,
            command_id="resume-acquire",
        )
        advanced = await _send(
            service,
            run_id=run_id,
            session_id=session_id,
            command_id="resume",
            command_type=ReplayV2CommandType.ADVANCE,
            payload={"basis": "BASE_BAR", "count": 1},
        )
        assert (
            advanced["cursor"]["source_sequence"]
            > committed["cursor"]["source_sequence"]
        )
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["history", "checkpoint", "final_checkpoint"])
async def test_recorded_interval_failure_rolls_back_the_entire_prefix(
    tmp_path, monkeypatch, stage
):
    path = tmp_path / "recorded.db"
    service, run_id, session_id = await seed(path)
    try:
        await _send(
            service,
            run_id=run_id,
            session_id=session_id,
            command_id="prime",
            command_type=ReplayV2CommandType.ADVANCE,
            payload={"basis": "BASE_BAR", "count": 3},
        )
        store = service.training.store
        snapshot = (await service.get_session(session_id))["snapshot"]
        binding = await store.run_binding(run_id)
        tracks = tuple(await store.get_market_track_heads(run_id))
        inputs = await service.training.hedge_inputs.runtime_snapshot(run_id)
        tables = (
            "replay_training_contract_ledger",
            "replay_training_position_leg",
            "replay_training_margin_bucket",
            "replay_hedge_track_public_projection",
            "replay_hedge_track_public_applied_event",
            "replay_training_global_checkpoint",
            "replay_training_global_event",
            "replay_review_timeline_event",
            "replay_review_actor_anchor",
            "replay_equity_sample",
            "replay_checkpoint",
            "replay_command_log",
            "replay_session",
        )

        def capture(connection):
            return {
                table: tuple(
                    tuple(row)
                    for row in connection.execute(
                        f"SELECT * FROM {table} ORDER BY rowid"
                    )
                )
                for table in tables
            }

        before = await service.store.run_extension_read(capture)
        cache = dict(store._hedge_risk_fingerprints)
        offset = (await service.store.get_session(session_id))["command_log_offset"]
        called = 0
        owner = service.store if stage == "final_checkpoint" else store
        name = (
            "_insert_checkpoint"
            if stage == "final_checkpoint"
            else "_finalize_hedge_inputs_in_transaction"
            if stage == "history"
            else "_record_global_events_in_transaction"
        )
        original = getattr(owner, name)

        def fail_inside(*args, **kwargs):
            nonlocal called
            result = original(*args, **kwargs)
            if stage == "final_checkpoint":
                if kwargs["state"]["command_log_offset"] > offset:
                    called += 1
                    raise RuntimeError("recorded history fault")
                return result
            called += 1
            if called == 2:
                raise RuntimeError("recorded history fault")
            return result

        monkeypatch.setattr(owner, name, fail_inside)
        with pytest.raises(ReplayDomainError) as failed:
            result = await service.training._try_recorded_interval(
                command=SimpleNamespace(
                    run_id=run_id,
                    command_id="recorded-fault",
                    client_instance_id=snapshot["controller_client_id"],
                ),
                binding=binding,
                tracks=tracks,
                snapshot=snapshot,
                target=snapshot["cursor"]["virtual_time_ms"] + 4 * 60000,
                runtime_snapshot=inputs,
            )
            assert result is not None, (
                snapshot["components"]["position"],
                snapshot["cursor"],
                binding["funding_mode"],
                cache,
            )
        assert "recorded history fault" in str(failed.value.details)
        assert called == (1 if stage == "final_checkpoint" else 2)
        assert await service.store.run_extension_read(capture) == before
        assert store._hedge_risk_fingerprints == cache
        assert store._recorded_interval_plans == {}
        assert store._recorded_review_frame is None
        state = await service.get_session_state(session_id)
        assert state["cursor"] == snapshot["cursor"]
        assert state["state_hash"] == snapshot["state_hash"]
        monkeypatch.setattr(owner, name, original)
        # Preserve the crash-time durable image. A graceful shutdown of the
        # intentionally degraded actor separately persists its diagnostic state.
        recovered_path = tmp_path / "crash-recovery.db"
        copy_store(path, recovered_path)
        with sqlite3.connect(path) as source, sqlite3.connect(recovered_path) as target:
            source.backup(target)
        await service.shutdown(step_timeout=1)
        service = await _risk_service(recovered_path)
        assert (await service.get_session_state(session_id))["state_hash"] == snapshot[
            "state_hash"
        ]
        assert (await service.training.audit_account(run_id))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
@pytest.mark.parametrize("touch,funding", [(True, 0), (False, 11)])
async def test_recorded_prefix_stops_at_first_interaction(
    tmp_path, monkeypatch, touch, funding
):
    await run_case(tmp_path, monkeypatch, touch, funding, True, "LONG", "CROSS", True)


@pytest.mark.anyio
async def test_risk_envelope_rejects_unsafe_range_and_changed_account(tmp_path):
    service, run_id, session_id = await seed(tmp_path / "proof.db")
    try:
        await _send(
            service,
            run_id=run_id,
            session_id=session_id,
            command_id="prime",
            command_type=ReplayV2CommandType.ADVANCE,
            payload={"basis": "BASE_BAR", "count": 3},
        )
        store = service.training.store
        assert await store.recorded_interval_certificate(
            run_id, low=Decimal("90"), high=Decimal("110")
        )
        projection = await service.store.run_extension_read(
            lambda c: dict(
                c.execute(
                    "SELECT p.component_hash,b.bound_range_end_ms FROM replay_hedge_track_public_projection p JOIN replay_hedge_track_public_binding b USING(run_id,track_id) WHERE run_id=?",
                    (run_id,),
                ).fetchone()
            )
        )
        assert (
            await store.recorded_interval_certificate(
                run_id,
                low=Decimal("90"),
                high=Decimal("110"),
                target_actual_time_ms=projection["bound_range_end_ms"] + 1,
            )
            is None
        )
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_hedge_track_public_projection SET component_hash=? WHERE run_id=?",
                ("sha256:" + "0" * 64, run_id),
            )
        )
        assert (
            await store.recorded_interval_certificate(
                run_id, low=Decimal("90"), high=Decimal("110")
            )
            is None
        )
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_hedge_track_public_projection SET component_hash=? WHERE run_id=?",
                (projection["component_hash"], run_id),
            )
        )
        assert (
            await store.recorded_interval_certificate(
                run_id, low=Decimal("0.001"), high=Decimal("1000000000")
            )
            is None
        )
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_training_contract_account SET overlay_cash = '-9999' WHERE run_id = ?",
                (run_id,),
            )
        )
        assert (
            await store.recorded_interval_certificate(
                run_id, low=Decimal("90"), high=Decimal("110")
            )
            is None
        )
    finally:
        await service.shutdown(step_timeout=1)
