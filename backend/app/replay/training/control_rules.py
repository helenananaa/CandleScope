"""Control rules shared by training coordinators."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from app.replay.period_summary import (
    ReplayPeriodSummary,
)

from . import service_validation as service_validation_ops
from .commands import ReplayV2Command
from .control import (
    control_rate,
)
from .errors import TrainingRunError
from .fast_forward import FastForwardDecision

ADVANCE_PROGRESS_RETENTION_SECONDS = 2.0


FINAL_STATE_PROJECTION_DELIVERY = "FINAL_STATE"


FINAL_STATE_EMPTY_ACCOUNT_CHUNK_EVENTS = 10_000


FINAL_STATE_EMPTY_ACCOUNT_INTERACTIVE_BATCH_UNITS = 512


STABLE_ORDER_RESPONSE_EVENTS = 512


ORDERED_PLAYBACK_INTERACTIVE_BATCH_UNITS = 1


ORDERED_PLAYBACK_FINAL_STATE_MIN_RATE = 60


ORDERED_PLAYBACK_FINAL_STATE_TARGET_HZ = 3


ORDERED_SOURCE_COHORT_PLAN_EVENTS = 32


@dataclass(frozen=True, slots=True)
class _OrderedSourceGoal:
    """One immutable-source boundary planned before an ordered mutation."""

    start_source_sequence: int
    start_revision: int
    target_source_sequence: int
    target_virtual_time_ms: int
    planned_count: int


_SetupAdmissionCacheKey = tuple[str, str, str, str, str]


def stop_on_event(command: ReplayV2Command) -> bool:
    value = command.payload.get("stop_on_event", False)
    if type(value) is not bool:
        raise TrainingRunError(
            "REPLAY_CONTROL_INVALID", "stop_on_event must be boolean", status_code=422
        )
    return value


def interaction_reason(
    before: Mapping[str, object], after: Mapping[str, object]
) -> str | None:
    old = before.get("components", {})
    new = after.get("components", {})
    if not isinstance(old, Mapping) or not isinstance(new, Mapping):
        return None
    if len(new.get("fills", ())) > len(old.get("fills", ())):
        return "ORDER_FILLED"

    def orders(state):
        return [
            (order.get("order_id"), order.get("status"), order.get("filled_quantity"))
            for order in state.get("orders", ())
            if isinstance(order, Mapping)
        ]

    if orders(old) != orders(new):
        return "ORDER_CHANGED"
    if len(new.get("warnings", ())) > len(old.get("warnings", ())):
        return "WARNING"
    return None


def snapshot_is_flat(snapshot: Mapping[str, object]) -> bool:
    components = snapshot.get("components")
    position = components.get("position") if isinstance(components, Mapping) else None
    if not isinstance(position, Mapping):
        return False
    if position.get("position_mode") == "HEDGE":
        return all(
            isinstance(position.get(side), Mapping)
            and position[side].get("quantity") in {"0", 0}
            for side in ("long", "short")
        )
    return position.get("quantity") in {"0", 0}


def actual_event_time_ms(
    binding: Mapping[str, object],
    virtual_time_ms: int,
) -> int:
    synthetic_origin = binding.get("synthetic_origin_ms")
    if synthetic_origin is None:
        return virtual_time_ms
    return (
        service_validation_ops._stored_counter(
            binding["actual_replay_start_ms"],
            field_name="actual_replay_start_ms",
        )
        + virtual_time_ms
        - service_validation_ops._stored_counter(
            synthetic_origin, field_name="synthetic_origin_ms"
        )
    )


def virtual_event_time_ms(
    binding: Mapping[str, object],
    actual_time_ms: int,
) -> int:
    synthetic_origin = binding.get("synthetic_origin_ms")
    if synthetic_origin is None:
        return actual_time_ms
    return (
        service_validation_ops._stored_counter(
            synthetic_origin,
            field_name="synthetic_origin_ms",
        )
        + actual_time_ms
        - service_validation_ops._stored_counter(
            binding["actual_replay_start_ms"],
            field_name="actual_replay_start_ms",
        )
    )


def training_terminal_time_ms(binding: Mapping[str, object]) -> int:
    actual_start_ms = service_validation_ops._stored_counter(
        binding.get("actual_replay_start_ms"),
        field_name="actual_replay_start_ms",
    )
    actual_end_ms = service_validation_ops._stored_counter(
        binding.get("actual_replay_end_ms"),
        field_name="actual_replay_end_ms",
    )
    adapter_config = service_validation_ops._stored_mapping(
        binding.get("adapter_config"), field_name="adapter_config"
    )
    public_start_ms = (
        service_validation_ops._stored_counter(
            binding.get("synthetic_origin_ms"),
            field_name="synthetic_origin_ms",
        )
        if adapter_config.get("blind_mode") is True
        else actual_start_ms
    )
    return public_start_ms + actual_end_ms - actual_start_ms


def multi_command_id(
    command_id: str,
    track_id: str,
    operation: str,
    revision: int,
) -> str:
    material = f"{command_id}:{track_id}:{operation}:{revision}".encode("utf-8")
    return f"v2multi-{hashlib.sha256(material).hexdigest()[:40]}"


def fast_forward_plan_payload(
    decision: FastForwardDecision,
    *,
    summary_lookup: Mapping[str, object],
) -> dict[str, object]:
    payload = decision.to_dict()
    candidate = summary_lookup.get("summary")
    payload["period_summary"] = {
        "status": str(summary_lookup.get("status", "UNAVAILABLE")),
        "reason_code": str(summary_lookup.get("reason_code", "SUMMARY_UNAVAILABLE")),
        **(
            {
                "set_id": str(summary_lookup["set_id"]),
                "summary_id": candidate.summary_id,
                "summary_hash": candidate.summary_hash,
                "build_proof_hash": str(summary_lookup["build_proof_hash"]),
                "base_source_sequence": candidate.base_source_sequence,
                "end_source_sequence": candidate.end_source_sequence,
                "skippable_source_events": candidate.event_count,
                "algorithm_version": candidate.algorithm_version,
            }
            if isinstance(candidate, ReplayPeriodSummary)
            else {}
        ),
    }
    return payload


def public_progress(job: Mapping[str, object]) -> dict[str, object]:
    initial = service_validation_ops._stored_counter(
        job.get("initial_virtual_time_ms"), field_name="initial_virtual_time_ms"
    )
    target = service_validation_ops._stored_counter(
        job.get("target_virtual_time_ms"), field_name="target_virtual_time_ms"
    )
    current = min(
        target,
        max(
            initial,
            service_validation_ops._stored_counter(
                job.get("current_virtual_time_ms"),
                field_name="current_virtual_time_ms",
            ),
        ),
    )
    span = target - initial
    ratio_ppm = 1_000_000 if span <= 0 else ((current - initial) * 1_000_000) // span
    return {
        "status": str(job["status"]),
        "current_virtual_time_ms": current,
        "target_virtual_time_ms": target,
        "ratio_ppm": ratio_ppm,
        "consumed": service_validation_ops._stored_counter(
            job.get("consumed"), field_name="consumed"
        ),
        "summary_skipped_events": service_validation_ops._stored_counter(
            job.get("summary_skipped_events", 0),
            field_name="summary_skipped_events",
        ),
        "tail_reducer_events": service_validation_ops._stored_counter(
            job.get("tail_reducer_events", 0),
            field_name="tail_reducer_events",
        ),
        "coalesced_projection_events": service_validation_ops._stored_counter(
            job.get("coalesced_projection_events", 0),
            field_name="coalesced_projection_events",
        ),
        "published_projection_events": service_validation_ops._stored_counter(
            job.get("published_projection_events", 0),
            field_name="published_projection_events",
        ),
        "batch_reducer_events": service_validation_ops._stored_counter(
            job.get("batch_reducer_events", 0),
            field_name="batch_reducer_events",
        ),
        "chunks": service_validation_ops._stored_counter(
            job.get("chunks"), field_name="chunks"
        ),
        "cancelable": bool(job["cancelable"]),
        "commit_boundary": "COMPLETE_ACTOR_COMMAND",
        "chunk_event_limit": service_validation_ops._stored_counter(
            job.get("chunk_event_limit", 32), field_name="chunk_event_limit"
        ),
        "queue_high_water": service_validation_ops._stored_counter(
            job.get("queue_high_water", 0), field_name="queue_high_water"
        ),
        "plan": dict(
            service_validation_ops._stored_mapping(
                job.get("plan"), field_name="fast-forward plan"
            )
        ),
    }


def advance_part_id(
    command: ReplayV2Command,
    *,
    source_sequence: int,
    virtual_time_ms: int,
    target_virtual_time_ms: int,
) -> str:
    material = (
        f"{command.run_id}:{command.command_id}:{source_sequence}:"
        f"{virtual_time_ms}:{target_virtual_time_ms}"
    ).encode("utf-8")
    return f"v2part-{hashlib.sha256(material).hexdigest()[:40]}"


def legacy_playback_rate(value: object) -> int:
    return control_rate(
        10_000 if value == "MAX" else value,
        field_name="rate",
    )
