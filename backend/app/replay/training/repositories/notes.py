"""Versioned text annotations in the existing replay SQLite transaction owner.

Annotation writes never call the account reducer, move a cursor, or append an
actor journal entry. A saved request context is also its uncertain-reply retry
identity: a retry cannot silently move a plan to a later virtual time.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from app.replay.storage.sqlite_store import ReplaySQLiteStore
from app.trading_accounts.models import TradingAccountError, normalize_fields

from ..errors import TrainingRunError
from ..models import REPLAY_V2_PROTOCOL
from ..review_lifecycle import event_clock
from . import note_links, note_captures

MAX_NOTES = 500
MAX_VERSIONS = 100
MAX_TEXT_BYTES = 65_536
MAX_RUN_BYTES = 8 * 1024 * 1024


def _error(code: str, message: str, status: int = 409) -> TrainingRunError:
    return TrainingRunError(code, message, status_code=status)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _context(connection: sqlite3.Connection, run_id: str, track_id: str) -> dict[str, object]:
    run = connection.execute(
        "SELECT revision,source_sequence,virtual_time_ms FROM replay_training_run WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if run is None:
        raise _error("TRAINING_RUN_NOT_FOUND", "Training run does not exist", 404)
    track = connection.execute(
        "SELECT dataset_epoch,adapter_session_id FROM replay_training_market_track WHERE run_id=? AND track_id=?",
        (run_id, track_id),
    ).fetchone()
    if track is None:
        raise _error("MARKET_TRACK_NOT_FOUND", "Market track does not belong to this run", 404)
    if track["dataset_epoch"] is None or track["adapter_session_id"] is None or run["virtual_time_ms"] is None:
        raise _error("MARKET_TRACK_NOT_PREPARED", "Prepare the track before writing annotations")
    checkpoint = connection.execute(
        "SELECT checkpoint_sequence FROM replay_training_global_checkpoint "
        "WHERE run_id=? ORDER BY checkpoint_sequence DESC LIMIT 1", (run_id,),
    ).fetchone()
    timeline_sequence = connection.execute(
        "SELECT COALESCE(MAX(timeline_sequence),0) FROM replay_review_timeline_event WHERE run_id=?", (run_id,),
    ).fetchone()[0]
    context = {
        "runId": run_id, "trackId": track_id, "dataEpoch": str(track["dataset_epoch"]),
        "runRevision": int(run["revision"]), "sourceSequence": int(run["source_sequence"]),
        "checkpointSequence": 0 if checkpoint is None else int(checkpoint["checkpoint_sequence"]),
        # Ordered checkpoints update this run clock in their own transaction;
        # later direct adapter advances may legitimately outlive that checkpoint.
        "virtualTimeMs": int(run["virtual_time_ms"]),
        "reviewId": None, "reviewRevision": None, "reviewNote": False,
        "timelineSequence": int(timeline_sequence),
    }
    review = connection.execute(
        "SELECT s.review_id,c.cursor_revision,e.* FROM replay_review_session s "
        "JOIN replay_review_cursor c USING(review_id) "
        "JOIN replay_review_timeline_event e ON e.run_id=s.run_id AND e.timeline_sequence=c.timeline_sequence "
        "WHERE s.run_id=? ORDER BY s.updated_at_ms DESC,s.review_id DESC LIMIT 1", (run_id,),
    ).fetchone()
    if review is not None:
        effective = event_clock(connection, review, strict=True)
        context.update(reviewId=str(review["review_id"]), reviewRevision=int(review["cursor_revision"]),
                       virtualTimeMs=int(effective["virtual_time_ms"]), reviewNote=True,
                       timelineSequence=int(review["timeline_sequence"]))
    else:
        visited = connection.execute(
            "SELECT virtual_time_ms FROM replay_review_timeline_event WHERE run_id=? "
            "ORDER BY virtual_time_ms DESC LIMIT 1", (run_id,),
        ).fetchone()
        if visited is not None and int(visited["virtual_time_ms"]) > context["virtualTimeMs"]:
            context["reviewNote"] = True
    return context


def _view(connection: sqlite3.Connection, note: sqlite3.Row, revision: sqlite3.Row) -> dict[str, object]:
    try:
        fields = normalize_fields(json.loads(revision["fields_json"]))
    except (ValueError, TypeError, TradingAccountError):
        raise _error("REPLAY_NOTE_CORRUPT", "Annotation text version is unavailable", 503) from None
    links = note_links.load(connection, str(note["run_id"]), str(note["note_id"]), int(revision["revision"]))
    if any(link["eventTimeMs"] > int(revision["virtual_time_ms"]) for link in links):
        raise _error("REPLAY_NOTE_LINK_CORRUPT", "Annotation reference crosses its version time", 503)
    return {
        "id": str(note["note_id"]), "runId": str(note["run_id"]), "trackId": str(note["track_id"]),
        "marketTimeMs": int(note["market_time_ms"]), "createdAtMs": int(note["created_at_ms"]),
        "updatedAtMs": int(revision["saved_at_ms"]), "effectiveTimeMs": int(revision["virtual_time_ms"]),
        "revisionCount": int(revision["revision"]), "fields": fields, "body": "",
        "timelineSequence": int(revision["timeline_sequence"]),
        "reviewNote": bool(note["review_note"]), "revisions": [],
        "links": links,
        "screenshots": note_captures.load_version(connection, note, revision, fields),
    }


class TrainingNoteRepository:
    def __init__(self, base_store: ReplaySQLiteStore) -> None:
        self.base_store = base_store
        self.captures = note_captures.TrainingNoteCaptureRepository(base_store, _context)

    async def notes(self, run_id: str, track_id: str, *, at_time_ms: int | None = None) -> dict[str, object]:
        def read(connection: sqlite3.Connection):
            context = _context(connection, run_id, track_id)
            cutoff = context["virtualTimeMs"] if at_time_ms is None else at_time_ms
            if type(cutoff) is not int or not 0 <= cutoff <= context["virtualTimeMs"]:
                raise _error("REPLAY_NOTE_TIME_INVALID", "Annotation query exceeds the current view time", 422)
            rows = connection.execute(
                "SELECT * FROM replay_training_note WHERE run_id=? AND track_id=? AND market_time_ms<=? AND timeline_sequence<=? "
                "ORDER BY market_time_ms,created_at_ms,note_id LIMIT ?", (run_id, track_id, cutoff, context["timelineSequence"], MAX_NOTES),
            ).fetchall()
            notes = []
            for note in rows:
                revision = connection.execute(
                    "SELECT * FROM replay_training_note_revision WHERE run_id=? AND note_id=? AND virtual_time_ms<=? AND timeline_sequence<=? "
                    "ORDER BY revision DESC LIMIT 1", (run_id, note["note_id"], cutoff, context["timelineSequence"]),
                ).fetchone()
                if revision is None:
                    raise _error("REPLAY_NOTE_CORRUPT", "Annotation historical version is unavailable", 503)
                notes.append(_view(connection, note, revision))
            return {"protocol": REPLAY_V2_PROTOCOL, "schema_version": "replay.notes.v1",
                    "run_id": run_id, "track_id": track_id, "context": context, "asOfMs": cutoff, "notes": notes}
        return await self.base_store.run_extension_read(read)

    async def link_options(self, run_id: str, track_id: str, *, kind: str,
                           before_id: str | None = None, limit: int = 20) -> dict[str, object]:
        def read(connection: sqlite3.Connection):
            context = _context(connection, run_id, track_id)
            return note_links.options(connection, context, kind=kind, before_id=before_id, limit=limit)
        return await self.base_store.run_extension_read(read)

    async def note_versions(self, run_id: str, track_id: str, note_id: str, *,
                            at_time_ms: int | None = None, before_revision: int | None = None,
                            limit: int = 20) -> dict[str, object]:
        if type(limit) is not int or not 1 <= limit <= 20 or (before_revision is not None
                and (type(before_revision) is not int or not 1 <= before_revision <= MAX_VERSIONS + 1)):
            raise _error("REPLAY_NOTE_PAGE_INVALID", "Invalid annotation version page", 422)

        def read(connection: sqlite3.Connection):
            context = _context(connection, run_id, track_id)
            cutoff = context["virtualTimeMs"] if at_time_ms is None else at_time_ms
            if type(cutoff) is not int or not 0 <= cutoff <= context["virtualTimeMs"]:
                raise _error("REPLAY_NOTE_TIME_INVALID", "Annotation query exceeds the current view time", 422)
            note = connection.execute(
                "SELECT * FROM replay_training_note WHERE run_id=? AND track_id=? AND note_id=? "
                "AND market_time_ms<=? AND timeline_sequence<=?",
                (run_id, track_id, note_id, cutoff, context["timelineSequence"]),
            ).fetchone()
            if note is None:
                raise _error("REPLAY_NOTE_NOT_FOUND", "Annotation is not visible in this view", 404)
            allowed = (run_id, note_id, cutoff, context["timelineSequence"])
            where = "run_id=? AND note_id=? AND virtual_time_ms<=? AND timeline_sequence<=?"
            if connection.execute("SELECT 1 FROM replay_training_note_revision WHERE " + where + " LIMIT 1", allowed).fetchone() is None:
                raise _error("REPLAY_NOTE_CORRUPT", "Annotation historical version is unavailable", 503)
            rows = connection.execute("SELECT * FROM replay_training_note_revision WHERE " + where
                + " AND revision<? ORDER BY revision DESC LIMIT ?",
                (*allowed, MAX_VERSIONS + 1 if before_revision is None else before_revision, limit + 1),
            ).fetchall()
            versions = [_view(connection, note, row) for row in rows[:limit]]
            return {"protocol": REPLAY_V2_PROTOCOL, "schema_version": "replay.note-versions.v1",
                "run_id": run_id, "track_id": track_id, "note_id": note_id, "context": context,
                "asOfMs": cutoff, "versions": versions,
                "nextBeforeRevision": versions[-1]["revisionCount"] if len(rows) > limit else None}
        return await self.base_store.run_extension_read(read)

    async def save_note(self, run_id: str, track_id: str, *, note_id: str, fields: dict[str, str],
                        expected_revision: int, context: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(note_id, str) or not 1 <= len(note_id) <= 128:
            raise _error("REPLAY_NOTE_INVALID", "Invalid annotation id", 422)
        if type(expected_revision) is not int or not 0 <= expected_revision < MAX_VERSIONS:
            raise _error("REPLAY_NOTE_INVALID", "Annotation version limit reached", 422)
        try:
            fields_json = _json(normalize_fields(fields))
            context_json = _json(dict(context))
        except (ValueError, TypeError, TradingAccountError):
            raise _error("REPLAY_NOTE_INVALID", "Invalid annotation text or context", 422) from None
        if len(fields_json.encode("utf-8")) > MAX_TEXT_BYTES or len(context_json.encode("utf-8")) > 4096:
            raise _error("REPLAY_NOTE_INVALID", "Annotation text or context is too large", 422)

        def write(connection: sqlite3.Connection):
            note = connection.execute("SELECT * FROM replay_training_note WHERE run_id=? AND note_id=?",
                                      (run_id, note_id)).fetchone()
            if note is not None and note["track_id"] != track_id:
                raise _error("REPLAY_NOTE_CONFLICT", "Annotation belongs to another track")
            saved = connection.execute(
                "SELECT * FROM replay_training_note_revision WHERE run_id=? AND note_id=? AND revision=?",
                (run_id, note_id, expected_revision + 1),
            ).fetchone()
            if saved is not None:
                if saved["fields_json"] != fields_json or saved["context_json"] != context_json:
                    raise _error("REPLAY_NOTE_CONFLICT", "Annotation changed in another editor")
                # Return this exact version, never a newer text or save time.
                return _view(connection, note, saved)
            current = _context(connection, run_id, track_id)
            if context_json != _json(current):
                raise _error("REPLAY_NOTE_CONTEXT_CHANGED", "Replay view changed; retain the draft and reload its context")
            latest = connection.execute(
                "SELECT revision,virtual_time_ms FROM replay_training_note_revision WHERE run_id=? AND note_id=? "
                "ORDER BY revision DESC LIMIT 1", (run_id, note_id),
            ).fetchone()
            if (0 if latest is None else int(latest["revision"])) != expected_revision:
                raise _error("REPLAY_NOTE_CONFLICT", "Annotation changed in another editor")
            if latest is not None and (int(latest["virtual_time_ms"]) > current["virtualTimeMs"]
                                       or (current["reviewNote"] and not note["review_note"])):
                raise _error("REPLAY_NOTE_REVIEW_REQUIRED", "Create a review supplement instead of rewriting an original plan")
            image_ids = note_captures.freeze(connection, current, fields)
            links_json = _json(note_links.freeze(connection, current, fields))
            links_bytes = len(links_json.encode("utf-8"))
            stored_bytes = len(fields_json.encode("utf-8")) + len(context_json.encode("utf-8"))
            used = connection.execute(
                "SELECT (SELECT COALESCE(SUM(stored_bytes),0) FROM replay_training_note_revision WHERE run_id=?) "
                "+ (SELECT COALESCE(SUM(stored_bytes),0) FROM replay_training_note_links WHERE run_id=?)", (run_id, run_id),
            ).fetchone()[0]
            if used + stored_bytes + links_bytes > MAX_RUN_BYTES:
                raise _error("REPLAY_NOTE_BUDGET_EXCEEDED", "This run has reached its annotation storage budget")
            now = self.base_store._validated_now_ms()
            if note is None:
                count = connection.execute("SELECT COUNT(*) FROM replay_training_note WHERE run_id=?", (run_id,)).fetchone()[0]
                if count >= MAX_NOTES:
                    raise _error("REPLAY_NOTE_BUDGET_EXCEEDED", "This run has reached its annotation count limit")
                connection.execute("INSERT INTO replay_training_note VALUES(?,?,?,?,?,?,?)",
                                   (run_id, note_id, track_id, current["virtualTimeMs"], now, int(current["reviewNote"]), current["timelineSequence"]))
                note = connection.execute("SELECT * FROM replay_training_note WHERE run_id=? AND note_id=?",
                                          (run_id, note_id)).fetchone()
            connection.execute("INSERT INTO replay_training_note_revision VALUES(?,?,?,?,?,?,?,?,?)",
                               (run_id, note_id, expected_revision + 1, current["virtualTimeMs"], now,
                                fields_json, context_json, stored_bytes, current["timelineSequence"]))
            connection.execute("INSERT INTO replay_training_note_links VALUES(?,?,?,?,?)",
                               (run_id, note_id, expected_revision + 1, links_json, links_bytes))
            connection.executemany("INSERT INTO replay_training_note_capture_link VALUES(?,?,?,?)",
                                   [(run_id, note_id, expected_revision + 1, identifier) for identifier in image_ids])
            revision = connection.execute("SELECT * FROM replay_training_note_revision WHERE run_id=? AND note_id=? AND revision=?",
                                          (run_id, note_id, expected_revision + 1)).fetchone()
            return _view(connection, note, revision)
        return await self.base_store.run_extension_write(write)
