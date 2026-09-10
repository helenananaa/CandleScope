import sqlite3

import pytest

from app.replay.training.schema import TRAINING_SCHEMA_VERSION
from app.replay.training.storage import TrainingRunStore
from tests.test_replay_hedge_wave_commit import seed
from tests.test_replay_v2_training_phase6 import _risk_service


@pytest.mark.anyio
@pytest.mark.parametrize("old_version", [19, 20])
async def test_schema_upgrade_preserves_existing_session(tmp_path, old_version):
    path = tmp_path / "old.db"
    service, run_id, session_id = await seed(path)
    before = await service.get_session_state(session_id)
    await service.shutdown(step_timeout=1)
    with sqlite3.connect(path) as connection:
        if old_version == 19:
            connection.execute("DROP TABLE replay_interval_curve")
        connection.execute("DROP TABLE replay_prepared_curve")
        connection.execute("DROP TABLE replay_hedge_mark_span")
        connection.execute(
            "UPDATE replay_training_schema_version SET version=?", (old_version,)
        )
    service = await _risk_service(path)
    try:
        after = await service.get_session_state(session_id)
        assert after["state_hash"] == before["state_hash"]
        assert after["cursor"] == before["cursor"]
        version = await service.store.run_extension_read(
            lambda c: c.execute(
                "SELECT version FROM replay_training_schema_version"
            ).fetchone()[0]
        )
        assert version == TRAINING_SCHEMA_VERSION
        assert (await service.training.equity(run_id))["samples"]
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
async def test_lazy_curve_merge_is_atomic_and_does_not_replace_newer_values(
    tmp_path, monkeypatch
):
    service, run_id, session_id = await seed(tmp_path / "curve.db")
    try:
        before = await service.get_session_state(session_id)

        def prepare(c):
            base = c.execute(
                "SELECT * FROM replay_equity_sample WHERE run_id=? LIMIT 1", (run_id,)
            ).fetchone()
            row = list(base)
            row[1:5] = ["EVENT", 10, 10, 10]
            row[6] = "1234"
            TrainingRunStore._write_equity_samples(c, [row])
            older = list(row)
            older[4] = 9
            older[6] = "999"
            missing = list(row)
            missing[2:5] = [9, 9, 9]
            missing[6] = "1200"
            TrainingRunStore._write_interval_curve(
                c,
                run_id=run_id,
                command_id="interval-test",
                end_sequence=10,
                rows=[missing, older],
            )
            return tuple(row)

        expected = await service.store.run_extension_write(prepare)

        def capture(c):
            return (
                [
                    tuple(row)
                    for row in c.execute(
                        "SELECT * FROM replay_equity_sample WHERE run_id=? ORDER BY resolution,bucket_id",
                        (run_id,),
                    )
                ],
                [
                    tuple(row)
                    for row in c.execute(
                        "SELECT * FROM replay_interval_curve WHERE run_id=?", (run_id,)
                    )
                ],
            )

        untouched = await service.store.run_extension_read(capture)
        original = TrainingRunStore._write_equity_samples

        def fail(c, rows, **kwargs):
            original(c, rows, **kwargs)
            raise RuntimeError("curve materialization fault")

        monkeypatch.setattr(
            TrainingRunStore, "_write_equity_samples", staticmethod(fail)
        )
        with pytest.raises(RuntimeError, match="curve materialization fault"):
            await service.training.equity(run_id, resolution="EVENT")
        assert await service.store.run_extension_read(capture) == untouched
        monkeypatch.setattr(
            TrainingRunStore, "_write_equity_samples", staticmethod(original)
        )
        result = await service.training.equity(run_id, resolution="EVENT")
        samples = {r["source_sequence"]: r for r in result["samples"]}
        assert samples[9]["equity"] == "1200"
        assert samples[10]["equity"] == expected[6]
        cached = await service.store.run_extension_read(capture)
        assert cached[1][0][-1] == 1
        assert (await service.training.equity(run_id, resolution="EVENT")) == result
        assert await service.store.run_extension_read(capture) == cached
        after = await service.get_session_state(session_id)
        assert after["state_hash"] == before["state_hash"]
        assert after["cursor"] == before["cursor"]
    finally:
        await service.shutdown(step_timeout=1)
