import asyncio
import sqlite3
import threading

import pytest

from app.replay.broker.shared_prepared import account_sample, restore_curve
from app.replay.canonical import canonical_json, canonical_sha256
from app.replay.shared_market_index import MarketRange
from app.replay.training.schema import TRAINING_SCHEMA_VERSION
from app.replay.training.storage import TrainingRunStore
from tests.fixtures.replay.service_fakes import START_MS
from tests.test_replay_hedge_wave_commit import seed
from tests.test_replay_shared_market_index import market
from tests.test_replay_v2_training_phase6 import _risk_service


@pytest.mark.anyio
@pytest.mark.parametrize("old_version", [19, 20, 21])
async def test_schema_upgrade_preserves_existing_session(tmp_path, old_version):
    path = tmp_path / "old.db"
    service, run_id, session_id = await seed(path)
    before = await service.get_session_state(session_id)
    await service.shutdown(step_timeout=1)
    with sqlite3.connect(path) as connection:
        if old_version == 19:
            connection.execute("DROP TABLE replay_interval_curve")
        if old_version < 21:
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
                    int(row["materialized"])
                    for row in c.execute(
                        "SELECT materialized FROM replay_interval_curve WHERE run_id=?",
                        (run_id,),
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
        assert cached[1][0] == 1
        assert (await service.training.equity(run_id, resolution="EVENT")) == result
        assert await service.store.run_extension_read(capture) == cached
        after = await service.get_session_state(session_id)
        assert after["state_hash"] == before["state_hash"]
        assert after["cursor"] == before["cursor"]
    finally:
        await service.shutdown(step_timeout=1)


def test_equity_query_does_not_call_event_materialize_helper():
    import inspect

    source = inspect.getsource(TrainingRunStore.equity)
    assert "_materialize_interval_curves" not in source
    assert "_expand_pending_interval_curves" in source
    assert "run_extension_read" in source
    assert "_persist_interval_curve_samples" in source


@pytest.mark.anyio
async def test_hourly_equity_query_does_not_expand_every_pending_bar(
    tmp_path, monkeypatch
):
    service, run_id, session_id = await seed(tmp_path / "hotpath.db")
    try:
        index_dir = tmp_path / "shared-index"
        index_dir.mkdir()
        count = 3_000
        obj, base = market(index_dir, count)
        view = MarketRange(base.parts, offset_ms=START_MS + 20_000 * 60_000)
        account = {"legs": [["1", "100"]], "cash": "10000"}
        curve_id = canonical_sha256({"run": run_id, "pending": "hourly"})
        basis = {
            "schema": "shared-curve.v1",
            "market": view.descriptor(),
            "reference": view.reference(),
            "start": 0,
            "seed": "sha256:" + "0" * 64,
            "account": account,
            "ledger_hash": "sha256:" + "1" * 64,
        }
        interval = {
            "schema": "indexed-curve.v1",
            "curve_id": curve_id,
            "start": 0,
            "end": count,
            "session_id": session_id,
            "revision_base": 0,
            "policy": "NONE",
            "revealed": True,
            "created_at_ms": 0,
        }

        def insert(connection):
            connection.execute(
                "INSERT INTO replay_prepared_curve VALUES (?, ?, ?)",
                (curve_id, run_id, canonical_json(basis)),
            )
            connection.execute(
                "INSERT INTO replay_interval_curve("
                "run_id, command_id, end_sequence, samples_json"
                ") VALUES (?, ?, ?, ?)",
                (run_id, "interval-hotpath", count, canonical_json(interval)),
            )

        await service.store.run_extension_write(insert)

        sample_calls = []
        original_sample = account_sample
        in_write = {"active": False}

        def tracking_sample(sample_basis, close):
            assert not in_write["active"], "curve expansion ran inside the write lock"
            sample_calls.append(close)
            return original_sample(sample_basis, close)

        monkeypatch.setattr(
            "app.replay.broker.shared_prepared.account_sample", tracking_sample
        )
        original_write = service.store.run_extension_write

        async def wrapped_write(operation, **kwargs):
            def guarded(connection):
                in_write["active"] = True
                try:
                    return operation(connection)
                finally:
                    in_write["active"] = False

            return await original_write(guarded, **kwargs)

        monkeypatch.setattr(service.store, "run_extension_write", wrapped_write)

        expand_calls = []
        original_expand = TrainingRunStore._expand_pending_interval_curves

        request_thread = threading.get_ident()

        def tracking_expand(cls, pending, origins, *, run_id, resolution, limit, **kwargs):
            assert not in_write["active"], "curve expansion ran inside the write lock"
            assert threading.get_ident() != request_thread
            expand_calls.append((resolution, limit, in_write["active"]))
            return original_expand(
                pending,
                origins,
                run_id=run_id,
                resolution=resolution,
                limit=limit,
                **kwargs,
            )

        monkeypatch.setattr(
            TrainingRunStore,
            "_expand_pending_interval_curves",
            classmethod(tracking_expand),
        )
        assert not hasattr(TrainingRunStore, "_materialize_interval_curves")

        limit = 12
        hourly = await service.training.equity(
            run_id, resolution="1H", limit=limit
        )
        assert hourly["resolution"] == "1H"
        assert expand_calls == [("1H", limit, False)]
        assert len(sample_calls) <= limit
        assert len(sample_calls) < count / 10
        restored = restore_curve(basis)
        for sample in hourly["samples"]:
            offset = int(sample["source_sequence"]) - restored["start"] - 1
            if 0 <= offset < count:
                expected = original_sample(account, view.row(offset)[5])
                assert sample["equity"] == expected[0]
                assert sample["cash_balance"] == expected[1]
                assert sample["unrealized_pnl"] == expected[2]

        sample_calls.clear()
        assert await service.training.equity(run_id, resolution="1H", limit=limit) == hourly
        assert sample_calls == []

        sample_calls.clear()
        auto = await service.training.equity(
            run_id, resolution="AUTO", limit=limit
        )
        assert auto["resolution"] == "1H"
        assert expand_calls[-1] == ("1H", limit, False)
        assert len(sample_calls) <= limit

        sample_calls.clear()
        events = await service.training.equity(
            run_id, resolution="EVENT", limit=20
        )
        assert events["resolution"] == "EVENT"
        assert expand_calls[-1] == ("EVENT", 20, False)
        assert len(sample_calls) <= 20
        assert len(events["samples"]) <= 20
        event_rows = [
            sample
            for sample in events["samples"]
            if int(sample["source_sequence"]) > count - 20
        ]
        assert event_rows
        for sample in event_rows:
            offset = int(sample["source_sequence"]) - restored["start"] - 1
            expected = original_sample(account, view.row(offset)[5])
            assert sample["equity"] == expected[0]
    finally:
        await service.shutdown(step_timeout=1)


def _pending_curve_parts():
    pending = []
    # Boundaries deliberately split 15-minute/hourly buckets.
    for part, (start, end) in enumerate(((0, 67), (67, 143), (143, 240))):
        basis = {
            "schema": "prepared-curve.v1", "start": start,
            "times": [i * 60_000 for i in range(start, end)],
            "samples": [[str(10000 + i), "10000", str(i)] for i in range(start, end)],
            "chains": ["sha256:" + "0" * 64] * (end - start + 1),
            "ledger_hash": "sha256:" + "1" * 64,
        }
        payload = {
            "schema": "indexed-curve.v1", "curve_id": str(part),
            "start": 0, "end": end - start, "session_id": "session",
            "revision_base": start, "policy": "NONE", "revealed": True,
            "created_at_ms": 0,
        }
        pending.append({"command_id": str(part), "samples_json": canonical_json(payload),
                        "curve_json": canonical_json(basis)})
    return pending


@pytest.mark.parametrize("resolution,bucket_ms", [("EVENT", 0), ("1M", 60000),
                                                  ("15M", 900000), ("1H", 3600000)])
@pytest.mark.parametrize("limit", [2, 12, 500])
def test_curve_global_window_matches_full_reference_and_reuses_cache(resolution, bucket_ms, limit):
    pending = _pending_curve_parts()
    origins = {"session": {"actual_replay_start_ms": 0, "synthetic_origin_ms": None}}
    reference = {}
    for i in range(240):
        bucket = i + 1 if bucket_ms == 0 else i * 60000 // bucket_ms
        reference[bucket] = (i + 1, str(10000 + i))
    expected = dict(sorted(reference.items(), reverse=True)[:limit])
    rows, _ = TrainingRunStore._expand_pending_interval_curves(
        pending, origins, run_id="run", resolution=resolution, limit=limit,
    )
    assert {r[2]: (r[3], r[6]) for r in rows} == expected
    assert len(rows) <= limit
    cached = {(r[1], r[2]): (r[3], r[4]) for r in rows}
    again, _ = TrainingRunStore._expand_pending_interval_curves(
        pending, origins, run_id="run", resolution=resolution, limit=limit, cached=cached,
    )
    assert again == []
    larger, _ = TrainingRunStore._expand_pending_interval_curves(
        pending, origins, run_id="run", resolution=resolution, limit=500, cached=cached,
    )
    assert {r[2]: (r[3], r[6]) for r in rows + larger} == reference


def test_curve_existing_newer_bucket_wins_without_recomputation():
    pending = _pending_curve_parts()
    origins = {"session": {"actual_replay_start_ms": 0, "synthetic_origin_ms": None}}
    # Most recent cached point is newer than the deferred interval in its bucket.
    cached = {("1H", 3): (250, 250)}
    rows, _ = TrainingRunStore._expand_pending_interval_curves(
        pending, origins, run_id="run", resolution="1H", limit=2, cached=cached,
    )
    assert len(rows) == 1
    assert rows[0][2] == 2
    assert rows[0][3] == 180


@pytest.mark.anyio
async def test_auto_counts_buckets_instead_of_source_events(tmp_path):
    service, run_id, session_id = await seed(tmp_path / "auto.db")
    try:
        pending = _pending_curve_parts()
        # Four hours contain 240 source events, 16 fifteen-minute buckets and
        # four hourly buckets. The finest resolution fitting 20 is 15M.
        def insert(c):
            c.execute("DELETE FROM replay_equity_sample WHERE run_id=?", (run_id,))
            for item in pending:
                import json
                payload = json.loads(item["samples_json"])
                payload["session_id"] = session_id
                basis = json.loads(item["curve_json"])
                basis["times"] = [START_MS + t for t in basis["times"]]
                c.execute("INSERT INTO replay_prepared_curve VALUES (?, ?, ?)",
                          (payload["curve_id"], run_id, canonical_json(basis)))
                c.execute("INSERT INTO replay_interval_curve(run_id,command_id,end_sequence,samples_json) VALUES (?,?,?,?)",
                          (run_id, item["command_id"], basis["start"] + payload["end"], canonical_json(payload)))
        await service.store.run_extension_write(insert)
        result = await service.training.equity(run_id, resolution="AUTO", limit=20)
        assert result["resolution"] == "15M"
        assert len(result["samples"]) == 16
        assert await service.training.equity(run_id, resolution="AUTO", limit=20) == result
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
async def test_curve_preparation_leaves_event_loop_and_writer_available(tmp_path, monkeypatch):
    service, run_id, _ = await seed(tmp_path / "concurrent.db")
    started, release = threading.Event(), threading.Event()
    original = TrainingRunStore._expand_pending_interval_curves

    def paused(cls, *args, **kwargs):
        started.set()
        assert release.wait(5), "curve preparation blocked the event loop"
        return original(*args, **kwargs)

    monkeypatch.setattr(TrainingRunStore, "_expand_pending_interval_curves", classmethod(paused))
    query = asyncio.create_task(service.training.equity(run_id, resolution="1H", limit=12))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        # This needs both a responsive loop and an available database writer.
        result = await asyncio.wait_for(
            service.store.run_extension_write(lambda c: c.execute("SELECT 42").fetchone()[0]),
            timeout=2,
        )
        assert result == 42
    finally:
        release.set()
        await query
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
async def test_bounded_hourly_read_does_not_load_every_pending_curve_body(tmp_path):
    service, run_id, session_id = await seed(tmp_path / "bounds.db")
    try:
        intervals, chunk = 12, 600
        count = intervals * chunk
        index_dir = tmp_path / "bounds-index"
        index_dir.mkdir()
        obj, base = market(index_dir, count)
        view = MarketRange(base.parts, offset_ms=START_MS)
        account = {"legs": [["1", "100"]], "cash": "10000"}
        bases = []
        for part in range(intervals):
            start = part * chunk
            end = start + chunk
            curve_id = f"curve-{part}"
            basis = {
                "schema": "shared-curve.v1",
                "market": view.descriptor(),
                "reference": view.reference(),
                "start": 0,
                "seed": "sha256:" + "0" * 64,
                "account": account,
                "ledger_hash": "sha256:" + "1" * 64,
            }
            payload = {
                "schema": "indexed-curve.v1",
                "curve_id": curve_id,
                "start": start,
                "end": end,
                "session_id": session_id,
                "revision_base": start,
                "policy": "NONE",
                "revealed": True,
                "created_at_ms": 0,
            }
            bases.append((curve_id, basis, payload, start, end))

        def insert(connection):
            connection.execute("DELETE FROM replay_equity_sample WHERE run_id=?", (run_id,))
            for curve_id, basis, payload, start, end in bases:
                connection.execute(
                    "INSERT INTO replay_prepared_curve VALUES (?, ?, ?)",
                    (curve_id, run_id, canonical_json(basis)),
                )
                connection.execute(
                    """
                    INSERT INTO replay_interval_curve(
                        run_id, command_id, end_sequence, samples_json,
                        start_sequence, start_time_ms, end_time_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        curve_id,
                        end,
                        canonical_json(payload),
                        start + 1,
                        int(view.row(start)[1]),
                        int(view.row(end - 1)[1]),
                    ),
                )

        await service.store.run_extension_write(insert)
        before = TrainingRunStore._curve_body_loads
        limit = 8
        hourly = await service.training.equity(run_id, resolution="1H", limit=limit)
        loaded = TrainingRunStore._curve_body_loads - before
        assert hourly["resolution"] == "1H"
        assert len(hourly["samples"]) <= limit
        assert loaded < intervals
        assert loaded >= 1
        restored = restore_curve(bases[-1][1])
        for sample in hourly["samples"]:
            offset = int(sample["source_sequence"]) - restored["start"] - 1
            expected = account_sample(account, view.row(offset)[5])
            assert sample["equity"] == expected[0]
            assert sample["cash_balance"] == expected[1]
            assert sample["unrealized_pnl"] == expected[2]
    finally:
        await service.shutdown(step_timeout=1)

@pytest.mark.anyio
async def test_auto_sparse_interval_counts_only_occupied_buckets(tmp_path):
    service, run_id, session_id = await seed(tmp_path / "sparse.db")
    try:
        times = [START_MS + i * 60000 for i in range(15)] + [START_MS + (360 + i) * 60000 for i in range(15)]
        basis = {"schema": "prepared-curve.v1", "start": 0, "times": times,
                 "samples": [["10000", "10000", "0"]] * 30,
                 "chains": ["sha256:" + "0" * 64] * 31, "ledger_hash": "sha256:" + "1" * 64}
        payload = {"schema": "indexed-curve.v1", "curve_id": "sparse", "start": 0, "end": 30,
                   "revision_base": 0, "session_id": session_id, "policy": "NONE", "revealed": True, "created_at_ms": 0}
        def insert(c):
            c.execute("DELETE FROM replay_equity_sample WHERE run_id=?", (run_id,))
            c.execute("INSERT INTO replay_prepared_curve VALUES (?,?,?)", ("sparse", run_id, canonical_json(basis)))
            c.execute("INSERT INTO replay_interval_curve(run_id, command_id, end_sequence, samples_json, start_sequence, start_time_ms, end_time_ms) VALUES (?,?,?,?,?,?,?)",
                      (run_id, "sparse", 30, canonical_json(payload), 1, times[0], times[-1]))
        await service.store.run_extension_write(insert)
        result = await service.training.equity(run_id, resolution="AUTO", limit=20)
        assert result["resolution"] == "15M"
        assert [row["source_sequence"] for row in result["samples"]] == [15, 30]
        assert await service.training.equity(run_id, resolution="15M", limit=20) == result
    finally:
        await service.shutdown(step_timeout=1)
