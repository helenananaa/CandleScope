from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from app.replay.training.models import ReplayV2CommandType
from app.replay.training.commands import ReplayV2Command
from tests.fixtures.replay.hedge_input_fakes import prepare_hedge_request
from tests.test_replay_v2_training_phase5 import _acquire, _request
from tests.test_replay_v2_training_phase6 import _risk_service, _sandbox_request, _send

pytestmark = pytest.mark.anyio


async def seed(path: Path):
    service = await _risk_service(path)
    request = await prepare_hedge_request(
        service,
        replace(_sandbox_request(await _request(service)), market_type="futures"),
        root=path.parent,
        prefix="wave",
        mark_prices=["104", "103", "102", "105"] + ["104"] * 9,
        book_mode="OFF",
    )
    created = await service.training.create_run(request)
    run_id = str(created["run"]["run_id"])
    session_id = str(created["run"]["adapter_session_id"])
    await _acquire(
        service,
        run_id=run_id,
        selected_session_id=session_id,
        command_id="wave-acquire",
    )
    await _send(
        service,
        run_id=run_id,
        session_id=session_id,
        command_id="wave-open",
        command_type=ReplayV2CommandType.PLACE_ORDER,
        payload={
            "client_order_id": "wave-open",
            "side": "BUY",
            "position_side": "LONG",
            "order_type": "MARKET",
            "quantity": "0.1",
            "reduce_only": False,
            "limit_price": None,
            "stop_price": None,
        },
    )
    return service, run_id, session_id


def copy_store(source: Path, target: Path):
    shutil.copy2(source, target)
    for suffix in (
        ".datasets",
        "-hedge-inputs",
        "-historical-books",
        "-account-history",
    ):
        src = (
            Path(str(source) + suffix)
            if suffix.startswith(".")
            else source.with_name(source.stem + suffix)
        )
        dst = (
            Path(str(target) + suffix)
            if suffix.startswith(".")
            else target.with_name(target.stem + suffix)
        )
        if src.is_dir():
            shutil.copytree(src, dst)


async def test_merged_wave_matches_reference_and_reduces_transactions(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "seed.db"
    service, run_id, session_id = await seed(source)
    await service.shutdown(step_timeout=1)
    results = []
    for mode in ("reference", "merged"):
        database = tmp_path / f"{mode}.db"
        copy_store(source, database)
        service = await _risk_service(database)
        try:
            store = service.training.store
            if mode == "reference":

                async def reference(run_id, *, risk_virtual_time_ms, events):
                    await store.finalize_hedge_inputs(
                        run_id, risk_virtual_time_ms=risk_virtual_time_ms
                    )
                    return False

                monkeypatch.setattr(
                    store, "finalize_hedge_inputs_and_checkpoint", reference
                )
            await _acquire(
                service,
                run_id=run_id,
                selected_session_id=session_id,
                command_id="wave-resume",
            )
            before = service.store._metrics["transactions"]
            response = await _send(
                service,
                run_id=run_id,
                session_id=session_id,
                command_id="wave-step",
                command_type=ReplayV2CommandType.ADVANCE,
                payload={"basis": "BASE_BAR", "count": 4},
            )
            commits = service.store._metrics["transactions"] - before
            events = await store.global_events(run_id)
            tracks = await store.get_market_tracks(run_id)
            review = await service.store.run_extension_read(
                lambda connection: [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT timeline_sequence, event_hash, projection_json FROM replay_review_timeline_event WHERE run_id = ? ORDER BY timeline_sequence",
                        (run_id,),
                    )
                ]
            )
            results.append((response, events, tracks, review, commits))
            command_json = await service.store.run_extension_read(
                lambda connection: connection.execute(
                    "SELECT command_json FROM replay_training_command WHERE run_id = ? AND command_id = 'wave-step'",
                    (run_id,),
                ).fetchone()[0]
            )
        finally:
            await service.shutdown(step_timeout=1)
        recovered = await _risk_service(database)
        try:
            replayed = await recovered.training.command(
                run_id, ReplayV2Command.from_dict(json.loads(command_json))
            )
            assert replayed == response
            assert (await recovered.get_session_state(session_id))[
                "state_hash"
            ] == response["state_hash"]
        finally:
            await recovered.shutdown(step_timeout=1)
    assert results[0][:4] == results[1][:4]
    assert results[0][4] - results[1][4] == 4


