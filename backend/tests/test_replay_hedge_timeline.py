from __future__ import annotations

import json
import random
from decimal import Decimal

import pytest

from app.replay.training.hedge_inputs import HedgeInputEvent, HedgeInputArchiveManager
from app.replay.training.hedge_timeline import IndexedHedgeSnapshot, InputLane


def event(
    seq, time, *, track="track-1", kind="MARK_INDEX", price="100", source="PUBLIC"
):
    return HedgeInputEvent(
        source_kind=source,
        source_id=f"source-{track}",
        event_sequence=seq,
        event_time_ms=time,
        event_phase=30 if kind == "MARK_INDEX" else 40,
        event_kind=kind,
        component_sequence=seq,
        previous_hash="sha256:" + "0" * 64,
        event_hash="sha256:" + "1" * 64,
        payload={"mark_price": price, "index_price": price},
        track_id=track,
    )


def test_varying_mark_envelope_stops_before_price_and_input_boundaries():
    public = (
        event(1, 0),
        event(2, 10, price="105"),
        event(3, 20, price="95"),
        event(4, 30, price="120"),
        event(5, 40, kind="FUNDING"),
    )
    snapshot = IndexedHedgeSnapshot(public, ())
    kwargs = dict(low=Decimal("90"), high=Decimal("110"))
    assert snapshot.mark_envelope_prefix(
        {"track-1": 1}, 0, "track-1", 100, **kwargs
    ) == (Decimal("100"), 29)
    assert snapshot.mark_envelope_prefix(
        {"track-1": 1}, 0, "track-1", 25, **kwargs
    ) == (Decimal("100"), 25)
    assert (
        snapshot.mark_envelope_prefix({"track-1": 4}, 0, "track-1", 100, **kwargs)
        is None
    )
    assert snapshot.mark_envelope_prefix(
        {"track-1": 1}, 0, "track-1", 100, low=Decimal("90"), high=Decimal("120")
    ) == (Decimal("100"), 39)
    simulation = (event(1, 15, kind="SIMULATION", source="SIMULATION"),)
    with_simulation = IndexedHedgeSnapshot(public, simulation)
    assert with_simulation.mark_envelope_prefix(
        {"track-1": 1}, 0, "track-1", 100, **kwargs
    ) == (Decimal("100"), 14)
    assert with_simulation.mark_envelope_prefix(
        {"track-1": 1}, 1, "track-1", 100, **kwargs
    ) == (Decimal("100"), 29)


