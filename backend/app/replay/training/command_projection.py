"""Command projection shared by training coordinators."""

from __future__ import annotations

from collections.abc import Mapping

from .commands import ReplayV2Command
from .errors import TrainingRunError

_PRIVATE_COMMAND_RESULT_FIELDS = frozenset(
    {
        "actual_event_time_ms",
        "actual_time_ms",
        "as_of_actual_time_ms",
        "bound_range_end_ms",
        "bound_range_start_ms",
        "global_checkpoint",
        "hedge_inputs",
        "recovery_checkpoint",
        "source_fingerprint",
    }
)


def result_payload(
    *,
    command: ReplayV2Command,
    session_id: str,
    snapshot: Mapping[str, object],
    viewer: Mapping[str, object],
    data: Mapping[str, object],
) -> dict[str, object]:
    return {
        "protocol": "replay.v3",
        "run_id": command.run_id,
        "session_id": session_id,
        "command_id": command.command_id,
        "revision": snapshot["revision"],
        "sequence": snapshot["sequence"],
        "state": snapshot["state"],
        "state_hash": snapshot["state_hash"],
        "cursor": snapshot["cursor"],
        "viewer_state": dict(viewer),
        "data": dict(data),
    }


def project_public_command_result(
    result: Mapping[str, object],
) -> dict[str, object]:
    """Project a durable internal command result onto the HTTP boundary."""

    data = result.get("data")
    if not isinstance(data, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "stored command result data is invalid",
            status_code=503,
        )
    return {
        **dict(result),
        "data": project_public_command_value(data),
    }


def project_public_command_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): project_public_command_value(item)
            for key, item in value.items()
            if str(key) not in _PRIVATE_COMMAND_RESULT_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [project_public_command_value(item) for item in value]
    return value
