"""Stored checkpoints stay self-contained, bounded and byte-exact on recovery."""
import base64
import hashlib
import json
import zlib

import pytest

from app.backtest.native import digest, encoded
from app.backtest import native_checkpoint as codec
from app.backtest.native_replay_storage import ResultJournal, same_json


def test_large_checkpoint_round_trip_preserves_complete_json_without_aliasing():
    value = {"rows": [{"text":"观察"*90, "values":[True, 1, 1.0, -0.0]} for _ in range(6000)]}
    value["checksum"] = digest(value)
    stored = codec.pack(value)
    assert len(stored.encode()) < len(encoded(value).encode()) // 10
    assert json.loads(stored)["storage_schema"] == codec.SCHEMA
    restored = codec.unpack(stored)
    assert same_json(restored, value)
    restored["rows"][0]["values"][0] = False
    assert same_json(codec.unpack(stored), value)
    assert same_json(codec.unpack(encoded(value)), value)  # legacy format


@pytest.mark.parametrize("damage", ["hash", "size", "truncated", "extra", "invalid", "bomb"])
def test_corrupt_or_oversized_compression_cannot_replace_a_checkpoint(damage):
    payload = b'"' + b'x' * (2 * 1024 * 1024) + b'"'
    envelope = {"storage_schema":codec.SCHEMA, "decoded_bytes":len(payload),
        "decoded_sha256":hashlib.sha256(payload).hexdigest(),
        "payload":base64.b64encode(zlib.compress(payload, 1)).decode()}
    if damage == "hash": envelope["decoded_sha256"] = "wrong"
    if damage == "size": envelope["decoded_bytes"] = codec.MAX_DECODED_BYTES + 1
    if damage == "truncated": envelope["payload"] = base64.b64encode(zlib.compress(payload)[:-3]).decode()
    if damage == "extra": envelope["payload"] = base64.b64encode(zlib.compress(payload) + b"extra").decode()
    if damage == "invalid": envelope["payload"] = "?"
    if damage == "bomb": envelope["decoded_bytes"] = 12
    with pytest.raises(ValueError):
        codec.unpack(encoded(envelope))


def test_host_journal_recovers_compressed_base_and_delta_from_only_its_database():
    import sqlite3
    db = sqlite3.connect(":memory:")
    journal = ResultJournal(db)
    first = {"history":["first"*250 for _ in range(1500)]}
    assert journal.save("host:replay", first) == 0
    final = {"history":[*first["history"], *("second"*250 for _ in range(1500))]}
    assert journal.save("host:replay", final) == 1
    assert same_json(ResultJournal(db).load("host:replay", expected_revision=1), final)
    db.execute("UPDATE native_replay_result_deltas SET checksum='broken'")
    with pytest.raises(ValueError, match="checksum"):
        ResultJournal(db).load("host:replay")
    db.close()
