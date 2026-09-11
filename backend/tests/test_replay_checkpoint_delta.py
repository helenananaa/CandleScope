import pytest

from app.replay.checkpoints import CheckpointCodec
from app.replay.storage import checkpoint_delta as delta
from app.replay.training.models import ReplayV2CommandType
from tests.test_replay_hedge_wave_commit import seed
from tests.test_replay_v2_training_phase6 import _risk_service, _send


@pytest.mark.parametrize("base,current", [
    ({"a": [1, {"b": 2}], "old": 1}, {"a": [1, {"b": 3}, 4], "new": None}),
    ([1, 2, 3], [4]), (None, [1]), ({}, {}),
    ({"a": [True, 1]}, {"a": [1, True]}),
])
def test_delta_patch_round_trip(base, current):
    from app.replay.canonical import canonical_json_bytes
    assert canonical_json_bytes(delta.apply(base, delta.difference(base, current))) == canonical_json_bytes(current)


async def advance(service, run, session, count):
    for i in range(count):
        await _send(service, run_id=run, session_id=session, command_id=f"delta-advance-{i}",
                    command_type=ReplayV2CommandType.ADVANCE,
                    payload={"basis": "BASE_BAR", "count": 1})


@pytest.mark.anyio
async def test_real_commands_write_deltas_and_restart_recovers(tmp_path, monkeypatch):
    monkeypatch.setattr(delta, "MIN_BYTES", 0)
    monkeypatch.setattr(delta, "BASE_INTERVAL", 4)
    path = tmp_path / "run.db"
    service, run, session = await seed(path)
    service.store._max_recent_checkpoints = 4
    try:
        await advance(service, run, session, 10)
        expected = await service.get_session_state(session)
        def inspect(c):
            rows = c.execute("SELECT * FROM replay_checkpoint WHERE session_id=?", (session,)).fetchall()
            deltas = [r for r in rows if bytes(r["payload"]).startswith(delta.MAGIC)]
            assert deltas
            full_bytes = sum(len(delta.resolve(c, row)) for row in rows)
            stored_bytes = sum(len(row["payload"]) for row in rows)
            assert stored_bytes < full_bytes
            for row in rows:
                CheckpointCodec().decode(delta.resolve(c, row))
            assert c.execute("PRAGMA foreign_key_check").fetchall() == []
            assert c.execute("SELECT COUNT(*) FROM replay_checkpoint_base WHERE session_id=?", (session,)).fetchone()[0] <= 3
        await service.store.run_extension_read(inspect)
        # Review anchors must be independently decodable after checkpoint pruning.
        def anchors(c):
            from app.replay.training.anchor_codec import decode_anchor_payload
            rows = c.execute("SELECT * FROM replay_review_actor_anchor WHERE run_id=?", (run,)).fetchall()
            for row in rows:
                payload = decode_anchor_payload(bytes(row["payload"]), encoding=row["payload_encoding"],
                                                raw_bytes=row["payload_bytes"], stored_bytes=row["stored_bytes"],
                                                raw_sha256=row["payload_sha256"])
                CheckpointCodec().decode(payload)
                assert not payload.startswith(delta.MAGIC)
            return len(rows)
        assert await service.store.run_extension_read(anchors) > 0
    finally:
        await service.shutdown(step_timeout=1)
    recovered = await _risk_service(path)
    try:
        actual = await recovered.get_session_state(session)
        assert actual["cursor"] == expected["cursor"]
        assert actual["state_hash"] == expected["state_hash"]
    finally:
        await recovered.shutdown(step_timeout=1)


@pytest.mark.anyio
async def test_corrupt_base_skips_dependent_deltas_but_retains_full_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(delta, "MIN_BYTES", 0)
    service, run, session = await seed(tmp_path / "bad.db")
    try:
        await advance(service, run, session, 4)
        def corrupt(c):
            row = c.execute("SELECT MAX(base_id) FROM replay_checkpoint_delta_ref").fetchone()
            assert row[0] is not None
            ids = {r[0] for r in c.execute("SELECT checkpoint_id FROM replay_checkpoint_delta_ref WHERE base_id=?", (row[0],))}
            c.execute("UPDATE replay_checkpoint_base SET payload=? WHERE base_id=?", (b"bad", row[0]))
            return ids
        corrupt_ids = await service.store.run_extension_write(corrupt)
        valid = await service.store.load_valid_checkpoints(session)
        assert valid
        assert not corrupt_ids.intersection(c.checkpoint_id for c in valid)
        for checkpoint in valid:
            CheckpointCodec().decode(checkpoint.payload)
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
async def test_delta_transaction_rollback_and_session_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(delta, "MIN_BYTES", 0)
    service, run, session = await seed(tmp_path / "atomic.db")
    try:
        await advance(service, run, session, 3)
        def counts(c):
            return [c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in
                    ("replay_checkpoint", "replay_checkpoint_base", "replay_checkpoint_delta_ref")]
        before = await service.store.run_extension_read(counts)
        def snapshot(c):
            return [[tuple(row) for row in c.execute(f"SELECT * FROM {table}")] for table in
                    ("replay_checkpoint", "replay_checkpoint_base", "replay_checkpoint_delta_ref")]
        persisted = await service.store.run_extension_read(snapshot)
        def rollback(c):
            row = c.execute("SELECT * FROM replay_checkpoint ORDER BY checkpoint_id DESC LIMIT 1").fetchone()
            payload = delta.resolve(c, row)
            service.store._insert_checkpoint(c, session_id=session, state=dict(row), payload=payload,
                                             initial=False, mutation_id=row["mutation_id"], now_ms=0)
            raise RuntimeError("interrupt before commit")
        with pytest.raises(RuntimeError):
            await service.store.run_extension_write(rollback)
        assert await service.store.run_extension_read(counts) == before
        assert await service.store.run_extension_read(snapshot) == persisted
        await service.training.delete_run(run)
        assert await service.store.run_extension_read(counts) == [0, 0, 0]
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
async def test_v4_database_upgrades_without_rewriting_full_checkpoints(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    service, _, session = await seed(path)
    before = await service.get_session_state(session)
    await service.shutdown(step_timeout=1)
    with sqlite3.connect(path) as c:
        c.execute("DROP TABLE replay_checkpoint_delta_ref")
        c.execute("DROP TABLE replay_checkpoint_base")
        c.execute("UPDATE replay_schema_version SET version=4")
    upgraded = await _risk_service(path)
    try:
        after = await upgraded.get_session_state(session)
        assert after["state_hash"] == before["state_hash"]
        assert after["cursor"] == before["cursor"]
    finally:
        await upgraded.shutdown(step_timeout=1)
