"""Fork records operations on a caller-owned transaction."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_json, canonical_sha256

from ..account import (
    CONTRACT_ACCOUNT_MODEL,
    InstrumentRule,
    initial_ledger_hash,
    isolated_margin_key,
)
from ..errors import TrainingRunError
from ..models import (
    validate_v2_counter,
)
from ..schema import (
    RUN_RULES_SCHEMA_VERSION,
)
from . import account_marks as account_marks_ops
from . import ledger as ledger_ops
from . import liquidation as liquidation_ops
from . import run_records as run_records_ops


def copy_review_rule_policies(
    connection: sqlite3.Connection,
    *,
    child_run_id: str,
    parent_run_id: str,
    parent_event_id: str,
    virtual_time_ms: int,
    source_sequence: int,
    now_ms: int,
) -> None:
    event = connection.execute(
        """
        SELECT projection_json FROM replay_review_timeline_event
        WHERE run_id = ? AND event_id = ?
        """,
        (parent_run_id, parent_event_id),
    ).fetchone()
    if event is None:
        raise TypeError("review fork projection is missing")
    projection = json.loads(str(event["projection_json"]))
    if not isinstance(projection, Mapping):
        raise TypeError("review fork projection is invalid")
    rules = projection.get("rules")
    if not isinstance(rules, Mapping):
        raise TypeError("review fork rule projection is missing")
    leverage = rules.get("leverage_policy")
    funding = rules.get("funding_policy")
    if not isinstance(leverage, Mapping) or not isinstance(funding, Mapping):
        raise TypeError("review fork active policies are missing")
    leverage_revision = validate_v2_counter(
        leverage.get("revision"),
        field_name="review leverage revision",
    )
    funding_revision = validate_v2_counter(
        funding.get("revision"),
        field_name="review funding revision",
    )
    for row in connection.execute(
        """
        SELECT * FROM replay_training_leverage_policy
        WHERE run_id = ?
          AND revision <= ?
          AND (
              effective_virtual_time_ms < ?
              OR (
                  effective_virtual_time_ms = ?
                  AND source_sequence <= ?
              )
          )
        ORDER BY revision
        """,
        (
            parent_run_id,
            leverage_revision,
            virtual_time_ms,
            virtual_time_ms,
            source_sequence,
        ),
    ).fetchall():
        payload = {
            "schema_version": RUN_RULES_SCHEMA_VERSION,
            "kind": "LEVERAGE_CAP",
            "run_id": child_run_id,
            "revision": int(row["revision"]),
            "effective_virtual_time_ms": int(row["effective_virtual_time_ms"]),
            "source_sequence": int(row["source_sequence"]),
            "max_leverage": str(row["max_leverage"]),
            "fidelity": str(row["fidelity"]),
        }
        connection.execute(
            """
            INSERT INTO replay_training_leverage_policy(
                run_id, revision, effective_virtual_time_ms,
                source_sequence, max_leverage, policy_hash, fidelity,
                reason, command_id, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                child_run_id,
                row["revision"],
                row["effective_virtual_time_ms"],
                row["source_sequence"],
                row["max_leverage"],
                canonical_sha256(payload),
                row["fidelity"],
                f"fork of {parent_run_id}: {row['reason']}",
                now_ms,
            ),
        )
    for row in connection.execute(
        """
        SELECT * FROM replay_training_funding_policy
        WHERE run_id = ?
          AND revision <= ?
          AND (
              effective_virtual_time_ms < ?
              OR (
                  effective_virtual_time_ms = ?
                  AND source_sequence <= ?
              )
          )
        ORDER BY revision
        """,
        (
            parent_run_id,
            funding_revision,
            virtual_time_ms,
            virtual_time_ms,
            source_sequence,
        ),
    ).fetchall():
        payload = {
            "schema_version": RUN_RULES_SCHEMA_VERSION,
            "kind": "FUNDING_POLICY",
            "run_id": child_run_id,
            "revision": int(row["revision"]),
            "effective_virtual_time_ms": int(row["effective_virtual_time_ms"]),
            "source_sequence": int(row["source_sequence"]),
            "funding_mode": str(row["funding_mode"]),
            "fixed_funding_rate": row["fixed_funding_rate"],
            "funding_interval_ms": row["funding_interval_ms"],
            "fidelity": str(row["fidelity"]),
        }
        connection.execute(
            """
            INSERT INTO replay_training_funding_policy(
                run_id, revision, effective_virtual_time_ms,
                source_sequence, funding_mode, fixed_funding_rate,
                funding_interval_ms, policy_hash, fidelity, reason,
                command_id, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                child_run_id,
                row["revision"],
                row["effective_virtual_time_ms"],
                row["source_sequence"],
                row["funding_mode"],
                row["fixed_funding_rate"],
                row["funding_interval_ms"],
                canonical_sha256(payload),
                row["fidelity"],
                f"fork of {parent_run_id}: {row['reason']}",
                now_ms,
            ),
        )
    for table in (
        "replay_training_leverage_policy",
        "replay_training_funding_policy",
    ):
        if (
            connection.execute(
                f"SELECT 1 FROM {table} WHERE run_id = ? LIMIT 1",
                (child_run_id,),
            ).fetchone()
            is None
        ):
            raise TypeError(f"forked run has no {table} history")


def copy_review_book_inputs(
    connection: sqlite3.Connection,
    *,
    child_run_id: str,
    parent_run_id: str,
    parent_event_id: str,
    track_mapping: Mapping[str, str],
    now_ms: int,
) -> None:
    event = connection.execute(
        """
        SELECT projection_json FROM replay_review_timeline_event
        WHERE run_id = ? AND event_id = ?
        """,
        (parent_run_id, parent_event_id),
    ).fetchone()
    if event is None:
        raise TypeError("book-assisted fork review projection is missing")
    projection = json.loads(str(event["projection_json"]))
    if not isinstance(projection, Mapping):
        raise TypeError("book-assisted fork projection is invalid")
    internal = projection.get("_book_history_internal")
    if not isinstance(internal, Mapping):
        raise TrainingRunError(
            "HISTORICAL_BOOK_REVIEW_FORK_UNAVAILABLE",
            "review event has no pinned historical book snapshot",
            status_code=409,
            details={"fallback_applied": False},
        )
    inputs = internal.get("tracks")
    if not isinstance(inputs, list):
        raise TypeError("review historical book inputs are invalid")
    input_by_track = {
        str(item["track_id"]): item
        for item in inputs
        if isinstance(item, Mapping) and isinstance(item.get("track_id"), str)
    }
    for parent_track_id, child_track_id in track_mapping.items():
        item = input_by_track.get(parent_track_id)
        if item is None:
            raise TrainingRunError(
                "HISTORICAL_BOOK_REVIEW_FORK_UNAVAILABLE",
                "review event lacks one required historical book snapshot",
                status_code=409,
                details={
                    "track_id": parent_track_id,
                    "fallback_applied": False,
                },
            )
        connection.execute(
            """
            INSERT INTO replay_historical_book_ref(
                archive_id, run_id, track_id, binding_generation,
                bound_range_start_ms, bound_range_end_ms, active,
                created_at_ms, released_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL)
            """,
            (
                item["archive_id"],
                child_run_id,
                child_track_id,
                item["binding_generation"],
                item["bound_range_start_ms"],
                item["bound_range_end_ms"],
                now_ms,
            ),
        )
        if item.get("capability_state") is not None:
            connection.execute(
                """
                INSERT INTO replay_historical_book_projection(
                    run_id, track_id, archive_id, capability_state,
                    status, execution_fidelity, queue_exact,
                    as_of_actual_ms, as_of_virtual_ms, last_update_id,
                    bids_json, asks_json, book_hash, message, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    child_run_id,
                    child_track_id,
                    item["archive_id"],
                    item["capability_state"],
                    item["status"],
                    item["execution_fidelity"],
                    item["queue_exact"],
                    item["as_of_actual_ms"],
                    item["as_of_virtual_ms"],
                    item["last_update_id"],
                    item["bids_json"],
                    item["asks_json"],
                    item["book_hash"],
                    item["message"],
                    now_ms,
                ),
            )
        connection.execute(
            """
            UPDATE replay_historical_book_archive
            SET last_used_at_ms = ?, updated_at_ms = ?
            WHERE archive_id = ?
            """,
            (now_ms, now_ms, item["archive_id"]),
        )


