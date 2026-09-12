"""SQLite-owned checkpoint deltas against independently retained full bases.

The actor and exported review anchors still exchange self-contained v1 bytes.
No delta depends on another delta; bases and references share the write transaction.
"""

import hashlib
import json
import zlib
from collections import OrderedDict
from threading import Lock

from ..canonical import canonical_json_bytes
from ..checkpoints import CheckpointCodec, CheckpointError, _OwnedCheckpoint, CHECKPOINT_SCHEMA_VERSION, CHECKPOINT_ZLIB_MAGIC
from ..immutable_json import freeze

MAGIC = b"CSRP-SQL-DELTA-V1\x00"
BASE_INTERVAL = 16
MIN_BYTES = 8192
BASE_CACHE_MAX_ENTRIES = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_checkpoint_base (
    base_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES replay_session(session_id) ON DELETE CASCADE,
    payload BLOB NOT NULL,
    payload_sha256 TEXT NOT NULL,
    uses INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replay_checkpoint_base_session
ON replay_checkpoint_base(session_id, base_id DESC);
CREATE TABLE IF NOT EXISTS replay_checkpoint_delta_ref (
    checkpoint_id INTEGER PRIMARY KEY REFERENCES replay_checkpoint(checkpoint_id) ON DELETE CASCADE,
    base_id INTEGER NOT NULL REFERENCES replay_checkpoint_base(base_id)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS idx_replay_checkpoint_delta_base
ON replay_checkpoint_delta_ref(base_id);
"""


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


# A small disposable cache. Keys include exact bytes, so corruption or rolled-back
# base-id reuse never substitutes a different base. Large bases use the normal path.
_base_cache = OrderedDict()
_base_lock = Lock()


def _logical(payload):
    if type(payload) is _OwnedCheckpoint and payload.schema == CHECKPOINT_SCHEMA_VERSION:
        return payload.payload
    return freeze(CheckpointCodec().decode(payload))


def _remember_base(payload, value):
    # Bound by raw JSON, not compressed wire size. Imported compressed bases
    # have no trusted raw-size receipt and are deliberately not retained.
    raw_size = payload.raw_size if type(payload) is _OwnedCheckpoint else (
        None if payload.startswith(CHECKPOINT_ZLIB_MAGIC) else len(payload)
    )
    if raw_size is None or raw_size > 4 * 1024 * 1024:
        return
    key = digest(payload)
    with _base_lock:
        _base_cache[key] = (payload, value)
        _base_cache.move_to_end(key)
        while len(_base_cache) > BASE_CACHE_MAX_ENTRIES:
            _base_cache.popitem(last=False)


def _base_value(payload):
    key = digest(payload)
    with _base_lock:
        cached = _base_cache.get(key)
        if cached is not None and cached[0] == payload:
            _base_cache.move_to_end(key)
            return cached[1]
    value = _logical(payload)
    _remember_base(payload, value)
    return value


def difference(base, value):
    if base is value or (type(base) is type(value) and not isinstance(base, (dict, list)) and base == value):
        return None
    if isinstance(base, dict) and isinstance(value, dict):
        changed = {}
        for key, item in value.items():
            patch = difference(base[key], item) if key in base else ["=", item]
            if patch is not None:
                changed[key] = patch
        removed = sorted(base.keys() - value.keys())
        return ["d", removed, changed] if removed or changed else None
    if isinstance(base, list) and isinstance(value, list):
        common = min(len(base), len(value))
        changed = {}
        for i in range(common):
            patch = difference(base[i], value[i])
            if patch is not None:
                changed[str(i)] = patch
        return ["l", common, changed, value[common:]] if changed or len(base) != len(value) else None
    return ["=", value]


def apply(base, patch):
    if patch is None:
        return base
    if not isinstance(patch, list) or not patch:
        raise CheckpointError("invalid checkpoint delta")
    if patch[0] == "=" and len(patch) == 2:
        return patch[1]
    if patch[0] == "d" and len(patch) == 3 and isinstance(base, dict):
        result = dict(base)
        for key in patch[1]:
            del result[key]
        for key, item in patch[2].items():
            result[key] = apply(base.get(key), item)
        return result
    if patch[0] == "l" and len(patch) == 4 and isinstance(base, list):
        length = patch[1]
        if not isinstance(length, int) or not 0 <= length <= len(base):
            raise CheckpointError("invalid checkpoint delta list length")
        result = base[:length]
        for index, item in patch[2].items():
            index = int(index)
            if not 0 <= index < length:
                raise CheckpointError("invalid checkpoint delta offset")
            result[index] = apply(base[index], item)
        return result + patch[3]
    raise CheckpointError("invalid checkpoint delta operation")


def compact(connection, session_id, payload):
    if len(payload) < MIN_BYTES:
        return payload, None
    base = connection.execute(
        "SELECT * FROM replay_checkpoint_base WHERE session_id=? ORDER BY base_id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if base is None or int(base["uses"]) >= BASE_INTERVAL:
        connection.execute(
            "INSERT INTO replay_checkpoint_base(session_id,payload,payload_sha256,uses) VALUES (?,?,?,1)",
            (session_id, payload, digest(payload)),
        )
        _remember_base(payload, _logical(payload))
        return payload, None
    raw_base = bytes(base["payload"])
    if digest(raw_base) != base["payload_sha256"]:
        # Do not build new checkpoints on a corrupt base. Keep this full checkpoint.
        connection.execute("UPDATE replay_checkpoint_base SET uses=? WHERE base_id=?", (BASE_INTERVAL, base["base_id"]))
        return payload, None
    patch = difference(_base_value(raw_base), _logical(payload))
    body = canonical_json_bytes({"base_id": int(base["base_id"]), "patch": patch})
    packed = MAGIC + zlib.compress(body, 1)
    connection.execute("UPDATE replay_checkpoint_base SET uses=uses+1 WHERE base_id=?", (base["base_id"],))
    # Include a margin for the reference row and SQLite overhead.
    if len(packed) + 128 >= len(payload):
        return payload, None
    return packed, int(base["base_id"])


def resolve(connection, row):
    payload = bytes(row["payload"])
    if payload.startswith(MAGIC):
        # Reuse the checkpoint codec's bounded zlib reader.
        from ..checkpoints import CHECKPOINT_ZLIB_MAGIC
        decoded = json.loads(CheckpointCodec._decode_wire(CHECKPOINT_ZLIB_MAGIC + payload[len(MAGIC):]))
        reference = connection.execute(
            "SELECT b.* FROM replay_checkpoint_delta_ref r JOIN replay_checkpoint_base b USING(base_id) "
            "WHERE r.checkpoint_id=? AND b.session_id=? AND b.base_id=?",
            (row["checkpoint_id"], row["session_id"], decoded["base_id"]),
        ).fetchone()
        if reference is None:
            raise CheckpointError("checkpoint delta base missing")
        base = bytes(reference["payload"])
        if digest(base) != reference["payload_sha256"]:
            raise CheckpointError("checkpoint delta base checksum mismatch")
        codec = CheckpointCodec()
        payload = codec.encode(apply(_base_value(base), decoded["patch"]))
    if digest(payload) != row["payload_sha256"]:
        raise CheckpointError("checkpoint checksum mismatch")
    return payload


def collect(connection, session_id):
    connection.execute(
        "DELETE FROM replay_checkpoint_base WHERE session_id=? "
        "AND base_id != (SELECT MAX(base_id) FROM replay_checkpoint_base WHERE session_id=?) "
        "AND base_id NOT IN (SELECT base_id FROM replay_checkpoint_delta_ref)",
        (session_id, session_id),
    )
