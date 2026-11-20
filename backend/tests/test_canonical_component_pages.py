"""Session H127 pages read ``(*bar components, close_time)`` tuples instead of full rows.

The projection must return exactly the rows ``query_klines`` returns, the page
guard must decide exactly as the exact retained-size count does, and a composed
query must publish exactly what the full-row path publishes, including rows
whose values send the decoder down its slow path or fail it.
"""
from __future__ import annotations

import asyncio
import random
import sqlite3
import sys

import pytest

from app.core import config as core_config
from app.data_engine.data_manager import mixed_query
from app.data_engine.memory_budget import flat_rows_within, retained_size
from app.data_engine.series_identity import KlineSeriesIdentity
from app.data_engine.storage import klines_repo
from tests.test_mixed_history_session import CONTRACT, TARGET_WIDTH, history, manager_for, outcome

MINUTE = 60_000
COLUMNS = ("open_time", "open", "high", "low", "close", "volume", "quote_volume", "trades",
           "taker_buy_base", "taker_buy_quote", "source", "close_time")


def _value(rng):
    kind = rng.randrange(9)
    if kind == 0:
        return rng.randrange(-2 ** 70, 2 ** 70)
    if kind == 1:
        return rng.random() * 10 ** rng.randrange(0, 20)
    if kind == 2:
        return "x" * rng.randrange(0, 4000)
    if kind == 3:
        return b"y" * rng.randrange(0, 4000)
    if kind == 4:
        return None
    if kind == 5:
        return rng.random() < 0.5
    if kind == 6:
        return rng.randrange(0, 256)  # small cached ints are shared objects
    if kind == 7:
        return complex(rng.random(), 1)  # a leaf, but not a flat row value
    return (rng.random(),)  # nested container


@pytest.mark.parametrize("seed", range(40))
def test_tuple_page_guard_decides_as_the_exact_count(seed):
    rng = random.Random(seed)
    shared = "shared-" + "s" * rng.randrange(100)
    rows = []
    for _ in range(rng.randrange(0, 40)):
        width = rng.randrange(0, 14)
        row = [_value(rng) if rng.random() < 0.3 else rng.random() for _ in range(width)]
        if row and rng.random() < 0.5:
            row[-1] = shared
        rows.append(tuple(row))
    if rows and rng.random() < 0.3:
        rows.append(rows[0])  # the same tuple twice is counted once
    exact = retained_size((rows,))[0]
    getsizeof = sys.getsizeof
    bound = getsizeof(rows) + sum(map(getsizeof, rows)) + sum(getsizeof(v) for row in rows for v in row)
    for limit in {0, exact - 1, exact, exact + 1, bound - 1, bound, bound + 1, rng.randrange(0, 2 * bound + 2)}:
        assert flat_rows_within(rows, limit) == (exact <= limit), (limit, exact, bound)


def test_tuple_page_guard_counts_every_value():
    rows = [(1, "x" * 5000, b"y" * 3000, None, True), (2, "x" * 5000, None, None, False)]
    exact = retained_size((rows,))[0]
    assert exact > 8000
    assert not flat_rows_within(rows, exact - 1) and flat_rows_within(rows, exact)
    assert not flat_rows_within([("z" * 9000,)], 4096)


