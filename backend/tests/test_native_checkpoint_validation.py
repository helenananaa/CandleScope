"""Large private-base replacement retains the original validated DB history."""
import sqlite3

import pytest

from app.backtest import native_replay_storage as storage
from app.backtest.native import encoded


def seeded(db):
    journal = storage.ResultJournal(db)
    journal.save("host:account", {"history": list(range(20)), "cursor": 20})
    journal.save("host:account", {"history": list(range(30)), "cursor": 30})
    db.commit()
    return journal


def rows(db):
    return (db.execute("SELECT * FROM native_replay_result_bases ORDER BY id").fetchall(),
            db.execute("SELECT * FROM native_replay_result_deltas ORDER BY id,revision").fetchall())


def test_validated_replacement_decodes_once_then_recovers_from_only_the_new_base(monkeypatch):
    db = sqlite3.connect(":memory:")
    journal = seeded(db)
    old, receipt = journal.load("host:account", validation=True)
    assert old == {"history": list(range(30)), "cursor": 30}
    del old
    journal.cache.clear()
    final = {"history": list(range(100)), "cursor": 100}
    with monkeypatch.context() as patch:
        patch.setattr(storage, "unpack", lambda _: pytest.fail("replacement reparsed the old account"))
        with db:
            assert journal.save("host:account", final, validated_base=receipt) == 2
    assert not journal.cache
    assert not db.execute("SELECT * FROM native_replay_result_deltas").fetchall()
    assert storage.ResultJournal(db).load("host:account", expected_revision=2) == final
    with pytest.raises(ValueError, match="revision"):
        journal.save("host:account", final, validated_base=receipt)
    db.close()


@pytest.mark.parametrize("damage", ["base", "base_hash", "base_forged_hash", "delta", "delta_hash",
    "delta_forged_hash", "missing_delta", "extra_delta", "delta_gap", "revision", "base_revision", "missing_base"])
def test_replacement_rejects_changed_history_even_with_recomputed_stored_hashes(damage):
    db = sqlite3.connect(":memory:")
    journal = seeded(db)
    _, receipt = journal.load("host:account", validation=True)
    if damage.startswith("base") and damage != "base_revision":
        if damage == "base_hash":
            db.execute("UPDATE native_replay_result_bases SET checksum='changed'")
        else:
            raw = encoded({"different": "valid JSON"})
            db.execute("UPDATE native_replay_result_bases SET payload=?", (raw,))
            if damage == "base_forged_hash":
                db.execute("UPDATE native_replay_result_bases SET checksum=?", (storage.checksum(raw),))
    if damage in {"delta", "delta_hash", "delta_forged_hash"}:
        if damage == "delta_hash":
            db.execute("UPDATE native_replay_result_deltas SET checksum='changed'")
        else:
            raw = encoded([["set", ["cursor"], 999]])
            db.execute("UPDATE native_replay_result_deltas SET payload=?", (raw,))
            if damage == "delta_forged_hash":
                db.execute("UPDATE native_replay_result_deltas SET checksum=?", (storage.checksum(raw),))
    if damage == "missing_delta": db.execute("DELETE FROM native_replay_result_deltas")
    if damage == "extra_delta":
        db.execute("INSERT INTO native_replay_result_deltas VALUES (?,?,?,?)", ("host:account", 2, "[]", storage.checksum("[]")))
    if damage == "delta_gap": db.execute("UPDATE native_replay_result_deltas SET revision=5")
    if damage == "revision": db.execute("UPDATE native_replay_result_bases SET revision=9")
    if damage == "base_revision": db.execute("UPDATE native_replay_result_bases SET base_revision=1")
    if damage == "missing_base": db.execute("DELETE FROM native_replay_result_bases")
    before = rows(db)
    with pytest.raises(ValueError):
        journal.save("host:account", {"cursor": 100}, validated_base=receipt)
    assert rows(db) == before
    db.close()


def test_receipt_is_bound_to_its_journal_and_private_account():
    db = sqlite3.connect(":memory:")
    journal = seeded(db)
    _, receipt = journal.load("host:account", validation=True)
    for owner, key in ((storage.ResultJournal(db), "host:account"),
                       (journal, "host:another"), (journal, "public")):
        with pytest.raises(ValueError, match="receipt"):
            owner.save(key, {}, validated_base=receipt)
    with pytest.raises(ValueError, match="private"):
        journal.load("public", validation=True)
    db.close()


@pytest.mark.parametrize("bad", ["{", encoded({"storage_schema": "candlescope.replay-checkpoint-zlib/1", "decoded_bytes": 12})])
def test_new_receipt_requires_full_decoding_even_when_an_older_value_is_cached(bad):
    db = sqlite3.connect(":memory:")
    journal = seeded(db)
    assert journal.load("host:account")["cursor"] == 30
    db.execute("UPDATE native_replay_result_bases SET payload=?,checksum=?", (bad, storage.checksum(bad)))
    with pytest.raises(ValueError):
        journal.load("host:account", validation=True)
    db.close()


def test_new_receipt_requires_applying_every_delta():
    db = sqlite3.connect(":memory:")
    journal = seeded(db)
    raw = encoded([["unsupported", []]])
    db.execute("UPDATE native_replay_result_deltas SET payload=?,checksum=?", (raw, storage.checksum(raw)))
    with pytest.raises(ValueError, match="unknown"):
        journal.load("host:account", validation=True)
    db.close()


def test_replacement_holds_writer_reservation_until_caller_commit(tmp_path, monkeypatch):
    path = tmp_path / "journal.db"
    db = sqlite3.connect(path)
    journal = seeded(db)
    _, receipt = journal.load("host:account", validation=True)
    other = sqlite3.connect(path, timeout=0)
    pack = storage.pack
    def attempt_write(value):
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("UPDATE native_replay_result_bases SET revision=99")
        return pack(value)
    monkeypatch.setattr(storage, "pack", attempt_write)
    with db:
        journal.save("host:account", {"cursor": 100}, validated_base=receipt)
    other.execute("UPDATE native_replay_result_bases SET revision=99")
    other.rollback()
    other.close()
    db.close()


def test_private_replacement_and_public_result_roll_back_together():
    db = sqlite3.connect(":memory:")
    journal = seeded(db)
    _, receipt = journal.load("host:account", validation=True)
    before = rows(db)
    with pytest.raises(RuntimeError):
        with db:
            journal.save("host:account", {"cursor": 100}, validated_base=receipt)
            journal.save("public", {"cursor": 100})
            raise RuntimeError("public cursor write failed")
    assert rows(db) == before
    assert storage.ResultJournal(db).load("host:account")["cursor"] == 30
    db.close()