def copy_exact_review_fork_inputs(
    connection: sqlite3.Connection,
    *,
    child_run_id: str,
    parent_run_id: str,
    parent_event_id: str,
    track_mapping: Mapping[str, str],
    now_ms: int,
) -> None:
    event = connection.execute(
        """
        SELECT projection_json FROM replay_review_timeline_event
        WHERE run_id = ? AND event_id = ?
        """,
        (parent_run_id, parent_event_id),
    ).fetchone()
    if event is None:
        raise TypeError("exact fork review projection is missing")
    raw_projection = json.loads(str(event["projection_json"]))
    if not isinstance(raw_projection, dict):
        raise TypeError("review projection must be an object")
    projection = raw_projection
    history = projection.get("_account_history_internal")
    if (
        not isinstance(history, Mapping)
        or history.get("account_data_mode") != "HISTORICAL_EXACT"
    ):
        raise TrainingRunError(
            "ACCOUNT_HISTORY_REVIEW_FORK_UNAVAILABLE",
            "review event has no exact account input snapshot",
            status_code=409,
            details={"fallback_applied": False},
        )
    inputs = history.get("tracks")
    if not isinstance(inputs, list):
        raise TypeError("exact review track inputs are invalid")
    input_by_track = {
        str(item["track_id"]): item
        for item in inputs
        if isinstance(item, Mapping) and isinstance(item.get("track_id"), str)
    }
    for parent_track_id, child_track_id in track_mapping.items():
        item = input_by_track.get(parent_track_id)
        if item is None:
            raise TrainingRunError(
                "ACCOUNT_HISTORY_REVIEW_FORK_UNAVAILABLE",
                "review event lacks an exact input for one track",
                status_code=409,
                details={
                    "track_id": parent_track_id,
                    "fallback_applied": False,
                },
            )
        connection.execute(
            """
            INSERT INTO replay_account_history_ref(
                archive_id, run_id, track_id, binding_generation, active,
                bound_range_start_ms, bound_range_end_ms, dataset_epoch,
                checksum_sha256, archive_generation, event_chain_tail,
                created_at_ms, released_at_ms
            ) VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                item["archive_id"],
                child_run_id,
                child_track_id,
                item["bound_range_start_ms"],
                item["bound_range_end_ms"],
                item["dataset_epoch"],
                item["checksum_sha256"],
                item["archive_generation"],
                item["event_chain_tail"],
                now_ms,
            ),
        )
        connection.execute(
            """
            INSERT INTO replay_account_history_projection(
                run_id, track_id, archive_id, archive_generation,
                last_event_sequence, last_rule_sequence,
                last_mark_sequence, last_funding_sequence,
                as_of_actual_time_ms, as_of_virtual_time_ms,
                current_rule_json, current_rule_hash, mark_price,
                index_price, input_chain_hash, status,
                degraded_reason, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?)
            """,
            (
                child_run_id,
                child_track_id,
                item["archive_id"],
                item["archive_generation"],
                item["last_event_sequence"],
                item["last_rule_sequence"],
                item["last_mark_sequence"],
                item["last_funding_sequence"],
                item["as_of_actual_time_ms"],
                item["as_of_virtual_time_ms"],
                item["current_rule_json"],
                item["current_rule_hash"],
                item["mark_price"],
                item["index_price"],
                item["input_chain_hash"],
                item["status"],
                item["degraded_reason"],
                now_ms,
            ),
        )
        connection.execute(
            """
            INSERT INTO replay_account_history_applied_event(
                run_id, track_id, archive_id, archive_event_sequence,
                event_time_ms, event_phase, event_kind,
                component_sequence, archive_event_hash,
                applied_payload_hash, created_at_ms
            )
            SELECT ?, ?, archive_id, archive_event_sequence,
                   event_time_ms, event_phase, event_kind,
                   component_sequence, archive_event_hash,
                   applied_payload_hash, ?
            FROM replay_account_history_applied_event
            WHERE run_id = ? AND track_id = ?
              AND archive_event_sequence <= ?
            ORDER BY archive_event_sequence
            """,
            (
                child_run_id,
                child_track_id,
                now_ms,
                parent_run_id,
                parent_track_id,
                item["last_event_sequence"],
            ),
        )
        for rule_row in connection.execute(
            """
            SELECT * FROM replay_training_instrument_rule
            WHERE run_id = ? AND track_id = ?
              AND effective_virtual_time_ms <= ?
            ORDER BY revision
            """,
            (
                parent_run_id,
                parent_track_id,
                item["as_of_virtual_time_ms"],
            ),
        ).fetchall():
            raw_rule = json.loads(str(rule_row["rule_json"]))
            if not isinstance(raw_rule, dict):
                raise TypeError("fork instrument rule must be an object")
            raw_rule["track_id"] = child_track_id
            rule = InstrumentRule.from_mapping(raw_rule)
            connection.execute(
                """
                INSERT OR IGNORE INTO replay_training_instrument_rule(
                    run_id, track_id, revision,
                    effective_virtual_time_ms, rule_json, rule_hash,
                    fidelity, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    child_run_id,
                    child_track_id,
                    rule_row["revision"],
                    rule_row["effective_virtual_time_ms"],
                    canonical_json(rule.to_dict()),
                    rule.rule_hash,
                    rule_row["fidelity"],
                    now_ms,
                ),
            )
        parent_track = connection.execute(
            """
            SELECT capabilities_json
            FROM replay_training_market_track
            WHERE run_id = ? AND track_id = ?
            """,
            (parent_run_id, parent_track_id),
        ).fetchone()
        if parent_track is not None:
            connection.execute(
                """
                UPDATE replay_training_market_track
                SET capabilities_json = ?, updated_at_ms = ?
                WHERE run_id = ? AND track_id = ?
                """,
                (
                    parent_track["capabilities_json"],
                    now_ms,
                    child_run_id,
                    child_track_id,
                ),
            )
    parent_account = connection.execute(
        """
        SELECT fidelity FROM replay_training_contract_account
        WHERE run_id = ?
        """,
        (parent_run_id,),
    ).fetchone()
    if parent_account is not None:
        connection.execute(
            """
            UPDATE replay_training_contract_account
            SET fidelity = ?, updated_at_ms = ? WHERE run_id = ?
            """,
            (parent_account["fidelity"], now_ms, child_run_id),
        )