@pytest.mark.anyio
async def test_indexed_queries_match_reference_with_rewinds_and_equal_timestamps():
    public = tuple(
        event(i, i // 3, track=track)
        for track in ("track-1", "track-2", None)
        for i in range(1, 151)
    )
    simulation = tuple(
        event(i, i // 2, track=None, kind="CAPITAL", source="SIMULATION")
        for i in range(1, 101)
    )
    indexed = IndexedHedgeSnapshot(public, simulation)
    service = object.__new__(HedgeInputArchiveManager)
    rng = random.Random(581)
    for _ in range(300):
        cursors = {"track-1": rng.randrange(151), "track-2": rng.randrange(151)}
        simulation_cursor = rng.randrange(101)

        async def read(_run):
            return cursors, simulation_cursor

        service._projection_cursors = read
        target = rng.randrange(60)
        for method, key in (
            (service.next_event_time, "target_actual_time_ms"),
            (service.events_at, "actual_time_ms"),
            (service.events_through, "target_actual_time_ms"),
        ):
            assert await method(
                run_id="run", runtime_snapshot=indexed, **{key: target}
            ) == await method(
                run_id="run", runtime_snapshot=tuple(indexed), **{key: target}
            )


def test_constant_mark_prefix_stops_before_price_and_account_boundaries():
    public = (
        event(1, 0),
        event(2, 10),
        event(3, 20),
        event(4, 30, price="99"),
        event(5, 40, price="99", kind="FUNDING"),
        event(6, 50, price="99"),
    )
    indexed = IndexedHedgeSnapshot(public, ())
    assert indexed.stable_mark_prefix({"track-1": 1}, 0, "track-1", 100) == (
        Decimal("100"),
        29,
    )
    assert indexed.stable_mark_prefix({"track-1": 4}, 0, "track-1", 100) == (
        Decimal("99"),
        39,
    )
    assert indexed.stable_mark_prefix({"track-1": 5}, 0, "track-1", 100) == (
        Decimal("99"),
        100,
    )
    assert indexed.stable_mark_prefix({}, 0, "track-1", 100) is None
    with_sim = IndexedHedgeSnapshot(
        public, (event(1, 15, source="SIMULATION", kind="CAPITAL", track=None),)
    )
    assert with_sim.stable_mark_prefix({"track-1": 1}, 0, "track-1", 100) == (
        Decimal("100"),
        14,
    )


def test_index_owns_price_payload_and_rejects_non_monotone_streams():
    original = event(1, 0)
    indexed = IndexedHedgeSnapshot((original, event(2, 10)), ())
    original.payload["mark_price"] = "50"
    assert indexed[0][0].payload["mark_price"] == "100"
    with pytest.raises(TypeError):
        indexed[0][0].payload["mark_price"] = "50"
    with pytest.raises(ValueError):
        InputLane.build("PUBLIC", "track-1", (event(2, 0), event(1, 10)))
    with pytest.raises(ValueError):
        InputLane.build("PUBLIC", "track-1", (event(1, 10), event(2, 0)))


@pytest.mark.anyio
async def test_risk_certificate_rejects_tampered_current_state(tmp_path):
    from tests.test_replay_hedge_wave_commit import seed

    service, run, session = await seed(tmp_path / "guard.db")
    try:
        store = service.training.store
        await store.finalize_hedge_inputs(run)
        row = await service.store.run_extension_read(
            lambda c: dict(
                c.execute(
                    "SELECT * FROM replay_hedge_track_public_projection WHERE run_id = ? AND track_id = 'track-1'",
                    (run,),
                ).fetchone()
            )
        )
        kwargs = dict(
            track_id="track-1",
            mark=Decimal(json.loads(row["state_json"])["mark_index"]["mark_price"]),
            current_virtual_time_ms=row["as_of_virtual_time_ms"],
            target_actual_time_ms=row["as_of_actual_time_ms"],
        )
        assert await store.held_mark_guard(run, **kwargs)
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_hedge_track_public_projection SET component_hash = 'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff' WHERE run_id = ?",
                (run,),
            )
        )
        assert not await store.held_mark_guard(run, **kwargs)
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_hedge_track_public_projection SET component_hash = ? WHERE run_id = ?",
                (row["component_hash"], run),
            )
        )
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_training_run SET current_equity = '1' WHERE run_id = ?",
                (run,),
            )
        )
        assert not await store.held_mark_guard(run, **kwargs)
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
async def test_cached_index_still_checks_binding_health(tmp_path):
    from tests.test_replay_hedge_wave_commit import seed
    from app.replay.training.errors import TrainingRunError

    service, run, _ = await seed(tmp_path / "cache.db")
    try:
        manager = service.training.hedge_inputs
        first = await manager.runtime_snapshot(run)
        assert await manager.runtime_snapshot(run) is first
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_hedge_track_public_binding SET status = 'PAUSED', degraded_reason = 'test' WHERE run_id = ?",
                (run,),
            )
        )
        with pytest.raises(TrainingRunError):
            await manager.runtime_snapshot(run)
    finally:
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_hedge_track_public_binding SET status = 'ACTIVE', degraded_reason = NULL WHERE run_id = ?",
                (run,),
            )
        )
        await service.store.run_extension_write(
            lambda c: c.execute(
                "UPDATE replay_hedge_input_binding SET status = 'ACTIVE',degraded_reason = NULL WHERE run_id = ?",
                (run,),
            )
        )
        await service.shutdown(step_timeout=1)
