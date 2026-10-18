"""Small review-time HEDGE input snapshots and stable fork track identities."""

from __future__ import annotations

import json

from app.replay.canonical import canonical_json

from .portfolio import derived_full_reasons


def input_snapshot(connection, run_id):
    binding = connection.execute("SELECT * FROM replay_hedge_input_binding WHERE run_id=?", (run_id,)).fetchone()
    if binding is None:
        return None
    return {
        "schema_version": "replay.review.hedge-inputs.v1",
        "binding": dict(binding),
        "projections": [dict(row) for row in connection.execute(
            "SELECT * FROM replay_hedge_input_projection WHERE run_id=? ORDER BY source_kind", (run_id,),
        )],
        "track_bindings": [dict(row) for row in connection.execute(
            "SELECT b.*,a.proof_hash FROM replay_hedge_track_public_binding b "
            "JOIN replay_hedge_public_archive a ON a.archive_id=b.public_archive_id "
            "WHERE b.run_id=? ORDER BY b.track_id", (run_id,),
        )],
        "track_projections": [dict(row) for row in connection.execute(
            "SELECT * FROM replay_hedge_track_public_projection WHERE run_id=? ORDER BY track_id", (run_id,),
        )],
    }


def selected_inputs(connection, run_id, event_id):
    event = connection.execute(
        "SELECT * FROM replay_review_timeline_event WHERE run_id=? AND event_id=?", (run_id, event_id),
    ).fetchone()
    projection = json.loads(event["projection_json"])
    return projection.get("_hedge_history_internal")


def reserve_review_tracks(connection, *, parent_run_id, child_run_id, event_id, now_ms):
    """Reserve every selected-event track before copying shared account rows."""
    projection = json.loads(connection.execute(
        "SELECT * FROM replay_review_timeline_event WHERE run_id=? AND event_id=?",
        (parent_run_id, event_id),
    ).fetchone()["projection_json"])
    for track in projection["tracks"]:
        track_id = track["track_id"]
        reasons = derived_full_reasons(
            stored_reasons=[], selected=projection["viewer_state"]["selected_track_id"] == track_id,
            position=track["position"], open_orders=track["open_orders"],
        )
        tier = "FULL" if reasons else track["subscription_tier"]
        if track_id == "track-1":
            # insert_track defaults to VIEWED, but the selected review can be
            # viewing a secondary market while the primary is only WARM/NONE.
            connection.execute(
                "UPDATE replay_training_market_track SET subscription_tier=?, forced_full_reasons_json=? WHERE run_id=? AND track_id=?",
                (tier, canonical_json(reasons), child_run_id, track_id),
            )
            continue
        parent = dict(connection.execute(
            "SELECT * FROM replay_training_market_track WHERE run_id=? AND track_id=?", (parent_run_id, track_id),
        ).fetchone())
        parent.update(run_id=child_run_id, adapter_session_id=None,
                      state="PREPARING" if track["state_hash"] is not None else track["state"],
                      subscription_tier=tier, position_json=canonical_json(track["position"]),
                      account_json=canonical_json(track["account"]), open_orders_json=canonical_json(track["open_orders"]),
                      public_price=track["position"].get("mark_price"), forced_full_reasons_json=canonical_json(reasons),
                      degraded_reason=None, created_at_ms=now_ms, updated_at_ms=now_ms)
        if track["state_hash"] is None:
            parent.update(dataset_epoch=None, virtual_time_ms=None, source_sequence=None, revision=None)
        if "cursor" in track:
            parent.update(track["cursor"])
        columns = tuple(parent)
        connection.execute(
            f"INSERT INTO replay_training_market_track ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            tuple(parent.values()),
        )


def repair_legacy_fork_viewed_reason(connection):
    """Remove only the stale primary VIEWED default from earlier review forks.

    Other forced reasons and financial/cursor rows are untouched. Repeated
    startup is idempotent; no actor history needs to be loaded or replayed.
    """
    rows = connection.execute(
        "SELECT t.run_id,t.forced_full_reasons_json FROM replay_training_market_track t "
        "JOIN replay_training_viewer_state v USING(run_id) "
        "JOIN replay_review_fork_lineage f ON f.child_run_id=t.run_id "
        "WHERE t.track_id='track-1' AND v.selected_track_id<>t.track_id "
        "AND t.forced_full_reasons_json LIKE '%VIEWED%'",
    ).fetchall()
    for row in rows:
        reasons = json.loads(row["forced_full_reasons_json"])
        if "VIEWED" not in reasons:
            continue
        reasons.remove("VIEWED")
        connection.execute(
            "UPDATE replay_training_market_track SET forced_full_reasons_json=? "
            "WHERE run_id=? AND track_id='track-1'",
            (canonical_json(reasons), row["run_id"]),
        )