def copy_hedge_input_binding(
    connection: sqlite3.Connection,
    *,
    parent_run_id: str,
    child_run_id: str,
    now_ms: int,
) -> None:
    binding = connection.execute(
        "SELECT * FROM replay_hedge_input_binding WHERE run_id = ?",
        (parent_run_id,),
    ).fetchone()
    if binding is None or binding["status"] != "ACTIVE":
        raise TypeError("review fork HEDGE input binding is unavailable")
    connection.execute(
        """
        INSERT INTO replay_hedge_input_binding(
            run_id, public_archive_id, public_generation,
            public_dataset_epoch, public_checksum_sha256,
            public_event_chain_tail, simulation_manifest_id,
            simulation_generation, simulation_dataset_epoch,
            simulation_checksum_sha256, simulation_contract_hash,
            bound_range_start_ms, bound_range_end_ms, status,
            degraded_reason, input_proof_hash, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', NULL,
                  ?, ?, ?)
        """,
        (
            child_run_id,
            binding["public_archive_id"],
            binding["public_generation"],
            binding["public_dataset_epoch"],
            binding["public_checksum_sha256"],
            binding["public_event_chain_tail"],
            binding["simulation_manifest_id"],
            binding["simulation_generation"],
            binding["simulation_dataset_epoch"],
            binding["simulation_checksum_sha256"],
            binding["simulation_contract_hash"],
            binding["bound_range_start_ms"],
            binding["bound_range_end_ms"],
            binding["input_proof_hash"],
            now_ms,
            now_ms,
        ),
    )
    connection.execute(
        """
        INSERT INTO replay_hedge_input_projection(
            run_id, source_kind, last_event_sequence,
            as_of_actual_time_ms, as_of_virtual_time_ms, state_json,
            input_chain_hash, component_hash, updated_at_ms
        )
        SELECT ?, source_kind, last_event_sequence,
               as_of_actual_time_ms, as_of_virtual_time_ms, state_json,
               input_chain_hash, component_hash, ?
        FROM replay_hedge_input_projection WHERE run_id = ?
        """,
        (child_run_id, now_ms, parent_run_id),
    )
    applied_rows = connection.execute(
        """
        SELECT * FROM replay_hedge_input_applied_event
        WHERE run_id = ? ORDER BY source_kind, event_sequence
        """,
        (parent_run_id,),
    ).fetchall()
    source_ids = {
        "PUBLIC": str(binding["public_archive_id"]),
        "SIMULATION": str(binding["simulation_manifest_id"]),
    }
    for row in applied_rows:
        payload = json.loads(str(row["payload_json"]))
        applied_hash = canonical_sha256(
            {
                "run_id": child_run_id,
                "virtual_time_ms": int(row["applied_virtual_time_ms"]),
                "source_kind": str(row["source_kind"]),
                "source_id": source_ids[str(row["source_kind"])],
                "event_sequence": int(row["event_sequence"]),
                "event_hash": str(row["source_event_hash"]),
                "payload": payload,
            }
        )
        connection.execute(
            """
            INSERT INTO replay_hedge_input_applied_event(
                run_id, source_kind, event_sequence, event_time_ms,
                event_phase, event_kind, component_sequence,
                applied_virtual_time_ms, source_event_hash, payload_json,
                applied_payload_hash, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                child_run_id,
                row["source_kind"],
                row["event_sequence"],
                row["event_time_ms"],
                row["event_phase"],
                row["event_kind"],
                row["component_sequence"],
                row["applied_virtual_time_ms"],
                row["source_event_hash"],
                row["payload_json"],
                applied_hash,
                now_ms,
            ),
        )
    track_mapping = {
        str(row["parent_track_id"]): str(row["child_track_id"])
        for row in connection.execute(
            """
            SELECT parent.track_id AS parent_track_id,
                   child.track_id AS child_track_id
            FROM replay_training_market_track AS parent
            JOIN replay_training_market_track AS child
              ON child.run_id = ?
             AND child.stable_ordinal = parent.stable_ordinal
             AND child.exchange = parent.exchange
             AND child.market_type = parent.market_type
             AND child.symbol = parent.symbol
            WHERE parent.run_id = ?
            """,
            (child_run_id, parent_run_id),
        ).fetchall()
    }
    for parent_track_id, child_track_id in track_mapping.items():
        track_binding = connection.execute(
            """
            SELECT track_binding.*, archive.proof_hash
            FROM replay_hedge_track_public_binding AS track_binding
            JOIN replay_hedge_public_archive AS archive
              ON archive.archive_id = track_binding.public_archive_id
            WHERE track_binding.run_id = ? AND track_binding.track_id = ?
            """,
            (parent_run_id, parent_track_id),
        ).fetchone()
        if track_binding is None:
            continue
        track_proof = canonical_sha256(
            {
                "schema_version": "replay.hedge-track-public-binding.v1",
                "run_id": child_run_id,
                "track_id": child_track_id,
                "public": {
                    "archive_id": str(track_binding["public_archive_id"]),
                    "generation": int(track_binding["public_generation"]),
                    "dataset_epoch": str(track_binding["public_dataset_epoch"]),
                    "checksum_sha256": str(track_binding["public_checksum_sha256"]),
                    "event_chain_tail": str(track_binding["public_event_chain_tail"]),
                    "proof_hash": str(track_binding["proof_hash"]),
                },
                "bound_range_start_ms": int(track_binding["bound_range_start_ms"]),
                "bound_range_end_ms": int(track_binding["bound_range_end_ms"]),
            }
        )
        connection.execute(
            """
            INSERT INTO replay_hedge_track_public_binding(
                run_id, track_id, public_archive_id, public_generation,
                public_dataset_epoch, public_checksum_sha256,
                public_event_chain_tail, bound_range_start_ms,
                bound_range_end_ms, status, degraded_reason,
                input_proof_hash, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', NULL, ?, ?, ?)
            """,
            (
                child_run_id,
                child_track_id,
                track_binding["public_archive_id"],
                track_binding["public_generation"],
                track_binding["public_dataset_epoch"],
                track_binding["public_checksum_sha256"],
                track_binding["public_event_chain_tail"],
                track_binding["bound_range_start_ms"],
                track_binding["bound_range_end_ms"],
                track_proof,
                now_ms,
                now_ms,
            ),
        )
        projection = connection.execute(
            """
            SELECT * FROM replay_hedge_track_public_projection
            WHERE run_id = ? AND track_id = ?
            """,
            (parent_run_id, parent_track_id),
        ).fetchone()
        if projection is None:
            raise TypeError("forked HEDGE track projection is missing")
        state = json.loads(str(projection["state_json"]))
        projection_payload = {
            "schema_version": "replay.hedge-track-public-projection.v1",
            "run_id": child_run_id,
            "track_id": child_track_id,
            "last_event_sequence": int(projection["last_event_sequence"]),
            "as_of_actual_time_ms": int(projection["as_of_actual_time_ms"]),
            "as_of_virtual_time_ms": int(projection["as_of_virtual_time_ms"]),
            "state": state,
            "input_chain_hash": str(projection["input_chain_hash"]),
        }
        connection.execute(
            """
            INSERT INTO replay_hedge_track_public_projection(
                run_id, track_id, last_event_sequence,
                as_of_actual_time_ms, as_of_virtual_time_ms, state_json,
                input_chain_hash, component_hash, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                child_run_id,
                child_track_id,
                projection["last_event_sequence"],
                projection["as_of_actual_time_ms"],
                projection["as_of_virtual_time_ms"],
                projection["state_json"],
                projection["input_chain_hash"],
                canonical_sha256(projection_payload),
                now_ms,
            ),
        )
        track_events = connection.execute(
            """
            SELECT * FROM replay_hedge_track_public_applied_event
            WHERE run_id = ? AND track_id = ? ORDER BY event_sequence
            """,
            (parent_run_id, parent_track_id),
        ).fetchall()
        connection.execute(
            "INSERT INTO replay_hedge_mark_span SELECT ?, ?, first_sequence,last_sequence,first_previous_hash,last_event_hash,archive_id "
            "FROM replay_hedge_mark_span WHERE run_id=? AND track_id=? AND last_sequence<=?",
            (
                child_run_id,
                child_track_id,
                parent_run_id,
                parent_track_id,
                projection["last_event_sequence"],
            ),
        )
        for event_row in track_events:
            payload = json.loads(str(event_row["payload_json"]))
            event_hash = canonical_sha256(
                {
                    "run_id": child_run_id,
                    "track_id": child_track_id,
                    "virtual_time_ms": int(event_row["applied_virtual_time_ms"]),
                    "source_kind": "PUBLIC",
                    "source_id": str(track_binding["public_archive_id"]),
                    "event_sequence": int(event_row["event_sequence"]),
                    "event_hash": str(event_row["source_event_hash"]),
                    "payload": payload,
                }
            )
            connection.execute(
                """
                INSERT INTO replay_hedge_track_public_applied_event(
                    run_id, track_id, event_sequence, event_time_ms,
                    event_phase, event_kind, component_sequence,
                    applied_virtual_time_ms, source_event_hash,
                    payload_json, applied_payload_hash, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    child_run_id,
                    child_track_id,
                    event_row["event_sequence"],
                    event_row["event_time_ms"],
                    event_row["event_phase"],
                    event_row["event_kind"],
                    event_row["component_sequence"],
                    event_row["applied_virtual_time_ms"],
                    event_row["source_event_hash"],
                    event_row["payload_json"],
                    event_hash,
                    now_ms,
                ),
            )
        connection.execute(
            """
            UPDATE replay_hedge_public_archive
            SET last_used_at_ms = ?, updated_at_ms = ?
            WHERE archive_id = ?
            """,
            (now_ms, now_ms, track_binding["public_archive_id"]),
        )
    connection.execute(
        """
        UPDATE replay_hedge_public_archive
        SET last_used_at_ms = ?, updated_at_ms = ? WHERE archive_id = ?
        """,
        (now_ms, now_ms, binding["public_archive_id"]),
    )
    connection.execute(
        """
        UPDATE replay_hedge_simulation_manifest
        SET last_used_at_ms = ?, updated_at_ms = ? WHERE manifest_id = ?
        """,
        (now_ms, now_ms, binding["simulation_manifest_id"]),
    )


def copy_hedge_relational_state(
    connection: sqlite3.Connection,
    *,
    parent_run_id: str,
    child_run_id: str,
    parent_track_id: str,
    child_track_id: str,
    virtual_time_ms: int,
    source_sequence: int,
    now_ms: int,
) -> bool:
    """Copy one fork-visible relational HEDGE snapshot without flattening legs."""

    def insert_rows(
        table: str,
        rows: Sequence[sqlite3.Row],
        *,
        track_columns: Sequence[str] = (),
    ) -> None:
        if not rows:
            return
        columns = tuple(rows[0].keys())
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})"
        )
        for row in rows:
            values = dict(row)
            values["run_id"] = child_run_id
            for column in track_columns:
                if values.get(column) == parent_track_id:
                    values[column] = child_track_id
            for column in ("created_at_ms", "updated_at_ms"):
                if column in values:
                    values[column] = now_ms
            connection.execute(sql, tuple(values[column] for column in columns))

    # Position and margin rows are mutable projections.  Rehydrating them from
    # the selected actor checkpoint (below, via _detect_contract_liquidations)
    # is the only cursor-correct fork behavior; copying the parent's latest
    # rows would leak state from after the selected review event.
    case_rows = tuple(
        connection.execute(
            """
            SELECT DISTINCT case_row.*
            FROM replay_training_liquidation_case AS case_row
            JOIN replay_training_liquidation_leg AS leg
              ON leg.run_id = case_row.run_id AND leg.case_id = case_row.case_id
            WHERE case_row.run_id = ? AND leg.track_id = ? AND (
                case_row.trigger_virtual_time_ms < ? OR (
                    case_row.trigger_virtual_time_ms = ?
                    AND case_row.trigger_source_sequence <= ?
                )
            )
            ORDER BY case_row.case_sequence
            """,
            (
                parent_run_id,
                parent_track_id,
                virtual_time_ms,
                virtual_time_ms,
                source_sequence,
            ),
        ).fetchall()
    )
    case_ids = tuple(str(row["case_id"]) for row in case_rows)
    risk_ids = {
        str(value)
        for row in case_rows
        for value in (row["trigger_snapshot_id"], row["final_snapshot_id"])
        if value is not None
    }
    if case_ids:
        case_placeholders = ", ".join("?" for _ in case_ids)
        for row in connection.execute(
            f"""
            SELECT before_snapshot_id, after_snapshot_id
            FROM replay_training_liquidation_step
            WHERE run_id = ? AND case_id IN ({case_placeholders})
            """,
            (parent_run_id, *case_ids),
        ).fetchall():
            risk_ids.add(str(row["before_snapshot_id"]))
            if row["after_snapshot_id"] is not None:
                risk_ids.add(str(row["after_snapshot_id"]))
    if risk_ids:
        placeholders = ", ".join("?" for _ in risk_ids)
        risk_rows = tuple(
            connection.execute(
                f"""
                SELECT * FROM replay_training_risk_snapshot
                WHERE run_id = ? AND snapshot_id IN ({placeholders})
                ORDER BY snapshot_sequence
                """,
                (parent_run_id, *sorted(risk_ids)),
            ).fetchall()
        )
        insert_rows("replay_training_risk_snapshot", risk_rows)
    insert_rows("replay_training_liquidation_case", case_rows)
    if not case_ids:
        return False
    placeholders = ", ".join("?" for _ in case_ids)
    case_params = (parent_run_id, *case_ids)
    leg_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_liquidation_leg
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY case_id, leg_sequence
            """,
            case_params,
        ).fetchall()
    )
    insert_rows(
        "replay_training_liquidation_leg",
        leg_rows,
        track_columns=("track_id",),
    )
    book_snapshot_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_liquidation_book_snapshot
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY case_id, track_id
            """,
            case_params,
        ).fetchall()
    )
    insert_rows(
        "replay_training_liquidation_book_snapshot",
        book_snapshot_rows,
        track_columns=("track_id",),
    )
    price_proof_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_liquidation_leg_price_proof
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY case_id, liquidation_leg_id
            """,
            case_params,
        ).fetchall()
    )
    insert_rows("replay_training_liquidation_leg_price_proof", price_proof_rows)
    step_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_liquidation_step
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY case_id, step_sequence
            """,
            case_params,
        ).fetchall()
    )
    insert_rows("replay_training_liquidation_step", step_rows)
    book_execution_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_liquidation_book_execution
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY case_id, step_sequence
            """,
            case_params,
        ).fetchall()
    )
    insert_rows(
        "replay_training_liquidation_book_execution",
        book_execution_rows,
        track_columns=("track_id",),
    )
    order_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_liquidation_order
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY case_id, step_sequence, order_sequence
            """,
            case_params,
        ).fetchall()
    )
    insert_rows("replay_training_liquidation_order", order_rows)
    fill_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_liquidation_fill
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY case_id, order_id, fill_sequence
            """,
            case_params,
        ).fetchall()
    )
    insert_rows("replay_training_liquidation_fill", fill_rows)
    fund_rows = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_insurance_fund
            WHERE run_id = ? ORDER BY asset
            """,
            (parent_run_id,),
        ).fetchall()
    )
    insert_rows("replay_training_insurance_fund", fund_rows)
    insurance_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_insurance_posting
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY asset, posting_sequence
            """,
            case_params,
        ).fetchall()
    )
    insert_rows("replay_training_insurance_posting", insurance_rows)
    adl_snapshot_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_adl_snapshot
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY case_id, cohort_sequence
            """,
            case_params,
        ).fetchall()
    )
    insert_rows("replay_training_adl_snapshot", adl_snapshot_rows)
    adl_snapshot_ids = tuple(str(row["snapshot_id"]) for row in adl_snapshot_rows)
    if adl_snapshot_ids:
        adl_placeholders = ", ".join("?" for _ in adl_snapshot_ids)
        candidate_rows = tuple(
            connection.execute(
                f"""
                SELECT * FROM replay_training_adl_candidate
                WHERE run_id = ? AND snapshot_id IN ({adl_placeholders})
                ORDER BY snapshot_id, rank
                """,
                (parent_run_id, *adl_snapshot_ids),
            ).fetchall()
        )
        insert_rows("replay_training_adl_candidate", candidate_rows)
    adl_event_rows = tuple(
        connection.execute(
            f"""
            SELECT * FROM replay_training_adl_event
            WHERE run_id = ? AND case_id IN ({placeholders})
            ORDER BY case_id, step_sequence
            """,
            case_params,
        ).fetchall()
    )
    insert_rows("replay_training_adl_event", adl_event_rows)
    adl_event_ids = tuple(str(row["adl_event_id"]) for row in adl_event_rows)
    if adl_event_ids:
        event_placeholders = ", ".join("?" for _ in adl_event_ids)
        selection_rows = tuple(
            connection.execute(
                f"""
                SELECT * FROM replay_training_adl_selection
                WHERE run_id = ? AND adl_event_id IN ({event_placeholders})
                ORDER BY adl_event_id, selection_sequence
                """,
                (parent_run_id, *adl_event_ids),
            ).fetchall()
        )
        insert_rows("replay_training_adl_selection", selection_rows)
        counterparty_rows = tuple(
            connection.execute(
                f"""
                SELECT * FROM replay_training_adl_counterparty_ledger
                WHERE run_id = ? AND adl_event_id IN ({event_placeholders})
                ORDER BY adl_event_id, ledger_sequence
                """,
                (parent_run_id, *adl_event_ids),
            ).fetchall()
        )
        insert_rows("replay_training_adl_counterparty_ledger", counterparty_rows)
    return any(
        str(row["state"])
        not in {
            "COMPLETED",
            "BANKRUPT",
            "FAILED_CLOSED",
            "RECOVERED_AFTER_CANCEL",
        }
        for row in case_rows
    )


def insert_fork_contract_account(
    connection: sqlite3.Connection,
    *,
    child_run_id: str,
    parent_run_id: str,
    parent_event_id: str,
    source_kind: str,
    settlement_asset: str,
    virtual_time_ms: int,
    source_sequence: int,
    component_state: Mapping[str, object],
    broker_config: Mapping[str, object],
    now_ms: int,
) -> None:
    """Rebuild the additive contract account at the selected fork cursor."""

    parent = connection.execute(
        """
        SELECT account.*, run.initial_equity, run.settlement_asset,
               run.position_mode, run.book_mode
        FROM replay_training_contract_account AS account
        JOIN replay_training_run AS run USING(run_id)
        WHERE run_id = ?
        """,
        (parent_run_id,),
    ).fetchone()
    if parent is None:
        raise TypeError("parent contract account is missing")
    event = connection.execute(
        """
        SELECT projection_json FROM replay_review_timeline_event
        WHERE run_id = ? AND event_id = ?
        """,
        (parent_run_id, parent_event_id),
    ).fetchone()
    if event is None:
        raise TypeError("review fork projection is missing")
    review_projection = json.loads(str(event["projection_json"]))
    if not isinstance(review_projection, Mapping):
        raise TypeError("review fork projection is invalid")
    review_domain = review_projection.get("domain")
    review_account = review_projection.get("account")
    review_rules = review_projection.get("rules")
    if (
        not isinstance(review_domain, Mapping)
        or not isinstance(review_account, Mapping)
        or not isinstance(review_rules, Mapping)
    ):
        raise TypeError("review fork account projection is incomplete")
    ledger_count = validate_v2_counter(
        review_domain.get("ledger_count"),
        field_name="review ledger count",
    )
    fee_policy = review_rules.get("fee_policy")
    leverage_policy = review_rules.get("leverage_policy")
    funding_policy = review_rules.get("funding_policy")
    instrument_policies = review_rules.get("instrument_rules")
    if (
        not isinstance(fee_policy, Mapping)
        or not isinstance(leverage_policy, Mapping)
        or not isinstance(funding_policy, Mapping)
        or not isinstance(instrument_policies, list)
    ):
        raise TypeError("review fork rule projection is incomplete")
    fee_revision = validate_v2_counter(
        fee_policy.get("revision"),
        field_name="review fee revision",
    )
    instrument_revision_by_track = {
        str(item["track_id"]): validate_v2_counter(
            item.get("revision"),
            field_name="review instrument revision",
        )
        for item in instrument_policies
        if isinstance(item, Mapping) and isinstance(item.get("track_id"), str)
    }
    if str(parent["account_model"]) != CONTRACT_ACCOUNT_MODEL:
        raise TrainingRunError(
            "CONTRACT_ACCOUNT_UNAVAILABLE",
            "review fork requires a current v2 contract account",
            status_code=409,
        )

    parent_ledger = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_contract_ledger
            WHERE run_id = ?
            ORDER BY ledger_sequence
            LIMIT ?
            """,
            (parent_run_id, ledger_count),
        ).fetchall()
    )
    if len(parent_ledger) != ledger_count:
        raise TrainingRunError(
            "REVIEW_FORK_MISMATCH",
            "review ledger prefix is no longer reconstructable",
            status_code=409,
            details={
                "expected_ledger_count": ledger_count,
                "actual_ledger_count": len(parent_ledger),
            },
        )
    creation_metadata: dict[str, object] = {}
    for entry in parent_ledger:
        if str(entry["kind"]) != "INITIAL_CAPITAL":
            continue
        raw = json.loads(str(entry["metadata_json"]))
        if isinstance(raw, dict):
            creation_metadata = raw
        break
    margin_mode = str(
        review_account.get(
            "margin_mode",
            creation_metadata.get("margin_mode", parent["margin_mode"]),
        )
    )
    funding_mode = str(funding_policy["funding_mode"])
    fixed_rate = funding_policy.get("fixed_funding_rate")
    funding_interval = funding_policy.get("funding_interval_ms")
    allocations: dict[str, str] = {}
    for entry in parent_ledger:
        metadata = json.loads(str(entry["metadata_json"]))
        if not isinstance(metadata, dict):
            raise TypeError("parent contract ledger metadata is invalid")
        kind = str(entry["kind"])
        track_id = entry["track_id"]
        if kind == "POLICY_REVISION":
            policy = metadata.get("policy")
            if metadata.get("command_type") == "change_funding_policy" and isinstance(
                policy, Mapping
            ):
                funding_mode = str(policy.get("funding_mode", funding_mode))
                fixed_rate = policy.get("fixed_funding_rate")
                funding_interval = policy.get("funding_interval_ms")
        elif kind in {"MARGIN_ALLOCATION", "MARGIN_RELEASE"} and isinstance(
            track_id,
            str,
        ):
            position_side = metadata.get("position_side")
            allocation_key = isolated_margin_key(
                "track-1",
                (
                    str(position_side)
                    if parent["position_mode"] == "HEDGE"
                    and position_side in {"LONG", "SHORT"}
                    else None
                ),
            )
            target = metadata.get("new_allocation")
            if target is None or Decimal(str(target)) == 0:
                allocations.pop(allocation_key, None)
            else:
                allocations[allocation_key] = decimal_to_string(
                    Decimal(str(target)),
                    field_name="fork isolated allocation",
                )

    interval_value = None if funding_interval is None else int(funding_interval)
    next_funding = (
        None
        if interval_value is None
        else ((virtual_time_ms // interval_value) + 1) * interval_value
    )
    root_hash = initial_ledger_hash(
        run_id=child_run_id,
        initial_equity=str(parent["initial_equity"]),
        asset=settlement_asset,
    )
    connection.execute(
        """
        INSERT INTO replay_training_contract_account(
            run_id, account_model, margin_mode, funding_mode,
            fixed_funding_rate, funding_interval_ms, next_funding_time_ms,
            overlay_cash, isolated_margin_json, status, fidelity,
            ledger_tail_hash, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '0', ?, 'ACTIVE', ?, ?, ?, ?)
        """,
        (
            child_run_id,
            CONTRACT_ACCOUNT_MODEL,
            margin_mode,
            funding_mode,
            fixed_rate,
            interval_value,
            next_funding,
            canonical_json(allocations),
            "AVAILABLE_APPROX_NO_HISTORICAL_MARK_INDEX",
            root_hash,
            now_ms,
            now_ms,
        ),
    )

    rule_rows = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_instrument_rule
            WHERE run_id = ? AND track_id = 'track-1'
              AND revision <= ?
              AND effective_virtual_time_ms <= ?
            ORDER BY revision
            """,
            (
                parent_run_id,
                instrument_revision_by_track.get("track-1", 1),
                virtual_time_ms,
            ),
        ).fetchall()
    )
    if not rule_rows:
        earliest_rule = connection.execute(
            """
            SELECT * FROM replay_training_instrument_rule
            WHERE run_id = ? AND track_id = 'track-1'
            ORDER BY revision LIMIT 1
            """,
            (parent_run_id,),
        ).fetchone()
        if earliest_rule is not None:
            rule_rows = (earliest_rule,)
    for row in rule_rows:
        raw_rule = json.loads(str(row["rule_json"]))
        if not isinstance(raw_rule, dict):
            raise TypeError("parent instrument rule is invalid")
        raw_rule["track_id"] = "track-1"
        rule = InstrumentRule.from_mapping(raw_rule)
        connection.execute(
            """
            INSERT INTO replay_training_instrument_rule(
                run_id, track_id, revision, effective_virtual_time_ms,
                rule_json, rule_hash, fidelity, created_at_ms
            ) VALUES (?, 'track-1', ?, ?, ?, ?, ?, ?)
            """,
            (
                child_run_id,
                int(row["revision"]),
                min(int(row["effective_virtual_time_ms"]), virtual_time_ms),
                canonical_json(rule.to_dict()),
                rule.rule_hash,
                rule.rule_fidelity,
                now_ms,
            ),
        )
    if not rule_rows:
        run_records_ops.insert_contract_track_rule(
            connection,
            run_id=child_run_id,
            track_id="track-1",
            source_kind=source_kind,
            broker_config=broker_config,
            effective_virtual_time_ms=virtual_time_ms,
            now_ms=now_ms,
        )

    policy_rows = tuple(
        connection.execute(
            """
            SELECT * FROM replay_training_fee_policy
            WHERE run_id = ? AND revision <= ?
              AND effective_virtual_time_ms <= ?
            ORDER BY revision
            """,
            (parent_run_id, fee_revision, virtual_time_ms),
        ).fetchall()
    )
    if not policy_rows:
        earliest_policy = connection.execute(
            """
            SELECT * FROM replay_training_fee_policy
            WHERE run_id = ? ORDER BY revision LIMIT 1
            """,
            (parent_run_id,),
        ).fetchone()
        if earliest_policy is None:
            raise TypeError("parent fee policy is missing")
        policy_rows = (earliest_policy,)
    for row in policy_rows:
        effective_virtual_time_ms = min(
            int(row["effective_virtual_time_ms"]),
            virtual_time_ms,
        )
        policy = {
            "schema_version": "replay.training.fee-policy.v1",
            "run_id": child_run_id,
            "revision": int(row["revision"]),
            "effective_virtual_time_ms": effective_virtual_time_ms,
            "maker_fee_bps": str(row["maker_fee_bps"]),
            "taker_fee_bps": str(row["taker_fee_bps"]),
            "fidelity": str(row["fidelity"]),
        }
        connection.execute(
            """
            INSERT INTO replay_training_fee_policy(
                run_id, revision, effective_virtual_time_ms, maker_fee_bps,
                taker_fee_bps, policy_hash, fidelity, reason, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                child_run_id,
                int(row["revision"]),
                effective_virtual_time_ms,
                row["maker_fee_bps"],
                row["taker_fee_bps"],
                canonical_sha256(policy),
                row["fidelity"],
                f"fork of {parent_run_id}: {row['reason']}",
                now_ms,
            ),
        )
        extension_row = connection.execute(
            """
            SELECT * FROM replay_training_fee_policy_extension
            WHERE run_id = ? AND revision = ?
            """,
            (parent_run_id, int(row["revision"])),
        ).fetchone()
        if extension_row is not None:
            complete_policy = {
                "schema_version": "replay.training.fee-policy.v1",
                "run_id": child_run_id,
                "revision": int(row["revision"]),
                "effective_virtual_time_ms": effective_virtual_time_ms,
                "maker_fee_bps": str(row["maker_fee_bps"]),
                "taker_fee_bps": str(row["taker_fee_bps"]),
                "liquidation_fee_bps": str(extension_row["liquidation_fee_bps"]),
                "policy_version": str(extension_row["policy_version"]),
                "account_tier": str(extension_row["account_tier"]),
                "fidelity": str(row["fidelity"]),
            }
            connection.execute(
                """
                UPDATE replay_training_fee_policy SET policy_hash = ?
                WHERE run_id = ? AND revision = ?
                """,
                (
                    canonical_sha256(complete_policy),
                    child_run_id,
                    int(row["revision"]),
                ),
            )
            extension = {
                "schema_version": "replay.training.fee-policy-extension.v1",
                "run_id": child_run_id,
                "revision": int(row["revision"]),
                "policy_version": str(extension_row["policy_version"]),
                "account_tier": str(extension_row["account_tier"]),
                "liquidation_fee_bps": str(extension_row["liquidation_fee_bps"]),
                "source_kind": str(extension_row["source_kind"]),
                "source_id": str(extension_row["source_id"]),
                "source_event_sequence": int(extension_row["source_event_sequence"]),
            }
            connection.execute(
                """
                INSERT INTO replay_training_fee_policy_extension(
                    run_id, revision, policy_version, account_tier,
                    liquidation_fee_bps, source_kind, source_id,
                    source_event_sequence, component_hash, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    child_run_id,
                    int(row["revision"]),
                    extension_row["policy_version"],
                    extension_row["account_tier"],
                    extension_row["liquidation_fee_bps"],
                    extension_row["source_kind"],
                    extension_row["source_id"],
                    extension_row["source_event_sequence"],
                    canonical_sha256(extension),
                    now_ms,
                ),
            )

    ledger_ops.append_contract_ledger(
        connection,
        run_id=child_run_id,
        posting_id="initial-capital",
        track_id=None,
        kind="INITIAL_CAPITAL",
        cash_delta=Decimal(str(parent["initial_equity"])),
        asset=settlement_asset,
        virtual_time_ms=virtual_time_ms,
        source_sequence=0,
        fidelity="FORKED_INITIAL_CAPITAL_EXACT",
        rule_revision=1,
        reference_type="FORK",
        reference_id=parent_run_id,
        metadata={
            "account_model": CONTRACT_ACCOUNT_MODEL,
            "parent_run_id": parent_run_id,
            "parent_virtual_time_ms": virtual_time_ms,
        },
        now_ms=now_ms,
    )
    account_marks_ops.sync_contract_components(
        connection,
        run_id=child_run_id,
        track_id="track-1",
        virtual_time_ms=virtual_time_ms,
        source_sequence=source_sequence,
        component_state=component_state,
        now_ms=now_ms,
        fork_parent_run_id=parent_run_id,
        fork_parent_track_id="track-1",
    )

    extra_cash = Decimal(0)
    copied_kinds = {
        "FUNDING_SETTLEMENT",
        "LIQUIDATION_FEE",
        "MARGIN_ALLOCATION",
        "MARGIN_RELEASE",
        "POLICY_REVISION",
    }
    for entry in parent_ledger:
        if str(entry["kind"]) not in copied_kinds:
            continue
        metadata = json.loads(str(entry["metadata_json"]))
        if not isinstance(metadata, dict):
            raise TypeError("parent contract ledger metadata is invalid")
        metadata["fork_parent_run_id"] = parent_run_id
        metadata["fork_parent_ledger_sequence"] = int(entry["ledger_sequence"])
        sequence = ledger_ops.append_contract_ledger(
            connection,
            run_id=child_run_id,
            posting_id=f"fork:{parent_run_id}:{entry['posting_id']}",
            track_id=(None if entry["track_id"] is None else "track-1"),
            kind=str(entry["kind"]),
            cash_delta=Decimal(str(entry["cash_delta"])),
            asset=str(entry["asset"]),
            virtual_time_ms=int(entry["virtual_time_ms"]),
            source_sequence=int(entry["source_sequence"]),
            fidelity=str(entry["fidelity"]),
            rule_revision=int(entry["rule_revision"]),
            reference_type=str(entry["reference_type"]),
            reference_id=str(entry["reference_id"]),
            metadata=metadata,
            now_ms=now_ms,
        )
        if str(entry["kind"]) in {"FUNDING_SETTLEMENT", "LIQUIDATION_FEE"}:
            extra_cash += Decimal(str(entry["cash_delta"]))
        if str(entry["kind"]) == "FUNDING_SETTLEMENT":
            settlement = connection.execute(
                """
                SELECT * FROM replay_training_funding_settlement
                WHERE run_id = ? AND track_id = ? AND settlement_time_ms = ?
                """,
                (
                    parent_run_id,
                    entry["track_id"],
                    int(entry["virtual_time_ms"]),
                ),
            ).fetchone()
            if settlement is not None:
                connection.execute(
                    """
                    INSERT INTO replay_training_funding_settlement(
                        run_id, track_id, settlement_time_ms, position_quantity,
                        mark_price, funding_rate, cash_delta, fidelity,
                        ledger_sequence, created_at_ms
                    ) VALUES (?, 'track-1', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        child_run_id,
                        settlement["settlement_time_ms"],
                        settlement["position_quantity"],
                        settlement["mark_price"],
                        settlement["funding_rate"],
                        settlement["cash_delta"],
                        settlement["fidelity"],
                        sequence,
                        now_ms,
                    ),
                )

    parent_track = connection.execute(
        """
        SELECT track_id FROM replay_training_market_track
        WHERE run_id = ? ORDER BY stable_ordinal LIMIT 1
        """,
        (parent_run_id,),
    ).fetchone()
    if parent_track is None:
        raise TypeError("parent fork track is missing")
    copy_hedge_relational_state(
        connection,
        parent_run_id=parent_run_id,
        child_run_id=child_run_id,
        parent_track_id=str(parent_track["track_id"]),
        child_track_id="track-1",
        virtual_time_ms=virtual_time_ms,
        source_sequence=source_sequence,
        now_ms=now_ms,
    )
    # Build the child-owned, content-addressed position and margin snapshot
    # from the selected checkpoint.  The detector is idempotent against any
    # copied liquidation case with the same public source sequence.
    liquidation_ops.detect_contract_liquidations(
        connection,
        run_id=child_run_id,
        now_ms=now_ms,
        trigger_virtual_time_ms=virtual_time_ms,
    )
    if str(parent["position_mode"]) == "HEDGE":
        parent_settlements = tuple(
            connection.execute(
                """
                SELECT settlement.*, ledger.posting_id
                FROM replay_training_hedge_funding_settlement AS settlement
                JOIN replay_training_contract_ledger AS ledger
                  ON ledger.run_id = settlement.run_id
                 AND ledger.ledger_sequence = settlement.ledger_sequence
                WHERE settlement.run_id = ?
                ORDER BY settlement.settlement_time_ms,
                         CASE settlement.position_side
                             WHEN 'LONG' THEN 0 ELSE 1 END
                """,
                (parent_run_id,),
            ).fetchall()
        )
        copied_settlements = 0
        for settlement in parent_settlements:
            child_ledger = connection.execute(
                """
                SELECT ledger_sequence
                FROM replay_training_contract_ledger
                WHERE run_id = ? AND posting_id = ?
                """,
                (
                    child_run_id,
                    f"fork:{parent_run_id}:{settlement['posting_id']}",
                ),
            ).fetchone()
            if child_ledger is None:
                continue
            component = {
                "schema_version": ("replay.training.hedge-funding-settlement.v1"),
                "run_id": child_run_id,
                "track_id": "track-1",
                "position_side": str(settlement["position_side"]),
                "settlement_time_ms": int(settlement["settlement_time_ms"]),
                "actual_settlement_time_ms": int(
                    settlement["actual_settlement_time_ms"]
                ),
                "source_kind": str(settlement["source_kind"]),
                "source_id": str(settlement["source_id"]),
                "source_event_sequence": int(settlement["source_event_sequence"]),
                "source_event_hash": str(settlement["source_event_hash"]),
                "pre_settlement_signed_quantity": str(
                    settlement["pre_settlement_signed_quantity"]
                ),
                "pre_settlement_absolute_quantity": str(
                    settlement["pre_settlement_absolute_quantity"]
                ),
                "mark_price": str(settlement["mark_price"]),
                "funding_rate": str(settlement["funding_rate"]),
                "contract_size": str(settlement["contract_size"]),
                "cash_delta": str(settlement["cash_delta"]),
                "rounding": str(settlement["rounding"]),
                "fidelity": str(settlement["fidelity"]),
                "rule_revision": int(settlement["rule_revision"]),
            }
            connection.execute(
                """
                INSERT INTO replay_training_hedge_funding_settlement(
                    run_id, track_id, position_side, settlement_time_ms,
                    actual_settlement_time_ms, source_kind, source_id,
                    source_event_sequence, source_event_hash,
                    pre_settlement_signed_quantity,
                    pre_settlement_absolute_quantity, mark_price,
                    funding_rate, contract_size, cash_delta, rounding,
                    fidelity, rule_revision, ledger_sequence,
                    component_hash, created_at_ms
                ) VALUES (?, 'track-1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    child_run_id,
                    settlement["position_side"],
                    settlement["settlement_time_ms"],
                    settlement["actual_settlement_time_ms"],
                    settlement["source_kind"],
                    settlement["source_id"],
                    settlement["source_event_sequence"],
                    settlement["source_event_hash"],
                    settlement["pre_settlement_signed_quantity"],
                    settlement["pre_settlement_absolute_quantity"],
                    settlement["mark_price"],
                    settlement["funding_rate"],
                    settlement["contract_size"],
                    settlement["cash_delta"],
                    settlement["rounding"],
                    settlement["fidelity"],
                    settlement["rule_revision"],
                    child_ledger["ledger_sequence"],
                    canonical_sha256(component),
                    now_ms,
                ),
            )
            copied_settlements += 1
        if copied_settlements:
            account_marks_ops.refresh_hedge_leg_accounting(
                connection,
                run_id=child_run_id,
                track_id="track-1",
                virtual_time_ms=virtual_time_ms,
                source_sequence=source_sequence,
                now_ms=now_ms,
                reason="REVIEW_FORK",
            )
    has_pending_liquidation = (
        connection.execute(
            """
            SELECT 1 FROM replay_training_liquidation_case
            WHERE run_id = ? AND state NOT IN (
                'COMPLETED', 'BANKRUPT', 'FAILED_CLOSED',
                'RECOVERED_AFTER_CANCEL'
            )
            LIMIT 1
            """,
            (child_run_id,),
        ).fetchone()
        is not None
    )
    current = connection.execute(
        """
        SELECT overlay_cash FROM replay_training_contract_account
        WHERE run_id = ?
        """,
        (child_run_id,),
    ).fetchone()
    overlay = Decimal(str(current["overlay_cash"])) + extra_cash
    status = "LIQUIDATING" if has_pending_liquidation else "ACTIVE"
    connection.execute(
        """
        UPDATE replay_training_contract_account
        SET overlay_cash = ?, status = ?, updated_at_ms = ? WHERE run_id = ?
        """,
        (
            decimal_to_string(overlay, field_name="fork overlay_cash"),
            status,
            now_ms,
            child_run_id,
        ),
    )
