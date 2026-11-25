"""A data folder moved, copied or restored to another path keeps its derived stores.

Each store that records an absolute path is checked for both sides: the same
database at a new path passes, and a marker written for another database is
still refused (or, for a registry, left alone).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.backtest.continuous_inputs import ContinuousInputs
from app.backtest.continuous_repair_stages import RepairStages
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from app.backtest.repository import BacktestRepository
from app.core import profile_relocation, startup_failure
from app.data_engine.backfill.archive_cache import HistoricalArchiveCache
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.models import PreparationError
from app.data_preparation.repository import PreparationRepository
from app.replay import service as replay_service
from app.replay.training import raw_trade_retention

OTHER_ID = "0123456789abcdef0123456789abcdef"


def _profile(root: Path) -> Path:
    data = root / "Library" / "Application Support" / "CandleScope" / "data"
    data.mkdir(parents=True)
    return data


def _move(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# Shared rule -----------------------------------------------------------------

def test_owner_rule_accepts_the_same_database_and_refuses_another(tmp_path):
    data = tmp_path / "new" / "data"
    database, directory = data / "store.sqlite3", data / "cache"
    check = profile_relocation.check_owner
    moved = check("/old/home/data/store.sqlite3", "a" * 32, database=database, database_id="a" * 32, directory=directory)
    assert moved.owned and moved.relocated and moved.previous == Path("/old/home/data/store.sqlite3")
    # Legacy marker without an id: the path must end the way this one does.
    assert check("/old/home/data/store.sqlite3", None, database=database, database_id=None, directory=directory).owned
    assert not check("/old/home/data/other.sqlite3", None, database=database, database_id=None, directory=directory).owned
    assert not check(str(data / "other.sqlite3"), None, database=database, database_id="a" * 32, directory=directory).owned
    # Both sides have an id: a different id is another database unless it is this very path.
    assert not check("/old/home/data/store.sqlite3", "b" * 32, database=database, database_id="a" * 32, directory=directory).owned
    in_place = check(str(database), "b" * 32, database=database, database_id="a" * 32, directory=directory)
    assert in_place.owned and not in_place.relocated
    assert not check("relative/store.sqlite3", None, database=database, database_id=None, directory=directory).owned
    assert profile_relocation.relocation_prefixes(Path("/Users/old/Library/data/x.db"), Path("/Users/new/Library/data/x.db")) == (
        Path("/Users/old"), Path("/Users/new"))
    assert profile_relocation.relocation_prefixes(Path("/x.db"), Path("/y/x.db")) is None  # never rebase the root


# 1. data/prepared-inputs/.preparation-owner ----------------------------------

def _preparation(data: Path):
    repository = PreparationRepository(data / "data-preparation.sqlite3")
    adapter = BarPreparationAdapter(data / "prepared-inputs", coordinator=None)
    return repository, adapter


def test_moved_profile_keeps_prepared_inputs_and_rebases_the_storage_ledger(tmp_path):
    old = _profile(tmp_path / "Users" / "old")
    repository, adapter = _preparation(old)
    assert adapter.reconcile_cache(repository) == 0
    identity = repository.database_identity()
    retained = adapter.root / ("a" * 64 + ".json.gz")
    retained.write_bytes(b"retained")
    repository.publish_chunk("known", {}, {"sha256": "a" * 64}, 8, "owner")
    published = old.parent / "local-data" / "dataset" / "manifest.json"
    published.parent.mkdir(parents=True)
    published.write_text("{}")
    repository.register_publications([(published, "strategy_input")])
    repository.register_publication_scopes([(old.parent / "local-data", "strategy_input")])

    new_home = tmp_path / "Users" / "new"
    _move(tmp_path / "Users" / "old" / "Library", new_home / "Library")
    new = new_home / "Library" / "Application Support" / "CandleScope" / "data"
    repository, adapter = _preparation(new)
    assert adapter.reconcile_cache(repository) == 0
    marker = _json(adapter.root / ".preparation-owner")
    assert marker["database"] == str((new / "data-preparation.sqlite3").resolve())
    assert marker["database_id"] == identity == repository.database_identity()
    assert (adapter.root / ("a" * 64 + ".json.gz")).read_bytes() == b"retained"
    moved = str((new.parent / "local-data" / "dataset" / "manifest.json").resolve())
    assert repository.publication_paths() == {moved}
    assert [str(path) for path, _ in repository.publication_scopes()] == [str((new.parent / "local-data").resolve())]


def test_copied_profile_and_its_original_both_keep_prepared_inputs(tmp_path):
    original = _profile(tmp_path / "original")
    repository, adapter = _preparation(original)
    adapter.reconcile_cache(repository)
    copy_root = tmp_path / "copy"
    shutil.copytree(tmp_path / "original", copy_root)
    copy = copy_root / "Library" / "Application Support" / "CandleScope" / "data"
    copied_repository, copied_adapter = _preparation(copy)
    copied_adapter.reconcile_cache(copied_repository)
    adapter.reconcile_cache(repository)
    assert _json(copied_adapter.root / ".preparation-owner")["database"] == str((copy / "data-preparation.sqlite3").resolve())
    assert _json(adapter.root / ".preparation-owner")["database"] == str((original / "data-preparation.sqlite3").resolve())


def test_legacy_path_only_marker_is_adopted_after_a_move_and_gains_an_id(tmp_path):
    data = _profile(tmp_path / "new")
    repository, adapter = _preparation(data)
    legacy = {"database": "/Users/old/Library/Application Support/CandleScope/data/data-preparation.sqlite3",
              "legacy_files": [".preparation-owner.lock", "notes.txt"]}
    (adapter.root / ".preparation-owner").write_text(json.dumps(legacy))
    (adapter.root / "notes.txt").write_text("unclassified")
    assert adapter.reconcile_cache(repository) == 0
    marker = _json(adapter.root / ".preparation-owner")
    assert marker["database_id"] == repository.database_identity()
    assert sorted(marker["legacy_files"]) == sorted(legacy["legacy_files"])
    assert (adapter.root / "notes.txt").read_text() == "unclassified"


@pytest.mark.parametrize("marker", [
    # Written for another database (another id at another path).
    {"database": "/Users/someone/Library/Application Support/CandleScope/data/data-preparation.sqlite3",
     "database_id": OTHER_ID, "legacy_files": []},
    # An older marker naming a different database file.
    {"database": "/Users/someone/data/jobs.sqlite3", "legacy_files": []},
])
def test_prepared_inputs_of_another_database_are_still_refused_without_changes(tmp_path, marker):
    data = _profile(tmp_path / "profile")
    repository, adapter = _preparation(data)
    repository.database_identity(create=True)
    (adapter.root / ".preparation-owner").write_text(json.dumps(marker))
    orphan = adapter.root / ("b" * 64 + ".json.gz")
    orphan.write_bytes(b"belongs to the other database")
    with pytest.raises(PreparationError) as failure:
        adapter.reconcile_cache(repository)
    assert failure.value.code == "CACHE_OWNER_MISMATCH"
    assert str(adapter.root) in str(failure.value) and marker["database"] in str(failure.value)
    assert orphan.read_bytes() == b"belongs to the other database"
    assert _json(adapter.root / ".preparation-owner") == marker


def test_second_database_in_the_same_folder_still_cannot_share_prepared_inputs(tmp_path):
    repository = PreparationRepository(tmp_path / "jobs.db")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None)
    adapter.reconcile_cache(repository)
    with pytest.raises(PreparationError, match="another preparation database"):
        adapter.reconcile_cache(PreparationRepository(tmp_path / "other.db"))


# 2. data/continuous-strategy-inputs/owner.json -------------------------------
# 3. data/continuous-strategy-repairs/owner.json ------------------------------

def _store(data: Path) -> ContinuousStrategyStore:
    return ContinuousStrategyStore(data / "continuous-strategy.sqlite3")


def test_moved_profile_keeps_continuous_inputs_and_repair_staging(tmp_path):
    old = _profile(tmp_path / "Users" / "old")
    store = _store(old)
    try:
        ContinuousInputs(store)
        RepairStages(store)
        identity = store.identity()
    finally:
        store.close()
    _move(tmp_path / "Users" / "old" / "Library", tmp_path / "Users" / "new" / "Library")
    new = tmp_path / "Users" / "new" / "Library" / "Application Support" / "CandleScope" / "data"
    store = _store(new)
    try:
        ContinuousInputs(store)
        RepairStages(store)
        database = str((new / "continuous-strategy.sqlite3").resolve())
        for folder in ("continuous-strategy-inputs", "continuous-strategy-repairs"):
            marker = _json(new / folder / "owner.json")
            assert marker["database"] == database and marker["database_id"] == identity == store.identity()
    finally:
        store.close()


def test_legacy_continuous_markers_are_adopted_after_a_move(tmp_path):
    data = _profile(tmp_path / "new")
    old = "/Users/old/Library/Application Support/CandleScope/data/continuous-strategy.sqlite3"
    (data / "continuous-strategy-inputs").mkdir()
    (data / "continuous-strategy-inputs" / "owner.json").write_text(json.dumps(
        {"schema": "candlescope.continuous-private-inputs/1", "database": old}))
    (data / "continuous-strategy-repairs").mkdir()
    (data / "continuous-strategy-repairs" / "owner.json").write_text(json.dumps(
        {"schema": "candlescope.continuous-repair-stages/1", "database": old}))
    store = _store(data)
    try:
        ContinuousInputs(store)
        RepairStages(store)
        assert _json(data / "continuous-strategy-inputs" / "owner.json")["database_id"] == store.identity()
        assert _json(data / "continuous-strategy-repairs" / "owner.json")["database_id"] == store.identity()
    finally:
        store.close()


@pytest.mark.parametrize("folder,schema,build", [
    ("continuous-strategy-inputs", "candlescope.continuous-private-inputs/1", ContinuousInputs),
    ("continuous-strategy-repairs", "candlescope.continuous-repair-stages/1", RepairStages),
])
@pytest.mark.parametrize("recorded", [
    {"database": "/Users/someone/Library/Application Support/CandleScope/data/continuous-strategy.sqlite3",
     "database_id": OTHER_ID},
    {"database": "/Users/someone/data/run.db"},
])
def test_continuous_folders_of_another_database_are_still_refused(tmp_path, folder, schema, build, recorded):
    data = _profile(tmp_path / "profile")
    store = _store(data)
    try:
        store.identity(create=True)
        marker = {"schema": schema, **recorded}
        (data / folder).mkdir()
        (data / folder / "owner.json").write_text(json.dumps(marker))
        (data / folder / "kept.txt").write_text("other profile")
        with pytest.raises(BacktestError) as failure:
            build(store)
        assert failure.value.code == "CONTINUOUS_INPUT_OWNERSHIP"
        assert _json(data / folder / "owner.json") == marker
        assert (data / folder / "kept.txt").read_text() == "other profile"
    finally:
        store.close()


# 4. data/replay-agg-trades/.replay-reference-stores/<key>.json ---------------

def _registrations(directory: Path) -> set[tuple[str, str]]:
    return {(str(raw_trade_retention._read_registration(path)[0]), raw_trade_retention._read_registration(path)[1])
            for path in directory.glob("*.json")}


def test_moved_replay_store_drops_its_registration_at_the_old_path(tmp_path):
    registry = tmp_path / "archive" / ".replay-reference-stores"
    registry.parent.mkdir()
    old, new = tmp_path / "old" / "replay.db", tmp_path / "new" / "replay.db"
    old.parent.mkdir()
    old.write_bytes(b"")
    raw_trade_retention._register_store_with_lease(registry, old, "a" * 32)
    _move(old, new)
    raw_trade_retention._register_store_with_lease(registry, new, "a" * 32)
    assert _registrations(registry) == {(str(new), "a" * 32)}


def test_replay_registrations_that_are_not_a_moved_copy_of_this_store_stay(tmp_path):
    registry = tmp_path / "archive" / ".replay-reference-stores"
    registry.parent.mkdir()
    original, copy = tmp_path / "original" / "replay.db", tmp_path / "copy" / "replay.db"
    gone = tmp_path / "gone" / "replay.db"
    for path in (original, copy):
        path.parent.mkdir()
        path.write_bytes(b"")
    raw_trade_retention._register_store_with_lease(registry, original, "a" * 32)
    # Another store whose database is unavailable: its references stay protected.
    raw_trade_retention._register_store(registry, gone, "b" * 32)
    # A copy shares the id while the original still exists: both stay registered.
    raw_trade_retention._register_store_with_lease(registry, copy, "a" * 32)
    assert _registrations(registry) == {(str(original), "a" * 32), (str(gone), "b" * 32), (str(copy), "a" * 32)}


# 5. Replay progressive-history pin scope --------------------------------------

def test_progressive_pin_scope_is_saved_once_and_survives_a_move(tmp_path):
    connection = sqlite3.connect(tmp_path / "replay.db")
    try:
        first = replay_service._legacy_progressive_scope(tmp_path / "old" / "replay.db")
        assert replay_service._saved_progressive_scope(first, connection) == first
        moved = replay_service._legacy_progressive_scope(tmp_path / "new" / "replay.db")
        assert moved != first
        assert replay_service._saved_progressive_scope(moved, connection) == first
    finally:
        connection.close()
    other = sqlite3.connect(tmp_path / "other.db")
    try:
        assert replay_service._saved_progressive_scope(moved, other) == moved
    finally:
        other.close()


# 6. backtest_strategy_bundles.store_path -------------------------------------

def _bundle(store_path: str, bundle_id: str = "psb_" + "1" * 32) -> dict:
    return {"bundle_id": bundle_id, "bundle_hash": "h-" + bundle_id, "manifest_hash": "m", "source_hash": "s",
            "requirements_lock_hash": "r", "sdk_hash": "k", "capability_hash": "c", "parameter_schema_hash": "p",
            "size_bytes": 1, "file_count": 1, "store_path": store_path, "manifest_json": "{}", "created_at_ms": 1}


def test_strategy_bundles_are_read_from_the_moved_data_folder(tmp_path):
    old = _profile(tmp_path / "Users" / "old")
    repository = BacktestRepository(old / "backtest.db")
    repository.open(now_ms=1)
    bundle_id = "psb_" + "1" * 32
    repository.insert_strategy_bundle(_bundle(str(old / "python-strategy-bundles" / bundle_id), bundle_id))
    repository.insert_strategy_bundle(_bundle("/opt/elsewhere/bundle", "psb_" + "2" * 32))
    repository.close()
    _move(tmp_path / "Users" / "old" / "Library", tmp_path / "Users" / "new" / "Library")
    new = tmp_path / "Users" / "new" / "Library" / "Application Support" / "CandleScope" / "data"
    repository = BacktestRepository(new / "backtest.db")
    repository.open(now_ms=2)
    try:
        expected = str(new / "python-strategy-bundles" / bundle_id)
        assert repository.get_strategy_bundle(bundle_id)["store_path"] == expected
        assert repository.get_strategy_bundle_by_hash("h-" + bundle_id)["store_path"] == expected
        # A path outside the bundle layout is not this folder's to reinterpret.
        assert repository.get_strategy_bundle("psb_" + "2" * 32)["store_path"] == "/opt/elsewhere/bundle"
    finally:
        repository.close()


# 7. data/history_archives/history_archive_cache.sqlite -----------------------

def test_archive_cache_objects_follow_the_moved_cache_root(tmp_path):
    old = tmp_path / "old" / "history_archives"
    cache = HistoricalArchiveCache(old, max_bytes=10_000_000)
    digest = hashlib.sha256(b"zip").hexdigest()
    with sqlite3.connect(cache.index_path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(archive_objects)")]
        values = {name: 0 for name in columns}
        values.update({name: "x" for name in ("object_key", "provider_id", "exchange", "market_type", "symbol",
                                              "interval", "granularity", "period", "source_url", "state")})
        values.update({"object_key": "kept", "content_sha256": digest, "path": str(cache._content_path(digest)),
                       "cache_generation": "g", "state": "ready"})
        db.execute(f"INSERT INTO archive_objects ({','.join(values)}) VALUES ({','.join('?' * len(values))})",
                   list(values.values()))
        db.execute("INSERT INTO archive_blob_cleanup (content_sha256, path) VALUES (?, ?)",
                   ("f" * 64, "/somewhere/else/objects/ff/" + "f" * 64 + ".zip"))
    _move(tmp_path / "old", tmp_path / "new")
    cache = HistoricalArchiveCache(tmp_path / "new" / "history_archives", max_bytes=10_000_000)
    with sqlite3.connect(cache.index_path) as db:
        assert db.execute("SELECT path FROM archive_objects WHERE object_key='kept'").fetchone()[0] == str(
            cache._content_path(digest))
        # Cleanup rows move too, so they stay inside the root they may delete from.
        assert db.execute("SELECT path FROM archive_blob_cleanup").fetchone()[0] == str(cache._content_path("f" * 64))


def test_archive_cache_leaves_paths_outside_its_layout_alone(tmp_path):
    cache = HistoricalArchiveCache(tmp_path / "cache", max_bytes=10_000_000)
    digest = "e" * 64
    assert cache._relocated_content_path("/other/objects/ee/" + digest + ".zip", digest) == str(cache._content_path(digest))
    assert cache._relocated_content_path("/other/not-objects/ee/" + digest + ".zip", digest) is None
    assert cache._relocated_content_path("/other/objects/ee/" + "d" * 64 + ".zip", digest) is None
    assert cache._relocated_content_path(str(cache._content_path(digest)), digest) is None


# 8. OS secret-store namespaces (read-only accounts, proxy subscriptions) ------

def test_secret_namespace_follows_a_moved_folder(tmp_path):
    folder = tmp_path / "old" / "readonly-accounts"
    folder.mkdir(parents=True)
    origin = profile_relocation.secret_namespace_origin(folder)
    assert origin == str(folder.resolve())  # the namespace earlier versions used
    _move(tmp_path / "old", tmp_path / "new")
    moved = tmp_path / "new" / "readonly-accounts"
    assert profile_relocation.secret_namespace_origin(moved) == origin
    assert _json(moved / ".secret-namespace.json")["directory"] == str(moved.resolve())


def test_copied_folder_gets_its_own_secret_namespace_while_the_original_exists(tmp_path):
    original = tmp_path / "original" / "proxy-subscriptions"
    original.mkdir(parents=True)
    origin = profile_relocation.secret_namespace_origin(original)
    shutil.copytree(tmp_path / "original", tmp_path / "copy")
    copy = tmp_path / "copy" / "proxy-subscriptions"
    assert profile_relocation.secret_namespace_origin(copy) == str(copy.resolve()) != origin
    assert profile_relocation.secret_namespace_origin(original) == origin


# Startup failure named for the desktop dialog ---------------------------------

def test_startup_failure_records_the_first_cause_for_the_host(tmp_path, monkeypatch):
    target = tmp_path / "failure.json"
    monkeypatch.setenv(startup_failure.ENVIRONMENT, str(target))
    assert startup_failure.record(PreparationError("CACHE_OWNER_MISMATCH", "Prepared inputs belong elsewhere"))
    assert not startup_failure.record(RuntimeError("cleanup fallout"))
    assert _json(target) == {"code": "CACHE_OWNER_MISMATCH", "message": "Prepared inputs belong elsewhere",
                             "type": "PreparationError"}
    monkeypatch.delenv(startup_failure.ENVIRONMENT)
    assert not startup_failure.record(RuntimeError("no host"))


def test_application_startup_failure_is_recorded_before_it_propagates(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import main
    target = tmp_path / "failure.json"
    monkeypatch.setenv(startup_failure.ENVIRONMENT, str(target))
    monkeypatch.setattr(main, "RUNTIME_MODE", "LOCAL_OFFLINE")
    monkeypatch.setattr(main, "app", SimpleNamespace(state=SimpleNamespace()))

    async def fail():
        raise PreparationError("CACHE_OWNER_MISMATCH", "Prepared inputs in /x belong to another preparation database")

    monkeypatch.setattr(main, "_startup_event_impl", fail)
    with pytest.raises(PreparationError):
        asyncio.run(main.startup_event())
    assert _json(target)["code"] == "CACHE_OWNER_MISMATCH"


def test_sidecar_records_failures_raised_before_the_application_starts(tmp_path, monkeypatch):
    from app import desktop_sidecar
    target = tmp_path / "failure.json"
    monkeypatch.setenv(startup_failure.ENVIRONMENT, str(target))

    def refuse(host, port):
        raise OSError(48, "Address already in use")

    monkeypatch.setattr(desktop_sidecar, "_serve", refuse)
    with pytest.raises(OSError):
        desktop_sidecar.serve("127.0.0.1", 1)
    assert "Address already in use" in _json(target)["message"]
