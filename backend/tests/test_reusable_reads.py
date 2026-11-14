"""A borrowed read connection must behave like the fresh one it replaces."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import threading

import pytest

from app.data_engine.storage import klines_repo
from app.data_engine.storage.sqlite_runtime import ReusableReads

MINUTE = 60_000
START = 1_700_000_040_000


def make_database(path, value=1):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t(v INTEGER)")
    connection.executemany("INSERT INTO t VALUES (?)", [(value,), (value + 1,)])
    connection.commit()
    connection.close()
    return path


def write(path, value):
    connection = sqlite3.connect(path)
    connection.execute("INSERT INTO t VALUES (?)", (value,))
    connection.commit()
    connection.close()


class Opener:
    def __init__(self, path):
        self.path = path
        self.opened = 0

    def __call__(self):
        self.opened += 1
        return sqlite3.connect(self.path, check_same_thread=False)


@pytest.fixture
def database(tmp_path):
    return make_database(tmp_path / "reads.sqlite")


@pytest.fixture
def reads(database):
    opener = Opener(database)
    pool = ReusableReads(opener, lambda: opener.path)
    pool.opener = opener
    yield pool
    pool.close_idle()


def total(connection):
    return connection.execute("SELECT SUM(v) FROM t").fetchone()[0]


def closed(connection):
    try:
        connection.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


def test_sequential_reads_share_one_connection_and_see_new_commits(reads, database):
    with reads.reading() as first:
        assert total(first) == 3
    write(database, 10)
    with reads.reading() as second:
        assert second is first
        assert total(second) == 13
    assert reads.opener.opened == 1


def test_a_partly_fetched_result_does_not_pin_the_old_snapshot(reads, database):
    with reads.reading() as connection:
        # Two rows match; reading only the first leaves the statement unfinished
        # until its temporary cursor is released at the end of the expression.
        assert connection.execute("SELECT v FROM t ORDER BY v").fetchone()[0] == 1
    write(database, 10)
    with reads.reading() as connection:
        assert total(connection) == 13
    assert reads.opener.opened == 1


def test_write_ahead_log_readers_see_each_commit(tmp_path):
    # The product database runs in WAL mode, where a pinned snapshot would
    # show as stale data instead of a blocked writer.
    path = make_database(tmp_path / "wal.sqlite")
    setup = sqlite3.connect(path)
    assert setup.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    setup.close()
    opener = Opener(path)
    reads = ReusableReads(opener, lambda: opener.path)
    seen = []
    for value in (10, 20, 30):
        with reads.reading() as connection:
            connection.execute("SELECT v FROM t ORDER BY v").fetchone()
            seen.append(total(connection))
        write(path, value)
    with reads.reading() as connection:
        seen.append(total(connection))
    assert seen == [3, 13, 33, 63] and opener.opened == 1
    reads.close_idle()


def test_row_shape_is_chosen_per_read(reads):
    with reads.reading() as connection:
        assert connection.execute("SELECT v FROM t ORDER BY v").fetchone()["v"] == 1
    with reads.reading(rows=False) as connection:
        assert connection.execute("SELECT v FROM t ORDER BY v").fetchone() == (1,)
    with reads.reading() as connection:
        assert connection.execute("SELECT v FROM t ORDER BY v").fetchone()["v"] == 1
    assert reads.opener.opened == 1


def test_nested_reads_hold_separate_connections(reads):
    with reads.reading() as outer:
        with reads.reading() as inner:
            assert inner is not outer
            assert total(inner) == total(outer) == 3
    assert reads.opener.opened == 2
    # One idle slot per thread: the second connection to return is closed.
    assert not closed(inner) and closed(outer)
    with reads.reading() as again:
        assert again is inner


def test_a_failed_read_closes_its_connection(reads):
    with pytest.raises(RuntimeError):
        with reads.reading() as broken:
            raise RuntimeError("reader failed")
    assert closed(broken)
    with reads.reading() as fresh:
        assert fresh is not broken and total(fresh) == 3
    assert reads.opener.opened == 2


def test_an_open_transaction_is_never_handed_to_the_next_reader(reads, database):
    with reads.reading() as holding:
        holding.execute("BEGIN")
        assert total(holding) == 3
    assert closed(holding)
    write(database, 10)
    with reads.reading() as fresh:
        assert total(fresh) == 13


def test_writes_through_a_borrowed_connection_are_refused(reads, database):
    with reads.reading() as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO t VALUES (99)")
    with reads.reading() as connection:
        assert total(connection) == 3


def test_another_file_at_the_same_path_gets_a_new_connection(reads, database, tmp_path):
    with reads.reading() as first:
        assert total(first) == 3
    os.replace(make_database(tmp_path / "replacement.sqlite", value=100), database)
    with reads.reading() as second:
        assert second is not first and closed(first)
        assert total(second) == 201


def test_a_changed_path_gets_a_new_connection(reads, tmp_path):
    with reads.reading() as first:
        assert total(first) == 3
    reads.opener.path = make_database(tmp_path / "other.sqlite", value=100)
    with reads.reading() as second:
        assert second is not first and closed(first)
        assert total(second) == 201


def test_a_missing_file_is_not_kept_until_it_exists(tmp_path):
    opener = Opener(tmp_path / "created-on-open.sqlite")
    reads = ReusableReads(opener, lambda: opener.path)
    with reads.reading() as creating:
        assert creating.execute("SELECT 1").fetchone()[0] == 1
    assert closed(creating)
    with reads.reading() as second:
        pass
    with reads.reading() as third:
        assert third is second
    assert opener.opened == 2
    reads.close_idle()


def test_each_thread_keeps_its_own_connection(reads):
    seen = {}

    def read(name):
        with reads.reading() as connection:
            seen[name] = (connection, total(connection))

    read("main")
    worker = threading.Thread(target=read, args=("worker",))
    worker.start()
    worker.join()
    assert seen["worker"][0] is not seen["main"][0] and seen["worker"][1] == 3
    with reads.reading() as again:
        assert again is seen["main"][0]
    assert reads.opener.opened == 2


def test_close_idle_releases_idle_and_retires_borrowed_connections(reads):
    with reads.reading() as borrowed:
        with reads.reading() as idle:
            pass
        assert reads.close_idle() == 1
        assert closed(idle) and total(borrowed) == 3
    # Borrowed across the call: closed on return instead of becoming idle.
    assert closed(borrowed)
    assert reads.close_idle() == 0
    with reads.reading() as fresh:
        assert total(fresh) == 3
    assert reads.opener.opened == 3


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    opened = []
    connect = klines_repo._connect

    def counting(**options):
        opened.append(options)
        return connect(**options)

    monkeypatch.setattr(klines_repo, "_connect", counting)
    yield opened
    klines_repo.close_idle_reads()


def bar(index, close=100.0):
    open_time = START + index * MINUTE
    return dict(open_time=open_time, close_time=open_time + MINUTE - 1, open=100, high=250, low=50, close=close,
                volume=10, quote_volume=1000, trades=10, taker_buy_base=5, taker_buy_quote=500)


def read_everything(store):
    return (
        store.head(),
        len(klines_repo.query_klines("BTCUSDT", "1m")),
        klines_repo.KlinesRepoAdapter().count_bars("BTCUSDT", "1m", START, START + 10 * MINUTE),
        klines_repo._query_bars_range_presence(
            "BTCUSDT", "1m", ((START, START + 10 * MINUTE),), exchange="binance", market_type="spot"),
        len(klines_repo.query_kline_bar_components("BTCUSDT", "1m")),
        len(store.changes_since(0)["changes"]),
        store.read_versions([klines_repo.series_values("BTCUSDT", "1m", "binance", "spot")])[1],
    )


def test_storage_reads_stop_opening_connections_but_stay_current(storage):
    store = klines_repo.KlinesRepoAdapter().revision_store
    klines_repo.upsert_klines("BTCUSDT", "1m", [bar(0)], source="backfill_rest_verified")
    before = read_everything(store)
    assert before[1:5] == (1, 1, [True], 1)
    opened = len(storage)
    for _ in range(25):
        assert read_everything(store) == before
    # 175 reads, and neither the bar reader nor the revision reader reopened.
    assert len(storage) == opened

    klines_repo.upsert_klines("BTCUSDT", "1m", [bar(1)], source="backfill_rest_verified")
    after = read_everything(store)
    assert after[0] > before[0] and after[1:3] == (2, 2) and after[4] == 2
    assert after[6] != before[6]


def test_the_async_adapter_shares_the_readers_across_new_store_objects(storage):
    klines_repo.upsert_klines("BTCUSDT", "1m", [bar(0), bar(1)], source="backfill_rest_verified")
    adapter = klines_repo.AsyncKlinesRepoAdapter()

    async def scenario():
        counts = [await adapter.count_bars("BTCUSDT", "1m", START, START + 10 * MINUTE) for _ in range(12)]
        # Each access builds a new RevisionStore; the readers behind it persist.
        heads = [adapter.revision_store.head() for _ in range(12)]
        return counts, heads

    counts, heads = asyncio.run(scenario())
    assert counts == [2] * 12 and len(set(heads)) == 1
    # One write, at most one bar reader per storage worker, one revision reader.
    from app.core import config
    assert len(storage) <= 1 + config.STORAGE_THREAD_WORKERS + 1


def test_initializing_storage_releases_idle_readers(storage):
    store = klines_repo.KlinesRepoAdapter().revision_store
    klines_repo.upsert_klines("BTCUSDT", "1m", [bar(0)], source="backfill_rest_verified")
    read_everything(store)
    klines_repo.init_klines_storage()
    assert klines_repo.close_idle_reads() == 0
    assert read_everything(store)[1] == 1