def _store(path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()


@pytest.mark.parametrize("seed", range(12))
def test_component_projection_returns_the_rows_of_query_klines(tmp_path, monkeypatch, seed):
    rng = random.Random(seed)
    _store(tmp_path / "k.sqlite", monkeypatch)
    other = KlineSeriesIdentity.for_exchange("binance")
    series = [("BTCUSDT", "1m"), ("BTCUSDT", "1h"), ("ETHUSDT", "1m")]
    for symbol, interval in series:
        width = 60 * MINUTE if interval == "1h" else MINUTE
        items = []
        for at in sorted(rng.sample(range(0, 600 * width, width), 300)):
            volume = rng.random() * 10
            items.append(dict(open_time=at, close_time=rng.choice([at + width - 1, at + width, None]),
                              open=100 + rng.random(), high=102.0, low=99.0, close=101.0, volume=volume,
                              quote_volume=rng.choice([None, volume * 100]), trades=rng.choice([None, 7]),
                              taker_buy_base=rng.choice([None, volume / 2]), taker_buy_quote=None))
        for source in ("backfill", "data_manager"):
            part = [item for item in items if (item["open_time"] // width) % 2 == (source == "backfill")]
            klines_repo.upsert_klines(symbol, interval, part, source=source, market_type="futures")
    # A futures row on another market and a spot row at the same opens must not leak in.
    klines_repo.upsert_klines("BTCUSDT", "1m", [dict(open_time=0, close_time=MINUTE - 1, open=1.0, high=1.0,
                              low=1.0, close=1.0, volume=1.0, quote_volume=None, trades=None,
                              taker_buy_base=None, taker_buy_quote=None)], source="backfill", market_type="spot")
    adapter = klines_repo.KlinesRepoAdapter()
    for _ in range(20):
        symbol, interval = rng.choice(series)
        width = 60 * MINUTE if interval == "1h" else MINUTE
        start = rng.randrange(0, 600) * width
        end = start + rng.randrange(0, 300) * width
        limit = rng.randrange(1, 300)
        full = klines_repo.query_klines(symbol, interval, start, end, limit, "ASC",
                                        market_type="futures", series_identity=other)
        compact = adapter.query_canonical_components(symbol, interval, start, end, limit,
                                                     market_type="futures", series_identity=other)
        assert compact == [tuple(row[name] for name in COLUMNS) for row in full]
        assert all(type(row) is tuple for row in compact)


def _corrupt(path, rng, how):
    """Values SQLite can hold that the component decoder must not accept differently."""
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT interval, open_time FROM klines WHERE symbol='BTCUSDT'").fetchall()
        for interval, opened in rng.sample(rows, min(len(rows), 3)):
            set_sql = {
                "close_time": "close_time = close_time + 1",
                "null_close": "close_time = NULL",
                "text_price": "open = 'not a price'",
                "negative_volume": "volume = -1.0",
                "fractional_trades": "trades = 2.5",
                "infinite_quote": "quote_volume = 1e999",
                "text_source": "source = 'manual_csv_import'",
            }[how]
            conn.execute(f"UPDATE klines SET {set_sql} WHERE symbol='BTCUSDT' AND interval=? AND open_time=?",
                         (interval, opened))


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("how", ["none", "close_time", "null_close", "text_price", "negative_volume",
                                 "fractional_trades", "infinite_quote", "text_source"])
def test_session_component_pages_publish_exactly_the_full_row_result(tmp_path, monkeypatch, seed, how):
    targets = 4
    stop = targets * TARGET_WIDTH
    rows = history(seed, targets)
    monkeypatch.setattr(mixed_query, "SESSION_READS", True)
    results, compact_pages = {}, {}
    for full in (False, True):
        path = tmp_path / f"{full}.sqlite"
        manager = manager_for(path, rows, monkeypatch)
        if how != "none":
            _corrupt(path, random.Random(seed), how)
        engine = manager.query_engine
        # Without the projection (None), session pages read full rows.
        original = (lambda *args: None) if full else engine._read_canonical_history_components
        pages = []

        def counted(*args, original=original, pages=pages):
            rows = original(*args)
            pages.append(rows is not None)
            return rows

        monkeypatch.setattr(engine, "_read_canonical_history_components", counted)
        try:
            try:
                result = manager.query_composed("BTCUSDT", "10007m", start_ms=0, end_ms=stop - 1, limit=targets,
                    market_type="futures", composition_contract=CONTRACT,
                    min_revision=engine.storage.revision_store.head())
            except ValueError as exc:
                # Values no decoder accepts fail the query the same way on both paths.
                results[full] = ("raised", type(exc), str(exc))
            else:
                results[full] = outcome(result, manager, stop)
        finally:
            asyncio.run(manager.shutdown())
        assert manager.memory_budget.snapshot()["reserved_bytes"] == 0
        compact_pages[full] = pages
    # The comparison is meaningful: one side read tuples, the other full rows.
    assert compact_pages[False] and all(compact_pages[False])
    assert compact_pages[True] and not any(compact_pages[True])
    assert results[False] == results[True]
