"""Repeated complete reads stay detached, causal and bound to stored revisions."""
import json
import math
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from app.backtest.native import digest, encoded
from app.backtest.native_replay import NativeReplay
from app.backtest.native_replay_storage import same_json
from app.backtest.native_replay_views import ResultViews


@pytest.fixture
def replay():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("CREATE TABLE native_inputs (id TEXT PRIMARY KEY, wire TEXT NOT NULL)")
    wire = {"identity": {}, "bars": [{"time": i*60, "close": i+0.5} for i in range(4)]}
    db.execute("INSERT INTO native_inputs VALUES (?,?)", ("run", encoded(wire)))
    origin = dict(state="COMPLETED", execution_mode="NATIVE", config={"language":"pine"},
                  input_hash=digest(wire), result={"account_authority":"native"})
    native = SimpleNamespace(db=db, lock=threading.RLock(), get=lambda _: origin)
    service = NativeReplay(native)
    record = service.create("run")
    yield service, record, wire
    service.shutdown()
    db.close()


def save(service, record, cursor, marker):
    body = {"account_authority":"native", "values":[True, 0, 0.0, -0.0, "观察"],
            "plots":[{"data":[{"value":marker}]}]}
    record.update(cursor=cursor, result=body)
    service._save(record)
    return body


def test_repeated_reads_return_complete_detached_json_and_exact_hash(replay):
    service, record, wire = replay
    body = save(service, record, 2, 7)
    first = service.get(record["replay_id"])
    expected = {**body, "bars":wire["bars"][:2]}
    expected["report_hash"] = digest(expected)
    assert same_json(first["result"], expected)
    first["result"]["plots"][0]["data"][0]["value"] = 999
    first["result"]["bars"][0]["close"] = 999
    again = service.get(record["replay_id"])
    assert same_json(again["result"], expected)
    assert math.copysign(1, again["result"]["values"][3]) == -1


def test_result_and_cursor_changes_never_reuse_an_older_or_future_view(replay):
    service, record, _ = replay
    save(service, record, 2, 7)
    older = service.get(record["replay_id"])
    save(service, record, 3, 9)
    newer = service.get(record["replay_id"])
    assert len(older["result"]["bars"]) == 2
    assert len(newer["result"]["bars"]) == 3
    assert newer["result"]["plots"][0]["data"][0]["value"] == 9
    save(service, record, 1, 3)
    restored = service.get(record["replay_id"])
    assert len(restored["result"]["bars"]) == 1
    assert restored["result"]["plots"][0]["data"][0]["value"] == 3


def test_warm_views_cannot_bypass_revision_or_cold_journal_integrity(replay):
    service, record, _ = replay
    save(service, record, 2, 7)
    service.get(record["replay_id"])
    service.results.cache.clear()
    service.native.db.execute("UPDATE native_replay_result_bases SET checksum='invalid' WHERE id=?", (record["replay_id"],))
    with pytest.raises(ValueError, match="checksum"):
        service.get(record["replay_id"])


def test_warm_views_reject_a_header_pointing_at_a_different_result_revision(replay):
    service, record, _ = replay
    save(service, record, 2, 7)
    service.get(record["replay_id"])
    raw, = service.native.db.execute("SELECT record FROM native_replays").fetchone()
    header = json.loads(raw)
    header["_resultRevision"] += 1
    service.native.db.execute("UPDATE native_replays SET record=?", (encoded(header),))
    with pytest.raises(ValueError, match="revision"):
        service.get(record["replay_id"])


def test_retention_is_byte_bounded_and_oversized_views_remain_complete():
    views = ResultViews(max_bytes=2048, capacity=2)
    for index in range(5):
        result = views.read((index,), {"text":"x"*900}, [])
        assert len(result["text"]) == 900
        assert views.bytes <= 2048 and len(views.entries) <= 2
    result = views.read(("large",), {"text":"x"*4096}, [])
    assert len(result["text"]) == 4096
    assert ("large",) not in views.entries
    views.discard()
    assert not views.entries and views.bytes == 0


def test_conditional_poll_avoids_materializing_an_unchanged_report(replay, monkeypatch):
    service, record, _ = replay
    save(service, record, 2, 7)
    full = service.get(record["replay_id"])
    with monkeypatch.context() as patch:
        patch.setattr(service.results, "load", lambda *a, **kw: pytest.fail("unchanged poll loaded report"))
        header = service.get(record["replay_id"], if_revision=full["revision"])
    assert header["result_unchanged"] is True and "result" not in header
    assert header["cursor"] == full["cursor"]
    # A newly committed cursor must send its full causal report again.
    record["revision"] += 1
    save(service, record, 3, 9)
    newer = service.get(record["replay_id"], if_revision=full["revision"])
    assert "result_unchanged" not in newer
    assert len(newer["result"]["bars"]) == 3


def test_conditional_poll_does_not_hide_mismatched_journal_metadata(replay):
    service, record, _ = replay
    save(service, record, 2, 7)
    service.native.db.execute("UPDATE native_replay_result_bases SET revision=revision+1")
    with pytest.raises(ValueError, match="revision"):
        service.get(record["replay_id"], if_revision=record["revision"])


def test_http_conditional_poll_and_default_export_keep_distinct_contracts(replay, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1 import native_backtests as api
    service, record, _ = replay
    save(service, record, 2, 7)
    monkeypatch.setattr(api, "_native", lambda _: SimpleNamespace(replay=service))
    app = FastAPI()
    app.include_router(api.router)
    path = "/native/replays/" + record["replay_id"]
    with TestClient(app) as client:
        full = client.get(path).json()
        header = client.get(path, params={"if_revision":full["revision"]}).json()
        assert header["result_unchanged"] is True and "result" not in header
        assert client.get(path+"/export").json() == full
        assert client.get(path, params={"if_revision":-1}).status_code == 422


def test_large_durable_snapshot_restores_the_exact_complete_view(replay):
    from app.backtest.native_checkpoint import SCHEMA
    service, record, _ = replay
    save(service, record, 2, 7)
    record["result"]["payload"] = "观察" * 200000
    service._save(record)
    original = service.get(record["replay_id"])
    saved = service.snapshot(record["replay_id"], original["revision"])
    checkpoint_id = saved["snapshots"][0]["snapshot_id"]
    stored, = service.native.db.execute("SELECT record FROM native_replay_snapshots WHERE id=?", (checkpoint_id,)).fetchone()
    assert json.loads(stored)["storage_schema"] == SCHEMA
    save(service, saved, 3, 9)
    restored = service.restore(record["replay_id"], saved["revision"], checkpoint_id)
    assert same_json(restored["result"], original["result"])


def test_snapshot_serializes_private_state_without_exposing_a_mutable_alias(replay):
    service, record, _ = replay
    save(service, record, 2, 7)
    record["execution_mode"] = "CANDLESCOPE"
    state = {"cursor":2, "ledger":{"balance":"100.50"}}
    service._save(record, external_state=state)
    detached = service._host_state(record["replay_id"])
    detached["ledger"]["balance"] = "0"
    assert service._host_state(record["replay_id"])["ledger"]["balance"] == "100.50"
    saved = service.snapshot(record["replay_id"], record["revision"])
    stored, = service.native.db.execute("SELECT record FROM native_replay_snapshots").fetchone()
    assert json.loads(stored)["external_state"] == state
    assert "external_state" not in saved
    # Subsequent journal activity cannot change already serialized checkpoint bytes.
    service._save(saved, external_state={"cursor":2, "ledger":{"balance":"90.25"}})
    after, = service.native.db.execute("SELECT record FROM native_replay_snapshots").fetchone()
    assert after == stored
