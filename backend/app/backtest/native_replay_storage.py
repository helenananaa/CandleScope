"""Bounded replay result journals, committed with the replay cursor.

Public results and checkpoints remain complete JSON values. Storage keeps a
full base plus at most 63 structural deltas; no runtime is needed for recovery.
Unchanged historical arrays are compared, not encoded/hashed/written each step.
Large private account bases/deltas use self-contained lossless compression.
"""
from __future__ import annotations

import json
import hashlib
import math
from collections import OrderedDict
from dataclasses import dataclass

from .native import encoded
from .native_checkpoint import pack, unpack

SCHEMA = "native.replay-result/1"
MAX_DELTAS = 64
PRIVATE_CACHE_WRITE_BYTES = 1024 * 1024
PUBLIC_CACHE_WRITE_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class _ValidatedBase:
    owner: object
    key: str
    revision: int
    base_revision: int
    base_checksum: str
    deltas: tuple[tuple[int, str], ...]


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
        self._validation_owner = object()
        connection.execute("CREATE TABLE IF NOT EXISTS native_replay_result_bases (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, base_revision INTEGER NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS native_replay_result_deltas (id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL, PRIMARY KEY(id, revision))")

    def _remember(self, key, revision, value):
        self.cache[key] = (revision, value)
        self.cache.move_to_end(key)
        while len(self.cache) > 2:
            self.cache.popitem(last=False)

    def load(self, key, *, expected_revision=None, validation=False):
        if validation and not key.startswith("host:"):
            raise ValueError("validated replacement requires a private account")
        revision, base_revision = self.check_revision(key, expected_revision=expected_revision)
        # A replacement receipt must describe bytes that this read actually
        # decoded. A possibly stale cached graph cannot certify new DB bytes.
        if validation:
            self.cache.pop(key, None)
        cached = None if validation else self.cache.get(key)
        if cached is not None and cached[0] == revision:
            self.cache.move_to_end(key)
            return cached[1]
        raw, expected_hash = self.db.execute("SELECT payload,checksum FROM native_replay_result_bases WHERE id=?", (key,)).fetchone()
        if checksum(raw) != expected_hash:
            raise ValueError("native replay result base checksum mismatch")
        base_checksum = expected_hash
        value = unpack(raw) if key.startswith("host:") else json.loads(raw)
        del raw
        validated_deltas = []
        expected = base_revision + 1
        for sequence, patch, expected_hash in self.db.execute("SELECT revision,payload,checksum FROM native_replay_result_deltas WHERE id=? ORDER BY revision", (key,)):
            if sequence != expected:
                raise ValueError("native replay result journal has a gap")
            if checksum(patch) != expected_hash:
                raise ValueError("native replay result delta checksum mismatch")
            value = apply_changes(value, unpack(patch) if key.startswith("host:") else json.loads(patch))
            if validation:
                validated_deltas.append((sequence, expected_hash))
            expected += 1
            del patch
        if expected != revision + 1:
            raise ValueError("native replay result journal is incomplete")
        self._remember(key, revision, value)
        if validation:
            return value, _ValidatedBase(self._validation_owner, key, revision, base_revision,
                                         base_checksum, tuple(validated_deltas))
        return value

    def check_revision(self, key, *, expected_revision=None):
        """Check metadata without decoding a report for a conditional poll."""
        row = self.db.execute("SELECT revision,base_revision FROM native_replay_result_bases WHERE id=?", (key,)).fetchone()
        if row is None:
            raise ValueError("native replay result base is missing")
        revision, base_revision = row
        if expected_revision is not None and revision != expected_revision:
            raise ValueError("native replay result revision does not match its cursor")
        return revision, base_revision

    def _replace_validated(self, key, value, receipt):
        if (not isinstance(receipt, _ValidatedBase) or receipt.owner is not self._validation_owner
                or receipt.key != key or not key.startswith("host:")):
            raise ValueError("invalid private account validation receipt")
        # Hold the SQLite writer reservation across the recheck and replacement,
        # including callers whose surrounding connection context has not issued
        # its first write yet. The caller owns commit/rollback as for save().
        if not self.db.in_transaction:
            self.db.execute("BEGIN IMMEDIATE")
        if self.check_revision(key) != (receipt.revision, receipt.base_revision):
            raise ValueError("validated native replay result revision changed")
        raw, expected_hash = self.db.execute("SELECT payload,checksum FROM native_replay_result_bases WHERE id=?", (key,)).fetchone()
        if checksum(raw) != expected_hash or expected_hash != receipt.base_checksum:
            raise ValueError("validated native replay result base checksum changed")
        del raw
        count = 0
        for sequence, patch, expected_hash in self.db.execute("SELECT revision,payload,checksum FROM native_replay_result_deltas WHERE id=? ORDER BY revision", (key,)):
            if (count >= len(receipt.deltas) or (sequence, expected_hash) != receipt.deltas[count]
                    or checksum(patch) != expected_hash):
                raise ValueError("validated native replay result delta changed")
            count += 1
            del patch
        if count != len(receipt.deltas):
            raise ValueError("validated native replay result journal is incomplete")
        revision = receipt.revision + 1
        raw = pack(value)
        self.db.execute("INSERT OR REPLACE INTO native_replay_result_bases VALUES (?,?,?,?,?)", (key, revision, revision, raw, checksum(raw)))
        self.db.execute("DELETE FROM native_replay_result_deltas WHERE id=?", (key,))
        self.cache.pop(key, None)
        return revision

    def save(self, key, value, *, compare_base_bytes=False, validated_base=None):
        if validated_base is not None:
            return self._replace_validated(key, value, validated_base)
        row = self.db.execute("SELECT revision,base_revision FROM native_replay_result_bases WHERE id=?", (key,)).fetchone()
        if compare_base_bytes and key.startswith("host:") and row and row[0] == row[1]:
            # A validated snapshot can equal the current full base exactly.
            # Verify stored bytes and the absence of deltas before avoiding a
            # second complete parsed account merely to establish equality.
            raw, expected_hash = self.db.execute("SELECT payload,checksum FROM native_replay_result_bases WHERE id=?", (key,)).fetchone()
            if checksum(raw) != expected_hash:
                raise ValueError("native replay result base checksum mismatch")
            has_deltas = self.db.execute("SELECT 1 FROM native_replay_result_deltas WHERE id=? LIMIT 1", (key,)).fetchone()
            if has_deltas:
                raise ValueError("native replay result journal has unexpected deltas")
            if raw == pack(value):
                self.cache.pop(key, None)
                return row[0]
        previous = self.load(key) if row else None
        if row and same_json(previous, value):
            return row[0]
        revision = row[0] + 1 if row else 0
        cache_write_bytes = PRIVATE_CACHE_WRITE_BYTES if key.startswith("host:") else PUBLIC_CACHE_WRITE_BYTES
        if row is None or revision - row[1] >= MAX_DELTAS:
            raw = pack(value) if key.startswith("host:") else encoded(value)
            self.db.execute("INSERT OR REPLACE INTO native_replay_result_bases VALUES (?,?,?,?,?)", (key, revision, revision, raw, checksum(raw)))
            self.db.execute("DELETE FROM native_replay_result_deltas WHERE id=?", (key,))
            if len(raw.encode("utf-8")) > cache_write_bytes:
                self.cache.pop(key, None)
                return revision
            detached = unpack(raw) if key.startswith("host:") else json.loads(raw)
        else:
            changes = difference(previous, value)
            raw = pack(changes) if key.startswith("host:") else encoded(changes)
            self.db.execute("INSERT INTO native_replay_result_deltas VALUES (?,?,?,?)", (key, revision, raw, checksum(raw)))
            self.db.execute("UPDATE native_replay_result_bases SET revision=? WHERE id=?", (revision, key))
            # The caller already owns the complete result. Large writes stay
            # durable without decoding another graph just to warm this cache.
            if len(raw.encode("utf-8")) > cache_write_bytes:
                self.cache.pop(key, None)
                return revision
            detached = apply_changes(previous, unpack(raw) if key.startswith("host:") else json.loads(raw))
        self._remember(key, revision, detached)
        return revision
