"""Review records operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from app.replay.canonical import canonical_json

from ..errors import TrainingRunError
from ..review import (
    REVIEW_ARTIFACT_BYTES_LIMIT,
)


def review_budget(
    connection: sqlite3.Connection,
    run_id: str,
) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM replay_review_timeline_event
             WHERE run_id = ?) AS critical_events,
            (SELECT COUNT(*) FROM replay_review_viewport_sample
             WHERE run_id = ?) AS viewport_samples,
            COALESCE((SELECT SUM(
                          CASE WHEN stored_bytes > 0 THEN stored_bytes
                               ELSE length(payload) END
                      )
                      FROM replay_review_actor_anchor
                      WHERE run_id = ?), 0) AS anchor_bytes,
            COALESCE((SELECT SUM(length(CAST(projection_json AS BLOB)))
                      FROM replay_review_timeline_event
                      WHERE run_id = ?), 0)
                + COALESCE((SELECT SUM(document_bytes)
                            FROM replay_review_drawing_document
                            WHERE run_id = ?), 0)
                + COALESCE((SELECT SUM(length(CAST(text AS BLOB)))
                            FROM replay_review_marker
                            WHERE run_id = ?), 0) AS artifact_bytes
        """,
        (run_id, run_id, run_id, run_id, run_id, run_id),
    ).fetchone()
    return {
        "critical_events": int(row["critical_events"]),
        "critical_event_limit": 8_192,
        "viewport_samples": int(row["viewport_samples"]),
        "viewport_sample_limit": 2_048,
        "anchor_used_bytes": int(row["anchor_bytes"]),
        "anchor_limit_bytes": 512 * 1024 * 1024,
        "artifact_used_bytes": int(row["artifact_bytes"]),
        "artifact_limit_bytes": REVIEW_ARTIFACT_BYTES_LIMIT,
    }


def public_review_projection(
    projection: Mapping[str, object],
) -> dict[str, object]:
    public = json.loads(canonical_json(projection))
    if not isinstance(public, dict):
        raise TypeError("review projection is invalid")
    public.pop("_account_history_internal", None)
    public.pop("_book_history_internal", None)
    public.pop("_review_descriptor_internal", None)
    domain = public.get("domain")
    if isinstance(domain, dict):
        domain.pop("critical_ledger_count", None)

    blocked = {
        "archive_id",
        "as_of_actual_ms",
        "actual_time_ms",
        "actual_replay_start_ms",
        "actual_visible_history_start_ms",
    }

    def assert_public(value: object, field: str) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                assert_public(item, f"{field}[{index}]")
            return
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            if str(key).startswith("_") or key in blocked:
                raise TrainingRunError(
                    "REVIEW_DISCLOSURE_VIOLATION",
                    "review projection crosses the public disclosure boundary",
                    status_code=503,
                    details={"field": f"{field}.{key}"},
                )
            assert_public(item, f"{field}.{key}")

    assert_public(public, "projection")
    return public


def review_event_detail(
    connection: sqlite3.Connection,
    event: sqlite3.Row,
) -> dict[str, object] | None:
    command_id = event["command_id"]
    if command_id is None:
        return None
    if str(event["category"]) == "MARKER":
        marker = connection.execute(
            """
            SELECT marker_id, text, content_hash
            FROM replay_review_marker
            WHERE run_id = ? AND command_id = ?
            """,
            (event["run_id"], command_id),
        ).fetchone()
        if marker is not None:
            return {
                "marker_id": str(marker["marker_id"]),
                "text": str(marker["text"]),
                "content_hash": str(marker["content_hash"]),
            }
    if str(event["category"]) == "ORDER":
        plan = connection.execute(
            """
            SELECT plan_id, plan_hash, order_id, side, order_type,
                   sizing_mode, risk_amount, risk_percent, entry_price,
                   invalidation_price, target_price, reward_risk_ratio,
                   quantity, reason
            FROM replay_training_trade_plan
            WHERE run_id = ? AND command_id = ?
            """,
            (event["run_id"], command_id),
        ).fetchone()
        if plan is not None:
            return {
                "kind": "TRADE_PLAN",
                "plan_id": str(plan["plan_id"]),
                "plan_hash": str(plan["plan_hash"]),
                "order_id": str(plan["order_id"]),
                "side": str(plan["side"]),
                "order_type": str(plan["order_type"]),
                "sizing_mode": str(plan["sizing_mode"]),
                "risk_amount": str(plan["risk_amount"]),
                "risk_percent": plan["risk_percent"],
                "entry_price": str(plan["entry_price"]),
                "invalidation_price": str(plan["invalidation_price"]),
                "target_price": str(plan["target_price"]),
                "reward_risk_ratio": str(plan["reward_risk_ratio"]),
                "quantity": str(plan["quantity"]),
                "reason": str(plan["reason"]),
            }
    return None
