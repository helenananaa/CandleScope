import sqlite3
import json
from uuid import uuid4

import pytest

from app.replay.canonical import canonical_sha256
from app.replay.training.models import ReplayV2CommandType
from app.replay.training import review_lifecycle
from app.replay.training.review import ReviewRecorder
from app.replay.training.errors import TrainingRunError
from app.replay.training.persistence import hedge_review_fork
from tests.test_replay_hedge_dormant_account_inputs import _changing_inputs
from tests.test_replay_hedge_track_readmission import _dormant_run
from tests.test_replay_v2_training_phase5 import _acquire
from tests.test_replay_v2_training_phase6 import _risk_service, _send

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("mismatch", ["cash", "position", "view", "intervening_command"])
async def test_legacy_clock_never_borrows_another_account_or_decision(mismatch):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE replay_review_timeline_event(run_id TEXT, event_id TEXT, category TEXT, event_type TEXT, virtual_time_ms INTEGER, timeline_sequence INTEGER, viewer_revision INTEGER, projection_json TEXT)")
    projection = {"account": {"overlay_cash": "0"}, "domain": {"equity": "1000"},
                  "viewer_state": {"selected_track_id": "track-2"},
                  "tracks": [{"track_id": "track-2", "subscription_tier": "FULL", "cursor": {"virtual_time_ms": 20},
                              "position": {"quantity": "0", "mark_price": "10"}}]}
    connection.execute("INSERT INTO replay_review_timeline_event VALUES(?,?,?,?,?,?,?,?)", ("run", "old", "SYSTEM", "SHUTDOWN", 10, 1, 1, json.dumps(projection)))
    if mismatch == "cash":
        projection["account"]["overlay_cash"] = "1"
    if mismatch == "position":
        projection["tracks"][0]["position"]["quantity"] = "1"
    if mismatch == "view":
        projection["viewer_state"]["selected_track_id"] = "track-1"
    if mismatch == "intervening_command":
        connection.execute("INSERT INTO replay_review_timeline_event VALUES(?,?,?,?,?,?,?,?)", ("run", "decision", "COMMAND", "CHANGE_FEE_POLICY", 20, 2, 1, json.dumps(projection)))
    connection.execute("INSERT INTO replay_review_timeline_event VALUES(?,?,?,?,?,?,?,?)", ("run", "peer", "SYSTEM", "SHUTDOWN", 20, 3, 1, json.dumps(projection)))
    event = connection.execute("SELECT * FROM replay_review_timeline_event WHERE event_id='old'").fetchone()
    with pytest.raises(TrainingRunError) as error:
        review_lifecycle.legacy_shutdown_peer(connection, event)
    assert error.value.code == "REVIEW_LIFECYCLE_SNAPSHOT_UNAVAILABLE"
    assert review_lifecycle.event_clock(connection, event)["event_id"] == "old"
    connection.close()


@pytest.mark.parametrize("mode", ["current", "legacy", "legacy_without_cursors"])
@pytest.mark.parametrize("time_policy", ["NONE", "HIDE_ALL"])
async def test_shutdown_review_uses_frozen_global_clock_and_rules_after_restart(tmp_path, monkeypatch, mode, time_policy):
    _changing_inputs(monkeypatch)
    database = tmp_path / "clock.db"
    service = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    run, primary, secondary = await _dormant_run(service, tmp_path, initial_count=0, other_count=4,
                                                time_disclosure_policy=time_policy)
    before = await service.training.get_market_tracks(run)
    target = before["tracks"][1]["cursor"]["virtual_time_ms"]
    source = before["tracks"][1]["cursor"]["source_sequence"]
    projection = ReviewRecorder.projection

    def old_projection(self, *args, **kwargs):
        result = projection(self, *args, **kwargs)
        result["domain"].pop("portfolio", None)
        for track in result["tracks"]:
            track.pop("cursor", None)
        result["account_hash"] = canonical_sha256({"account": result["account"], "tracks": result["tracks"]})
        return result

    with monkeypatch.context() as old:
        if mode != "current":
            old.setattr(review_lifecycle, "lifecycle_clock", lambda kind, times, run, time, sequence: (time, sequence))
        if mode == "legacy_without_cursors":
            old.setattr(ReviewRecorder, "projection", old_projection)
            old.setattr(hedge_review_fork, "input_snapshot", lambda *_: None)
        await service.shutdown(step_timeout=1.0)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM replay_review_timeline_event WHERE run_id=? AND event_type='SHUTDOWN' ORDER BY timeline_sequence", (run,)).fetchall()
        assert len(rows) == 2
        if mode == "current":
            assert all(row["virtual_time_ms"] == target for row in rows)
            selected_id = rows[-1]["event_id"]
        else:
            selected_id = next(row["event_id"] for row in rows if row["virtual_time_ms"] < target)
        raw_before = [(row["event_id"], row["event_hash"], row["projection_json"]) for row in rows]
    restored = await _risk_service(database, symbols=("BTCUSDT", "ETHUSDT"))
    restored._session_id_factory = lambda: uuid4().hex
    restored.training._run_id_factory = lambda: uuid4().hex
    try:
        review = await restored.training.start_review(run, event_id=selected_id)
        assert review["projection"]["cursor"] == {"virtual_time_ms": target, "source_sequence": source}
        chosen = next(e for e in review["events"] if e["event_id"] == selected_id)
        assert chosen["source_sequence"] == source
        assert review["projection"]["rules"]["fee_policy"]["taker_fee_bps"] == "3"
        assert review["projection"]["domain"]["portfolio"]["available_equity"] == before["portfolio"]["available_equity"]
        forked = await restored.training.fork_run(run, event_id=selected_id)
        child = forked["run"]["run_id"]
        tracks = await restored.training.get_market_tracks(child)
        for key in ("equity", "cash_balance", "fees_paid", "funding_cashflow", "realized_pnl"):
            assert tracks["portfolio"][key] == before["portfolio"][key]
        assert tracks["portfolio"]["active_fee_policy"]["taker_fee_bps"] == "3"
        assert (await restored.training.audit_account(child))["status"] == "PASS"
        sid = forked["run"]["adapter_session_id"]
        await _acquire(restored, run_id=child, selected_session_id=sid, command_id="child-control")
        await _send(restored, run_id=child, session_id=sid, command_id="child-next",
                    command_type=ReplayV2CommandType.STEP_BASE, payload={"count": 1})
        assert (await restored.training.audit_account(child))["status"] == "PASS"
        with sqlite3.connect(database) as connection:
            rows_after = connection.execute("SELECT event_id,event_hash,projection_json FROM replay_review_timeline_event WHERE run_id=? AND event_type='SHUTDOWN' ORDER BY timeline_sequence", (run,)).fetchall()
            assert rows_after == raw_before
    finally:
        await restored.shutdown(step_timeout=1.0)
