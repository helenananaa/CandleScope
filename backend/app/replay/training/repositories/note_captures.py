"""Bounded immutable PNGs owned by replay annotations and their exact versions."""
from __future__ import annotations

import base64
import binascii
import json
import sqlite3
import struct
from collections.abc import Callable, Mapping

from app.replay.storage.sqlite_store import ReplaySQLiteStore
from ..errors import TrainingRunError
from .note_visibility import original_note_timeline

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_RUN_BYTES = 16 * 1024 * 1024
MAX_CAPTURES = 128
MAX_VERSION_IMAGES = 2
IMAGE_FIELD = "replayScreenshotIds"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
META_COLUMNS = ("run_id", "capture_id", "track_id", "dataset_epoch", "virtual_time_ms", "timeline_sequence",
                "captured_context_json", "chart_json", "saved_at_ms", "width", "height")


def _error(code: str, message: str, status: int = 422) -> TrainingRunError:
    return TrainingRunError(code, message, status_code=status)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _columns(alias: str = "") -> str:
    return ",".join((alias + "." if alias else "") + name for name in META_COLUMNS)


def _context_valid(value: Mapping[str, object]) -> bool:
    if not isinstance(value, Mapping):
        return False
    strings = ["runId", "trackId", "dataEpoch"]
    counters = ["runRevision", "sourceSequence", "checkpointSequence", "timelineSequence", "virtualTimeMs"]
    if set(value) != set(strings + counters + ["reviewId", "reviewRevision", "reviewNote"]):
        return False
    return (all(isinstance(value[key], str) and 1 <= len(value[key]) <= 128 for key in strings)
        and all(type(value[key]) is int and 0 <= value[key] <= 253_402_300_799_999 for key in counters)
        and type(value["reviewNote"]) is bool
        and ((value["reviewId"] is None and value["reviewRevision"] is None)
            or (isinstance(value["reviewId"], str) and 1 <= len(value["reviewId"]) <= 128
                and type(value["reviewRevision"]) is int and value["reviewRevision"] >= 1 and value["reviewNote"])))


def _chart_valid(chart: Mapping[str, object]) -> bool:
    return (isinstance(chart, Mapping) and set(chart) == {"interval", "chartType", "seriesKey", "sourceVersion"}
        and all(isinstance(chart[key], str) and 1 <= len(chart[key]) <= maximum
                for key, maximum in [("interval", 32), ("chartType", 32), ("seriesKey", 1024)])
        and type(chart["sourceVersion"]) is int and 0 <= chart["sourceVersion"] <= 9_007_199_254_740_991)


