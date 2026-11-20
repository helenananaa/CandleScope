"""Per-batch revision bookkeeping for one series' K-line upsert.

The row triggers in ``revisions`` record every changed candle: one revision,
one block receipt, a range span extension or a new span, the series head and
the history readback, after deleting the derived bars the candle can affect.
That costs several statements per row inside the single writer's
transaction. For a batch, the ``bulk`` flag makes the bookkeeping and
dependents triggers stand aside while lightweight capture triggers journal
each changed row in statement order; ``_apply`` then reproduces exactly what
the row triggers would have written, row by row in memory and in a few
set-based statements.

SQLite fires the dependents trigger before the bookkeeping trigger of the
same row, so a row whose dependents delete anything is handled at its own
position: the pending bookkeeping is written first and the original delete
runs, with its own delete triggers, before that row is recorded.

A batch that could delete proven-empty coverage, whose triggers also take
revisions, keeps the row triggers.
"""
from __future__ import annotations

import sqlite3
from bisect import bisect_left
from contextlib import contextmanager
from dataclasses import dataclass

from . import revisions as rv
from .revisions import IDENTITY_COLUMNS, REVISION_CHANGED_FIELDS

ENABLED = True
MIN_ROWS = 4
_INT_MIN = -9223372036854775807


def init_bulk_revision_storage(conn) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(kline_mutation_context)")}
    if "bulk" not in columns:
        conn.execute("ALTER TABLE kline_mutation_context ADD COLUMN bulk INTEGER NOT NULL DEFAULT 0")
    conn.execute("UPDATE kline_mutation_context SET bulk=0 WHERE singleton=1")
    names = ", ".join(f"{name} TEXT NOT NULL" for name in IDENTITY_COLUMNS)
    conn.execute(f"""CREATE TABLE IF NOT EXISTS kline_bulk_journal (
        seq INTEGER PRIMARY KEY, op TEXT NOT NULL, {names},
        open_time INTEGER NOT NULL, close_time INTEGER)""")
    values = ", ".join(f"NEW.{name}" for name in IDENTITY_COLUMNS)
    changed = " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in REVISION_CHANGED_FIELDS)
    for operation, condition in (("insert", ""), ("update", f" AND ({changed})")):
        rv._execute_schema(conn, f"""
            DROP TRIGGER IF EXISTS kline_bulk_capture_{operation};
            CREATE TRIGGER kline_bulk_capture_{operation} AFTER {operation.upper()} ON klines
            WHEN (SELECT bulk FROM kline_mutation_context WHERE singleton=1)=1{condition}
            BEGIN
                INSERT INTO kline_bulk_journal (op, {", ".join(IDENTITY_COLUMNS)}, open_time, close_time)
                VALUES ('{operation}', {values}, NEW.open_time, NEW.close_time);
            END;
        """)


def row_triggers_active() -> str:
    """Condition the bookkeeping and dependents insert/update triggers add."""
    return "(SELECT bulk FROM kline_mutation_context WHERE singleton=1)=0"


@dataclass
class _Span:
    span_id: int
    tx_epoch: int
    previous_revision: int
    first_revision: int
    last_revision: int
    start_ms: int
    end_ms: int
    step_ms: int
    stored: bool  # present in the table before this flush


@dataclass
class _State:
    values: tuple
    mode: str
    epoch: int
    clock: int
    head: int
    series: tuple | None  # (delete_revision, start_ms, end_ms) before the batch
    readback: int | None
    span: _Span | None
    span_seq: int
    table_max: int
    dependents: bool


def _eligible(conn, values, rows: int) -> bool:
    if not ENABLED or rows < MIN_ROWS:
        return False
    exchange, market_type, symbol, interval = values[:4]
    # Deleting proven-empty coverage also takes revisions inside the row
    # triggers; keep their exact order by not batching such a write.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trade_empty_buckets'").fetchone():
        if conn.execute("SELECT 1 FROM trade_empty_buckets WHERE exchange=? AND market_type=? AND symbol=? "
                        "AND interval=? LIMIT 1", (exchange, market_type, symbol, interval)).fetchone():
            return False
    if exchange == "upbit" and interval == "1s" and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_empty_seconds'").fetchone():
        if conn.execute("SELECT 1 FROM native_empty_seconds WHERE symbol=? LIMIT 1", (symbol,)).fetchone():
            return False
    return True


