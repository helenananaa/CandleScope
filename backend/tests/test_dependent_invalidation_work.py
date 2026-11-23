"""Derived invalidation reads registered derived series, not the whole family.

Every source mutation deletes the overlapping bars of the other derived
intervals in its semantic family. That set must stay exact while the work per
mutated row stays independent of how many native bars the family holds.
"""
from __future__ import annotations

import random

import pytest

from app.data_engine.storage import klines_repo, native_empty_seconds, trade_empty_buckets
from app.data_engine.storage.revisions import IDENTITY_COLUMNS

MINUTE = 60_000
SECOND = 1_000
START = 1_700_000_040_000
NATIVE = "backfill_rest_verified"
DERIVED = "backfill_aggregated"
WIDTHS = {"1m": MINUTE, "5m": 5 * MINUTE, "7m": 7 * MINUTE, "13m": 13 * MINUTE}
SPAN_MINUTES = 182


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def bars(opens, width, close=100.0):
    return [dict(open_time=open_time, close_time=open_time + width - 1, open=100, high=250, low=50,
                 close=close, volume=10, quote_volume=1000, trades=10, taker_buy_base=5, taker_buy_quote=500)
            for open_time in opens]


def write(interval, opens, *, width, source=NATIVE, symbol="BTCUSDT", close=100.0, **series):
    return klines_repo.upsert_klines(symbol, interval, bars(opens, width, close), source=source, **series)


def stored():
    """Every physical bar as {(market, symbol, interval, open): (close_time, source)}."""
    with klines_repo._connect() as conn:
        return {(row["market_type"], row["symbol"], row["interval"], row["open_time"]):
                (row["close_time"], row["source"]) for row in conn.execute("SELECT * FROM klines")}


def without_dependents(state, market, symbol, interval, open_time, close_time):
    """The documented contract: other derived intervals, same family, overlapping."""
    return {key: value for key, value in state.items() if not (
        value[1] == DERIVED and key[:2] == (market, symbol) and key[2] != interval
        and key[3] <= close_time and value[0] >= open_time)}


def grid(interval, *, skip=0):
    step = WIDTHS[interval]
    opens = range(START, START + SPAN_MINUTES * MINUTE, step)
    return [open_time for index, open_time in enumerate(opens) if not skip or index % skip]


def test_source_mutations_delete_exactly_the_overlapping_derived_bars(storage):
    # Holes leave room for later inserts. A second native interval, another
    # symbol and another market must never be read as dependents.
    write("1m", grid("1m", skip=9), width=MINUTE)
    write("5m", grid("5m", skip=4), width=5 * MINUTE)
    for series in ({}, {"symbol": "ETHUSDT"}, {"market_type": "futures"}):
        for interval in ("7m", "13m"):
            write(interval, grid(interval), width=WIDTHS[interval], source=DERIVED, **series)
    initial = state = stored()
    choose = random.Random(126)
    holes = {interval: sorted(set(grid(interval)) - set(grid(interval, skip=skip)))
             for interval, skip in (("1m", 9), ("5m", 4))}
    present = sorted(set(grid("1m", skip=9)))

    for step in range(24):
        operation = ("insert", "update", "delete", "insert_other_native", "derived_update")[step % 5]
        if operation == "insert":
            interval, open_time = "1m", holes["1m"].pop(choose.randrange(len(holes["1m"])))
            write(interval, [open_time], width=MINUTE)
            state = {**state, ("spot", "BTCUSDT", interval, open_time): (open_time + MINUTE - 1, NATIVE)}
        elif operation == "update":
            interval, open_time = "1m", choose.choice(present)
            write(interval, [open_time], width=MINUTE, close=200.0 + step)
        elif operation == "delete":
            interval, open_time = "1m", present.pop(choose.randrange(len(present)))
            with klines_repo._connect() as conn:
                conn.execute("DELETE FROM klines WHERE symbol='BTCUSDT' AND market_type='spot' "
                             "AND interval='1m' AND open_time=?", (open_time,))
            state = {key: value for key, value in state.items() if key != ("spot", "BTCUSDT", interval, open_time)}
        elif operation == "insert_other_native":
            interval, open_time = "5m", holes["5m"].pop(choose.randrange(len(holes["5m"])))
            write(interval, [open_time], width=5 * MINUTE)
            state = {**state, ("spot", "BTCUSDT", interval, open_time): (open_time + 5 * MINUTE - 1, NATIVE)}
        else:
            # A derived series is not a source of its sibling projections.
            survivors = sorted(key[3] for key in state if key[:3] == ("spot", "BTCUSDT", "7m"))
            if not survivors:
                continue
            write("7m", [choose.choice(survivors)], width=7 * MINUTE, source=DERIVED, close=300.0 + step)
            assert stored() == state
            continue
        state = without_dependents(state, "spot", "BTCUSDT", interval, open_time, open_time + WIDTHS[interval] - 1)
        assert stored() == state, operation

    remaining = {key for key, value in state.items() if value[1] == DERIVED}
    original = {key for key, value in initial.items() if value[1] == DERIVED}
    # The scenario both invalidated and retained bars of the mutated family.
    invalidated = original - remaining
    assert invalidated and all(key[:2] == ("spot", "BTCUSDT") for key in invalidated)
    assert any(key[:2] == ("spot", "BTCUSDT") for key in remaining)
    assert {key for key in original if key[:2] != ("spot", "BTCUSDT")} <= remaining


