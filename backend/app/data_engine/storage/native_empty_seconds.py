"""Durable evidence of absent Upbit native candles, never synthetic OHLCV."""
from __future__ import annotations

_revision = 0


def revision():
    return _revision


def invalidate_calendar_snapshots():
    global _revision
    _revision += 1


def init_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS native_empty_seconds (
            symbol TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
            PRIMARY KEY(symbol, start_ms, end_ms), CHECK(start_ms <= end_ms)
        );
        CREATE INDEX IF NOT EXISTS idx_native_empty_seconds_end ON native_empty_seconds(symbol, end_ms);
        CREATE TRIGGER IF NOT EXISTS invalidate_native_empty_second
        AFTER INSERT ON klines WHEN NEW.exchange = 'upbit' AND NEW.market_type = 'spot' AND NEW.interval = '1s'
        BEGIN
            DELETE FROM native_empty_seconds WHERE symbol = NEW.symbol
                AND start_ms <= NEW.open_time AND end_ms >= NEW.open_time;
        END;
    ''')


def read(symbol, start_ms, end_ms):
    from .klines_repo import _connect
    with _connect() as conn:
        return [tuple(row) for row in conn.execute(
            'SELECT start_ms, end_ms FROM native_empty_seconds WHERE symbol = ? AND end_ms >= ? AND start_ms <= ? ORDER BY start_ms',
            (symbol, start_ms, end_ms),
        )]


def record(symbol, ranges):
    from .klines_repo import _connect
    global _revision
    with _connect() as conn:
        # Serialize with bar writers; never hide a candle already in storage.
        conn.execute('BEGIN IMMEDIATE')
        for start, end in ranges:
            if start % 1000 or end % 1000 or start > end:
                raise ValueError('Invalid native empty-second evidence')
            opens = [int(row[0]) for row in conn.execute(
                "SELECT open_time FROM klines WHERE exchange = 'upbit' AND market_type = 'spot' AND interval = '1s' AND symbol = ? AND open_time BETWEEN ? AND ? ORDER BY open_time",
                (symbol, start, end),
            )]
            cursor = start
            for value in [*opens, end + 1000]:
                if cursor < value:
                    a, b = cursor, value - 1000
                    overlaps = conn.execute('SELECT start_ms, end_ms FROM native_empty_seconds WHERE symbol = ? AND start_ms <= ? AND end_ms >= ?', (symbol, b + 1000, a - 1000)).fetchall()
                    if overlaps:
                        a = min(a, min(int(row[0]) for row in overlaps))
                        b = max(b, max(int(row[1]) for row in overlaps))
                        conn.execute('DELETE FROM native_empty_seconds WHERE symbol = ? AND start_ms <= ? AND end_ms >= ?', (symbol, b, a))
                    conn.execute('INSERT OR IGNORE INTO native_empty_seconds VALUES (?, ?, ?)', (symbol, a, b))
                cursor = value + 1000
        conn.commit()
    _revision += 1


def clear(conn, symbol, start_ms=None, end_ms=None):
    """Forget only the selected opens, preserving adjacent protected spans."""
    start_ms = (int(start_ms) + 999) // 1000 * 1000 if start_ms is not None else None
    end_ms = int(end_ms) // 1000 * 1000 if end_ms is not None else None
    if start_ms is not None and end_ms is not None and start_ms > end_ms:
        return
    where = ['symbol = ?']
    params = [symbol]
    if start_ms is not None:
        where.append('end_ms >= ?')
        params.append(start_ms)
    if end_ms is not None:
        where.append('start_ms <= ?')
        params.append(end_ms)
    predicate = ' AND '.join(where)
    spans = conn.execute('SELECT start_ms, end_ms FROM native_empty_seconds WHERE ' + predicate, params).fetchall()
    conn.execute('DELETE FROM native_empty_seconds WHERE ' + predicate, params)
    for a, b in spans:
        if start_ms is not None and a < start_ms:
            conn.execute('INSERT OR IGNORE INTO native_empty_seconds VALUES (?, ?, ?)', (symbol, a, start_ms - 1000))
        if end_ms is not None and b > end_ms:
            conn.execute('INSERT OR IGNORE INTO native_empty_seconds VALUES (?, ?, ?)', (symbol, end_ms + 1000, b))
    invalidate_calendar_snapshots()


def make_calendar(symbol):
    from app.data_engine.history.native_seconds import NativeSparseSecondsCalendar
    return NativeSparseSecondsCalendar(symbol, read, revision)
