"""Bounded replay result journals, committed with the replay cursor.

Public results and checkpoints remain complete JSON values. Storage keeps a
full base plus at most 63 structural deltas; no runtime is needed for recovery.
Unchanged historical arrays are compared, not encoded/hashed/written each step.
"""
from __future__ import annotations

import json
import hashlib
import math
from collections import OrderedDict

from .native import encoded

SCHEMA = "native.replay-result/1"
MAX_DELTAS = 64


def checksum(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def same_json(left, right):
    """Equality for exact exported JSON bytes (Python merges bool/int/float)."""
    if type(left) is not type(right):
        return False
    if left is right:
        return True
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_json(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(same_json(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and left == right == 0:
        return math.copysign(1, left) == math.copysign(1, right)
    return left == right


def difference(old, new, path=()):
    if same_json(old, new):
        return []
    if isinstance(old, dict) and isinstance(new, dict):
        result = [["delete", [*path, key]] for key in old.keys() - new.keys()]
        for key, value in new.items():
            result.extend(difference(old[key], value, (*path, key)) if key in old
                          else [["set", [*path, key], value]])
        return result
    if isinstance(old, list) and isinstance(new, list):
        # Small containers often wrap large nested plot arrays.
        if len(old) == len(new) and len(new) <= 16:
            return [change for index, value in enumerate(new)
                    for change in difference(old[index], value, (*path, index))]
        prefix = 0
        while prefix < min(len(old), len(new)) and same_json(old[prefix], new[prefix]):
            prefix += 1
        suffix = 0
        while suffix < min(len(old), len(new)) - prefix and same_json(old[-1-suffix], new[-1-suffix]):
            suffix += 1
        return [["splice", list(path), prefix, len(old) - prefix - suffix,
                 new[prefix:len(new)-suffix if suffix else len(new)]]]
    return [["set", list(path), new]]


def apply_changes(value, changes):
    for change in changes:
        action, path = change[:2]
        if action == "set" and not path:
            value = change[2]
            continue
        target = value
        for part in (path if action == "splice" else path[:-1]):
            target = target[part]
        if action == "splice":
            start, count, rows = change[2:]
            target[start:start + count] = rows
        elif action == "delete":
            del target[path[-1]]
        elif action == "set":
            target[path[-1]] = change[2]
        else:
            raise ValueError("unknown native replay result operation")
    return value


class ResultJournal:
    def __init__(self, connection):
        self.db = connection
        self.cache = OrderedDict()
        connection.execute("CREATE TABLE IF NOT EXISTS native_replay_result_bases (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, base_revision INTEGER NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS native_replay_result_deltas (id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL, PRIMARY KEY(id, revision))")

    def _remember(self, key, revision, value):
        self.cache[key] = (revision, value)
        self.cache.move_to_end(key)
        while len(self.cache) > 2:
            self.cache.popitem(last=False)

    def load(self, key, *, expected_revision=None):
        row = self.db.execute("SELECT revision,base_revision FROM native_replay_result_bases WHERE id=?", (key,)).fetchone()
        if row is None:
            raise ValueError("native replay result base is missing")
        revision, base_revision = row
        if expected_revision is not None and revision != expected_revision:
            raise ValueError("native replay result revision does not match its cursor")
        cached = self.cache.get(key)
        if cached is not None and cached[0] == revision:
            self.cache.move_to_end(key)
            return cached[1]
        raw, expected_hash = self.db.execute("SELECT payload,checksum FROM native_replay_result_bases WHERE id=?", (key,)).fetchone()
        if checksum(raw) != expected_hash:
            raise ValueError("native replay result base checksum mismatch")
        value = json.loads(raw)
        expected = base_revision + 1
        for sequence, patch, expected_hash in self.db.execute("SELECT revision,payload,checksum FROM native_replay_result_deltas WHERE id=? ORDER BY revision", (key,)):
            if sequence != expected:
                raise ValueError("native replay result journal has a gap")
            if checksum(patch) != expected_hash:
                raise ValueError("native replay result delta checksum mismatch")
            value = apply_changes(value, json.loads(patch))
            expected += 1
        if expected != revision + 1:
            raise ValueError("native replay result journal is incomplete")
        self._remember(key, revision, value)
        return value

    def save(self, key, value):
        row = self.db.execute("SELECT revision,base_revision FROM native_replay_result_bases WHERE id=?", (key,)).fetchone()
        previous = self.load(key) if row else None
        if row and same_json(previous, value):
            return row[0]
        revision = row[0] + 1 if row else 0
        if row is None or revision - row[1] >= MAX_DELTAS:
            raw = encoded(value)
            self.db.execute("INSERT OR REPLACE INTO native_replay_result_bases VALUES (?,?,?,?,?)", (key, revision, revision, raw, checksum(raw)))
            self.db.execute("DELETE FROM native_replay_result_deltas WHERE id=?", (key,))
            detached = json.loads(raw)
        else:
            raw = encoded(difference(previous, value))
            self.db.execute("INSERT INTO native_replay_result_deltas VALUES (?,?,?,?)", (key, revision, raw, checksum(raw)))
            self.db.execute("UPDATE native_replay_result_bases SET revision=? WHERE id=?", (revision, key))
            detached = apply_changes(previous, json.loads(raw))
        self._remember(key, revision, detached)
        return revision