def vm_steps(conn, sql, parameters=()):
    """SQLite virtual-machine instructions, including trigger programs."""
    steps = 0

    def count():
        nonlocal steps
        steps += 1
        return 0

    conn.set_progress_handler(count, 1)
    try:
        conn.execute(sql, parameters)
    finally:
        conn.set_progress_handler(None, 1)
    return steps


def seed_family(symbol, native_bars, *, native_interval="1m", derived_interval="7m", width=MINUTE, **series):
    write(native_interval, range(START, START + native_bars * width, width), width=width, symbol=symbol, **series)
    write(derived_interval, range(START, START + 21 * width, 7 * width), width=7 * width, source=DERIVED,
          symbol=symbol, **series)


def source_row(conn, symbol, interval, open_time):
    return dict(conn.execute("SELECT * FROM klines WHERE symbol=? AND interval=? AND open_time=?",
                             (symbol, interval, open_time)).fetchone())


def identity_match(row):
    names = (*IDENTITY_COLUMNS, "open_time")
    return " AND ".join(f"{name}=?" for name in names), tuple(row[name] for name in names)


def source_mutation_steps(symbol, native_bars, operation):
    with klines_repo._connect() as conn:
        last = START + (native_bars - 1) * MINUTE
        row = source_row(conn, symbol, "1m", last)
        where, key = identity_match(row)
        if operation == "insert":
            row.update(open_time=last + MINUTE, close_time=last + 2 * MINUTE - 1)
            return vm_steps(conn, f"INSERT INTO klines ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                            tuple(row.values()))
        if operation == "update":
            return vm_steps(conn, f"UPDATE klines SET close=close+1 WHERE {where}", key)
        return vm_steps(conn, f"DELETE FROM klines WHERE {where}", key)


@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_source_mutation_work_does_not_grow_with_native_family_size(storage, operation):
    small, large = 64, 4096
    seed_family("SMALLUSDT", small)
    seed_family("LARGEUSDT", large)
    baseline = source_mutation_steps("SMALLUSDT", small, operation)
    measured = source_mutation_steps("LARGEUSDT", large, operation)
    # Sixty-four times more native bars may not buy sixty-four times the work.
    assert measured <= baseline + baseline // 4, (baseline, measured)


def empty_coverage_case(table):
    if table == "trade_empty_buckets":
        return dict(exchange="kraken", small="SML/USD", large="LRG/USD",
                    insert="INSERT INTO trade_empty_buckets VALUES ('kraken','spot',?,'1s',?,?)",
                    delete="DELETE FROM trade_empty_buckets WHERE exchange='kraken' AND market_type='spot' "
                           "AND symbol=? AND interval='1s' AND start_ms=?")
    return dict(exchange="upbit", small="SML/KRW", large="LRG/KRW",
                insert="INSERT INTO native_empty_seconds VALUES (?,?,?)",
                delete="DELETE FROM native_empty_seconds WHERE symbol=? AND start_ms=?")


@pytest.mark.parametrize("table", ["trade_empty_buckets", "native_empty_seconds"])
@pytest.mark.parametrize("operation", ["insert", "delete"])
def test_empty_coverage_work_does_not_grow_with_native_family_size(storage, table, operation):
    case = empty_coverage_case(table)
    sizes = {case["small"]: 64, case["large"]: 4096}
    steps = {}
    for symbol, native_bars in sizes.items():
        seed_family(symbol, native_bars, native_interval="1s", derived_interval="7s", width=SECOND,
                    exchange=case["exchange"])
        empty_from = START + (native_bars + 10) * SECOND
        with klines_repo._connect() as conn:
            inserted = vm_steps(conn, case["insert"], (symbol, empty_from, empty_from + 5 * SECOND))
            steps[symbol] = inserted if operation == "insert" else vm_steps(conn, case["delete"], (symbol, empty_from))
    baseline, measured = steps[case["small"]], steps[case["large"]]
    assert measured <= baseline + baseline // 4, (baseline, measured)


@pytest.mark.parametrize("exchange", ["kraken", "upbit"])
def test_empty_coverage_deletes_exactly_the_overlapping_derived_bars(storage, exchange):
    symbol, other = ("BTC/USD", "ETH/USD") if exchange == "kraken" else ("BTC/KRW", "ETH/KRW")
    # Native seconds stop before the proven-empty range; derived bars cross it.
    write("1s", range(START, START + 20 * SECOND, SECOND), width=SECOND, symbol=symbol, exchange=exchange)
    write("5s", range(START, START + 70 * SECOND, 5 * SECOND), width=5 * SECOND, symbol=symbol, exchange=exchange)
    for name in (symbol, other):
        write("7s", range(START, START + 70 * SECOND, 7 * SECOND), width=7 * SECOND, source=DERIVED,
              symbol=name, exchange=exchange)
    before = stored()
    empty_from, empty_to = START + 30 * SECOND, START + 40 * SECOND
    if exchange == "kraken":
        trade_empty_buckets.record(exchange, "spot", symbol, "1s", [(empty_from, empty_to)])
    else:
        native_empty_seconds.record(symbol, [(empty_from, empty_to)])
    expected = without_dependents(before, "spot", symbol, "1s", empty_from, empty_to)
    assert stored() == expected
    assert len(before) - len(expected) == 2  # the two 7s bars touching 30s..40s


@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_restart_replaces_an_older_dependents_trigger(storage, operation):
    seed_family("BTCUSDT", 64)
    with klines_repo._connect() as conn:
        conn.execute(f"DROP TRIGGER kline_dependents_{operation}")
        conn.execute(f"CREATE TRIGGER kline_dependents_{operation} AFTER {operation.upper()} ON klines "
                     "BEGIN SELECT 1; END")
    klines_repo.init_klines_storage()
    before = stored()
    if operation == "delete":
        with klines_repo._connect() as conn:
            conn.execute("DELETE FROM klines WHERE symbol='BTCUSDT' AND interval='1m' AND open_time=?", (START,))
        before.pop(("spot", "BTCUSDT", "1m", START))
        touched = START
    elif operation == "update":
        write("1m", [START], width=MINUTE, symbol="BTCUSDT", close=200.0)
        touched = START
    else:
        touched = START + 64 * MINUTE
        write("7m", [START + 63 * MINUTE], width=7 * MINUTE, source=DERIVED, symbol="BTCUSDT")
        before = stored()
        write("1m", [touched], width=MINUTE, symbol="BTCUSDT")
        before[("spot", "BTCUSDT", "1m", touched)] = (touched + MINUTE - 1, NATIVE)
    expected = without_dependents(before, "spot", "BTCUSDT", "1m", touched, touched + MINUTE - 1)
    assert stored() == expected
    assert len(expected) < len(before)
