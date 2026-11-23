"""The strategy editor's working copies, stored in the backend (ADR-BACKTEST-015 P3a).

A draft is mutable and private to the editor: chart attachments and the research
page point at it by id. Runs never reference a draft; they reference the frozen
version created from it. Writes are compare-and-set on the draft's revision, so two
windows editing one draft cannot silently overwrite each other's newer copy.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .errors import BacktestError

if TYPE_CHECKING:
    from .repository import BacktestRepository

SCHEMA = "candlescope.strategy-draft/1"
DRAFT_ID = re.compile(r"^draft-[A-Za-z0-9_-]{8,152}$")
LANGUAGES = frozenset({"pine", "python"})
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_NAME_CHARS = 120
MAX_DRAFTS = 500
MAX_IMPORT = 200
MAX_COUNTER = 9_007_199_254_740_991


def _invalid(message: str) -> BacktestError:
    return BacktestError("DRAFT_INVALID", message)


def _counter(value: object, name: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_COUNTER:
        raise _invalid(f"{name} must be a non-negative integer")
    return value


def _record(value: object) -> dict[str, Any]:
    """Validate a wire draft (the editor's own limits) into a stored row."""
    if not isinstance(value, Mapping):
        raise _invalid("a draft must be an object")
    draft_id = value.get("draft_id")
    if not isinstance(draft_id, str) or not DRAFT_ID.fullmatch(draft_id):
        raise _invalid("draft_id is not a strategy draft id")
    language = value.get("language")
    if language not in LANGUAGES:
        raise _invalid("language must be pine or python")
    source = value.get("source")
    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise _invalid("source must be text within 2 MiB")
    name = value.get("display_name")
    if not isinstance(name, str):
        raise _invalid("display_name must be text")
    cursor = value.get("cursor")
    if cursor is not None:
        if (not isinstance(cursor, Mapping) or set(cursor) != {"line", "column"}
                or any(type(cursor[key]) is not int or not 1 <= cursor[key] <= MAX_COUNTER for key in ("line", "column"))):
            raise _invalid("cursor must be a 1-based line and column")
    created = _counter(value.get("created_at_ms"), "created_at_ms")
    updated = _counter(value.get("updated_at_ms"), "updated_at_ms")
    return {
        "draft_id": draft_id, "revision": _counter(value.get("revision"), "revision"),
        "display_name": name.strip()[:MAX_NAME_CHARS], "language": language, "source_text": source,
        "cursor_json": None if cursor is None else json.dumps({"line": cursor["line"], "column": cursor["column"]}),
        "created_at_ms": created, "updated_at_ms": max(created, updated),
    }


def _wire(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "draft_id": row["draft_id"], "revision": int(row["revision"]),
        "display_name": row["display_name"], "language": row["language"], "source": row["source_text"],
        "cursor": None if row["cursor_json"] is None else json.loads(row["cursor_json"]),
        "created_at_ms": int(row["created_at_ms"]), "updated_at_ms": int(row["updated_at_ms"]),
    }


def _draft_id(draft_id: str) -> str:
    if not isinstance(draft_id, str) or not DRAFT_ID.fullmatch(draft_id):
        raise BacktestError("DRAFT_NOT_FOUND", "unknown strategy draft")
    return draft_id


class StrategyDrafts:
    def __init__(self, repository: BacktestRepository) -> None:
        self.repository = repository

    def list(self, limit: int = 50) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= MAX_IMPORT:
            raise _invalid(f"limit must be 1 to {MAX_IMPORT}")
        return {"drafts": [_wire(row) for row in self.repository.list_strategy_drafts(limit)]}

    def get(self, draft_id: str) -> dict[str, Any]:
        row = self.repository.get_strategy_draft(_draft_id(draft_id))
        if row is None:
            raise BacktestError("DRAFT_NOT_FOUND", "unknown strategy draft")
        return _wire(row)

    def save(self, draft_id: str, body: object) -> dict[str, Any]:
        """Store ``body.draft`` if the stored revision is ``body.expected_revision`` (null: no draft yet)."""
        if not isinstance(body, Mapping) or set(body) != {"expected_revision", "draft"}:
            raise _invalid("a save carries expected_revision and draft")
        expected = body["expected_revision"]
        if expected is not None:
            expected = _counter(expected, "expected_revision")
        record = _record(body["draft"])
        if record["draft_id"] != _draft_id(draft_id):
            raise _invalid("the draft belongs to another id")
        if expected is not None and record["revision"] <= expected:
            raise _invalid("a saved draft's revision must advance")
        if expected is None and self.repository.count_strategy_drafts() >= MAX_DRAFTS \
                and self.repository.get_strategy_draft(draft_id) is None:
            raise BacktestError("DRAFT_CAPACITY_EXCEEDED", "the strategy draft limit is reached")
        if not self.repository.compare_and_set_strategy_draft(record, expected):
            current = self.repository.get_strategy_draft(draft_id)
            raise BacktestError("DRAFT_REVISION_CONFLICT", "the draft changed in another window",
                                details={"current_revision": None if current is None else int(current["revision"])})
        return self.get(draft_id)

    def remove(self, draft_id: str) -> dict[str, Any]:
        return {"draft_id": draft_id, "removed": self.repository.delete_strategy_draft(_draft_id(draft_id))}

    def import_drafts(self, body: object) -> dict[str, Any]:
        """Bring drafts from browser or desktop storage in once; a newer stored copy wins. Idempotent."""
        if not isinstance(body, Mapping) or set(body) != {"drafts"} or not isinstance(body["drafts"], list):
            raise _invalid("an import carries a list of drafts")
        if len(body["drafts"]) > MAX_IMPORT:
            raise _invalid(f"an import carries at most {MAX_IMPORT} drafts")
        records = [_record(item) for item in body["drafts"]]
        if len({record["draft_id"] for record in records}) != len(records):
            raise _invalid("an import lists each draft once")
        return self.repository.import_strategy_drafts(records, capacity=MAX_DRAFTS)