@contextmanager
def batch_bookkeeping(conn, values, rows: int):
    """Write one series' batch with per-batch bookkeeping when it is eligible."""
    if not _eligible(conn, tuple(values), rows):
        yield False
        return
    values = tuple(values)
    state = _capture_state(conn, values)
    conn.execute("UPDATE kline_mutation_context SET bulk=1 WHERE singleton=1")
    try:
        yield True
    except BaseException:
        # The caller rolls back; do not let cleanup hide the original failure.
        try:
            conn.execute("UPDATE kline_mutation_context SET bulk=0 WHERE singleton=1")
            conn.execute("DELETE FROM kline_bulk_journal")
        except sqlite3.Error:
            pass
        raise
    conn.execute("UPDATE kline_mutation_context SET bulk=0 WHERE singleton=1")
    _apply(conn, values, state)


def _series_where():
    return " AND ".join(f"{name}=?" for name in IDENTITY_COLUMNS)


def _capture_state(conn, values) -> _State:
    mode, epoch = conn.execute(
        "SELECT mode, active_tx_epoch FROM kline_mutation_context WHERE singleton=1").fetchone()
    clock = rv.current_revision(conn)
    series = conn.execute("SELECT revision, delete_revision, start_ms, end_ms FROM kline_series_changes WHERE "
                          + _series_where(), values).fetchone()
    readback = conn.execute("SELECT revision FROM kline_history_readback WHERE " + _series_where(),
                            values).fetchone()
    span = conn.execute("SELECT span_id, tx_epoch, previous_revision, first_revision, last_revision, start_ms, "
                        "end_ms, step_ms FROM kline_series_range_changes WHERE " + _series_where()
                        + " ORDER BY last_revision DESC LIMIT 1", values).fetchone()
    seq_row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='kline_series_range_changes'").fetchone()
    table_max = conn.execute("SELECT COALESCE(MAX(span_id), 0) FROM kline_series_range_changes").fetchone()[0]
    family = [(name, value) for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval"]
    family_sql = " AND ".join(f"d.{name}=?" for name, _ in family)
    family_args = tuple(value for _, value in family)
    source_derived = conn.execute("SELECT 1 FROM kline_derived_series WHERE " + _series_where(), values).fetchone()
    dependents = (str(mode) not in ("retention", "provenance_migration") and source_derived is None
                  and conn.execute(f"SELECT 1 FROM kline_derived_series d WHERE {family_sql} AND d.interval<>?",
                                   (*family_args, values[3])).fetchone() is not None)
    return _State(
        values=values, mode=str(mode), epoch=int(epoch or 0), clock=int(clock),
        head=int(series[0]) if series else 0,
        series=(int(series[1]), int(series[2]), int(series[3])) if series else None,
        readback=int(readback[0]) if readback else None,
        span=_Span(*(int(item) for item in span), stored=True) if span else None,
        span_seq=max(int(seq_row[0]) if seq_row else 0, int(table_max)), table_max=int(table_max),
        dependents=dependents)


def _load_candidates(conn, state: _State, first: int, last: int) -> list:
    """Derived bars any journaled row's dependents delete could select.

    Grouped by series span bound and sorted by open, so each source row only
    looks at the bars that can overlap it: a month of archived minutes must
    not compare every row with every derived bar of that month.
    """
    family = [(name, value) for name, value in zip(IDENTITY_COLUMNS, state.values) if name != "interval"]
    join = " AND ".join(f"k.{name}=d.{name}" for name in IDENTITY_COLUMNS)
    rows = conn.execute(
        f"SELECT k.rowid, k.open_time, k.close_time, d.max_span_ms FROM kline_derived_series d "
        f"CROSS JOIN klines k ON {join} WHERE "
        + " AND ".join(f"d.{name}=?" for name, _ in family)
        + " AND d.interval<>? AND k.open_time<=? AND k.open_time>=(CASE WHEN d.max_span_ms>0 "
          "THEN ?-d.max_span_ms ELSE ? END)",
        (*(value for _, value in family), state.values[3], last, first, _INT_MIN)).fetchall()
    groups: dict[int, list] = {}
    for rowid, opened, closed, span in rows:
        groups.setdefault(int(span), []).append([int(opened), closed, rowid, False])
    result = []
    for span, items in groups.items():
        items.sort(key=lambda item: item[0])
        result.append((span, [item[0] for item in items], items))
    return result


def _deletes_dependents(candidates, opened: int, closed) -> bool:
    """The dependents delete predicate of ``revisions`` for one source row."""
    end = opened if closed is None else closed
    width = end - opened
    for span, opens, items in candidates:
        # Index in place: slicing would copy the rest of the batch per row.
        for at in range(bisect_left(opens, opened - span) if span > 0 else 0, len(items)):
            k_open, k_close, _, gone = items[at]
            if k_open > end:
                break
            if gone or (k_open if k_close is None else k_close) < opened:
                continue
            if k_close is None or k_close < k_open or k_close - k_open >= width:
                return True
    return False


def _run_dependents(conn, state: _State, opened: int, closed, candidates) -> None:
    """Execute the trigger's own dependents delete for one source row."""
    values = state.values
    family = [(name, value) for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval"]
    join = " AND ".join(f"k.{name}=d.{name}" for name in IDENTITY_COLUMNS)
    end = opened if closed is None else closed
    conn.execute("UPDATE kline_projection_invalidation SET depth=depth+1 WHERE singleton=1")
    deleted = [row[0] for row in conn.execute(
        f"SELECT k.rowid FROM kline_derived_series d CROSS JOIN klines k ON {join} WHERE "
        + " AND ".join(f"d.{name}=?" for name, _ in family)
        + " AND d.interval<>? AND k.open_time<=? AND k.open_time>=(CASE WHEN d.max_span_ms>0 "
          "THEN ?-d.max_span_ms ELSE ? END) AND COALESCE(k.close_time,k.open_time)>=? "
          "AND (k.close_time IS NULL OR k.close_time<k.open_time OR k.close_time-k.open_time>=?)",
        (*(value for _, value in family), values[3], end, opened, _INT_MIN, opened, end - opened))]
    if deleted:
        # The trigger deletes ``rowid IN (...)``: in rowid order.
        conn.executemany("DELETE FROM klines WHERE rowid=?", [(rowid,) for rowid in sorted(deleted)])
    conn.execute("UPDATE kline_projection_invalidation SET depth=depth-1 WHERE singleton=1")
    gone = set(deleted)
    for _, _, items in candidates:
        for item in items:
            if item[2] in gone:
                item[3] = True


def _apply(conn, values, state: _State) -> None:
    journal = conn.execute("SELECT op, open_time, close_time, " + ", ".join(IDENTITY_COLUMNS)
                           + " FROM kline_bulk_journal ORDER BY seq").fetchall()
    conn.execute("DELETE FROM kline_bulk_journal")
    if not journal:
        return
    if any(tuple(row[3:]) != values for row in journal):
        raise RuntimeError("batch bookkeeping journaled another series")
    candidates = []
    if state.dependents:
        first = min(int(row[1]) for row in journal)
        last = max(int(row[1] if row[2] is None else row[2]) for row in journal)
        candidates = _load_candidates(conn, state, first, last)
    pending: list = []
    for op, opened, closed in ((row[0], int(row[1]), row[2]) for row in journal):
        closed = None if closed is None else int(closed)
        if candidates and _deletes_dependents(candidates, opened, closed):
            _flush(conn, state, pending)
            pending = []
            _run_dependents(conn, state, opened, closed, candidates)
            # Their delete triggers took revisions and may have pruned spans.
            state.clock = rv.current_revision(conn)
            seq_row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='kline_series_range_changes'").fetchone()
            state.table_max = conn.execute("SELECT COALESCE(MAX(span_id), 0) FROM kline_series_range_changes").fetchone()[0]
            state.span_seq = max(int(seq_row[0]) if seq_row else 0, int(state.table_max))
            if state.span is not None and not state.span.stored:
                raise RuntimeError("unflushed span across a dependents delete")
            if state.span is not None and state.span.span_id <= state.table_max - rv.SERIES_RANGE_SPAN_WINDOW:
                state.span = None
        pending.append(_record(state, op, opened, closed))
    _flush(conn, state, pending)


def _record(state: _State, op: str, opened: int, closed):
    state.clock += 1
    revision = state.clock
    head = state.head
    width = closed - opened + 1 if closed is not None and closed >= opened else 0
    block = (revision, *state.values, head, opened, opened)
    span = state.span
    if span is not None and span.span_id <= state.table_max - rv.SERIES_RANGE_SPAN_WINDOW:
        span = state.span = None
    extended = False
    if (span is not None and state.epoch > 0 and span.tx_epoch == state.epoch
            and span.last_revision == head and head > 0 and width > 0):
        single = span.start_ms == span.end_ms and span.step_ms == 0
        if single:
            fits = opened == span.start_ms or opened == span.end_ms + width or span.start_ms == opened + width
        else:
            fits = span.step_ms == width and (
                (span.start_ms <= opened <= span.end_ms and (opened - span.start_ms) % span.step_ms == 0)
                or opened == span.end_ms + width or span.start_ms == opened + width)
        if fits:
            if single and opened != span.start_ms:
                span.step_ms = width
            span.start_ms = min(span.start_ms, opened)
            span.end_ms = max(span.end_ms, opened)
            span.last_revision = revision
            extended = True
    if not extended:
        state.span_seq += 1
        state.table_max = state.span_seq
        span = state.span = _Span(state.span_seq, state.epoch, head, revision, revision, opened, opened, 0,
                                  stored=False)
    state.head = revision
    return (op, opened, closed, block, span, extended)


def _flush(conn, state: _State, pending) -> None:
    if not pending:
        return
    values = state.values
    conn.execute("UPDATE kline_revision_clock SET revision=? WHERE singleton=1", (state.clock,))
    conn.executemany(f"INSERT INTO kline_block_changes VALUES ({', '.join('?' for _ in range(len(values) + 4))})",
                     [record[3] for record in pending])
    conn.execute("DELETE FROM kline_block_changes WHERE revision<=?", (state.clock - rv.BLOCK_CHANGE_WINDOW,))
    spans = {}
    for record in pending:
        spans[record[4].span_id] = record[4]
    keys = ", ".join(IDENTITY_COLUMNS)
    for span in spans.values():
        row = (span.tx_epoch, span.previous_revision, span.first_revision, span.last_revision,
               span.start_ms, span.end_ms, span.step_ms)
        if span.stored:
            conn.execute("UPDATE kline_series_range_changes SET last_revision=?, start_ms=?, end_ms=?, step_ms=? "
                         "WHERE span_id=?", (span.last_revision, span.start_ms, span.end_ms, span.step_ms,
                                              span.span_id))
        else:
            conn.execute(f"INSERT INTO kline_series_range_changes (span_id, {keys}, tx_epoch, previous_revision, "
                         "first_revision, last_revision, start_ms, end_ms, step_ms) VALUES "
                         f"(?, {', '.join('?' for _ in values)}, ?, ?, ?, ?, ?, ?, ?)",
                         (span.span_id, *values, *row))
            span.stored = True
    conn.execute("DELETE FROM kline_series_range_changes WHERE span_id<=(SELECT COALESCE(MAX(span_id), 0) - ? "
                 "FROM kline_series_range_changes)", (rv.SERIES_RANGE_SPAN_WINDOW,))
    first = min(record[1] for record in pending)
    last = max(record[1] if record[2] is None else record[2] for record in pending)
    op = pending[-1][0]
    if state.series is None:
        state.series = (0, first, last)
    else:
        deletion, start, end = state.series
        state.series = (deletion, min(start, first), max(end, last))
    deletion, start, end = state.series
    conn.execute(f"INSERT INTO kline_series_changes VALUES ({', '.join('?' for _ in values)}, ?, ?, ?, ?, ?) "
                 f"ON CONFLICT({keys}) DO UPDATE SET revision=excluded.revision, "
                 "delete_revision=MAX(delete_revision, excluded.delete_revision), "
                 "start_ms=MIN(start_ms, excluded.start_ms), end_ms=MAX(end_ms, excluded.end_ms), "
                 "operation=excluded.operation",
                 (*values, state.clock, deletion, start, end, op))
    if state.mode not in ("bar_delivery", "derived_materialization"):
        previous = pending[-2][3][0] if len(pending) >= 2 else (state.readback or 0)
        conn.execute(f"INSERT INTO kline_history_readback VALUES ({', '.join('?' for _ in values)}, ?, ?, ?, ?) "
                     f"ON CONFLICT({keys}) DO UPDATE SET previous_revision=excluded.previous_revision, "
                     "revision=excluded.revision, start_ms=excluded.start_ms, end_ms=excluded.end_ms",
                     (*values, state.clock, previous, pending[-1][1], pending[-1][1]))
        state.readback = state.clock
