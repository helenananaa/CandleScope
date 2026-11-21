"""Small references the strategy pages keep, stored in the backend (ADR-BACKTEST-015 P3c).

They used to live in origin-scoped browser storage, which a new web origin or a
changed desktop UI port could not see. Values are bounded JSON objects that the
frontend validates when it reads them; the backend bounds and keeps them.

Kinds:
- ``continuous-run``: which forward run a chart strategy follows, and its archive.
  Losing one loses the way back to a live account, so a full store refuses.
- ``research-handoff`` / ``research-return``: one-shot transfers between the chart
  and the research page. Only recent ones matter, so the oldest are dropped.
"""
from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

from .errors import BacktestError

SCHEMA = "candlescope.strategy-reference/1"
# kind -> (capacity, prune the oldest instead of refusing)
KINDS = {"continuous-run": (512, False), "research-handoff": (200, True), "research-return": (200, True)}
MAX_KEY_CHARS = 512
MAX_VALUE_BYTES = 64 * 1024
MAX_IMPORT = 512
MAX_LIST = 512


def _kind(kind: str) -> tuple[int, bool]:
    if kind not in KINDS:
        raise BacktestError("REFERENCE_NOT_FOUND", "unknown strategy reference kind")
    return KINDS[kind]


def _key(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_KEY_CHARS or "\x00" in value:
        raise BacktestError("REFERENCE_INVALID", f"a reference key is 1 to {MAX_KEY_CHARS} characters")
    return value


def _value(value: object) -> str:
    if not isinstance(value, Mapping):
        raise BacktestError("REFERENCE_INVALID", "a reference value is a JSON object")
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        raise BacktestError("REFERENCE_INVALID", "a reference value must be finite JSON") from None
    if len(text.encode("utf-8")) > MAX_VALUE_BYTES:
        raise BacktestError("REFERENCE_INVALID", "a reference value exceeds 64 KiB")
    return text


def _wire(kind: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": SCHEMA, "kind": kind, "key": row["ref_key"], "value": json.loads(row["value_json"]),
            "updated_at_ms": int(row["updated_at_ms"])}


class StrategyReferences:
    def __init__(self, repository) -> None:
        self.repository = repository

    def get(self, kind: str, key: str) -> dict[str, Any]:
        _kind(kind)
        row = self.repository.get_strategy_reference(kind, _key(key))
        if row is None:
            raise BacktestError("REFERENCE_NOT_FOUND", "unknown strategy reference")
        return _wire(kind, row)

    def list(self, kind: str, prefix: str = "", limit: int = 200) -> dict[str, Any]:
        _kind(kind)
        if not isinstance(prefix, str) or len(prefix) > MAX_KEY_CHARS:
            raise BacktestError("REFERENCE_INVALID", "a key prefix is at most 512 characters")
        if type(limit) is not int or not 1 <= limit <= MAX_LIST:
            raise BacktestError("REFERENCE_INVALID", f"limit must be 1 to {MAX_LIST}")
        return {"kind": kind, "entries": [_wire(kind, row) for row in self.repository.list_strategy_references(kind, prefix, limit)]}

    def put(self, kind: str, body: object, *, now_ms: int | None = None) -> dict[str, Any]:
        capacity, prune = _kind(kind)
        if not isinstance(body, Mapping) or set(body) != {"key", "value"}:
            raise BacktestError("REFERENCE_INVALID", "a reference carries a key and a value")
        key = _key(body["key"])
        self.repository.put_strategy_references(kind, [(key, _value(body["value"]))], now_ms=now_ms or _now_ms(),
                                                capacity=capacity, prune=prune, keep_existing=False)
        return self.get(kind, key)

    def remove(self, kind: str, key: str) -> dict[str, Any]:
        _kind(kind)
        return {"kind": kind, "key": key, "removed": self.repository.delete_strategy_reference(kind, _key(key))}

    def import_entries(self, kind: str, body: object, *, now_ms: int | None = None) -> dict[str, Any]:
        """Bring browser-storage entries in once; an entry the backend already holds is kept. Idempotent."""
        capacity, prune = _kind(kind)
        if not isinstance(body, Mapping) or set(body) != {"entries"} or not isinstance(body["entries"], list):
            raise BacktestError("REFERENCE_INVALID", "an import carries a list of entries")
        if len(body["entries"]) > MAX_IMPORT:
            raise BacktestError("REFERENCE_INVALID", f"an import carries at most {MAX_IMPORT} entries")
        entries = []
        for item in body["entries"]:
            if not isinstance(item, Mapping) or set(item) != {"key", "value"}:
                raise BacktestError("REFERENCE_INVALID", "each imported entry carries a key and a value")
            entries.append((_key(item["key"]), _value(item["value"])))
        if len({key for key, _ in entries}) != len(entries):
            raise BacktestError("REFERENCE_INVALID", "an import lists each key once")
        imported = self.repository.put_strategy_references(kind, entries, now_ms=now_ms or _now_ms(), capacity=capacity,
                                                           prune=prune, keep_existing=True)
        return {"kind": kind, "imported": imported, "kept": [key for key, _ in entries if key not in set(imported)]}


def _now_ms() -> int:
    return int(time.time() * 1000)
