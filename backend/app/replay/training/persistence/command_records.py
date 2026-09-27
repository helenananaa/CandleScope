"""Command records operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from app.replay.canonical import canonical_json, canonical_sha256

from ..errors import TrainingRunError
from ..schema import (
    ADVANCE_INTENT_SCHEMA_VERSION,
)


def save_command_result_in_transaction(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    command_id: str,
    command_json: str,
    result_json: str,
    now_ms: int,
) -> None:
    existing = connection.execute(
        """
        SELECT command_json, result_json
        FROM replay_training_command
        WHERE run_id = ? AND command_id = ?
        """,
        (run_id, command_id),
    ).fetchone()
    if existing is not None:
        if (
            str(existing["command_json"]) != command_json
            or str(existing["result_json"]) != result_json
        ):
            raise TrainingRunError(
                "COMMAND_ID_REUSED",
                "command_id conflicts with a stored replay.v3 command",
                status_code=409,
            )
        return
    connection.execute(
        """
        INSERT INTO replay_training_command(
            run_id, command_id, command_json, result_json, created_at_ms
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            run_id,
            command_id,
            command_json,
            result_json,
            now_ms,
        ),
    )


def advance_intent_from_row(row: sqlite3.Row) -> dict[str, object]:
    def object_json(column: str, label: str) -> dict[str, object]:
        raw = str(row[column])
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                f"durable advance {label} JSON is invalid",
                status_code=503,
            ) from exc
        if not isinstance(value, dict) or canonical_json(value) != raw:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                f"durable advance {label} JSON is not canonical",
                status_code=503,
            )
        return value

    def valid_cursor(value: Mapping[str, object]) -> bool:
        for field_name in ("virtual_time_ms", "source_sequence"):
            field = value.get(field_name)
            if isinstance(field, bool) or not isinstance(field, int) or field < 0:
                return False
        revision = value.get("revision")
        return revision is None or (
            not isinstance(revision, bool)
            and isinstance(revision, int)
            and revision >= 0
        )

    command = object_json("command_json", "command")
    initial_cursor = object_json("initial_cursor_json", "initial cursor")
    latest_cursor = object_json("latest_cursor_json", "latest cursor")
    plan = object_json("plan_json", "plan")
    result = (
        None if row["result_json"] is None else object_json("result_json", "result")
    )
    command_hash = str(row["command_hash"])
    summary_id = row["summary_id"]
    summary_hash = row["summary_hash"]
    digest_valid = (
        len(command_hash) == 71
        and command_hash.startswith("sha256:")
        and all(value in "0123456789abcdef" for value in command_hash[7:])
    )
    summary_digest_valid = summary_hash is None or (
        isinstance(summary_hash, str)
        and len(summary_hash) == 71
        and summary_hash.startswith("sha256:")
        and all(value in "0123456789abcdef" for value in summary_hash[7:])
    )
    decoded: dict[str, object] = {
        "schema_version": str(row["schema_version"]),
        "run_id": str(row["run_id"]),
        "command_id": str(row["command_id"]),
        "command_hash": command_hash,
        "session_id": str(row["session_id"]),
        "initial_cursor": initial_cursor,
        "target_virtual_time_ms": int(row["target_virtual_time_ms"]),
        "plan": plan,
        "summary_id": summary_id,
        "summary_hash": summary_hash,
        "status": str(row["status"]),
        "latest_cursor": latest_cursor,
        "result": result,
    }
    if (
        decoded["schema_version"] != ADVANCE_INTENT_SCHEMA_VERSION
        or not digest_valid
        or canonical_sha256(command) != command_hash
        or command.get("run_id") != decoded["run_id"]
        or command.get("command_id") != decoded["command_id"]
        or not valid_cursor(initial_cursor)
        or not valid_cursor(latest_cursor)
        or int(latest_cursor["virtual_time_ms"])
        < int(initial_cursor["virtual_time_ms"])
        or int(latest_cursor["source_sequence"])
        < int(initial_cursor["source_sequence"])
        or (summary_id is None) != (summary_hash is None)
        or (
            summary_id is not None
            and (
                not isinstance(summary_id, str)
                or not summary_id
                or len(summary_id) > 200
            )
        )
        or not summary_digest_valid
        or (decoded["status"] in {"COMPLETED", "CANCELLED"} and result is None)
        or (decoded["status"] not in {"COMPLETED", "CANCELLED"} and result is not None)
    ):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "durable advance intent JSON is invalid",
            status_code=503,
        )
    return decoded
