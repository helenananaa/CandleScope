"""Service validation shared by training coordinators."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from app.replay.models import (
    validate_identifier,
)

from .commands import ReplayV2Command
from .errors import TrainingRunError
from .models import (
    validate_v2_counter,
)


def _stored_counter(value: object, *, field_name: str) -> int:
    try:
        return validate_v2_counter(value, field_name=field_name)
    except (TypeError, ValueError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            f"{field_name} is invalid",
            status_code=503,
        ) from exc


def _stored_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            f"{field_name} must be an object",
            status_code=503,
        )
    return cast(Mapping[str, object], value)


def cursor_time(snapshot: Mapping[str, object]) -> int:
    cursor = snapshot.get("cursor")
    if not isinstance(cursor, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "adapter cursor is invalid",
            status_code=503,
        )
    return int(cursor["virtual_time_ms"])


def track_session_id(track: Mapping[str, object]) -> str:
    session_id = track.get("adapter_session_id")
    if not isinstance(session_id, str):
        raise TrainingRunError(
            "MARKET_TRACK_NOT_PREPARED",
            "FULL market track has no adapter session",
            status_code=409,
        )
    return session_id


def adapter_snapshot(session: Mapping[str, object]) -> Mapping[str, object]:
    snapshot = session.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "adapter snapshot is invalid",
            status_code=503,
        )
    return snapshot


def assert_expected_cursor(
    command: ReplayV2Command,
    session: Mapping[str, object],
) -> Mapping[str, object]:
    snapshot = adapter_snapshot(session)
    cursor = snapshot.get("cursor")
    if not isinstance(cursor, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "adapter cursor is invalid",
            status_code=503,
        )
    actual = {
        "virtual_time_ms": cursor.get("virtual_time_ms"),
        "source_sequence": cursor.get("source_sequence"),
        "revision": snapshot.get("revision"),
    }
    if actual != command.expected_cursor.to_dict():
        raise TrainingRunError(
            "REVISION_CONFLICT",
            "command cursor does not match the authoritative run cursor",
            status_code=409,
            details={
                "expected": command.expected_cursor.to_dict(),
                "actual": actual,
            },
        )
    return snapshot


def exact_payload(
    payload: Mapping[str, object],
    expected: set[str],
) -> Mapping[str, object]:
    missing = expected - set(payload)
    unknown = set(payload) - expected
    if missing or unknown:
        raise TrainingRunError(
            "REPLAY_CONTROL_INVALID",
            "command payload fields do not match the control contract",
            status_code=422,
            details={"missing": sorted(missing), "unknown": sorted(unknown)},
        )
    return payload


def identifier(value: object, *, field_name: str) -> str:
    try:
        return validate_identifier(value, field_name=field_name)
    except (TypeError, ValueError) as exc:
        raise TrainingRunError(
            "TRAINING_RUN_INVALID",
            f"{field_name} is invalid",
            status_code=422,
        ) from exc


def digest(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
    ):
        raise TrainingRunError(
            "TRAINING_RUN_INVALID",
            f"{field_name} is invalid",
            status_code=422,
        )
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise TrainingRunError(
            "TRAINING_RUN_INVALID",
            f"{field_name} is invalid",
            status_code=422,
        ) from exc
    return value
