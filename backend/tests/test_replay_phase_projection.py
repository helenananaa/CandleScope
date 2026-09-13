"""Phase batching must retain the old financial and review boundary results."""

import json
import sqlite3

import pytest

from app.replay.training.models import ReplayV2CommandType as C
from app.replay.training.phase_projection import load_track_rules
from tests.fixtures.replay.multi_interval_fakes import make_multi
from tests.fixtures.replay.shared_market_fakes import install_shared_market


@pytest.mark.anyio
@pytest.mark.parametrize("margin", ["CROSS", "ISOLATED"])
async def test_phase_boundaries_match_unbatched_summary(tmp_path, monkeypatch, margin):
    install_shared_market(monkeypatch, tmp_path / "market")
    outcomes = []
    for legacy in (True, False):
        service, run, session, send = await make_multi(
            tmp_path / str(legacy),
            tracks=8,
            horizon=40,
            margin_mode=margin,
            initial_equity="10000",
            marks=["100"] * 5 + ["80"] + ["110"] * 35,
        )
        boundaries = []
        try:
            store = service.training.store
            original_summary = store._sync_session_summary
            if legacy:

                def old_summary(
                    connection, sid, state, components, previous, now, **kw
                ):
                    phase = kw.pop("phase_summary", None)
                    bounds = kw.pop("revealed_price_bounds", None)
                    original_summary(
                        connection, sid, state, components, previous, now, **kw
                    )
                    if phase is not None:
                        track = phase.tracks[sid]
                        store._sync_trade_results_projection(
                            connection,
                            run_id=run,
                            track_id=track["track_id"],
                            component_state=components,
                            revealed_event_low=bounds[0],
                            revealed_event_high=bounds[1],
                            now_ms=now,
                        )
                        phase.last_revision = int(state["revision"])

                monkeypatch.setattr(store, "_sync_session_summary", old_summary)

            original_commit = service.store.commit_command_phases

            async def capture(phases):
                observed = []
                for rows, before, after in phases:

                    def finish(connection, after=after):
                        after(connection)
                        equity = tuple(
                            connection.execute(
                                "SELECT current_equity,summary_revision FROM replay_training_run WHERE run_id=?",
                                (run,),
                            ).fetchone()
                        )
                        tracks = [
                            tuple(row)
                            for row in connection.execute(
                                "SELECT position_json,account_json,source_sequence,virtual_time_ms "
                                "FROM replay_training_market_track WHERE run_id=? ORDER BY stable_ordinal",
                                (run,),
                            )
                        ]
                        trades = [
                            tuple(row)
                            for row in connection.execute(
                                "SELECT track_id,last_fill_ordinal,net_quantity,entry_price,highest_mark,lowest_mark "
                                "FROM replay_training_trade_projection WHERE run_id=? ORDER BY track_id",
                                (run,),
                            )
                        ]
                        review = [
                            tuple(row)
                            for row in connection.execute(
                                "SELECT category,event_type,virtual_time_ms,source_sequence "
                                "FROM replay_review_timeline_event WHERE run_id=? ORDER BY timeline_sequence",
                                (run,),
                            )
                        ]
                        domains = [
                            json.loads(row[0])["domain"]
                            for row in connection.execute(
                                "SELECT projection_json FROM replay_review_timeline_event WHERE run_id=? ORDER BY timeline_sequence",
                                (run,),
                            )
                        ]
                        anchors = [
                            tuple(row)
                            for row in connection.execute(
                                "SELECT track_id,source_sequence,event_sequence,virtual_time_ms,payload_sha256 "
                                "FROM replay_review_actor_anchor WHERE run_id=? ORDER BY track_id,source_sequence,event_sequence",
                                (run,),
                            )
                        ]
                        boundaries.append(
                            (equity, tracks, trades, review, domains, anchors)
                        )

                    observed.append((rows, before, finish))
                return await original_commit(observed)

            monkeypatch.setattr(service.store, "commit_command_phases", capture)
            state = await service.get_session_state(session)
            await send(
                "phase-boundary",
                C.ADVANCE_TO,
                dict(
                    virtual_time_ms=state["cursor"]["virtual_time_ms"] + 30 * 60000,
                    stop_on_event=False,
                ),
            )
            assert len(boundaries) == 2
            assert (await service.training.audit_account(run))["status"] == "PASS"
            outcomes.append(boundaries)
        finally:
            await service.shutdown(step_timeout=5)
    assert outcomes[0] == outcomes[1]


def test_batched_rules_keep_effective_time_and_latest_revision_distinct():
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE replay_training_market_track(
                run_id TEXT, track_id TEXT, subscription_tier TEXT, virtual_time_ms INTEGER);
            CREATE TABLE replay_training_instrument_rule(
                run_id TEXT, track_id TEXT, revision INTEGER, effective_virtual_time_ms INTEGER, rule_json TEXT);
            INSERT INTO replay_training_market_track VALUES
                ('run','a','FULL',100), ('run','b','FULL',NULL), ('run','c','NONE',100), ('other','a','FULL',100);
            INSERT INTO replay_training_instrument_rule VALUES
                ('run','a',1,0,'old'), ('run','a',2,100,'current'), ('run','a',3,200,'future'),
                ('run','b',1,0,'origin'), ('run','b',2,1,'later'), ('run','c',1,0,'dormant'),
                ('other','a',100,0,'foreign');
        """)
        effective = load_track_rules(connection, "run", effective=True)
        latest = load_track_rules(connection, "run", effective=False)
        assert {key: row["rule_json"] for key, row in effective.items()} == {
            "a": "current",
            "b": "origin",
        }
        assert {key: row["rule_json"] for key, row in latest.items()} == {
            "a": "future",
            "b": "later",
        }
