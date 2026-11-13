"""Bounded pre-fetch views for independent native REST repairs.

This is an optimistic range read, not a relaxation for derived calculations.
The existing native 1s sources, trusted Binance spot gap repairs and
source-receipted OKX spot native repairs qualify.
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


def _window_slots(task):
    if (task.exchange in {"binance", "gate", "upbit"}
            and task.market_type == "spot" and task.interval == "1s"):
        return (task.end_ms - task.start_ms) // 1000 + 1
    metadata = getattr(task, "metadata", {})
    if (task.market_type != "spot" or not (
            task.exchange == "okx" or (task.exchange == "binance"
            and metadata.get("requires_trusted_finality") is True))):
        return None
    from app.data_engine.interval_resolution import IntervalResolver, IntervalPurpose, IntervalResolutionError
    from app.data_engine.series_identity import identity_from_metadata

    identity = identity_from_metadata(task.exchange, metadata)
    if identity is not None and not identity.is_legacy_default_for(task.exchange):
        return None
    try:
        route = IntervalResolver().resolve(exchange=task.exchange, market_type=task.market_type,
                                           interval=task.interval, purpose=IntervalPurpose.HISTORY)
    except IntervalResolutionError:
        return None
    if not route.is_native or route.canonical_interval != task.interval:
        return None
    cursor, count = route.spec.floor_ms(task.start_ms), 0
    if cursor != task.start_ms:
        return None
    while cursor <= task.end_ms and count <= MAX_SLOTS:
        count += 1
        cursor = route.spec.next_ms(cursor)
    return count


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

    def check_history_receipts(self, conn, rows):
        # OKX's qualified fork journals exact native closed inputs. Only those
        # current REST heads may use range permission instead of the family
        # fence. Legacy/unreceipted, websocket, stale and derived writes cannot.
        if self.key[0] != "okx":
            return
        from .kline_sources import filter_projection_rows
        accepted = filter_projection_rows(
            conn, rows, exchange=self.key[0], market_type=self.key[1],
            symbol=self.key[2], interval=self.key[3], native_identity=True)
        if len(accepted) != len(rows) or any(not row.get("_history_source_ref") for row in accepted):
            raise StaleAcquisition("native history range requires current closed REST source receipts")

    def check(self, conn, scope):
        row = series_change(conn, self.key)
        floor = scope.revision if scope.delete_revision is None else scope.delete_revision
        # Own writes never grant permission over an intervening deletion.
        if row is not None and int(row["delete_revision"]) > max(floor, scope.accepted.get(self.key, 0)):
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
        start, end = task.start_ms, task.end_ms
        if not isinstance(start, int) or not isinstance(end, int) or start > end:
            continue
        count = _window_slots(task)
        if count is None:
            continue
        if len(selected) >= MAX_WINDOWS or slots + count > MAX_SLOTS:
            continue
        selected.append((series_values(task.symbol, task.interval, task.exchange, task.market_type), start, end))
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


def matching_empty_view(scope, key, ranges):
    # Only the existing Upbit REST negative-evidence owner can use this path.
    # No trade-derived, custom identity, or unknown-source absence is granted.
    if not ranges or key != series_values(key[2], '1s', 'upbit', 'spot'):
        return None
    start, end = min(a for a, _ in ranges), max(b for _, b in ranges)
    return next((view for view in scope.native_history_views
                 if view.key == key and view.start <= start <= end <= view.end), None)