async def test_failed_global_checkpoint_rolls_back_risk_and_does_not_cache(
    tmp_path: Path, monkeypatch
):
    service, run_id, _ = await seed(tmp_path / "rollback.db")
    try:
        store = service.training.store
        await store.finalize_hedge_inputs(run_id)
        cache_before = dict(store._hedge_risk_fingerprints)
        await service.store.run_extension_write(
            lambda connection: connection.execute(
                "UPDATE replay_training_market_track SET public_price = '999' WHERE run_id = ?",
                (run_id,),
            )
        )
        original = store._record_global_events_in_transaction

        def fail_after_checkpoint(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("checkpoint fault")

        monkeypatch.setattr(
            store, "_record_global_events_in_transaction", fail_after_checkpoint
        )
        with pytest.raises(RuntimeError, match="checkpoint fault"):
            await store.finalize_hedge_inputs_and_checkpoint(
                run_id, risk_virtual_time_ms=0, events=()
            )
        price = await service.store.run_extension_read(
            lambda connection: connection.execute(
                "SELECT public_price FROM replay_training_market_track WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
        )
        assert price == "999"
        assert store._hedge_risk_fingerprints == cache_before
        monkeypatch.setattr(store, "_record_global_events_in_transaction", original)
        assert await store.finalize_hedge_inputs_and_checkpoint(
            run_id, risk_virtual_time_ms=0, events=()
        )
    finally:
        await service.shutdown(step_timeout=1)


async def test_non_record_drawdown_skips_full_projection_but_keeps_new_minimum(
    tmp_path: Path, monkeypatch
):
    service, run_id, session_id = await seed(tmp_path / "review.db")
    try:
        review = service.training.store._review
        old = {"equity": "100", "order_hash": "same", "position_hash": "same"}
        await service.store.run_extension_write(
            lambda connection: connection.execute(
                "UPDATE replay_review_timeline_event SET projection_json = ? WHERE run_id = ?",
                (json.dumps({"domain": old}), run_id),
            )
        )
        from decimal import Decimal

        monkeypatch.setattr(
            review, "_minimum_prior_equity", lambda *args, **kwargs: Decimal("80")
        )
        monkeypatch.setattr(
            review,
            "_descriptor_domain",
            lambda *args, **kwargs: {**old, "equity": "90"},
        )

        def forbidden(*args, **kwargs):
            raise RuntimeError("full frame requested")

        monkeypatch.setattr(review, "projection", forbidden)

        def append(connection):
            return review.append(
                connection,
                run_id=run_id,
                session_id=session_id,
                context={"kind": "SOURCE_EVENT"},
                state=None,
                checkpoint=None,
                now_ms=0,
            )

        assert await service.store.run_extension_write(append) == ()
        monkeypatch.setattr(
            review,
            "_descriptor_domain",
            lambda *args, **kwargs: {**old, "equity": "70"},
        )
        with pytest.raises(RuntimeError, match="full frame requested"):
            await service.store.run_extension_write(append)
    finally:
        monkeypatch.undo()
        await service.shutdown(step_timeout=1)


async def test_pending_liquidation_keeps_separate_global_commit(
    tmp_path: Path, monkeypatch
):
    from tests.test_replay_v2_training_hedge_phase5 import (
        _create_bankrupt_hedge_run,
        _trigger_crash,
    )

    service = await _risk_service(tmp_path / "pending.db")
    try:
        run_id, session_id = await _create_bankrupt_hedge_run(
            service,
            root=tmp_path,
            prefix="pending",
            book_mode="OFF",
        )
        original = service.training._reconcile_liquidations

        async def stop_at_liquidation(**kwargs):
            if kwargs.get("pending"):
                raise RuntimeError("pending liquidation boundary")
            return await original(**kwargs)

        monkeypatch.setattr(
            service.training, "_reconcile_liquidations", stop_at_liquidation
        )
        with pytest.raises(RuntimeError, match="pending liquidation boundary"):
            await _trigger_crash(
                service, run_id=run_id, session_id=session_id, prefix="pending"
            )
        store = service.training.store
        assert await store.pending_liquidations(run_id)

        def forbidden(*args, **kwargs):
            raise AssertionError(
                "global checkpoint cannot precede liquidation reconciliation"
            )

        monkeypatch.setattr(store, "_record_global_events_in_transaction", forbidden)
        snapshot = await service.get_session_state(session_id)
        assert not await store.finalize_hedge_inputs_and_checkpoint(
            run_id,
            risk_virtual_time_ms=snapshot["cursor"]["virtual_time_ms"],
            events=(),
        )
    finally:
        monkeypatch.undo()
        await service.shutdown(step_timeout=1)
