"""Inputs shared only by one certified multi-market interval SQL phase."""

from dataclasses import dataclass
import sqlite3


def load_track_rules(connection: sqlite3.Connection, run_id: str, *, effective: bool):
    """Resolve exactly the old per-track rule choice in one statement."""
    predicate = (
        "AND candidate.effective_virtual_time_ms <= COALESCE(track.virtual_time_ms, 0)"
        if effective
        else ""
    )
    ordering = (
        "candidate.effective_virtual_time_ms DESC, candidate.revision DESC"
        if effective
        else "candidate.revision DESC"
    )
    rows = connection.execute(
        f"""
        SELECT rule.track_id, rule.revision, rule.rule_json
        FROM replay_training_market_track AS track
        JOIN replay_training_instrument_rule AS rule
          ON rule.run_id = track.run_id AND rule.track_id = track.track_id
        WHERE track.run_id = ? AND track.subscription_tier = 'FULL'
          AND rule.revision = (
            SELECT candidate.revision FROM replay_training_instrument_rule AS candidate
            WHERE candidate.run_id = track.run_id AND candidate.track_id = track.track_id
              {predicate}
            ORDER BY {ordering} LIMIT 1
          )
        """,
        (run_id,),
    ).fetchall()
    return {row["track_id"]: row for row in rows}


@dataclass
class PhaseSummary:
    tracks: dict[str, sqlite3.Row]
    account_history: sqlite3.Row | None
    last_revision: int | None = None

    @classmethod
    def load(cls, connection: sqlite3.Connection, run_id: str) -> "PhaseSummary":
        # These metadata rows remain unchanged while the certified phase stages
        # its actors. Reload for the next phase, inside the same transaction.
        tracks = connection.execute(
            """
            SELECT t.*, viewer.selected_track_id, r.time_disclosure_policy,
                   r.position_mode, COALESCE(integrity.revealed, 0) AS revealed
            FROM replay_training_market_track AS t
            JOIN replay_training_run AS r USING(run_id)
            JOIN replay_training_viewer_state AS viewer USING(run_id)
            LEFT JOIN replay_training_integrity AS integrity USING(run_id)
            WHERE t.run_id = ? AND t.adapter_session_id IS NOT NULL
            """,
            (run_id,),
        ).fetchall()
        history = connection.execute(
            "SELECT account_data_mode, status, degraded_reason "
            "FROM replay_training_account_history WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return cls({row["adapter_session_id"]: row for row in tracks}, history)
