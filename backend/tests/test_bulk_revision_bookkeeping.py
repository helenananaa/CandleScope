"""Per-batch revision bookkeeping must leave exactly what the per-row triggers leave.

The same randomized write history runs twice, once with batch bookkeeping and
once with the original row triggers, and every revision table is compared
exactly: clock, block receipts, range spans with their ids and sequence,
series heads, readbacks, deletion permissions and prefix watches.
"""
from __future__ import annotations

import random
import sqlite3

import pytest

from app.data_engine.storage import bulk_revisions, klines_repo, revisions
from app.data_engine.storage.revisions import mutation_mode

MINUTE = 60_000
NATIVE = "backfill_rest_verified"
DERIVED = "backfill_aggregated"
TABLES = {
    "klines": "SELECT exchange, market_type, symbol, interval, open_time, close_time, open, high, low, close, "
              "volume, quote_volume, trades, taker_buy_base, taker_buy_quote, source FROM klines "
              "ORDER BY exchange, market_type, symbol, interval, open_time",
    "clock": "SELECT * FROM kline_revision_clock",
    "blocks": "SELECT * FROM kline_block_changes ORDER BY revision",
    "spans": "SELECT * FROM kline_series_range_changes ORDER BY span_id",
    "sequence": "SELECT * FROM sqlite_sequence WHERE name='kline_series_range_changes'",
    "series": "SELECT * FROM kline_series_changes ORDER BY exchange, market_type, symbol, interval",
    "readback": "SELECT * FROM kline_history_readback ORDER BY exchange, market_type, symbol, interval",
    "permissions": "SELECT * FROM kline_delete_permissions ORDER BY exchange, market_type, symbol, interval",
    "derived": "SELECT * FROM kline_derived_series ORDER BY exchange, market_type, symbol, interval",
    "watches": "SELECT owner, version, dirty_from_ms, dirty_through_ms FROM kline_prefix_watches ORDER BY owner",
    "invalidation": "SELECT * FROM kline_projection_invalidation",
    "journal": "SELECT COUNT(*) FROM kline_bulk_journal",
}


def bars(opens, width, close=100.0, volume=10):
    return [dict(open_time=t, close_time=t + width - 1, open=100, high=250, low=50, close=close,
                 volume=volume, quote_volume=1000, trades=10, taker_buy_base=5, taker_buy_quote=500)
            for t in opens]


