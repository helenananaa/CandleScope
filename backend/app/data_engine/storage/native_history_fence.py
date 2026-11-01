"""Bounded pre-fetch views for independent native second-candle repairs.

This is an optimistic range read, not a relaxation for derived calculations.
Only the three explicitly supported spot/native 1s REST sources qualify.
There is no new durable mutation log: canonical rows and the existing durable
deletion watermark remain the authority, including writers in other processes.
"""
from contextlib import closing
from dataclasses import dataclass
import hashlib

from .revisions import IDENTITY_COLUMNS, series_values, series_change, StaleAcquisition

MAX_WINDOWS = 32
MAX_SLOTS = 8192
FIELDS = ("open_time", "close_time", "open", "high", "low", "close", "volume",
          "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "source")


def fingerprint(conn, key, start, end):
    digest = hashlib.sha256()
    rows = conn.execute("SELECT " + ",".join(FIELDS) + " FROM klines WHERE " +
                        " AND ".join(f"{name}=?" for name in IDENTITY_COLUMNS) +
                        " AND open_time BETWEEN ? AND ? ORDER BY open_time LIMIT ?",
                        (*key, start, end, MAX_SLOTS + 1))
    for index, row in enumerate(rows):
        if index >= MAX_SLOTS:
            raise StaleAcquisition("native history view exceeds bounded row budget")
        digest.update(repr(tuple(row)).encode("utf-8"))
        digest.update(b"\n")
    return digest.digest()


@dataclass
class NativeHistoryView:
    key: tuple
    start: int
    end: int
    digest: bytes

    def check(self, conn, scope):
        row = series_change(conn, self.key)
        floor = scope.revision if scope.delete_revision is None else scope.delete_revision
        # Own writes never grant permission over an intervening deletion.
        if row is not None and int(row["delete_revision"]) > floor:
            raise StaleAcquisition("native history was deleted after request permission")
        if fingerprint(conn, self.key, self.start, self.end) != self.digest:
            raise StaleAcquisition("native history window changed during acquisition")


def capture_native_history_views(store, scope, tasks):
    """Called once before REST acquisition; unknown/large/derived work stays strict."""
    if store is None or scope is None or scope.native_history_views:
        return
    selected = []
    slots = 0
    for task in tasks:
        if (task.exchange not in {"binance", "gate", "upbit"}
                or task.market_type != "spot" or task.interval != "1s"):
            continue
        start, end = task.start_ms, task.end_ms
        if not isinstance(start, int) or not isinstance(end, int) or start > end:
            continue
        count = (end - start) // 1000 + 1
        if len(selected) >= MAX_WINDOWS or slots + count > MAX_SLOTS:
            continue
        selected.append((series_values(task.symbol, "1s", task.exchange, "spot"), start, end))
        slots += count
    if not selected:
        return
    with scope.lock, closing(store.connect()) as conn, conn:
        conn.execute("BEGIN")
        views = [NativeHistoryView(key, start, end, fingerprint(conn, key, start, end))
                 for key, start, end in selected]
        # Do not renew a persisted/manual request's deletion permission here.
        for view in views:
            view.check(conn, scope)
        scope.native_history_views.extend(views)


def matching_view(scope, key, rows, source):
    if source != "backfill" or not rows:
        return None
    start = min(row["open_time"] for row in rows)
    end = max(row["open_time"] for row in rows)
    return next((view for view in scope.native_history_views
                 if view.key == key and view.start <= start <= end <= view.end), None)
