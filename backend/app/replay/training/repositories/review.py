"""TrainingReviewRepository operations using the shared SQLite owner."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from decimal import Decimal

from app.replay.canonical import canonical_json, canonical_sha256
from app.replay.storage.sqlite_store import ReplaySQLiteStore

from ..anchor_codec import (
    ANCHOR_PAYLOAD_ENCODING_RAW,
    decode_anchor_payload,
)
from ..errors import TrainingRunError
from ..models import (
    REPLAY_V2_PROTOCOL,
    ViewerState,
)
from ..persistence import account_math as account_math_ops
from ..persistence import portfolio as portfolio_ops
from ..persistence import public_time as public_time_ops
from ..persistence import review_records as review_records_ops
from ..persistence import run_records as run_records_ops
from ..review import (
    ReviewRecorder,
    validate_drawing_document,
)
from ..schema import (
    REVIEW_TIMELINE_SCHEMA_VERSION,
)


class TrainingReviewRepository:
    """Own review operations; keep each original read/write transaction intact."""

    def __init__(self, base_store: ReplaySQLiteStore, review: ReviewRecorder) -> None:
        self.base_store = base_store
        self._review = review

    async def record_view_action(
        self,
        *,
        run_id: str,
        command_id: str,
        event_type: str,
        semantic_key: str,
        value: Mapping[str, object],
        public_time_ms: int,
        source_sequence: int,
    ) -> dict[str, object]:
        value_json = canonical_json(value)

        def write(connection: sqlite3.Connection) -> dict[str, object]:
            run = connection.execute(
                """
                SELECT r.adapter_session_id, r.time_disclosure_policy,
                       COALESCE(i.revealed, 0) AS revealed
                FROM replay_training_run AS r
                LEFT JOIN replay_training_integrity AS i USING(run_id)
                WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            existing_command = connection.execute(
                """
                SELECT * FROM replay_run_view_event
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()
            if existing_command is not None:
                return run_records_ops.view_action_from_row(
                    existing_command, coalesced=True
                )
            public_time = public_time_ops.public_time(
                connection,
                session_id=str(run["adapter_session_id"]),
                policy=str(run["time_disclosure_policy"]),
                revealed=bool(run["revealed"]),
                public_time_ms=public_time_ms,
                sequence=source_sequence,
            )
            self._review.record_viewport(
                connection,
                run_id=run_id,
                bucket_key=semantic_key,
                event_type=event_type,
                value=value,
                public_time=public_time,
                now_ms=self.base_store._validated_now_ms(),
            )
            existing = connection.execute(
                """
                SELECT * FROM replay_run_view_event
                WHERE run_id = ? AND semantic_key = ?
                """,
                (run_id, semantic_key),
            ).fetchone()
            now_ms = self.base_store._validated_now_ms()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE replay_run_view_event
                    SET command_id = ?, event_type = ?, value_json = ?,
                        sample_count = sample_count + 1,
                        last_public_time_json = ?, updated_at_ms = ?
                    WHERE run_id = ? AND semantic_key = ?
                    """,
                    (
                        command_id,
                        event_type,
                        value_json,
                        canonical_json(public_time),
                        now_ms,
                        run_id,
                        semantic_key,
                    ),
                )
                row = connection.execute(
                    """
                    SELECT * FROM replay_run_view_event
                    WHERE run_id = ? AND semantic_key = ?
                    """,
                    (run_id, semantic_key),
                ).fetchone()
                return run_records_ops.view_action_from_row(row, coalesced=True)
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM replay_run_view_event WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            if count >= run_records_ops._VIEW_EVENT_LIMIT:
                connection.execute(
                    """
                    DELETE FROM replay_run_view_event WHERE rowid = (
                        SELECT rowid FROM replay_run_view_event
                        WHERE run_id = ? ORDER BY updated_at_ms, view_sequence LIMIT 1
                    )
                    """,
                    (run_id,),
                )
            next_sequence = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(view_sequence), 0) + 1
                    FROM replay_run_view_event WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()[0]
            )
            encoded_time = canonical_json(public_time)
            connection.execute(
                """
                INSERT INTO replay_run_view_event(
                    run_id, view_sequence, command_id, event_type,
                    semantic_key, value_json, sample_count,
                    first_public_time_json, last_public_time_json,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    next_sequence,
                    command_id,
                    event_type,
                    semantic_key,
                    value_json,
                    encoded_time,
                    encoded_time,
                    now_ms,
                    now_ms,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM replay_run_view_event
                WHERE run_id = ? AND semantic_key = ?
                """,
                (run_id, semantic_key),
            ).fetchone()
            return run_records_ops.view_action_from_row(row, coalesced=False)

        return await self.base_store.run_extension_write(write)

    async def run_rules(self, run_id: str) -> dict[str, object]:
        def read(connection: sqlite3.Connection) -> dict[str, object]:
            return self._review.rules_projection(
                connection,
                run_id=run_id,
                include_history=True,
            )

        return await self.base_store.run_extension_read(read)

    async def current_drawing_document(self, run_id: str) -> dict[str, object]:
        def read(connection: sqlite3.Connection) -> dict[str, object]:
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
            row = connection.execute(
                """
                SELECT document_hash, revision, document_json, entity_count
                FROM replay_review_drawing_document
                WHERE run_id = ? ORDER BY revision DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "schema_version": "replay.review.drawing-current.v1",
                "run_id": run_id,
                "document_hash": (None if row is None else str(row["document_hash"])),
                "revision": 0 if row is None else int(row["revision"]),
                "entity_count": 0 if row is None else int(row["entity_count"]),
                "document": (
                    None if row is None else json.loads(str(row["document_json"]))
                ),
                "budget": review_records_ops.review_budget(connection, run_id),
            }

        return await self.base_store.run_extension_read(read)

    async def record_drawing_document(
        self,
        *,
        run_id: str,
        command_id: str,
        document_hash: str,
        document: Mapping[str, object],
        entity_count: int,
    ) -> dict[str, object]:
        document_json, calculated_hash = validate_drawing_document(
            document,
            run_id=run_id,
            entity_count=entity_count,
        )
        document_bytes = len(document_json.encode("utf-8"))
        if calculated_hash != document_hash:
            raise TrainingRunError(
                "REVIEW_DRAWING_HASH_MISMATCH",
                "drawing document hash does not match canonical content",
                status_code=409,
                details={
                    "expected": calculated_hash,
                    "actual": document_hash,
                },
            )

        def write(connection: sqlite3.Connection) -> dict[str, object]:
            replayed = connection.execute(
                """
                SELECT * FROM replay_review_drawing_document
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()
            if replayed is not None:
                if str(replayed["document_hash"]) != document_hash:
                    raise TrainingRunError(
                        "COMMAND_ID_REUSED",
                        "command_id was reused with a different drawing document",
                        status_code=409,
                    )
                return {
                    "protocol": REPLAY_V2_PROTOCOL,
                    "schema_version": "replay.review.drawing-document.v1",
                    "run_id": run_id,
                    "document_hash": document_hash,
                    "revision": int(replayed["revision"]),
                    "entity_count": int(replayed["entity_count"]),
                    "deduplicated": True,
                    "budget": review_records_ops.review_budget(connection, run_id),
                }
            by_hash = connection.execute(
                """
                SELECT * FROM replay_review_drawing_document
                WHERE run_id = ? AND document_hash = ?
                """,
                (run_id, document_hash),
            ).fetchone()
            if by_hash is not None:
                return {
                    "protocol": REPLAY_V2_PROTOCOL,
                    "schema_version": "replay.review.drawing-document.v1",
                    "run_id": run_id,
                    "document_hash": document_hash,
                    "revision": int(by_hash["revision"]),
                    "entity_count": int(by_hash["entity_count"]),
                    "deduplicated": True,
                    "budget": review_records_ops.review_budget(connection, run_id),
                }
            run = connection.execute(
                """
                SELECT r.adapter_session_id, r.virtual_time_ms, r.source_sequence
                FROM replay_training_run AS r WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            budget = review_records_ops.review_budget(connection, run_id)
            if int(budget["artifact_used_bytes"]) + document_bytes > int(
                budget["artifact_limit_bytes"]
            ):
                raise TrainingRunError(
                    "REVIEW_ARTIFACT_BUDGET_EXCEEDED",
                    "review drawing artifact budget is exhausted",
                    status_code=409,
                    details={
                        **budget,
                        "offered_bytes": document_bytes,
                        "event_dropped": False,
                    },
                )
            revision = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(revision), 0) + 1
                    FROM replay_review_drawing_document WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()[0]
            )
            now_ms = self.base_store._validated_now_ms()
            connection.execute(
                """
                INSERT INTO replay_review_drawing_document(
                    run_id, document_hash, revision, command_id,
                    document_json, document_bytes, entity_count,
                    virtual_time_ms, source_sequence, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    document_hash,
                    revision,
                    command_id,
                    document_json,
                    document_bytes,
                    entity_count,
                    run["virtual_time_ms"],
                    run["source_sequence"],
                    now_ms,
                ),
            )
            self._review.append(
                connection,
                run_id=run_id,
                session_id=str(run["adapter_session_id"]),
                context={
                    "kind": "DIRECT",
                    "category": "DRAWING",
                    "event_type": "DRAWING_DOCUMENT",
                    "command_id": command_id,
                },
                state=None,
                checkpoint=None,
                now_ms=now_ms,
            )
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "schema_version": "replay.review.drawing-document.v1",
                "run_id": run_id,
                "document_hash": document_hash,
                "revision": revision,
                "entity_count": entity_count,
                "deduplicated": False,
                "budget": review_records_ops.review_budget(connection, run_id),
            }

        return await self.base_store.run_extension_write(write)

    async def record_review_marker(
        self,
        *,
        run_id: str,
        command_id: str,
        text: str,
    ) -> dict[str, object]:
        normalized_text = text.strip()
        if not normalized_text or len(normalized_text) > 500:
            raise TrainingRunError(
                "REVIEW_MARKER_INVALID",
                "review marker text must contain 1 to 500 characters",
                status_code=422,
            )
        content_hash = canonical_sha256(
            {
                "schema_version": "replay.review.marker.v1",
                "run_id": run_id,
                "text": normalized_text,
            }
        )

        def write(connection: sqlite3.Connection) -> dict[str, object]:
            existing = connection.execute(
                """
                SELECT marker.*, event.event_id, event.timeline_sequence
                FROM replay_review_marker AS marker
                LEFT JOIN replay_review_timeline_event AS event
                  ON event.run_id = marker.run_id
                 AND event.command_id = marker.command_id
                 AND event.category = 'MARKER'
                WHERE marker.run_id = ? AND marker.command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()
            if existing is not None:
                if str(existing["content_hash"]) != content_hash:
                    raise TrainingRunError(
                        "COMMAND_ID_REUSED",
                        "command_id was reused with different marker content",
                        status_code=409,
                    )
                return {
                    "protocol": REPLAY_V2_PROTOCOL,
                    "schema_version": "replay.review.marker.v1",
                    "run_id": run_id,
                    "marker_id": str(existing["marker_id"]),
                    "command_id": command_id,
                    "text": normalized_text,
                    "content_hash": content_hash,
                    "event_id": existing["event_id"],
                    "timeline_sequence": existing["timeline_sequence"],
                    "deduplicated": True,
                    "budget": review_records_ops.review_budget(connection, run_id),
                }
            run = connection.execute(
                """
                SELECT adapter_session_id, virtual_time_ms, source_sequence
                FROM replay_training_run WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            ordinal = int(
                connection.execute(
                    "SELECT COUNT(*) + 1 FROM replay_review_marker WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            marker_id = f"marker-{ordinal:08d}"
            now_ms = self.base_store._validated_now_ms()
            connection.execute(
                """
                INSERT INTO replay_review_marker(
                    run_id, marker_id, command_id, text, content_hash,
                    virtual_time_ms, source_sequence, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    marker_id,
                    command_id,
                    normalized_text,
                    content_hash,
                    run["virtual_time_ms"],
                    run["source_sequence"],
                    now_ms,
                ),
            )
            created = self._review.append(
                connection,
                run_id=run_id,
                session_id=str(run["adapter_session_id"]),
                context={
                    "kind": "DIRECT",
                    "category": "MARKER",
                    "event_type": "USER_MARKER",
                    "command_id": command_id,
                },
                state=None,
                checkpoint=None,
                now_ms=now_ms,
            )
            if len(created) != 1:
                raise TypeError(
                    "review marker did not create exactly one timeline event"
                )
            event = connection.execute(
                """
                SELECT timeline_sequence FROM replay_review_timeline_event
                WHERE run_id = ? AND event_id = ?
                """,
                (run_id, created[0]),
            ).fetchone()
            if event is None:
                raise TypeError("review marker timeline event is missing")
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "schema_version": "replay.review.marker.v1",
                "run_id": run_id,
                "marker_id": marker_id,
                "command_id": command_id,
                "text": normalized_text,
                "content_hash": content_hash,
                "event_id": created[0],
                "timeline_sequence": int(event["timeline_sequence"]),
                "deduplicated": False,
                "budget": review_records_ops.review_budget(connection, run_id),
            }

        return await self.base_store.run_extension_write(write)

    async def start_review(
        self,
        *,
        run_id: str,
        review_id: str,
        event_id: str | None,
    ) -> dict[str, object]:
        def write(connection: sqlite3.Connection) -> dict[str, object]:
            run = connection.execute(
                """
                SELECT r.adapter_session_id, r.time_disclosure_policy,
                       r.virtual_time_ms, r.source_sequence,
                       r.dataset_epoch,
                       COALESCE(i.revealed, 0) AS revealed,
                       s.state_hash, account.ledger_tail_hash,
                       viewer.semantic_view_revision
                FROM replay_training_run AS r
                JOIN replay_session AS s ON s.session_id = r.adapter_session_id
                JOIN replay_training_contract_account AS account USING(run_id)
                JOIN replay_training_viewer_state AS viewer USING(run_id)
                LEFT JOIN replay_training_integrity AS i USING(run_id)
                WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training run does not exist",
                    status_code=404,
                )
            portfolio_ops.assert_run_segments_ready(
                connection,
                run_id=run_id,
                operation="review",
            )
            rows = connection.execute(
                """
                SELECT event.*, anchor.checkpoint_id
                FROM replay_review_timeline_event AS event
                JOIN replay_review_event_anchor AS link
                  ON link.run_id = event.run_id
                 AND link.timeline_sequence = event.timeline_sequence
                 AND link.track_id = event.track_id
                JOIN replay_review_actor_anchor AS anchor
                  ON anchor.run_id = link.run_id
                 AND anchor.anchor_id = link.anchor_id
                WHERE event.run_id = ?
                ORDER BY event.timeline_sequence
                """,
                (run_id,),
            ).fetchall()
            if not rows:
                raise TrainingRunError(
                    "REVIEW_UNAVAILABLE",
                    "training run has no immutable review timeline",
                    status_code=409,
                )
            events = [
                {
                    "event_id": str(row["event_id"]),
                    "event_type": str(row["event_type"]),
                    "category": str(row["category"]),
                    "timeline_sequence": int(row["timeline_sequence"]),
                    "checkpoint_id": int(row["checkpoint_id"]),
                    "source_sequence": int(row["source_sequence"]),
                    "event_sequence": int(row["event_sequence"]),
                    "state_hash": str(row["state_hash"]),
                    "account_hash": str(row["account_hash"]),
                    "ledger_tail_hash": str(row["ledger_tail_hash"]),
                    "viewer_revision": int(row["viewer_revision"]),
                    "anchor_set_hash": str(row["anchor_set_hash"]),
                    "event_hash": str(row["event_hash"]),
                    "public_time": json.loads(str(row["public_time_json"])),
                    "detail": review_records_ops.review_event_detail(connection, row),
                }
                for row in rows
            ]
            selected: dict[str, object] | None = events[-1]
            if event_id is not None:
                selected = next(
                    (item for item in events if item["event_id"] == event_id),
                    None,
                )
            if selected is None:
                raise TrainingRunError(
                    "REVIEW_EVENT_NOT_FOUND",
                    "review event is not in the immutable timeline",
                    status_code=404,
                )
            original_cursor = {
                "virtual_time_ms": int(run["virtual_time_ms"]),
                "source_sequence": int(run["source_sequence"]),
            }
            current_projection = self._review.projection(
                connection,
                run_id=run_id,
                virtual_time_ms=int(run["virtual_time_ms"]),
                source_sequence=int(run["source_sequence"]),
            )
            selected_row = next(
                row for row in rows if str(row["event_id"]) == selected["event_id"]
            )
            selected_projection = ReviewRecorder.decode_event_projection(
                connection,
                event=selected_row,
            )
            drawing_document = None
            drawing_hash = selected_projection.get("drawing_document_hash")
            if isinstance(drawing_hash, str):
                drawing_row = connection.execute(
                    """
                    SELECT document_json FROM replay_review_drawing_document
                    WHERE run_id = ? AND document_hash = ?
                    """,
                    (run_id, drawing_hash),
                ).fetchone()
                if drawing_row is None:
                    raise TrainingRunError(
                        "REVIEW_DRAWING_UNAVAILABLE",
                        "review drawing content is missing",
                        status_code=503,
                    )
                drawing_document = json.loads(str(drawing_row["document_json"]))
            now_ms = self.base_store._validated_now_ms()
            existing_review = connection.execute(
                """
                SELECT session.review_id, cursor.cursor_revision
                FROM replay_review_session AS session
                JOIN replay_review_cursor AS cursor USING(review_id)
                WHERE session.run_id = ?
                ORDER BY session.updated_at_ms DESC, session.review_id DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            effective_review_id = (
                review_id
                if existing_review is None
                else str(existing_review["review_id"])
            )
            cursor_revision = (
                1
                if existing_review is None
                else int(existing_review["cursor_revision"]) + 1
            )
            if existing_review is None:
                connection.execute(
                    """
                    INSERT INTO replay_review_session(
                        review_id, run_id, event_id, checkpoint_id,
                        selected_state_hash, original_state_hash,
                        original_cursor_json, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        effective_review_id,
                        run_id,
                        selected["event_id"],
                        selected["checkpoint_id"],
                        selected["state_hash"],
                        run["state_hash"],
                        canonical_json(original_cursor),
                        now_ms,
                        now_ms,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO replay_review_cursor(
                        review_id, timeline_sequence, playback_state,
                        playback_rate, original_account_hash,
                        original_ledger_tail_hash, original_viewer_revision,
                        original_viewer_hash, cursor_revision, updated_at_ms
                    ) VALUES (?, ?, 'PAUSED', '1', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        effective_review_id,
                        selected["timeline_sequence"],
                        current_projection["account_hash"],
                        run["ledger_tail_hash"],
                        run["semantic_view_revision"],
                        current_projection["viewer_hash"],
                        cursor_revision,
                        now_ms,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE replay_review_session
                    SET event_id = ?, checkpoint_id = ?,
                        selected_state_hash = ?, original_state_hash = ?,
                        original_cursor_json = ?, updated_at_ms = ?
                    WHERE review_id = ? AND run_id = ?
                    """,
                    (
                        selected["event_id"],
                        selected["checkpoint_id"],
                        selected["state_hash"],
                        run["state_hash"],
                        canonical_json(original_cursor),
                        now_ms,
                        effective_review_id,
                        run_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE replay_review_cursor
                    SET timeline_sequence = ?, playback_state = 'PAUSED',
                        playback_rate = '1', original_account_hash = ?,
                        original_ledger_tail_hash = ?,
                        original_viewer_revision = ?, original_viewer_hash = ?,
                        cursor_revision = ?, updated_at_ms = ?
                    WHERE review_id = ?
                    """,
                    (
                        selected["timeline_sequence"],
                        current_projection["account_hash"],
                        run["ledger_tail_hash"],
                        run["semantic_view_revision"],
                        current_projection["viewer_hash"],
                        cursor_revision,
                        now_ms,
                        effective_review_id,
                    ),
                )
            connection.execute(
                """
                UPDATE replay_data_segment_ref
                SET active = 0, released_at_ms = ?
                WHERE run_id = ? AND owner_kind = 'REVIEW'
                  AND owner_id != ? AND active = 1
                """,
                (now_ms, run_id, effective_review_id),
            )
            connection.execute(
                """
                DELETE FROM replay_review_session
                WHERE run_id = ? AND review_id != ?
                """,
                (run_id, effective_review_id),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO replay_data_segment_ref(
                    segment_id, run_id, track_id, owner_kind, owner_id,
                    active, created_at_ms, released_at_ms
                )
                SELECT segment_id, run_id, track_id, 'REVIEW', ?, 1, ?, NULL
                FROM replay_data_segment_ref
                WHERE run_id = ? AND owner_kind = 'RUN_ARCHIVE'
                """,
                (effective_review_id, now_ms, run_id),
            )
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "schema_version": REVIEW_TIMELINE_SCHEMA_VERSION,
                "review_id": effective_review_id,
                "run_id": run_id,
                "read_only": True,
                "selected_event_id": selected["event_id"],
                "selected_timeline_sequence": selected["timeline_sequence"],
                "selected_state_hash": selected["state_hash"],
                "original_state_hash": str(run["state_hash"]),
                "original_cursor": original_cursor,
                "dataset_epoch": str(run["dataset_epoch"]),
                "cursor_revision": cursor_revision,
                "playback_state": "PAUSED",
                "playback_rate": "1",
                "projection": review_records_ops.public_review_projection(
                    selected_projection
                ),
                "drawing_document": drawing_document,
                "immutability_proof": {
                    "original_account_hash": current_projection["account_hash"],
                    "original_ledger_tail_hash": str(run["ledger_tail_hash"]),
                    "original_viewer_revision": int(run["semantic_view_revision"]),
                    "original_viewer_hash": current_projection["viewer_hash"],
                    "verified": True,
                },
                "budget": review_records_ops.review_budget(connection, run_id),
                "events": events,
                "jump_targets": [
                    {
                        "event_id": item["event_id"],
                        "event_type": item["event_type"],
                        "category": item["category"],
                    }
                    for item in events
                ],
            }

        return await self.base_store.run_extension_write(write)

    async def checkpoint_for_event(
        self,
        run_id: str,
        event_id: str,
    ) -> dict[str, object]:
        def read(
            connection: sqlite3.Connection,
        ) -> (
            tuple[
                sqlite3.Row,
                tuple[sqlite3.Row, ...],
                dict[str, object],
            ]
            | None
        ):
            event = connection.execute(
                """
                SELECT event.*, run.dataset_epoch, run.adapter_session_id
                FROM replay_review_timeline_event AS event
                JOIN replay_training_run AS run USING(run_id)
                WHERE event.run_id = ? AND event.event_id = ?
                """,
                (run_id, event_id),
            ).fetchone()
            if event is None:
                return None
            anchors = tuple(
                connection.execute(
                    """
                    SELECT link.track_id, anchor.*
                    FROM replay_review_event_anchor AS link
                    JOIN replay_review_actor_anchor AS anchor
                      ON anchor.run_id = link.run_id
                     AND anchor.anchor_id = link.anchor_id
                    WHERE link.run_id = ? AND link.timeline_sequence = ?
                    ORDER BY link.track_id
                    """,
                    (run_id, event["timeline_sequence"]),
                ).fetchall()
            )
            projection = ReviewRecorder.decode_event_projection(
                connection,
                event=event,
            )
            return event, anchors, projection

        result = await self.base_store.run_extension_read(read)
        if result is None:
            raise TrainingRunError(
                "REVIEW_EVENT_NOT_FOUND",
                "review event is not backed by immutable actor anchors",
                status_code=404,
            )
        row, anchors, projection = result
        if not anchors:
            raise TrainingRunError(
                "REVIEW_ANCHOR_UNAVAILABLE",
                "review event has no actor anchors",
                status_code=503,
            )
        decoded_payloads: dict[str, bytes] = {}
        for anchor in anchors:
            stored_payload = bytes(anchor["payload"])
            encoding = str(anchor["payload_encoding"])
            stored_bytes = int(anchor["stored_bytes"])
            if stored_bytes == 0 and encoding == ANCHOR_PAYLOAD_ENCODING_RAW:
                stored_bytes = len(stored_payload)
            try:
                decoded_payloads[str(anchor["anchor_id"])] = decode_anchor_payload(
                    stored_payload,
                    encoding=encoding,
                    raw_bytes=int(anchor["payload_bytes"]),
                    stored_bytes=stored_bytes,
                    raw_sha256=str(anchor["payload_sha256"]),
                )
            except (TypeError, ValueError) as exc:
                raise TrainingRunError(
                    "REVIEW_ANCHOR_CORRUPT",
                    "review event actor anchor failed integrity validation",
                    status_code=503,
                    details={
                        "anchor_id": str(anchor["anchor_id"]),
                        "track_id": str(anchor["track_id"]),
                    },
                ) from exc
        primary = next(
            (anchor for anchor in anchors if str(anchor["track_id"]) == "track-1"),
            anchors[0],
        )
        return {
            "run_id": run_id,
            "adapter_session_id": str(primary["adapter_session_id"]),
            "event_id": event_id,
            "timeline_sequence": int(row["timeline_sequence"]),
            "checkpoint_id": int(primary["checkpoint_id"]),
            "state_hash": str(row["state_hash"]),
            "primary_state_hash": str(primary["state_hash"]),
            "source_sequence": int(row["source_sequence"]),
            "event_sequence": int(row["event_sequence"]),
            "dataset_epoch": str(row["dataset_epoch"]),
            "anchor_set_hash": str(row["anchor_set_hash"]),
            "projection": projection,
            "anchors": [
                {
                    "track_id": str(anchor["track_id"]),
                    "anchor_id": str(anchor["anchor_id"]),
                    "adapter_session_id": str(anchor["adapter_session_id"]),
                    "checkpoint_id": int(anchor["checkpoint_id"]),
                    "state_hash": str(anchor["state_hash"]),
                    "source_sequence": int(anchor["source_sequence"]),
                    "event_sequence": int(anchor["event_sequence"]),
                    "virtual_time_ms": int(anchor["virtual_time_ms"]),
                    "dataset_epoch": str(anchor["dataset_epoch"]),
                    "payload": decoded_payloads[str(anchor["anchor_id"])],
                    "payload_sha256": str(anchor["payload_sha256"]),
                }
                for anchor in anchors
            ],
        }

    async def control_review(
        self,
        *,
        run_id: str,
        review_id: str,
        action: str,
        event_id: str | None,
        expected_cursor_revision: int,
        playback_rate: str | None,
    ) -> dict[str, object]:
        def write(connection: sqlite3.Connection) -> dict[str, object]:
            review = connection.execute(
                """
                SELECT session.*, cursor.timeline_sequence,
                       cursor.playback_state, cursor.playback_rate,
                       cursor.original_account_hash,
                       cursor.original_ledger_tail_hash,
                       cursor.original_viewer_revision,
                       cursor.original_viewer_hash,
                       cursor.cursor_revision,
                       run.virtual_time_ms, run.source_sequence,
                       run.dataset_epoch, actor.state_hash AS current_state_hash,
                       account.ledger_tail_hash,
                       viewer.semantic_view_revision
                FROM replay_review_session AS session
                JOIN replay_review_cursor AS cursor USING(review_id)
                JOIN replay_training_run AS run USING(run_id)
                JOIN replay_session AS actor
                  ON actor.session_id = run.adapter_session_id
                JOIN replay_training_contract_account AS account USING(run_id)
                JOIN replay_training_viewer_state AS viewer USING(run_id)
                WHERE session.review_id = ? AND session.run_id = ?
                """,
                (review_id, run_id),
            ).fetchone()
            if review is None:
                raise TrainingRunError(
                    "REVIEW_SESSION_NOT_FOUND",
                    "review session does not exist",
                    status_code=404,
                )
            if int(review["cursor_revision"]) != expected_cursor_revision:
                raise TrainingRunError(
                    "REVIEW_CURSOR_CONFLICT",
                    "review cursor revision does not match",
                    status_code=409,
                    details={
                        "expected": expected_cursor_revision,
                        "actual": int(review["cursor_revision"]),
                    },
                )
            original_cursor = json.loads(str(review["original_cursor_json"]))
            current_projection = self._review.projection(
                connection,
                run_id=run_id,
                virtual_time_ms=int(review["virtual_time_ms"]),
                source_sequence=int(review["source_sequence"]),
            )
            unchanged = (
                str(review["current_state_hash"]) == str(review["original_state_hash"])
                and int(review["virtual_time_ms"])
                == int(original_cursor["virtual_time_ms"])
                and int(review["source_sequence"])
                == int(original_cursor["source_sequence"])
                and str(current_projection["account_hash"])
                == str(review["original_account_hash"])
                and str(review["ledger_tail_hash"])
                == str(review["original_ledger_tail_hash"])
                and int(review["semantic_view_revision"])
                == int(review["original_viewer_revision"])
                and str(current_projection["viewer_hash"])
                == str(review["original_viewer_hash"])
            )
            if not unchanged:
                raise TrainingRunError(
                    "REVIEW_ORIGINAL_RUN_CHANGED",
                    "original run changed while ReviewMode was active",
                    status_code=409,
                    details={"review_mutated_original": False},
                )
            current_sequence = int(review["timeline_sequence"])
            target_sequence = current_sequence
            state = str(review["playback_state"])
            rate = str(review["playback_rate"])
            if action == "JUMP":
                target = connection.execute(
                    """
                    SELECT timeline_sequence
                    FROM replay_review_timeline_event
                    WHERE run_id = ? AND event_id = ?
                    """,
                    (run_id, event_id),
                ).fetchone()
                if target is None:
                    raise TrainingRunError(
                        "REVIEW_EVENT_NOT_FOUND",
                        "review event is not in the immutable timeline",
                        status_code=404,
                    )
                target_sequence = int(target["timeline_sequence"])
                state = "PAUSED"
            elif action in {"NEXT", "PREVIOUS"}:
                operator = ">" if action == "NEXT" else "<"
                direction = "ASC" if action == "NEXT" else "DESC"
                target = connection.execute(
                    f"""
                    SELECT timeline_sequence
                    FROM replay_review_timeline_event
                    WHERE run_id = ? AND timeline_sequence {operator} ?
                    ORDER BY timeline_sequence {direction} LIMIT 1
                    """,
                    (run_id, current_sequence),
                ).fetchone()
                if target is not None:
                    target_sequence = int(target["timeline_sequence"])
                state = (
                    "PLAYING"
                    if action == "NEXT" and state == "PLAYING" and target is not None
                    else "PAUSED"
                )
            elif action == "PLAY":
                if playback_rate not in {"0.25", "0.5", "1", "2", "4", "8"}:
                    raise TrainingRunError(
                        "REVIEW_CONTROL_INVALID",
                        "review playback rate is unsupported",
                        status_code=422,
                    )
                state = "PLAYING"
                rate = str(playback_rate)
            elif action == "PAUSE":
                state = "PAUSED"
            else:
                raise TrainingRunError(
                    "REVIEW_CONTROL_INVALID",
                    "review control action is unsupported",
                    status_code=422,
                )
            selected = connection.execute(
                """
                SELECT * FROM replay_review_timeline_event
                WHERE run_id = ? AND timeline_sequence = ?
                """,
                (run_id, target_sequence),
            ).fetchone()
            if selected is None:
                raise TypeError("review cursor target is missing")
            next_revision = int(review["cursor_revision"]) + 1
            now_ms = self.base_store._validated_now_ms()
            connection.execute(
                """
                UPDATE replay_review_cursor
                SET timeline_sequence = ?, playback_state = ?,
                    playback_rate = ?, cursor_revision = ?, updated_at_ms = ?
                WHERE review_id = ?
                """,
                (
                    target_sequence,
                    state,
                    rate,
                    next_revision,
                    now_ms,
                    review_id,
                ),
            )
            connection.execute(
                """
                UPDATE replay_review_session
                SET event_id = ?, selected_state_hash = ?, updated_at_ms = ?
                WHERE review_id = ?
                """,
                (
                    selected["event_id"],
                    selected["state_hash"],
                    now_ms,
                    review_id,
                ),
            )
            projection = ReviewRecorder.decode_event_projection(
                connection,
                event=selected,
            )
            drawing = None
            drawing_hash = projection.get("drawing_document_hash")
            if isinstance(drawing_hash, str):
                row = connection.execute(
                    """
                    SELECT document_json FROM replay_review_drawing_document
                    WHERE run_id = ? AND document_hash = ?
                    """,
                    (run_id, drawing_hash),
                ).fetchone()
                if row is None:
                    raise TypeError("review drawing document is missing")
                drawing = json.loads(str(row["document_json"]))
            return {
                "protocol": REPLAY_V2_PROTOCOL,
                "schema_version": REVIEW_TIMELINE_SCHEMA_VERSION,
                "review_id": review_id,
                "run_id": run_id,
                "read_only": True,
                "selected_event_id": str(selected["event_id"]),
                "selected_timeline_sequence": target_sequence,
                "selected_state_hash": str(selected["state_hash"]),
                "original_state_hash": str(review["original_state_hash"]),
                "cursor_revision": next_revision,
                "playback_state": state,
                "playback_rate": rate,
                "selected_event": {
                    "event_id": str(selected["event_id"]),
                    "event_type": str(selected["event_type"]),
                    "category": str(selected["category"]),
                    "timeline_sequence": int(selected["timeline_sequence"]),
                    "public_time": json.loads(str(selected["public_time_json"])),
                    "detail": review_records_ops.review_event_detail(
                        connection, selected
                    ),
                },
                "projection": review_records_ops.public_review_projection(projection),
                "drawing_document": drawing,
                "immutability_proof": {
                    "original_account_hash": str(review["original_account_hash"]),
                    "original_ledger_tail_hash": str(
                        review["original_ledger_tail_hash"]
                    ),
                    "original_viewer_revision": int(review["original_viewer_revision"]),
                    "original_viewer_hash": str(review["original_viewer_hash"]),
                    "verified": True,
                },
                "budget": review_records_ops.review_budget(connection, run_id),
            }

        return await self.base_store.run_extension_write(write)

    async def get_viewer_state(self, run_id: str) -> ViewerState:
        def read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return connection.execute(
                """
                SELECT * FROM replay_training_viewer_state WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

        row = await self.base_store.run_extension_read(read)
        if row is None:
            raise TrainingRunError(
                "TRAINING_RUN_NOT_FOUND",
                "training viewer state does not exist",
                status_code=404,
            )
        return run_records_ops.viewer_from_row(row)

    async def viewer_state_at_revision(
        self,
        run_id: str,
        revision: int,
    ) -> ViewerState:
        def read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return connection.execute(
                """
                SELECT viewer_state_json
                FROM replay_training_viewer_event
                WHERE run_id = ? AND semantic_view_revision = ?
                """,
                (run_id, revision),
            ).fetchone()

        row = await self.base_store.run_extension_read(read)
        if row is None:
            raise TrainingRunError(
                "VIEWER_REVISION_CONFLICT",
                "viewer revision is unavailable",
                status_code=409,
                details={"semantic_view_revision": revision},
            )
        return ViewerState.from_dict(json.loads(str(row["viewer_state_json"])))

    async def set_display_interval(
        self,
        *,
        run_id: str,
        display_interval: str,
        expected_revision: int,
        command_id: str,
        command: Mapping[str, object],
    ) -> ViewerState:
        request_json = canonical_json(command)

        def write(connection: sqlite3.Connection) -> ViewerState:
            replayed = connection.execute(
                """
                SELECT request_json, viewer_state_json
                FROM replay_training_viewer_event
                WHERE run_id = ? AND command_id = ?
                """,
                (run_id, command_id),
            ).fetchone()
            if replayed is not None:
                if str(replayed["request_json"]) != request_json:
                    raise TrainingRunError(
                        "COMMAND_ID_REUSED",
                        "command_id was reused with a different viewer command",
                        status_code=409,
                    )
                return ViewerState.from_dict(
                    json.loads(str(replayed["viewer_state_json"]))
                )
            row = connection.execute(
                "SELECT * FROM replay_training_viewer_state WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise TrainingRunError(
                    "TRAINING_RUN_NOT_FOUND",
                    "training viewer state does not exist",
                    status_code=404,
                )
            current = run_records_ops.viewer_from_row(row)
            if current.semantic_view_revision != expected_revision:
                raise TrainingRunError(
                    "VIEWER_REVISION_CONFLICT",
                    "viewer state revision does not match",
                    status_code=409,
                    details={
                        "expected": expected_revision,
                        "actual": current.semantic_view_revision,
                    },
                )
            updated = ViewerState(
                run_id=current.run_id,
                selected_track_id=current.selected_track_id,
                display_interval=display_interval,
                chart_type=current.chart_type,
                visible_range=current.visible_range,
                pane_layout=current.pane_layout,
                rail_layout=current.rail_layout,
                semantic_view_revision=current.semantic_view_revision + 1,
            )
            now_ms = self.base_store._validated_now_ms()
            payload_json = canonical_json(updated.to_dict())
            connection.execute(
                """
                UPDATE replay_training_viewer_state
                SET display_interval = ?, semantic_view_revision = ?, updated_at_ms = ?
                WHERE run_id = ?
                """,
                (
                    updated.display_interval,
                    updated.semantic_view_revision,
                    now_ms,
                    run_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO replay_training_viewer_event(
                    run_id, semantic_view_revision, command_id, event_type,
                    request_json, viewer_state_json, created_at_ms
                ) VALUES (?, ?, ?, 'SET_DISPLAY_INTERVAL', ?, ?, ?)
                """,
                (
                    run_id,
                    updated.semantic_view_revision,
                    command_id,
                    request_json,
                    payload_json,
                    now_ms,
                ),
            )
            run = connection.execute(
                "SELECT adapter_session_id FROM replay_training_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise TypeError("viewer run is missing")
            self._review.append(
                connection,
                run_id=run_id,
                session_id=str(run["adapter_session_id"]),
                context={
                    "kind": "DIRECT",
                    "category": "VIEWER",
                    "event_type": "SET_DISPLAY_INTERVAL",
                    "command_id": command_id,
                },
                state=None,
                checkpoint=None,
                now_ms=now_ms,
            )
            return updated

        return await self.base_store.run_extension_write(write)

    async def indexed_review_minimum(self, run_id, mark):
        def read(connection):
            prior = self._review._minimum_prior_equity(connection, run_id=run_id)
            row = connection.execute(
                "SELECT t.position_json,t.account_json,r.initial_equity,a.overlay_cash FROM replay_training_market_track t "
                "JOIN replay_training_run r USING(run_id) JOIN replay_training_contract_account a USING(run_id) "
                "WHERE t.run_id=? AND t.track_id='track-1'",
                (run_id,),
            ).fetchone()
            position = json.loads(row["position_json"])
            rule_row = connection.execute(
                "SELECT rule_json FROM replay_training_instrument_rule WHERE run_id=? AND track_id='track-1' ORDER BY revision DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            rule = account_math_ops._stored_instrument_rule(rule_row["rule_json"])
            pnl = Decimal(0)
            for side in ("long", "short"):
                leg = position[side]
                quantity = abs(Decimal(leg["quantity"]))
                if quantity:
                    entry = Decimal(leg["entry_price"])
                    pnl += (
                        ((mark - entry) if side == "long" else (entry - mark))
                        * quantity
                        * Decimal(rule.contract_size)
                    )
            initial, overlay = (
                Decimal(row["initial_equity"]),
                Decimal(row["overlay_cash"]),
            )
            cash = Decimal(json.loads(row["account_json"])["cash_balance"])
            equity = (initial + overlay) + (cash + pnl + overlay - initial)
            return prior is None or equity < prior

        return await self.base_store.run_extension_read(read)
