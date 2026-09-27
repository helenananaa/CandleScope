"""Public time operations on a caller-owned transaction."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from ..disclosure import project_public_time as disclose_public_time
from ..errors import TrainingRunError

_PUBLIC_TIME_BATCH_LIMIT = 20_000


def result_label(
    *,
    integrity_mode: str,
    start_time_known: bool,
    strict_eligible: bool,
    revealed: bool,
) -> str:
    if integrity_mode == "SANDBOX":
        return "SANDBOX_REVEALED" if revealed else "SANDBOX"
    if integrity_mode == "PRACTICE":
        return "PRACTICE_REVEALED" if revealed else "PRACTICE"
    if revealed:
        return "CHALLENGE_REVEALED"
    if start_time_known:
        return "START_TIME_KNOWN"
    if strict_eligible:
        return "STRICT_CHALLENGE"
    return "CHALLENGE_VISIBLE_TIME"


def required_synthetic_origin(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "hidden training synthetic origin is missing",
            status_code=503,
        )
    return value


def redact_active_rule(
    value: object,
    *,
    hidden: bool,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "active training rule must be an object",
            status_code=503,
        )
    rule = dict(value)
    if not hidden:
        return rule
    for field_name in ("requested_start_ms", "random_seed"):
        if field_name in rule:
            rule[field_name] = None
    nested = rule.get("config")
    if isinstance(nested, Mapping):
        public_config = dict(nested)
        public_config["requested_start_ms"] = None
        public_config["random_seed"] = None
        rule["config"] = public_config
    return rule


def project_public_time(
    *,
    actual_origin_ms: int,
    public_origin_ms: int,
    policy: str,
    revealed: bool,
    public_time_ms: int,
    sequence: int,
) -> dict[str, object]:
    effective_policy = "NONE" if revealed else policy
    actual_time_ms = actual_origin_ms + public_time_ms - public_origin_ms
    return dict(
        disclose_public_time(
            actual_time_ms=actual_time_ms,
            public_time_ms=(
                actual_time_ms if effective_policy == "NONE" else public_time_ms
            ),
            actual_origin_ms=actual_origin_ms,
            public_origin_ms=(
                actual_origin_ms if effective_policy == "NONE" else public_origin_ms
            ),
            policy=effective_policy,
            sequence=sequence,
        )
    )


def selection_public_bounds(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    policy: str,
    revealed: bool,
    actual_start_ms: int,
    actual_end_ms: int,
) -> tuple[dict[str, object], dict[str, object]]:
    dataset = connection.execute(
        """
        SELECT actual_replay_start_ms, actual_replay_end_ms,
               synthetic_origin_ms
        FROM replay_dataset_ref WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if dataset is None:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training dataset time binding is missing",
            status_code=503,
        )
    actual_origin = int(dataset["actual_replay_start_ms"])
    if (
        actual_origin != actual_start_ms
        or int(dataset["actual_replay_end_ms"]) != actual_end_ms
    ):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training start selection and dataset bounds disagree",
            status_code=503,
        )
    public_origin = (
        actual_origin
        if policy == "NONE"
        else required_synthetic_origin(dataset["synthetic_origin_ms"])
    )
    return (
        project_public_time(
            actual_origin_ms=actual_origin,
            public_origin_ms=public_origin,
            policy=policy,
            revealed=revealed,
            public_time_ms=public_origin,
            sequence=0,
        ),
        project_public_time(
            actual_origin_ms=actual_origin,
            public_origin_ms=public_origin,
            policy=policy,
            revealed=revealed,
            public_time_ms=public_origin + actual_end_ms - actual_origin,
            sequence=1,
        ),
    )


def public_time(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    policy: str,
    revealed: bool,
    public_time_ms: int,
    sequence: int,
) -> dict[str, object]:
    dataset = connection.execute(
        """
        SELECT actual_replay_start_ms, synthetic_origin_ms
        FROM replay_dataset_ref WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if dataset is None:
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training dataset time binding is missing",
            status_code=503,
        )
    actual_origin = int(dataset["actual_replay_start_ms"])
    public_origin = (
        actual_origin
        if policy == "NONE"
        else required_synthetic_origin(dataset["synthetic_origin_ms"])
    )
    return project_public_time(
        actual_origin_ms=actual_origin,
        public_origin_ms=public_origin,
        policy=policy,
        revealed=revealed,
        public_time_ms=public_time_ms,
        sequence=sequence,
    )
