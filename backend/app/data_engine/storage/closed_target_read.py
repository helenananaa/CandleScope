"""Bounded canonical target reads, independent of unrelated live source tails.

This reads no cache, computes no aggregate and grants no write permission.
Current target contents and the durable explicit-deletion floor are checked
again before adoption. A nearly complete page may expose its bounded holes;
untrusted/nonfixed pages and cold pages still decline.
"""
from dataclasses import dataclass, replace
import hashlib
import sqlite3
from contextlib import contextmanager
from collections.abc import Callable

from app.data_engine.aggregation.semantics import valid_ohlcv
from app.data_engine.kline_quality import source_is_trusted_final
from .derived_history_fence import check_deletions
from .native_history_fence import fingerprint, FIELDS
from .revisions import IDENTITY_COLUMNS, StaleAcquisition, current_revision


@contextmanager
def _snapshot(store):
    try:
        with store._reading() as conn, conn:
            conn.execute('BEGIN')
            yield conn
    except sqlite3.Error as exc:
        raise StaleAcquisition('canonical target snapshot is unavailable') from exc


@dataclass(frozen=True)
class ClosedTargetRead:
    storage: object
    store: object
    key: tuple
    start: int
    end: int
    revision: int
    digest: bytes
    bars: tuple | None = None
    preview_check: Callable[[], bool] | None = None

    def bind(self, rows, bars):
        digest = hashlib.sha256()
        for row in rows:
            if tuple(row[name] for name in IDENTITY_COLUMNS) != self.key:
                raise StaleAcquisition('canonical target row identity changed')
            digest.update(repr(tuple(row[name] for name in FIELDS)).encode('utf-8'))
            digest.update(b'\n')
        if digest.digest() != self.digest:
            raise StaleAcquisition('canonical target snapshot rows changed during decoding')
        return replace(self, bars=tuple(bars))

    def check(self, storage, store, scope, key, bars):
        if (storage is not self.storage or store is not self.store
                or key != self.key or self.bars is None or tuple(bars) != self.bars):
            raise StaleAcquisition('canonical target read binding or output changed')
        with _snapshot(self.store) as conn:
            if self.preview_check is not None and not self.preview_check():
                raise StaleAcquisition('current preview changed before read adoption')
            head = current_revision(conn)
            check_deletions(conn, scope, self.key)
            if head < self.revision or fingerprint(conn, self.key, self.start, self.end) != self.digest:
                raise StaleAcquisition('canonical target changed before read adoption')
            if self.preview_check is not None and not self.preview_check():
                raise StaleAcquisition('current preview changed during read adoption')
            return head


def read_closed_target(storage, store, scope, key, first, last, width, count, now_ms):
    if scope is None or not 0 < count <= 512 or first < 0 or last+width > now_ms:
        return None
    with _snapshot(store) as conn:
        head = current_revision(conn)
        if head < scope.revision:
            raise StaleAcquisition('canonical target revision rewound')
        check_deletions(conn, scope, key)
        rows = conn.execute('SELECT * FROM klines WHERE ' +
            ' AND '.join(f'{name}=?' for name in IDENTITY_COLUMNS) +
            ' AND open_time BETWEEN ? AND ? ORDER BY open_time LIMIT ?',
            (*key, first, last, count+1)).fetchall()
        if not rows or not 0 <= count-len(rows) <= 8:
            return [dict(row) for row in rows], None
        for row in rows:
            if ((row['open_time']-first) % width or row['close_time'] != row['open_time']+width-1
                    or not source_is_trusted_final(row['source'])
                    or any(type(row[name]) not in (int,float) for name in ('open','high','low','close','volume'))
                    or not valid_ohlcv(tuple(row[name] for name in ('open','high','low','close','volume')))):
                return [dict(row) for row in rows], None
        proof = ClosedTargetRead(storage, store, key, first, last, head,
                                 fingerprint(conn, key, first, last))
        return [dict(row) for row in rows], proof