def _png_info(image: bytes) -> tuple[int, int]:
    if (not image.startswith(PNG_SIGNATURE) or len(image) < 45 or len(image) > MAX_IMAGE_BYTES
            or image[8:16] != b"\x00\x00\x00\rIHDR" or image[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82"):
        raise _error("REPLAY_NOTE_CAPTURE_INVALID", "Expected a bounded PNG image")
    width, height = struct.unpack(">II", image[16:24])
    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise _error("REPLAY_NOTE_CAPTURE_INVALID", "PNG dimensions exceed the capture budget")
    return width, height


def _bounds(row: sqlite3.Row, context: Mapping[str, object]) -> bool:
    return (row["run_id"] == context["runId"] and row["track_id"] == context["trackId"]
        and row["dataset_epoch"] == context["dataEpoch"] and row["virtual_time_ms"] <= context["virtualTimeMs"]
        and row["timeline_sequence"] <= context["timelineSequence"])


def _visible_in_view(row: sqlite3.Row, context: Mapping[str, object]) -> bool:
    if not _bounds(row, context):
        return False
    if row["timeline_sequence"] <= original_note_timeline(context):
        return True
    try:
        return json.loads(row["captured_context_json"])["reviewNote"] is True
    except (TypeError, ValueError, KeyError):
        raise _error("REPLAY_NOTE_CAPTURE_CORRUPT", "Capture metadata is unavailable", 503) from None


def _view(row: sqlite3.Row) -> dict[str, object]:
    try:
        chart = json.loads(row["chart_json"])
        captured = json.loads(row["captured_context_json"])
        if (not isinstance(chart, dict) or not _chart_valid(chart) or not isinstance(captured, dict)
                or not _context_valid(captured) or not _bounds(row, captured)
                or row["virtual_time_ms"] != captured["virtualTimeMs"] or row["timeline_sequence"] != captured["timelineSequence"]
                or not 1 <= row["width"] <= 4096 or not 1 <= row["height"] <= 4096):
            raise ValueError
    except (TypeError, ValueError, KeyError):
        raise _error("REPLAY_NOTE_CAPTURE_CORRUPT", "Capture metadata is unavailable", 503) from None
    return {"id": str(row["capture_id"]), "runId": str(row["run_id"]), "trackId": str(row["track_id"]),
        "dataEpoch": str(row["dataset_epoch"]), "marketTimeMs": int(row["virtual_time_ms"]),
        "timelineSequence": int(row["timeline_sequence"]), "savedAtMs": int(row["saved_at_ms"]),
        "width": int(row["width"]), "height": int(row["height"]), "interval": chart["interval"], "chartType": chart["chartType"]}


def selected(fields: Mapping[str, str]) -> list[str]:
    try:
        value = json.loads(fields.get(IMAGE_FIELD, "[]"))
        if not isinstance(value, list) or len(value) > MAX_VERSION_IMAGES or any(
                not isinstance(identifier, str) or not 1 <= len(identifier) <= 128 for identifier in value) or len(set(value)) != len(value):
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise _error("REPLAY_NOTE_CAPTURE_INVALID", "Invalid version capture selection") from None


def freeze(connection: sqlite3.Connection, context: Mapping[str, object], fields: Mapping[str, str]) -> list[str]:
    if fields.get("replayPendingCaptureId"):
        raise _error("REPLAY_NOTE_CAPTURE_PENDING", "Resolve or explicitly discard the pending capture before saving")
    identifiers = selected(fields)
    for identifier in identifiers:
        row = connection.execute("SELECT " + _columns() + " FROM replay_training_note_capture WHERE run_id=? AND capture_id=?",
                                 (context["runId"], identifier)).fetchone()
        if row is None or not _visible_in_view(row, context):
            raise _error("REPLAY_NOTE_CAPTURE_INVALID", "Capture is not visible in this run, track, dataset and event")
        _view(row)
    return identifiers


def load_version(connection: sqlite3.Connection, note: sqlite3.Row, revision: sqlite3.Row,
                 fields: Mapping[str, str]) -> list[dict[str, object]]:
    try:
        identifiers = selected(fields)
        if not identifiers:
            return []
        context = json.loads(revision["context_json"])
        rows = connection.execute("SELECT " + _columns("c") + " FROM replay_training_note_capture_link AS l "
            "JOIN replay_training_note_capture AS c ON c.run_id=l.run_id AND c.capture_id=l.capture_id "
            "WHERE l.run_id=? AND l.note_id=? AND l.revision=?", (note["run_id"], note["note_id"], revision["revision"])).fetchall()
        by_id = {row["capture_id"]: row for row in rows}
        if set(by_id) != set(identifiers) or any(not _bounds(row, context) for row in rows):
            raise ValueError
        return [_view(by_id[identifier]) for identifier in identifiers]
    except (TrainingRunError, TypeError, ValueError, KeyError):
        raise _error("REPLAY_NOTE_CAPTURE_CORRUPT", "Version capture binding is unavailable", 503) from None


class TrainingNoteCaptureRepository:
    def __init__(self, base_store: ReplaySQLiteStore, context: Callable) -> None:
        self.base_store, self.context = base_store, context

    async def save(self, run_id: str, track_id: str, *, capture_id: str, image: str,
                   context: Mapping[str, object], captured_context: Mapping[str, object],
                   chart: Mapping[str, object]) -> dict[str, object]:
        if (not isinstance(capture_id, str) or not 1 <= len(capture_id) <= 128 or not isinstance(image, str)
                or len(image) > 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 22 or not image.startswith("data:image/png;base64,")
                or not _context_valid(context) or not _context_valid(captured_context) or not _chart_valid(chart)):
            raise _error("REPLAY_NOTE_CAPTURE_INVALID", "Invalid capture request")
        try:
            image_bytes = base64.b64decode(image[22:], validate=True)
        except (ValueError, binascii.Error):
            raise _error("REPLAY_NOTE_CAPTURE_INVALID", "Invalid PNG encoding") from None
        width, height = _png_info(image_bytes)
        context_json, captured_json, chart_json = _json(dict(context)), _json(dict(captured_context)), _json(dict(chart))
        if max(len(context_json.encode()), len(captured_json.encode()), len(chart_json.encode())) > 4096:
            raise _error("REPLAY_NOTE_CAPTURE_INVALID", "Capture metadata exceeds its budget")

        def write(connection: sqlite3.Connection):
            existing = connection.execute("SELECT * FROM replay_training_note_capture WHERE run_id=? AND capture_id=?",
                                          (run_id, capture_id)).fetchone()
            if existing is not None:
                if (existing["track_id"] != track_id or existing["request_context_json"] != context_json
                        or existing["captured_context_json"] != captured_json or existing["chart_json"] != chart_json
                        or bytes(existing["image_png"]) != image_bytes):
                    raise _error("REPLAY_NOTE_CAPTURE_CONFLICT", "Capture id belongs to a different submission", 409)
                return {"protocol": "replay.v3", "schema_version": "replay.note-capture.v1", "context": dict(context), "capture": _view(existing)}
            current = self.context(connection, run_id, track_id)
            if context_json != _json(current):
                raise _error("REPLAY_NOTE_CONTEXT_CHANGED", "Replay context changed; retain the capture request", 409)
            if (any(captured_context[key] != current[key] for key in ["runId", "trackId", "dataEpoch"])
                    or captured_context["virtualTimeMs"] > current["virtualTimeMs"]
                    or captured_context["timelineSequence"] > current["timelineSequence"]):
                raise _error("REPLAY_NOTE_CAPTURE_INVALID", "Capture exceeds this view boundary")
            count, used = connection.execute("SELECT COUNT(*),COALESCE(SUM(stored_bytes),0) FROM replay_training_note_capture WHERE run_id=?",
                                             (run_id,)).fetchone()
            size = len(image_bytes) + len(context_json.encode()) + len(captured_json.encode()) + len(chart_json.encode())
            if count >= MAX_CAPTURES or used + size > MAX_RUN_BYTES:
                raise _error("REPLAY_NOTE_CAPTURE_BUDGET_EXCEEDED", "Run capture budget reached", 409)
            connection.execute("INSERT INTO replay_training_note_capture VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, capture_id, track_id, current["dataEpoch"], captured_context["virtualTimeMs"], captured_context["timelineSequence"],
                 context_json, captured_json, chart_json, self.base_store._validated_now_ms(), width, height, image_bytes, size))
            row = connection.execute("SELECT " + _columns() + " FROM replay_training_note_capture WHERE run_id=? AND capture_id=?",
                                     (run_id, capture_id)).fetchone()
            return {"protocol": "replay.v3", "schema_version": "replay.note-capture.v1", "context": current, "capture": _view(row)}
        return await self.base_store.run_extension_write(write)

    async def list(self, run_id: str, track_id: str, capture_id: str | None = None) -> dict[str, object]:
        def read(connection: sqlite3.Connection):
            context = self.context(connection, run_id, track_id)
            sql = ("SELECT " + _columns() + " FROM replay_training_note_capture WHERE run_id=? AND track_id=? AND dataset_epoch=? "
                   "AND virtual_time_ms<=? AND timeline_sequence<=? "
                   "AND (timeline_sequence<=? OR json_extract(captured_context_json,'$.reviewNote')=1)")
            args = [run_id, track_id, context["dataEpoch"], context["virtualTimeMs"],
                    context["timelineSequence"], original_note_timeline(context)]
            if capture_id is not None:
                sql += " AND capture_id=?"
                args.append(capture_id)
            rows = connection.execute(sql + " ORDER BY saved_at_ms DESC,capture_id DESC LIMIT ?", (*args, MAX_CAPTURES)).fetchall()
            if capture_id is not None and not rows:
                raise _error("REPLAY_NOTE_CAPTURE_NOT_FOUND", "Capture is not visible in this view", 404)
            return {"protocol": "replay.v3", "schema_version": "replay.note-captures.v1", "context": context,
                    "captures": [_view(row) for row in rows]}
        return await self.base_store.run_extension_read(read)

    async def image(self, run_id: str, track_id: str, note_id: str, revision: int, capture_id: str) -> dict[str, object]:
        if type(revision) is not int or not 1 <= revision <= 100:
            raise _error("REPLAY_NOTE_CAPTURE_INVALID", "Invalid note image version")
        def read(connection: sqlite3.Connection):
            context = self.context(connection, run_id, track_id)
            version = connection.execute("SELECT v.* FROM replay_training_note_revision v JOIN replay_training_note n "
                "ON n.run_id=v.run_id AND n.note_id=v.note_id WHERE n.run_id=? AND n.track_id=? AND n.note_id=? AND v.revision=? "
                "AND n.market_time_ms<=? AND n.timeline_sequence<=? AND v.virtual_time_ms<=? AND v.timeline_sequence<=? "
                "AND (n.review_note=1 OR v.timeline_sequence<=?)",
                (run_id, track_id, note_id, revision, context["virtualTimeMs"], context["timelineSequence"],
                 context["virtualTimeMs"], context["timelineSequence"], original_note_timeline(context))).fetchone()
            if version is None:
                raise _error("REPLAY_NOTE_CAPTURE_NOT_FOUND", "Note version is not visible in this view", 404)
            selected_images = selected(json.loads(version["fields_json"]))
            if capture_id not in selected_images:
                raise _error("REPLAY_NOTE_CAPTURE_NOT_FOUND", "Capture does not belong to this version", 404)
            row = connection.execute("SELECT c.* FROM replay_training_note_capture_link l JOIN replay_training_note_capture c "
                "ON c.run_id=l.run_id AND c.capture_id=l.capture_id WHERE l.run_id=? AND l.note_id=? AND l.revision=? AND l.capture_id=?",
                (run_id, note_id, revision, capture_id)).fetchone()
            if row is None or not _bounds(row, context) or not _bounds(row, json.loads(version["context_json"])):
                raise _error("REPLAY_NOTE_CAPTURE_CORRUPT", "Version capture image is unavailable", 503)
            raw = bytes(row["image_png"])
            try:
                if _png_info(raw) != (row["width"], row["height"]):
                    raise ValueError
            except (TrainingRunError, ValueError):
                raise _error("REPLAY_NOTE_CAPTURE_CORRUPT", "Version PNG is unavailable", 503) from None
            return {"protocol": "replay.v3", "schema_version": "replay.note-image.v1", "context": context,
                "note_id": note_id, "revision": revision, "capture": _view(row),
                "image": "data:image/png;base64," + base64.b64encode(raw).decode("ascii")}
        return await self.base_store.run_extension_read(read)
