"""TrainingAdvanceRepository operations using the shared SQLite owner."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence

from app.replay.canonical import canonical_json, canonical_sha256
from app.replay.period_summary import (
    MAX_PERIOD_SUMMARY_CANDIDATES,
    MAX_PERIOD_SUMMARY_TOTAL_COMPRESSED_BYTES,
    PERIOD_SUMMARY_ALGORITHM_VERSION,
    EncodedPeriodSummaryCandidate,
    ReplayPeriodSummary,
    decode_component_state,
)
from app.replay.storage.sqlite_store import ReplaySQLiteStore

from ..errors import TrainingRunError
from ..persistence import command_records as command_records_ops
from ..schema import (
    ADVANCE_INTENT_SCHEMA_VERSION,
    PERIOD_SUMMARY_SET_SCHEMA_VERSION,
)


class TrainingAdvanceRepository:
    """Own advances operations; keep each original read/write transaction intact."""

    def __init__(self, base_store: ReplaySQLiteStore) -> None:
        self.base_store = base_store

    async def get_command_result(
        self,
        run_id: str,
        command_id: str,
        command: Mapping[str, object],
    ) -> dict[str, object] | None:
        def read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return connection.execute(
                """
                SELECT command_json, result_json
                FROM replay_training_command
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()

        row = await self.base_store.run_extension_read(read)
        if row is None:
            return None
        if str(row["command_json"]) != canonical_json(command):
            raise TrainingRunError(
                "COMMAND_ID_REUSED",
                "command_id was reused with a different replay.v3 command",
                status_code=409,
            )
        result = json.loads(str(row["result_json"]))
        if not isinstance(result, dict):
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "stored replay.v3 command result is invalid",
                status_code=503,
            )
        return result

    async def save_command_result(
        self,
        *,
        run_id: str,
        command_id: str,
        command: Mapping[str, object],
        result: Mapping[str, object],
    ) -> None:
        command_json = canonical_json(command)
        result_json = canonical_json(result)

        def write(connection: sqlite3.Connection) -> None:
            command_records_ops.save_command_result_in_transaction(
                connection,
                run_id=run_id,
                command_id=command_id,
                command_json=command_json,
                result_json=result_json,
                now_ms=self.base_store._validated_now_ms(),
            )

        await self.base_store.run_extension_write(write)

    async def begin_period_summary_build(
        self,
        *,
        run_id: str,
        set_id: str,
    ) -> dict[str, object]:
        """Persist a visible single-flight marker without publishing candidates."""

        now_ms = self.base_store._validated_now_ms()

        def write(connection: sqlite3.Connection) -> dict[str, object]:
            exists = connection.execute(
                "SELECT 1 FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if exists is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            active = connection.execute(
                """
                SELECT set_id FROM replay_training_fast_forward_summary_set
                WHERE run_id = ? AND status = 'PREPARING'
                """,
                (run_id,),
            ).fetchone()
            if active is not None:
                raise TrainingRunError(
                    "PERIOD_SUMMARY_BUILD_ACTIVE",
                    "a period-summary build is already active for this run",
                    status_code=409,
                    details={"set_id": str(active["set_id"])},
                )
            connection.execute(
                """
                INSERT INTO replay_training_fast_forward_summary_set(
                    set_id, run_id, schema_version, algorithm_version,
                    status, active, metadata_json, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, 'PREPARING', 0, '{}', ?, ?)
                """,
                (
                    set_id,
                    run_id,
                    PERIOD_SUMMARY_SET_SCHEMA_VERSION,
                    PERIOD_SUMMARY_ALGORITHM_VERSION,
                    now_ms,
                    now_ms,
                ),
            )
            return {
                "set_id": set_id,
                "status": "PREPARING",
                "created_at_ms": now_ms,
            }

        return await self.base_store.run_extension_write(write)

    async def finish_period_summary_build(
        self,
        *,
        run_id: str,
        set_id: str,
        metadata: Mapping[str, object],
        build_proof_hash: str,
        candidates: Sequence[EncodedPeriodSummaryCandidate],
        source_event_count: int,
        build_wall_ms: int,
        build_cpu_ms: int,
    ) -> dict[str, object]:
        """Atomically publish a complete checksum-verified summary generation."""

        if not 1 <= len(candidates) <= MAX_PERIOD_SUMMARY_CANDIDATES:
            raise ValueError("period summary candidate count is outside its budget")
        if canonical_sha256(metadata) != build_proof_hash:
            raise ValueError("period summary build proof does not match metadata")
        total_compressed = 0
        total_raw = 0
        normalized: list[tuple[str, int, int, int, str, str, bytes, int, str]] = []
        previous_end = -1
        common_fields = (
            "run_id",
            "session_id",
            "source_kind",
            "data_epoch",
            "snapshot_ref_hash",
            "session_config_hash",
            "execution_version",
            "rule_revision",
            "rule_hash",
            "base_source_sequence",
            "base_domain_command_position",
            "base_event_chain_hash",
            "base_component_state_hash",
            "algorithm_version",
            "schema_version",
        )
        common_reference: dict[str, object] | None = None
        candidate_hashes: list[str] = []
        candidate_ids: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, EncodedPeriodSummaryCandidate):
                raise TypeError(
                    "period summary build candidate has an incompatible type"
                )
            summary = candidate.decode()
            if summary.run_id != run_id:
                raise ValueError("period summary candidate belongs to another run")
            if summary.end_source_sequence <= previous_end:
                raise ValueError("period summary candidates are not strictly ordered")
            if summary.summary_id in candidate_ids:
                raise ValueError("period summary candidate IDs are not unique")
            observed_common = {
                field_name: getattr(summary, field_name) for field_name in common_fields
            }
            if common_reference is None:
                common_reference = observed_common
            elif observed_common != common_reference:
                raise ValueError(
                    "period summary candidates do not share one immutable base"
                )
            component_blob = candidate.component_blob
            raw_bytes = candidate.component_raw_bytes
            blob_hash = candidate.component_blob_hash
            total_compressed += len(component_blob)
            total_raw += raw_bytes
            if total_compressed > MAX_PERIOD_SUMMARY_TOTAL_COMPRESSED_BYTES:
                raise ValueError(
                    "period summary set exceeds its compressed byte budget"
                )
            normalized.append(
                (
                    summary.summary_id,
                    summary.end_source_sequence,
                    summary.end_virtual_time_ms,
                    summary.event_count,
                    str(summary.summary_hash),
                    canonical_json(summary.to_dict(include_component_state=False)),
                    bytes(component_blob),
                    raw_bytes,
                    blob_hash,
                )
            )
            candidate_ids.add(summary.summary_id)
            candidate_hashes.append(str(summary.summary_hash))
            previous_end = summary.end_source_sequence
            del summary
        assert common_reference is not None
        for field_name, value in (
            ("source_event_count", source_event_count),
            ("build_wall_ms", build_wall_ms),
            ("build_cpu_ms", build_cpu_ms),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        expected_metadata = {
            "schema_version": "replay.period-summary-build-proof.v1",
            "algorithm_version": PERIOD_SUMMARY_ALGORITHM_VERSION,
            "set_id": set_id,
            "run_id": run_id,
            "session_id": common_reference["session_id"],
            "source_kind": common_reference["source_kind"],
            "data_epoch": common_reference["data_epoch"],
            "snapshot_ref_hash": common_reference["snapshot_ref_hash"],
            "session_config_hash": common_reference["session_config_hash"],
            "execution_version": common_reference["execution_version"],
            "rule_revision": common_reference["rule_revision"],
            "rule_hash": common_reference["rule_hash"],
            "base_source_sequence": common_reference["base_source_sequence"],
            "base_domain_command_position": (
                common_reference["base_domain_command_position"]
            ),
            "base_event_chain_hash": common_reference["base_event_chain_hash"],
            "base_component_state_hash": (
                common_reference["base_component_state_hash"]
            ),
            "candidate_summary_hashes": candidate_hashes,
            "source_event_count": (
                normalized[-1][1] - int(common_reference["base_source_sequence"])
            ),
            "candidate_count": len(normalized),
            "compressed_bytes": total_compressed,
        }
        if dict(metadata) != expected_metadata:
            raise ValueError(
                "period summary build metadata does not match its candidates"
            )
        if source_event_count != expected_metadata["source_event_count"]:
            raise ValueError(
                "period summary source event count does not match its candidates"
            )
        metadata_json = canonical_json(metadata)
        now_ms = self.base_store._validated_now_ms()

        def write(connection: sqlite3.Connection) -> dict[str, object]:
            build = connection.execute(
                """
                SELECT status FROM replay_training_fast_forward_summary_set
                WHERE run_id = ? AND set_id = ?
                """,
                (run_id, set_id),
            ).fetchone()
            if build is None:
                raise TrainingRunError(
                    "PERIOD_SUMMARY_BUILD_NOT_FOUND",
                    "period-summary build marker does not exist",
                    status_code=404,
                )
            if str(build["status"]) != "PREPARING":
                raise TrainingRunError(
                    "PERIOD_SUMMARY_BUILD_NOT_ACTIVE",
                    "period-summary build is not preparing",
                    status_code=409,
                )
            connection.execute(
                """
                UPDATE replay_training_fast_forward_summary_set
                SET active = 0
                WHERE run_id = ? AND active = 1
                """,
                (run_id,),
            )
            for (
                summary_id,
                end_source_sequence,
                end_virtual_time_ms,
                event_count,
                summary_hash,
                summary_json,
                blob,
                raw_bytes,
                blob_hash,
            ) in normalized:
                connection.execute(
                    """
                    INSERT INTO replay_training_fast_forward_summary(
                        set_id, run_id, summary_id, end_source_sequence,
                        end_virtual_time_ms, event_count, summary_hash,
                        metadata_json, component_blob, component_raw_bytes,
                        component_blob_hash, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        set_id,
                        run_id,
                        summary_id,
                        end_source_sequence,
                        end_virtual_time_ms,
                        event_count,
                        summary_hash,
                        summary_json,
                        blob,
                        raw_bytes,
                        blob_hash,
                        now_ms,
                    ),
                )
            connection.execute(
                """
                UPDATE replay_training_fast_forward_summary_set
                SET status = 'READY', active = 1, metadata_json = ?,
                    build_proof_hash = ?, candidate_count = ?,
                    source_event_count = ?, raw_state_bytes = ?,
                    compressed_bytes = ?, build_wall_ms = ?,
                    build_cpu_ms = ?, error_code = NULL, error_message = NULL,
                    updated_at_ms = ?
                WHERE run_id = ? AND set_id = ? AND status = 'PREPARING'
                """,
                (
                    metadata_json,
                    build_proof_hash,
                    len(normalized),
                    source_event_count,
                    total_raw,
                    total_compressed,
                    build_wall_ms,
                    build_cpu_ms,
                    now_ms,
                    run_id,
                    set_id,
                ),
            )
            return {
                "set_id": set_id,
                "status": "READY",
                "candidate_count": len(normalized),
                "source_event_count": source_event_count,
                "raw_state_bytes": total_raw,
                "compressed_bytes": total_compressed,
                "build_wall_ms": build_wall_ms,
                "build_cpu_ms": build_cpu_ms,
                "build_proof_hash": build_proof_hash,
            }

        return await self.base_store.run_extension_write(write)

    async def fail_period_summary_build(
        self,
        *,
        run_id: str,
        set_id: str,
        cancelled: bool,
        error_code: str,
        error_message: str,
    ) -> None:
        now_ms = self.base_store._validated_now_ms()
        status = "CANCELLED" if cancelled else "FAILED"

        def write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                UPDATE replay_training_fast_forward_summary_set
                SET status = ?, active = 0, error_code = ?, error_message = ?,
                    updated_at_ms = ?
                WHERE run_id = ? AND set_id = ? AND status = 'PREPARING'
                """,
                (
                    status,
                    error_code[:100],
                    error_message[:500],
                    now_ms,
                    run_id,
                    set_id,
                ),
            )

        await self.base_store.run_extension_write(write)

    async def period_summary_status(self, run_id: str) -> dict[str, object]:
        def read(
            connection: sqlite3.Connection,
        ) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
            latest = connection.execute(
                """
                SELECT * FROM replay_training_fast_forward_summary_set
                WHERE run_id = ?
                ORDER BY updated_at_ms DESC, rowid DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            active = connection.execute(
                """
                SELECT * FROM replay_training_fast_forward_summary_set
                WHERE run_id = ? AND active = 1 AND status = 'READY'
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            return latest, active

        latest, active = await self.base_store.run_extension_read(read)

        def public(row: sqlite3.Row | None) -> dict[str, object] | None:
            if row is None:
                return None
            return {
                "set_id": str(row["set_id"]),
                "status": str(row["status"]),
                "active": bool(row["active"]),
                "algorithm_version": str(row["algorithm_version"]),
                "candidate_count": int(row["candidate_count"]),
                "source_event_count": int(row["source_event_count"]),
                "raw_state_bytes": int(row["raw_state_bytes"]),
                "compressed_bytes": int(row["compressed_bytes"]),
                "build_wall_ms": int(row["build_wall_ms"]),
                "build_cpu_ms": int(row["build_cpu_ms"]),
                "build_proof_hash": row["build_proof_hash"],
                "error_code": row["error_code"],
                "error_message": row["error_message"],
            }

        return {
            "schema_version": PERIOD_SUMMARY_SET_SCHEMA_VERSION,
            "latest_build": public(latest),
            "active_set": public(active),
            "limits": {
                "max_candidates": MAX_PERIOD_SUMMARY_CANDIDATES,
                "max_total_compressed_bytes": (
                    MAX_PERIOD_SUMMARY_TOTAL_COMPRESSED_BYTES
                ),
            },
        }

    async def period_summary_candidate(
        self,
        *,
        run_id: str,
        current_source_sequence: int,
        target_virtual_time_ms: int,
        identity: Mapping[str, object],
    ) -> dict[str, object]:
        """Load at most one active candidate and validate every persisted byte."""

        def read(
            connection: sqlite3.Connection,
        ) -> tuple[sqlite3.Row, tuple[sqlite3.Row, ...]] | None:
            row = connection.execute(
                """
                SELECT candidate.*, summary_set.metadata_json AS set_metadata_json,
                       summary_set.build_proof_hash,
                       summary_set.algorithm_version AS set_algorithm_version,
                       summary_set.candidate_count AS set_candidate_count,
                       summary_set.source_event_count AS set_source_event_count,
                       summary_set.raw_state_bytes AS set_raw_state_bytes,
                       summary_set.compressed_bytes AS set_compressed_bytes
                FROM replay_training_fast_forward_summary AS candidate
                JOIN replay_training_fast_forward_summary_set AS summary_set
                  ON summary_set.set_id = candidate.set_id
                WHERE candidate.run_id = ?
                  AND summary_set.run_id = candidate.run_id
                  AND summary_set.status = 'READY'
                  AND summary_set.active = 1
                  AND candidate.end_source_sequence > ?
                  AND candidate.end_virtual_time_ms <= ?
                ORDER BY candidate.end_virtual_time_ms DESC,
                         candidate.end_source_sequence DESC
                LIMIT 1
                """,
                (
                    run_id,
                    current_source_sequence,
                    target_virtual_time_ms,
                ),
            ).fetchone()
            if row is None:
                return None
            generation = tuple(
                connection.execute(
                    """
                    SELECT summary_hash, end_source_sequence,
                           length(component_blob) AS component_blob_bytes,
                           component_raw_bytes
                    FROM replay_training_fast_forward_summary
                    WHERE set_id = ? AND run_id = ?
                    ORDER BY end_source_sequence ASC, summary_id ASC
                    """,
                    (str(row["set_id"]), run_id),
                ).fetchall()
            )
            return row, generation

        loaded = await self.base_store.run_extension_read(read)
        if loaded is None:
            return {
                "status": "UNAVAILABLE",
                "reason_code": "NO_CANDIDATE_IN_RANGE",
                "summary": None,
            }
        row, generation = loaded
        try:
            set_metadata = json.loads(str(row["set_metadata_json"]))
            generation_hashes = [
                str(candidate["summary_hash"]) for candidate in generation
            ]
            generation_sequences = [
                int(candidate["end_source_sequence"]) for candidate in generation
            ]
            generation_compressed_bytes = sum(
                int(candidate["component_blob_bytes"]) for candidate in generation
            )
            generation_raw_bytes = sum(
                int(candidate["component_raw_bytes"]) for candidate in generation
            )
            if (
                not isinstance(set_metadata, dict)
                or canonical_sha256(set_metadata) != str(row["build_proof_hash"])
                or str(row["set_algorithm_version"]) != PERIOD_SUMMARY_ALGORITHM_VERSION
                or not 1
                <= int(row["set_candidate_count"])
                <= MAX_PERIOD_SUMMARY_CANDIDATES
                or len(generation) != int(row["set_candidate_count"])
                or any(
                    current <= previous
                    for previous, current in zip(
                        generation_sequences,
                        generation_sequences[1:],
                    )
                )
                or not 1
                <= int(row["set_compressed_bytes"])
                <= MAX_PERIOD_SUMMARY_TOTAL_COMPRESSED_BYTES
                or generation_compressed_bytes != int(row["set_compressed_bytes"])
                or generation_raw_bytes != int(row["set_raw_state_bytes"])
                or set_metadata.get("algorithm_version")
                != str(row["set_algorithm_version"])
                or set_metadata.get("set_id") != str(row["set_id"])
                or set_metadata.get("run_id") != run_id
                or set_metadata.get("candidate_count")
                != int(row["set_candidate_count"])
                or set_metadata.get("source_event_count")
                != int(row["set_source_event_count"])
                or set_metadata.get("compressed_bytes")
                != int(row["set_compressed_bytes"])
                or set_metadata.get("candidate_summary_hashes") != generation_hashes
            ):
                raise ValueError("period summary set proof is invalid")
            metadata = json.loads(str(row["metadata_json"]))
            if not isinstance(metadata, dict):
                raise ValueError("summary metadata is not an object")
            component_state = decode_component_state(
                bytes(row["component_blob"]),
                expected_raw_bytes=int(row["component_raw_bytes"]),
                expected_blob_hash=str(row["component_blob_hash"]),
                expected_state_hash=str(metadata["end_component_state_hash"]),
            )
            summary = ReplayPeriodSummary.from_dict(
                {**metadata, "end_component_state": component_state}
            )
            if (
                summary.summary_hash != str(row["summary_hash"])
                or summary.summary_id != str(row["summary_id"])
                or summary.end_source_sequence != int(row["end_source_sequence"])
                or summary.end_virtual_time_ms != int(row["end_virtual_time_ms"])
                or summary.event_count != int(row["event_count"])
            ):
                raise ValueError("period summary indexed fields changed")
            summary_hashes = generation_hashes
            if summary.summary_hash not in summary_hashes or len(
                set(summary_hashes)
            ) != len(summary_hashes):
                raise ValueError("period summary build proof omitted its candidate")
            set_identity = {
                "session_id": set_metadata.get("session_id"),
                "source_kind": set_metadata.get("source_kind"),
                "data_epoch": set_metadata.get("data_epoch"),
                "snapshot_ref_hash": set_metadata.get("snapshot_ref_hash"),
                "session_config_hash": set_metadata.get("session_config_hash"),
                "execution_version": set_metadata.get("execution_version"),
                "rule_revision": set_metadata.get("rule_revision"),
                "rule_hash": set_metadata.get("rule_hash"),
                "base_source_sequence": set_metadata.get("base_source_sequence"),
                "base_domain_command_position": set_metadata.get(
                    "base_domain_command_position"
                ),
                "base_event_chain_hash": set_metadata.get("base_event_chain_hash"),
                "base_component_state_hash": set_metadata.get(
                    "base_component_state_hash"
                ),
            }
            summary_identity = {
                "session_id": summary.session_id,
                "source_kind": summary.source_kind,
                "data_epoch": summary.data_epoch,
                "snapshot_ref_hash": summary.snapshot_ref_hash,
                "session_config_hash": summary.session_config_hash,
                "execution_version": summary.execution_version,
                "rule_revision": summary.rule_revision,
                "rule_hash": summary.rule_hash,
                "base_source_sequence": summary.base_source_sequence,
                "base_domain_command_position": (summary.base_domain_command_position),
                "base_event_chain_hash": summary.base_event_chain_hash,
                "base_component_state_hash": (summary.base_component_state_hash),
            }
            if set_identity != summary_identity:
                raise ValueError(
                    "period summary candidate does not match its set proof"
                )
            expected_identity = {
                key: identity[key]
                for key in (
                    "session_id",
                    "source_kind",
                    "data_epoch",
                    "snapshot_ref_hash",
                    "session_config_hash",
                    "execution_version",
                    "rule_revision",
                    "rule_hash",
                )
            }
            observed_identity = {
                "session_id": summary.session_id,
                "source_kind": summary.source_kind,
                "data_epoch": summary.data_epoch,
                "snapshot_ref_hash": summary.snapshot_ref_hash,
                "session_config_hash": summary.session_config_hash,
                "execution_version": summary.execution_version,
                "rule_revision": summary.rule_revision,
                "rule_hash": summary.rule_hash,
            }
            if observed_identity != expected_identity:
                return {
                    "status": "INCOMPATIBLE",
                    "reason_code": "SUMMARY_IDENTITY_MISMATCH",
                    "summary": None,
                }
            if not (
                summary.base_source_sequence
                <= current_source_sequence
                < summary.end_source_sequence
            ):
                return {
                    "status": "INCOMPATIBLE",
                    "reason_code": "SUMMARY_RANGE_MISMATCH",
                    "summary": None,
                }
        except (KeyError, TypeError, ValueError):
            return {
                "status": "CORRUPT",
                "reason_code": "SUMMARY_VALIDATION_FAILED",
                "summary": None,
            }
        return {
            "status": "READY",
            "reason_code": "EXACT_SUMMARY_CANDIDATE",
            "set_id": str(row["set_id"]),
            "build_proof_hash": str(row["build_proof_hash"]),
            "summary": summary,
        }

    async def get_advance_intent(
        self,
        *,
        run_id: str,
        command_id: str,
        command: Mapping[str, object],
    ) -> dict[str, object] | None:
        command_json = canonical_json(command)

        def read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return connection.execute(
                """
                SELECT * FROM replay_training_advance_intent
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()

        row = await self.base_store.run_extension_read(read)
        if row is None:
            return None
        if str(row["command_json"]) != command_json:
            raise TrainingRunError(
                "COMMAND_ID_REUSED",
                "command_id was reused with a different advance command",
                status_code=409,
            )
        return command_records_ops.advance_intent_from_row(row)

    async def begin_advance_intent(self, **kwargs) -> dict[str, object]:
        return command_records_ops.advance_intent_from_row(
            await self.base_store.run_extension_write(
                self._advance_intent_writer(**kwargs)
            )
        )

    def _advance_intent_writer(
        self,
        *,
        run_id: str,
        command_id: str,
        command: Mapping[str, object],
        session_id: str,
        initial_cursor: Mapping[str, object],
        target_virtual_time_ms: int,
        plan: Mapping[str, object],
        summary: ReplayPeriodSummary | None,
    ) -> Callable[[sqlite3.Connection], sqlite3.Row]:
        command_json = canonical_json(command)
        command_hash = canonical_sha256(command)
        cursor_json = canonical_json(initial_cursor)
        plan_json = canonical_json(plan)
        now_ms = self.base_store._validated_now_ms()

        def write(connection: sqlite3.Connection) -> sqlite3.Row:
            existing = connection.execute(
                """
                SELECT * FROM replay_training_advance_intent
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()
            if existing is not None:
                if str(existing["command_json"]) != command_json:
                    raise TrainingRunError(
                        "COMMAND_ID_REUSED",
                        "command_id conflicts with a durable advance intent",
                        status_code=409,
                    )
                return existing
            connection.execute(
                """
                INSERT INTO replay_training_advance_intent(
                    run_id, command_id, schema_version, command_json,
                    command_hash, session_id, initial_cursor_json,
                    target_virtual_time_ms, plan_json, summary_id,
                    summary_hash, status, latest_cursor_json,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?, ?)
                """,
                (
                    run_id,
                    command_id,
                    ADVANCE_INTENT_SCHEMA_VERSION,
                    command_json,
                    command_hash,
                    session_id,
                    cursor_json,
                    target_virtual_time_ms,
                    plan_json,
                    summary.summary_id if summary is not None else None,
                    summary.summary_hash if summary is not None else None,
                    cursor_json,
                    now_ms,
                    now_ms,
                ),
            )
            created = connection.execute(
                """
                SELECT * FROM replay_training_advance_intent
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()
            assert created is not None
            return created

        return write

    async def update_advance_intent_cursor(
        self,
        *,
        run_id: str,
        command_id: str,
        cursor: Mapping[str, object],
    ) -> None:
        for field_name in ("virtual_time_ms", "source_sequence"):
            value = cursor.get(field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"advance intent cursor {field_name} is invalid")
        cursor_json = canonical_json(cursor)
        now_ms = self.base_store._validated_now_ms()

        def write(connection: sqlite3.Connection) -> None:
            row = connection.execute(
                """
                SELECT status, latest_cursor_json
                FROM replay_training_advance_intent
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()
            if row is None:
                raise TrainingRunError(
                    "ADVANCE_INTENT_NOT_FOUND",
                    "durable advance intent does not exist",
                    status_code=503,
                )
            if str(row["status"]) != "RUNNING":
                raise TrainingRunError(
                    "ADVANCE_INTENT_NOT_RUNNING",
                    "durable advance intent is not running",
                    status_code=409,
                )
            try:
                previous = json.loads(str(row["latest_cursor_json"]))
            except json.JSONDecodeError as exc:
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "durable advance latest cursor is invalid",
                    status_code=503,
                ) from exc
            if not isinstance(previous, dict):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "durable advance latest cursor is invalid",
                    status_code=503,
                )
            for field_name in ("virtual_time_ms", "source_sequence"):
                prior = previous.get(field_name)
                current = cursor[field_name]
                if (
                    isinstance(prior, bool)
                    or not isinstance(prior, int)
                    or prior < 0
                    or int(current) < prior
                ):
                    raise TrainingRunError(
                        "ADVANCE_INTENT_CURSOR_REGRESSION",
                        "durable advance cursor cannot move backward",
                        status_code=503,
                    )
            updated = connection.execute(
                """
                UPDATE replay_training_advance_intent
                SET latest_cursor_json = ?, updated_at_ms = ?
                WHERE run_id = ? AND command_id = ? AND status = 'RUNNING'
                """,
                (cursor_json, now_ms, run_id, command_id),
            )
            if updated.rowcount != 1:
                raise TrainingRunError(
                    "ADVANCE_INTENT_NOT_RUNNING",
                    "durable advance intent stopped before cursor update",
                    status_code=409,
                )

        await self.base_store.run_extension_write(write)

    async def finish_advance_intent(
        self,
        *,
        run_id: str,
        command_id: str,
        result: Mapping[str, object],
        cancelled: bool,
    ) -> None:
        await self.base_store.run_extension_write(
            lambda connection: self._finish_advance_intent_in_transaction(
                connection,
                run_id=run_id,
                command_id=command_id,
                result=result,
                cancelled=cancelled,
            )
        )

    def _finish_advance_intent_in_transaction(
        self, connection, *, run_id, command_id, result, cancelled
    ):
        result_json = canonical_json(result)
        now_ms = self.base_store._validated_now_ms()
        status = "CANCELLED" if cancelled else "COMPLETED"
        row = connection.execute(
            """
            SELECT status, result_json, command_json
            FROM replay_training_advance_intent
            WHERE run_id = ? AND command_id = ?
            """,
            (run_id, command_id),
        ).fetchone()
        if row is None:
            raise TrainingRunError(
                "ADVANCE_INTENT_NOT_FOUND",
                "durable advance intent does not exist",
                status_code=503,
            )
        # The terminal intent and its idempotent response become durable
        # together; a conflict rolls back both writes.
        if str(row["status"]) == "FAILED":
            raise TrainingRunError(
                "ADVANCE_INTENT_FAILED",
                "a failed advance intent cannot publish a terminal result",
                status_code=409,
            )
        command_records_ops.save_command_result_in_transaction(
            connection,
            run_id=run_id,
            command_id=command_id,
            command_json=str(row["command_json"]),
            result_json=result_json,
            now_ms=now_ms,
        )
        if str(row["status"]) in {"COMPLETED", "CANCELLED"}:
            if str(row["status"]) != status or str(row["result_json"]) != result_json:
                raise TrainingRunError(
                    "COMMAND_ID_REUSED",
                    "durable advance result conflicts with its prior result",
                    status_code=409,
                )
            return
        connection.execute(
            """
            UPDATE replay_training_advance_intent
            SET status = ?, result_json = ?, updated_at_ms = ?
            WHERE run_id = ? AND command_id = ? AND status = 'RUNNING'
            """,
            (status, result_json, now_ms, run_id, command_id),
        )
