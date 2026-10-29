"""Durable no-trade evidence for verified fixed-period trade candles."""
from __future__ import annotations

from app.exchanges.trade_candles import fixed_trade_spec

_revision = 0


def invalidate():
    global _revision
    _revision += 1


def init_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS trade_empty_buckets (
            exchange TEXT NOT NULL, market_type TEXT NOT NULL, symbol TEXT NOT NULL,
            interval TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
            PRIMARY KEY(exchange, market_type, symbol, interval, start_ms), CHECK(start_ms <= end_ms)
        );
        CREATE TRIGGER IF NOT EXISTS invalidate_trade_empty_bucket
        AFTER INSERT ON klines BEGIN
            DELETE FROM trade_empty_buckets WHERE exchange = NEW.exchange AND market_type = NEW.market_type
                AND symbol = NEW.symbol AND interval = NEW.interval
                AND start_ms <= NEW.open_time AND end_ms >= NEW.open_time;
        END;
    ''')


def read(exchange, market_type, symbol, interval, start_ms, end_ms):
    from .klines_repo import _connect
    with _connect() as conn:
        return [tuple(row) for row in conn.execute(
            'SELECT start_ms, end_ms FROM trade_empty_buckets WHERE exchange=? AND market_type=? AND symbol=? AND interval=? AND end_ms>=? AND start_ms<=? ORDER BY start_ms',
            (exchange, market_type, symbol, interval, start_ms, end_ms),
        )]


def record(exchange, market_type, symbol, interval, ranges):
    from .klines_repo import _connect
    from app.exchanges.trade_candles import uses_trade_candles
    if not uses_trade_candles(exchange, market_type, interval):
        raise ValueError("No verified trade-candle provider for this series")
    width = fixed_trade_spec(interval).nominal_ms
    key = (exchange, market_type, symbol, interval)
    with _connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for start, end in ranges:
            if start % width or end % width or start > end:
                raise ValueError('Invalid empty trade bucket evidence')
            opens = [int(row[0]) for row in conn.execute(
                'SELECT open_time FROM klines WHERE exchange=? AND market_type=? AND symbol=? AND interval=? AND open_time BETWEEN ? AND ? ORDER BY open_time',
                (*key, start, end),
            )]
            cursor = start
            for value in [*opens, end + width]:
                if cursor < value:
                    a, b = cursor, value - width
                    overlaps = conn.execute('SELECT start_ms, end_ms FROM trade_empty_buckets WHERE exchange=? AND market_type=? AND symbol=? AND interval=? AND start_ms<=? AND end_ms>=?', (*key, b + width, a - width)).fetchall()
                    if overlaps:
                        a = min(a, min(int(row[0]) for row in overlaps))
                        b = max(b, max(int(row[1]) for row in overlaps))
                        conn.execute('DELETE FROM trade_empty_buckets WHERE exchange=? AND market_type=? AND symbol=? AND interval=? AND start_ms<=? AND end_ms>=?', (*key, b, a))
                    conn.execute('INSERT OR IGNORE INTO trade_empty_buckets VALUES (?, ?, ?, ?, ?, ?)', (*key, a, b))
                cursor = value + width
        conn.commit()
    invalidate()


def clear(conn, exchange, market_type, symbol, interval, start_ms=None, end_ms=None):
    width = fixed_trade_spec(interval).nominal_ms
    start_ms = (int(start_ms) + width - 1) // width * width if start_ms is not None else None
    end_ms = int(end_ms) // width * width if end_ms is not None else None
    if start_ms is not None and end_ms is not None and start_ms > end_ms:
        return
    key = (exchange, market_type, symbol, interval)
    where = ['exchange=?', 'market_type=?', 'symbol=?', 'interval=?']
    params = list(key)
    if start_ms is not None:
        where.append('end_ms>=?')
        params.append(start_ms)
    if end_ms is not None:
        where.append('start_ms<=?')
        params.append(end_ms)
    predicate = ' AND '.join(where)
    spans = conn.execute('SELECT start_ms, end_ms FROM trade_empty_buckets WHERE ' + predicate, params).fetchall()
    conn.execute('DELETE FROM trade_empty_buckets WHERE ' + predicate, params)
    for a, b in spans:
        if start_ms is not None and a < start_ms:
            conn.execute('INSERT OR IGNORE INTO trade_empty_buckets VALUES (?, ?, ?, ?, ?, ?)', (*key, a, start_ms - width))
        if end_ms is not None and b > end_ms:
            conn.execute('INSERT OR IGNORE INTO trade_empty_buckets VALUES (?, ?, ?, ?, ?, ?)', (*key, end_ms + width, b))
    invalidate()


def make_calendar(exchange, market_type, symbol, interval):
    from app.data_engine.history.native_seconds import NativeSparseSecondsCalendar
    return NativeSparseSecondsCalendar(symbol,
        lambda sym, start, end: read(exchange, market_type, sym, interval, start, end),
        lambda: _revision, interval=interval,
        calendar_id=f'{exchange}.{market_type}.trade-candles:{symbol}:{interval}')