def history(seed, steps):
    choose = random.Random(seed)
    widths = {"1m": MINUTE, "5m": 5 * MINUTE, "15m": 15 * MINUTE}
    derived = {"7m": 7 * MINUTE, "13m": 13 * MINUTE, "89m": 89 * MINUTE}
    ops = []
    for step in range(steps):
        kind = choose.choices(["native", "derived", "delete", "mode", "archive"], [10, 3, 1, 1, 2])[0]
        symbol = choose.choice(["BTCUSDT", "BTCUSDT", "ETHUSDT"])
        if kind == "native":
            interval = choose.choice(list(widths))
            width = widths[interval]
            start = choose.randrange(0, 400) * width
            count = choose.choice([1, 2, 3, 8, 40, 300])
            stride = choose.choice([1, 1, 1, 2, 3])
            opens = [start + i * stride * width for i in range(count)]
            if choose.random() < 0.2:
                opens = list(reversed(opens))
            if choose.random() < 0.2:
                opens += opens[: max(1, len(opens) // 4)]
            ops.append(("native", symbol, interval, width, opens, choose.choice([100.0, 101.0, 102.0]),
                        choose.choice([NATIVE, "backfill", "data_manager"])))
        elif kind == "derived":
            interval = choose.choice(list(derived))
            width = derived[interval]
            start = choose.randrange(0, 120) * width
            ops.append(("derived", symbol, interval, width, [start + i * width for i in range(choose.choice([1, 5, 30]))],
                        choose.choice([100.0, 103.0]), DERIVED))
        elif kind == "delete":
            interval = choose.choice(list(widths) + list(derived))
            start = choose.randrange(0, 300) * MINUTE
            ops.append(("delete", symbol, interval, start, start + choose.choice([5, 60, 600]) * MINUTE))
        elif kind == "mode":
            interval = choose.choice(list(widths))
            width = widths[interval]
            start = choose.randrange(0, 400) * width
            ops.append(("mode", symbol, interval, width, [start + i * width for i in range(choose.choice([3, 20]))],
                        choose.choice(["bar_delivery", "retention", "derived_materialization"])))
        else:
            # Archive objects: reimporting a key with another digest also drops derived bars.
            interval = choose.choice(["1m", "15m"])
            width = widths[interval]
            start = choose.randrange(0, 40) * 10 * width
            key = choose.randrange(4)
            ops.append(("archive", symbol, interval, width, [start + i * width for i in range(choose.choice([10, 120]))],
                        key, choose.choice(["a", "b"]) * 64))
    return ops


def replay(path, ops, *, bulk):
    bulk_revisions.ENABLED = bulk
    klines_repo.KLINES_DB_PATH = path
    klines_repo.init_klines_storage()
    store = klines_repo.KlinesRepoAdapter()
    with klines_repo._connect() as conn:
        # A watch over part of the history; its version counts every source row.
        conn.execute("INSERT INTO kline_prefix_watches VALUES ('watch', 'i', 'binance', 'spot', 'BTCUSDT', '*', "
                     "'binance', 'binance', 'crypto', 'native', 'raw', 'continuous', 'base_asset', "
                     "0, ?, 0, 0, 0, 0, 0, 0, 0, NULL, NULL)", (200 * MINUTE,))
    for op in ops:
        if op[0] in ("native", "derived"):
            _, symbol, interval, width, opens, close, source = op
            klines_repo.upsert_klines(symbol, interval, bars(opens, width, close), source=source)
        elif op[0] == "archive":
            _, symbol, interval, width, opens, key, digest = op
            rows = bars(opens, width, 105.0)
            klines_repo.import_history_archive(symbol, interval, rows, {
                "object_key": f"bench:{symbol}:{interval}:{key}", "provider_id": "binance-public-kline-v1",
                "exchange": "binance", "market_type": "spot", "symbol": symbol, "interval": interval,
                "granularity": "monthly", "period": str(key), "start_ms": opens[0],
                "end_ms": opens[-1] + width - 1, "content_sha256": digest, "provider_checksum": digest,
                "source_url": "https://data.binance.vision/example.zip", "row_count": len(rows),
                "revision_changed": False, "import_version": "history-archive-import.v1"},
                exchange="binance", market_type="spot")
        elif op[0] == "delete":
            _, symbol, interval, start, end = op
            store.delete_bars(symbol, interval, start, end)
        else:
            _, symbol, interval, width, opens, mode = op
            with klines_repo._connect() as conn, mutation_mode(conn, mode):
                klines_repo.upsert_klines(symbol, interval, bars(opens, width, 104.0), source=NATIVE,
                                          _connection=conn)
    with sqlite3.connect(path) as conn:
        return {name: conn.execute(sql).fetchall() for name, sql in TABLES.items()}


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "unused.sqlite")
    # Small receipt windows exercise every prune path inside one batch.
    monkeypatch.setattr(revisions, "BLOCK_CHANGE_WINDOW", 64)
    monkeypatch.setattr(revisions, "SERIES_RANGE_SPAN_WINDOW", 48)
    yield
    bulk_revisions.ENABLED = True


@pytest.mark.parametrize("seed", range(6))
def test_batch_bookkeeping_matches_row_triggers_exactly(tmp_path, windows, seed):
    ops = history(seed, 120)
    expected = replay(tmp_path / "rows.sqlite", ops, bulk=False)
    actual = replay(tmp_path / "batch.sqlite", ops, bulk=True)
    assert actual["journal"] == [(0,)]
    for name in TABLES:
        assert actual[name] == expected[name], name
    # The history really exercised dependents, pruning and span merging.
    assert len(expected["blocks"]) == 64 and expected["spans"] and expected["derived"]


def test_batches_use_the_journal_and_fall_back_when_empty_coverage_could_change(tmp_path, windows, monkeypatch):
    calls = []
    original = bulk_revisions._apply

    def counted(conn, values, state):
        calls.append(values[3])
        return original(conn, values, state)

    monkeypatch.setattr(bulk_revisions, "_apply", counted)
    replay(tmp_path / "used.sqlite", [("native", "BTCUSDT", "1m", MINUTE, list(range(0, 40 * MINUTE, MINUTE)),
                                        100.0, NATIVE)], bulk=True)
    assert calls == ["1m"]
    calls.clear()
    from app.data_engine.storage import trade_empty_buckets
    klines_repo.KLINES_DB_PATH = tmp_path / "empty.sqlite"
    klines_repo.init_klines_storage()
    trade_empty_buckets.record("kraken", "spot", "BTC/USD", "1s", [(100_000, 110_000)])
    klines_repo.upsert_klines("BTC/USD", "1s", bars(range(0, 40_000, 1000), 1000), source=NATIVE,
                              exchange="kraken", market_type="spot")
    assert calls == []


def test_dependent_lookup_stays_local_for_long_batches():
    # A month of archived minutes against a month of derived bars: each row
    # may only look at the bars near it, or the batch becomes quadratic.
    import time
    width, rows = 89 * MINUTE, 20_000
    opens = [i * width for i in range(20_000)]
    items = [[opened, opened + width - 1, index, False] for index, opened in enumerate(opens)]
    candidates = [(2 * width, opens, items)]
    started = time.perf_counter()
    hits = sum(bulk_revisions._deletes_dependents(candidates, i * MINUTE, i * MINUTE + MINUTE - 1)
               for i in range(rows))
    assert hits == rows
    assert time.perf_counter() - started < 2.0
