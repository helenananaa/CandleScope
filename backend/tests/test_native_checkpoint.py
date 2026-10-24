"""Stored checkpoints stay self-contained, bounded and byte-exact on recovery."""
import base64
import hashlib
import json
import zlib

import pytest

from app.backtest.native import digest, encoded
from app.backtest import native_checkpoint as codec
from app.backtest.native_replay_storage import ResultJournal, same_json


@pytest.mark.parametrize("size", [1024 * 1024, 1024 * 1024 + 1])
@pytest.mark.parametrize("text", ["a", "观察🙂\n\\\""])
def test_large_journal_checksum_preserves_exact_utf8_bytes(size, text):
    from app.backtest.native_replay_storage import checksum
    raw = (text * (size // len(text) + 1))[:size]
    assert checksum(raw) == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_large_journal_checksum_still_rejects_invalid_utf8():
    from app.backtest.native_replay_storage import checksum
    with pytest.raises(UnicodeEncodeError):
        checksum("a" * (1024 * 1024 + 1) + "\ud800")


@pytest.mark.parametrize("count", [0, 1, 16, 17, 511, 512, 513, 1025])
def test_streamed_checkpoint_bytes_and_hash_match_the_original_encoder(count):
    shared = {"text": "观察🙂\n\\\"", "numbers": [True, 1, 1.0, -0.0, 1e-7, 1e20]}
    value = {"rows": [shared] * count, "tuple": (shared, None),
             "delta": [["set", [], {"rows": [shared] * count}]],
             "keys": {"1": "converted"}}
    raw = encoded(value).encode("utf-8")
    assert b"".join(codec.canonical_fragments(value)) == raw
    assert codec.checkpoint_digest(value) == digest(value)
    assert codec.checkpoint_measure(value) == (digest(value), len(raw))


def test_streamed_checkpoint_preserves_numeric_key_encoding_and_mixed_key_rejection():
    value = {1: "converted", 2: False}
    assert b"".join(codec.canonical_fragments(value)) == encoded(value).encode("utf-8")
    with pytest.raises(TypeError):
        list(codec.canonical_fragments({1: "converted", "x": False}))


@pytest.mark.parametrize("shape", ["rows", "delta", "scalar"])
def test_streamed_compression_preserves_the_exact_legacy_envelope(shape):
    value = {"rows": [{"text": "观察" * 90, "values": [True, 1, 1.0, -0.0]} for _ in range(6000)]}
    if shape == "delta":
        value = [["set", [], value]]
    elif shape == "scalar":
        value = {"text": "观察🙂\n\\\"" * 200000, "number": -0.0}
    raw = encoded(value).encode("utf-8")
    expected = encoded({"storage_schema": codec.SCHEMA, "decoded_bytes": len(raw),
        "decoded_sha256": hashlib.sha256(raw).hexdigest(),
        "payload": base64.b64encode(zlib.compress(raw, level=1)).decode("ascii")})
    assert codec.pack(value) == expected
    assert same_json(codec.unpack(expected), value)


def test_streamed_checkpoint_keeps_raw_fallback_and_enforces_decoded_limit(monkeypatch):
    monkeypatch.setattr(codec, "COMPRESS_FROM_BYTES", 1)
    assert codec.pack({"x": 1}) == encoded({"x": 1})
    monkeypatch.setattr(codec, "MAX_DECODED_BYTES", 100)
    with pytest.raises(ValueError, match="decoded size"):
        codec.pack({"rows": list(range(100))})


@pytest.mark.parametrize("kind", [dict, list])
def test_streamed_checkpoint_rejects_cycles(kind):
    value = kind()
    if kind is dict:
        value["self"] = value
    else:
        value.append(value)
    with pytest.raises(ValueError, match="Circular"):
        codec.pack(value)


def test_detached_normalization_preserves_serialized_values_and_shared_container_ownership():
    from decimal import Decimal
    shared = [{"text": "观察🙂", "numbers": [True, 1, 1.0, -0.0], "decimal": Decimal("1.2300")}]
    value = {"accounts": shared, "clock": {"accounts": shared}, "tuple": (shared, None),
             "converted_keys": {1: "first", "1": "last", False: [Decimal("2.0")]}}
    expected = json.loads(json.dumps(value, default=str, allow_nan=False))
    result = codec.detached_json(value)
    assert encoded(result) == encoded(expected)
    assert result["accounts"] is result["clock"]["accounts"] is result["tuple"][0]
    assert result["accounts"] is not shared and result["accounts"][0] is not shared[0]
    shared[0]["numbers"].append(99)
    assert encoded(result) == encoded(expected)
    result["accounts"][0]["numbers"].append(100)
    assert 100 not in shared[0]["numbers"]


@pytest.mark.parametrize("preserve_aliases", [False, True])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_detached_normalization_rejects_nonfinite_values(value,preserve_aliases):
    with pytest.raises(ValueError):
        codec.detached_json({"nested": [value]},preserve_aliases=preserve_aliases)


@pytest.mark.parametrize("preserve_aliases", [False, True])
@pytest.mark.parametrize("kind", [dict, list])
def test_detached_normalization_rejects_cycles_instead_of_memoizing_them(kind,preserve_aliases):
    value = kind()
    if kind is dict:
        value["self"] = value
    else:
        value.append(value)
    with pytest.raises(ValueError, match="Circular"):
        codec.detached_json(value,preserve_aliases=preserve_aliases)


def test_large_checkpoint_round_trip_preserves_complete_json_without_aliasing():
    value = {"rows": [{"text":"观察"*90, "values":[True, 1, 1.0, -0.0]} for _ in range(6000)],"emoji":"🙂"}
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


def test_host_journal_recovers_compressed_base_and_delta_from_only_its_database(monkeypatch):
    import sqlite3
    from app.backtest import native_replay_storage as storage
    monkeypatch.setattr(storage,"PRIVATE_CACHE_WRITE_BYTES",64)
    decoded=[]
    unpack=storage.unpack
    def observe_unpack(raw):
        decoded.append(len(raw))
        return unpack(raw)
    monkeypatch.setattr(storage,"unpack",observe_unpack)
    db = sqlite3.connect(":memory:")
    journal = ResultJournal(db)
    first = {"history":["first"*250 for _ in range(1500)]}
    assert journal.save("host:replay", first) == 0
    assert decoded==[] and "host:replay" not in journal.cache
    assert same_json(journal.load("host:replay"),first)
    decoded.clear()
    final = {"history":[*first["history"], *("second"*250 for _ in range(1500))]}
    assert journal.save("host:replay", final) == 1
    # Persisting a private delta does not allocate another complete parsed
    # account; the next reader reconstructs and validates the database instead.
    assert decoded==[] and "host:replay" not in journal.cache
    assert same_json(ResultJournal(db).load("host:replay", expected_revision=1), final)
    db.execute("UPDATE native_replay_result_deltas SET checksum='broken'")
    with pytest.raises(ValueError, match="checksum"):
        ResultJournal(db).load("host:replay")
    db.close()


def test_identical_private_base_restore_checks_stored_bytes_and_rejects_stray_deltas(monkeypatch):
    import sqlite3
    from app.backtest import native_replay_storage as storage
    monkeypatch.setattr(storage,"PRIVATE_CACHE_WRITE_BYTES",64)
    db=sqlite3.connect(":memory:")
    journal=ResultJournal(db)
    value={"rows":["immutable account"*100 for _ in range(1500)],"numbers":[True,1,1.0,-0.0]}
    assert journal.save("host:restore",value)==0
    with monkeypatch.context() as patch:
        patch.setattr(storage,"unpack",lambda _:pytest.fail("identical base was unnecessarily decoded"))
        assert journal.save("host:restore",value,compare_base_bytes=True)==0
        raw,expected=db.execute("SELECT payload,checksum FROM native_replay_result_bases").fetchone()
        db.execute("UPDATE native_replay_result_bases SET checksum='broken'")
        with pytest.raises(ValueError,match="checksum"):
            journal.save("host:restore",value,compare_base_bytes=True)
    db.execute("UPDATE native_replay_result_bases SET checksum=?",(expected,))
    assert same_json(journal.load("host:restore"),value)
    db.execute("INSERT INTO native_replay_result_deltas VALUES (?,?,?,?)",("host:restore",1,"[]",storage.checksum("[]")))
    with pytest.raises(ValueError,match="journal"):
        journal.save("host:restore",value,compare_base_bytes=True)
    db.close()


@pytest.mark.parametrize("write_kind", ["base", "delta", "rebase"])
def test_large_public_writes_keep_complete_cold_results_without_decoding_a_write_cache(monkeypatch, write_kind):
    import sqlite3
    from app.backtest import native_replay_storage as storage
    monkeypatch.setattr(storage, "PUBLIC_CACHE_WRITE_BYTES", 64)
    db = sqlite3.connect(":memory:")
    journal = ResultJournal(db)
    if write_kind != "base":
        assert journal.save("public", {"history": ["first"], "numbers": [True, 1, 1.0, -0.0]}) == 0
    if write_kind == "rebase":
        monkeypatch.setattr(storage, "MAX_DELTAS", 1)
    value = {"history": ["first", "观察🙂" * 300], "numbers": [True, 1, 1.0, -0.0]}
    expected = json.loads(encoded(value))
    # The previous value is already warm. A large save must only encode/write;
    # complete reconstruction belongs to the subsequent reader.
    with monkeypatch.context() as patch:
        patch.setattr(storage.json, "loads", lambda _: pytest.fail("large write decoded a duplicate cache"))
        revision = journal.save("public", value)
    assert "public" not in journal.cache
    value["history"][1] = "caller mutation"
    assert same_json(ResultJournal(db).load("public", expected_revision=revision), expected)
    table = "native_replay_result_deltas" if write_kind == "delta" else "native_replay_result_bases"
    db.execute(f"UPDATE {table} SET checksum='broken'")
    with pytest.raises(ValueError, match="checksum"):
        ResultJournal(db).load("public")
    db.close()


@pytest.mark.parametrize("shortfall", [0, 1])
def test_public_write_cache_limit_counts_utf8_bytes_and_keeps_small_writes_detached(monkeypatch, shortfall):
    import sqlite3
    from app.backtest import native_replay_storage as storage
    value = {"history": ["观察🙂" * 30]}
    expected = json.loads(encoded(value))
    monkeypatch.setattr(storage, "PUBLIC_CACHE_WRITE_BYTES", len(encoded(value).encode("utf-8")) - shortfall)
    db = sqlite3.connect(":memory:")
    journal = ResultJournal(db)
    assert journal.save("public", value) == 0
    assert ("public" in journal.cache) is (shortfall == 0)
    value["history"][0] = "caller mutation"
    assert same_json(journal.load("public"), expected)
    assert journal.save("public", expected) == 0
    db.close()
