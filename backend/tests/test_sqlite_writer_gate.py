"""Writers of one process queue on a gate instead of SQLite's sleeping busy handler."""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from app.data_engine.storage import sqlite_runtime
from app.data_engine.storage.sqlite_runtime import connect_coordinated, open_sqlite


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "gate.sqlite"
    with open_sqlite(path) as conn:
        conn.execute("CREATE TABLE t (k INTEGER PRIMARY KEY, v TEXT)")
    return path


def held(conn):
    return conn._gate_held


def test_gate_is_held_for_exactly_the_write_transaction(db):
    conn = open_sqlite(db)
    conn.execute("SELECT * FROM t").fetchall()
    assert not held(conn)
    conn.execute("INSERT INTO t VALUES (1, 'a')")
    assert held(conn) and conn.in_transaction
    conn.commit()
    assert not held(conn)
    conn.execute("BEGIN IMMEDIATE")
    assert held(conn)
    conn.rollback()
    assert not held(conn)
    with conn:
        conn.execute("UPDATE t SET v='b'")
        assert held(conn)
    assert not held(conn)
    conn.execute("BEGIN IMMEDIATE")
    conn.close()
    assert not held(conn)


def test_failed_statement_outside_a_transaction_releases_the_gate(db):
    conn = open_sqlite(db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO missing VALUES (1)")
    assert not held(conn)
    other = open_sqlite(db)
    other.execute("INSERT INTO t VALUES (2, 'x')")
    other.commit()


def test_a_second_writer_waits_for_the_first_and_both_commit(db):
    first = open_sqlite(db)
    first.execute("BEGIN IMMEDIATE")
    first.execute("INSERT INTO t VALUES (1, 'first')")
    before = sqlite_runtime.writer_gate_snapshot()["waits"]
    done = threading.Event()

    def second():
        conn = open_sqlite(db)
        conn.execute("INSERT INTO t VALUES (2, 'second')")
        conn.commit()
        conn.close()
        done.set()

    worker = threading.Thread(target=second)
    worker.start()
    time.sleep(0.2)
    assert not done.is_set()
    first.commit()
    worker.join(5)
    assert done.is_set()
    assert sqlite_runtime.writer_gate_snapshot()["waits"] > before
    with open_sqlite(db) as conn:
        assert [row[0] for row in conn.execute("SELECT k FROM t ORDER BY k")] == [1, 2]


def test_readers_do_not_wait_for_a_writer(db):
    writer = open_sqlite(db)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO t VALUES (1, 'w')")
    result = []
    reader = threading.Thread(target=lambda: result.append(
        open_sqlite(db).execute("SELECT COUNT(*) FROM t").fetchone()[0]))
    reader.start()
    reader.join(2)
    assert result == [0]
    writer.commit()


def test_a_nested_writer_on_the_same_thread_fails_like_before_instead_of_hanging(db):
    outer = open_sqlite(db)
    outer.execute("BEGIN IMMEDIATE")
    inner = connect_coordinated(str(db), timeout=0.2)
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        inner.execute("INSERT INTO t VALUES (9, 'nested')")
    assert time.monotonic() - started < 2
    inner.close()
    outer.rollback()


def test_a_zero_timeout_writer_does_not_wait_on_the_gate(db):
    holder = open_sqlite(db)
    holder.execute("BEGIN IMMEDIATE")
    errors = []

    def attempt():
        conn = connect_coordinated(str(db), timeout=0)
        try:
            conn.execute("INSERT INTO t VALUES (3, 'now')")
        except sqlite3.OperationalError as exc:
            errors.append(str(exc))
        finally:
            conn.close()

    worker = threading.Thread(target=attempt)
    started = time.monotonic()
    worker.start()
    worker.join(2)
    assert time.monotonic() - started < 2 and errors and "locked" in errors[0]
    holder.rollback()


@pytest.mark.parametrize("sql,write", [
    ("INSERT INTO t VALUES (1)", True), ("  -- note\n  update t set v=1", True),
    ("BEGIN IMMEDIATE", True), ("begin exclusive", True), ("BEGIN", False), ("BEGIN DEFERRED", False),
    ("SELECT 1", False), ("PRAGMA journal_mode=WAL", False),
    ("WITH a AS (SELECT 1) SELECT * FROM a", False), ("WITH a AS (SELECT 1) DELETE FROM t", True),
])
def test_write_statement_detection(sql, write):
    assert sqlite_runtime._starts_write(sql) is write


# Reusable connections: closing returns a connection that is equivalent to a new one.

POLICY = sqlite_runtime.SQLiteConnectionPolicy()


def reusable(path):
    return open_sqlite(path, policy=POLICY, reuse=True)


def test_closed_connection_is_reused_on_its_thread_only(db):
    first = reusable(db)
    first.close()
    second = reusable(db)
    assert second is first
    second.close()
    other = []
    worker = threading.Thread(target=lambda: other.append(reusable(db)))
    worker.start()
    worker.join(2)
    assert other[0] is not first
    other[0].close()
    sqlite_runtime.close_idle_connections()


def test_returned_connection_drops_unfinished_cursors_and_sees_new_commits(db):
    with open_sqlite(db) as setup:
        setup.executemany("INSERT INTO t VALUES (?, 'x')", [(i,) for i in range(5)])
    conn = reusable(db)
    cursor = conn.execute("SELECT k FROM t ORDER BY k")
    assert cursor.fetchone()[0] == 0  # the statement is still active
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        cursor.fetchone()
    writer = open_sqlite(db)
    writer.execute("INSERT INTO t VALUES (99, 'new')")
    writer.commit()
    again = reusable(db)
    assert again is conn
    assert again.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 6
    again.close()
    sqlite_runtime.close_idle_connections()


def test_connection_left_in_a_transaction_is_rolled_back_and_not_reused(db):
    conn = reusable(db)
    conn.execute("INSERT INTO t VALUES (1, 'uncommitted')")
    conn.close()
    fresh = reusable(db)
    assert fresh is not conn
    assert fresh.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    fresh.close()
    sqlite_runtime.close_idle_connections()


def test_per_use_state_is_reset_before_reuse(db):
    conn = reusable(db)
    conn.execute("PRAGMA query_only=ON")
    conn.set_progress_handler(lambda: 1, 1)
    conn.row_factory = None
    conn.close()
    again = reusable(db)
    assert again is conn and again.row_factory is sqlite3.Row
    again.execute("INSERT INTO t VALUES (7, 'writable')")
    again.commit()
    again.close()
    sqlite_runtime.close_idle_connections()


def test_a_replaced_database_file_is_not_served_by_an_idle_connection(db, tmp_path):
    conn = reusable(db)
    conn.close()
    replacement = tmp_path / "replacement.sqlite"
    other = sqlite3.connect(replacement)
    other.execute("CREATE TABLE t (k INTEGER PRIMARY KEY, v TEXT)")
    other.execute("INSERT INTO t VALUES (42, 'replacement')")
    other.commit()
    other.close()
    sqlite_runtime.close_idle_connections()
    conn = reusable(db)
    conn.close()
    for sibling in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        sibling.unlink(missing_ok=True)
    replacement.rename(db)
    fresh = reusable(db)
    assert fresh is not conn
    assert fresh.execute("SELECT k FROM t").fetchall()[0][0] == 42
    fresh.close()
    assert sqlite_runtime.close_idle_connections() == 1


def test_revision_checks_and_source_page_lookups_reuse_this_threads_connection(tmp_path, monkeypatch):
    # Fence captures and source-journal page lookups ran once per chunk and
    # page, each parsing the whole K-line schema on a fresh connection.
    from contextlib import closing
    from app.data_engine.ingestion.models import StreamDescriptor, StreamType
    from app.data_engine.storage import kline_sources, klines_repo

    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "klines.sqlite")
    klines_repo.init_klines_storage()
    sqlite_runtime.close_idle_connections()
    store = klines_repo.KlinesRepoAdapter().revision_store
    opened = []
    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: opened.append(a[0]) or real_connect(*a, **k))
    descriptor = StreamDescriptor(exchange="binance", market_type="futures", symbol="BTCUSDT",
                                  stream_type=StreamType.KLINE, interval="1m")
    for _ in range(5):
        store.acquisition()
        with closing(store.connect()) as conn, conn:
            conn.execute("BEGIN")
            conn.execute("SELECT COUNT(*) FROM klines").fetchone()
        assert kline_sources.history_projection_inputs(descriptor, 0, 60_000 * 9, 60_000) is None
    assert len(opened) <= 2
    # A scoped live-input read still owns, and really closes, its connection.
    scoped = store.scoped_version_reader()
    scoped.read_versions(())
    held = scoped._connection
    scoped.close()
    with pytest.raises(sqlite3.ProgrammingError):
        held.execute("SELECT 1")
    sqlite_runtime.close_idle_connections()
