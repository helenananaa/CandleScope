"""A release that moves a database's schema forward keeps a copy for a downgrade.

0.3.0 (2026-10-25) refuses replay training schema 29 at startup, and it cannot
be changed. These tests pin that the new release keeps one consistent
pre-migration copy per database and from→to step, never touches it again, and
that restoring the copy gives back the data as it was before the upgrade.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.repository import BacktestRepository
from app.core import pre_migration_copy
from app.core.pre_migration_copy import PreMigrationCopyError, keep_pre_migration_copy
from app.replay.training.schema import TRAINING_SCHEMA_VERSION, migrate_training_schema
from app.trading_accounts.store import TradingStore
from tests.test_replay_training_notes import create
from tests.test_replay_v2_training_phase5 import _service

# Tables the replay training schema gained after 0.3.0 wrote version 26.
_TRAINING_TABLES_AFTER_26 = (
    "replay_training_note_capture_link",
    "replay_training_note_capture",
    "replay_training_note_links",
    "replay_training_note_revision",
    "replay_training_note",
)


def _dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        return list(db.iterdump())


def _fingerprint(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    return stat.st_ino, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def _copies(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.pre-*"))


def _training_version(path: Path) -> int:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        return db.execute("SELECT version FROM replay_training_schema_version").fetchone()[0]


async def _replay_db_written_by_0_3_0(path: Path) -> tuple[str, str]:
    """A replay database holding one training run, set back to training schema 26."""

    service = await _service(path)
    try:
        run, _, track = await create(service)
    finally:
        await service.shutdown(step_timeout=1)
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        # 0.3.0 had no note tables; the run's rows stay exactly as written.
        for table in _TRAINING_TABLES_AFTER_26:
            db.execute(f'DROP TABLE "{table}"')
        db.execute("UPDATE replay_training_schema_version SET version=26")
    return run, track


@pytest.mark.anyio
async def test_replay_training_upgrade_keeps_identical_pre_migration_copy_once(tmp_path):
    path = tmp_path / "CandleScope Replay" / "replay.db"
    path.parent.mkdir()
    run, track = await _replay_db_written_by_0_3_0(path)
    before = _dump(path)
    stale = path.with_name(f"{path.name}.pre-replay-training-v26-to-v{TRAINING_SCHEMA_VERSION}.sqlite.0123.partial")
    stale.write_bytes(b"interrupted copy")
    Path(f"{stale}-journal").write_bytes(b"stale journal")

    upgraded = await _service(path)
    await upgraded.shutdown(step_timeout=1)

    copy = path.with_name(f"replay.db.pre-replay-training-v26-to-v{TRAINING_SCHEMA_VERSION}.sqlite")
    assert _copies(path) == [copy]
    assert _training_version(path) == TRAINING_SCHEMA_VERSION
    assert _dump(copy) == before
    with closing(sqlite3.connect(copy)) as db:
        assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert db.execute("SELECT version FROM replay_training_schema_version").fetchone() == (26,)
    assert not list(path.parent.glob("*.partial*"))
    kept = _fingerprint(copy)

    # A second start migrates nothing and leaves the one copy alone.
    again = await _service(path)
    await again.shutdown(step_timeout=1)
    assert _copies(path) == [copy]
    assert _fingerprint(copy) == kept

    # Restoring the copy gives back the pre-upgrade database; this release
    # migrates it forward again without losing the run.
    restored = tmp_path / "restored" / "replay.db"
    restored.parent.mkdir()
    restored.write_bytes(copy.read_bytes())
    assert _dump(restored) == before
    reopened = await _service(restored)
    try:
        tracks = await reopened.training.store.get_market_tracks(run)
        assert [item["track_id"] for item in tracks["tracks"]] == [track]
    finally:
        await reopened.shutdown(step_timeout=1)
    # The restored file was moved into place, so upgrading it again keeps a
    # fresh copy of what is there now.
    assert _copies(restored) == [restored.with_name(copy.name)]


@pytest.mark.anyio
async def test_failed_copy_aborts_the_migration_and_leaves_the_database_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "replay.db"
    await _replay_db_written_by_0_3_0(path)
    before = _dump(path)

    def full_disk(*_args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pre_migration_copy.os, "replace", full_disk)
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(PreMigrationCopyError, match="database was not changed"):
            migrate_training_schema(db, now_ms=1)
        db.execute("ROLLBACK")
    finally:
        db.close()
    assert _dump(path) == before
    assert _copies(path) == []
    assert not list(tmp_path.glob("*.partial*"))


def test_copy_is_the_committed_snapshot_of_a_live_wal_database(tmp_path):
    path = tmp_path / "live.db"
    writer = sqlite3.connect(path, isolation_level=None)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE facts(value TEXT)")
        writer.execute("INSERT INTO facts VALUES ('committed')")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO facts VALUES ('not committed')")
        copy = keep_pre_migration_copy(writer, schema="facts", from_version=1, to_version=2)
        writer.execute("ROLLBACK")
    finally:
        writer.close()
    assert copy == tmp_path / "live.db.pre-facts-v1-to-v2.sqlite"
    with closing(sqlite3.connect(copy)) as db:
        assert db.execute("SELECT value FROM facts").fetchall() == [("committed",)]
    with closing(sqlite3.connect(":memory:")) as memory:
        assert keep_pre_migration_copy(memory, schema="facts", from_version=1, to_version=2) is None


def test_backtest_schema_step_keeps_one_copy(tmp_path):
    path = tmp_path / "backtest.db"
    repository = BacktestRepository(path)
    repository.open(now_ms=1)
    repository.connection.execute("UPDATE backtest_schema_meta SET schema_version = 8")
    repository.connection.commit()
    repository.close()
    before = _dump(path)

    for _ in range(2):
        repository = BacktestRepository(path)
        repository.open(now_ms=2)
        repository.close()

    copy = tmp_path / "backtest.db.pre-backtest-v8-to-v9.sqlite"
    assert _copies(path) == [copy]
    assert _dump(copy) == before


def test_continuous_strategy_schema_step_keeps_one_copy(tmp_path):
    path = tmp_path / "continuous-strategy.sqlite3"
    store = ContinuousStrategyStore(path)
    store.db.execute("DROP TABLE continuous_auto_repair")
    store.db.execute("PRAGMA user_version=4")
    store.close()
    before = _dump(path)

    for _ in range(2):
        ContinuousStrategyStore(path).close()

    copy = tmp_path / "continuous-strategy.sqlite3.pre-continuous-strategy-v4-to-v5.sqlite"
    assert _copies(path) == [copy]
    assert _dump(copy) == before
    with closing(sqlite3.connect(copy)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (4,)


def test_trading_accounts_schema_step_keeps_one_copy(tmp_path):
    path = tmp_path / "trading-accounts.sqlite3"
    store = TradingStore(path)
    store._conn.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
    store.close()
    before = _dump(path)

    for _ in range(2):
        TradingStore(path).close()

    copy = tmp_path / "trading-accounts.sqlite3.pre-trading-accounts-v3-to-v5.sqlite"
    assert _copies(path) == [copy]
    assert _dump(copy) == before


def test_current_and_fresh_databases_keep_no_copy(tmp_path):
    TradingStore(tmp_path / "trading-accounts.sqlite3").close()
    TradingStore(tmp_path / "trading-accounts.sqlite3").close()
    ContinuousStrategyStore(tmp_path / "continuous-strategy.sqlite3").close()
    repository = BacktestRepository(tmp_path / "backtest.db")
    repository.open(now_ms=1)
    repository.close()
    assert not list(tmp_path.glob("*.pre-*"))
