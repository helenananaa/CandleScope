"""Durable bar receipt, canonical commit and publication recovery journal.

The receipt precedes processing. Canonical row arbitration and the committed
publication marker share one transaction; bus handoff is acknowledged later.
"""
from __future__ import annotations

import json
import time
from contextlib import closing

from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.series_identity import KlineSeriesIdentity
from .revisions import current_revision, series_change, series_values, register_derived, IDENTITY_COLUMNS


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def init_bar_delivery_storage(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bar_delivery (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL,
            phase TEXT NOT NULL CHECK(phase IN ('pending','committed','published','rejected')),
            created_ms INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bar_delivery_pending ON bar_delivery(phase,sequence);
        CREATE TABLE IF NOT EXISTS bar_delivery_watches (
            watch_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            series TEXT NOT NULL,
            from_ms INTEGER NOT NULL,
            through_ms INTEGER
        );
    """)

    for table, column in (("bar_delivery", "observed_revision"),
                          ("bar_delivery", "committed_revision"),
                          ("bar_delivery", "recovery_required"),
                          ("bar_delivery_watches", "observed_revision")):
        if column not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")


class BarDeliveryJournal:
    def __init__(self, connect, write, *, max_pending=4096, retained=8192):
        self._connect, self._write = connect, write
        self.max_pending, self.retained = max_pending, retained

    @staticmethod
    def _record(row):
        return {**dict(row), "payload": json.loads(row["payload"])}

    def enqueue(self, event_id, payload):
        encoded = _json(payload)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM bar_delivery WHERE event_id=?", (event_id,)).fetchone()
            if existing is not None:
                if existing["payload"] != encoded:
                    raise ValueError("Bar delivery identity reused with different content")
                return self._record(existing)
            pending = conn.execute("SELECT COUNT(*) FROM bar_delivery WHERE phase IN ('pending','committed') OR recovery_required=1").fetchone()[0]
            if pending >= self.max_pending:
                raise BarDeliveryUnavailable("Bar delivery journal is at capacity")
            conn.execute("INSERT INTO bar_delivery(event_id,payload,phase,created_ms,observed_revision) VALUES (?,?,'pending',?,?)",
                         (event_id, encoded, int(time.time() * 1000), payload.get("acquisition_revision", current_revision(conn))))
            return self._record(conn.execute("SELECT * FROM bar_delivery WHERE event_id=?", (event_id,)).fetchone())

    def pending(self, limit=64):
        with closing(self._connect()) as conn:
            return [self._record(row) for row in conn.execute(
                "SELECT * FROM bar_delivery WHERE phase IN ('pending','committed') OR recovery_required=1 ORDER BY sequence LIMIT ?", (limit,))]

    def pending_count(self):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM bar_delivery WHERE phase IN ('pending','committed') OR recovery_required=1").fetchone()[0]

    def _prune(self, conn):
        conn.execute("""DELETE FROM bar_delivery WHERE phase IN ('published','rejected')
            AND recovery_required=0
            AND sequence < (SELECT COALESCE(MAX(sequence),0)-? FROM bar_delivery)""", (self.retained,))

    @staticmethod
    def _canonical(conn, record):
        payload = record["payload"]
        identity = KlineSeriesIdentity.for_exchange(payload["exchange"], **{
            name: payload[name] for name in KlineSeriesIdentity.for_exchange(payload["exchange"]).to_dict() if name in payload})
        scope = {name: payload[name] for name in ("exchange", "market_type", "symbol", "interval")}
        scope.update(identity.to_dict(), open_time=payload["storage_row"]["open_time"])
        row = conn.execute("SELECT * FROM klines WHERE " + " AND ".join(f"{name}=?" for name in scope), tuple(scope.values())).fetchone()
        record["canonical_row"] = dict(row) if row is not None else None
        change = series_change(conn, series_values(payload["symbol"], payload["interval"],
                                                   payload["exchange"], payload["market_type"], identity))
        record["canonical_revision"] = int(change["revision"]) if change else 0
        return record

    def commit(self, event_id):
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM bar_delivery WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError(event_id)
            record = self._record(row)
            if record["phase"] != "pending":
                return self._canonical(conn, record)
            payload = record["payload"]
            identity = KlineSeriesIdentity.for_exchange(payload["exchange"], **{
                name: payload[name] for name in KlineSeriesIdentity.for_exchange(payload["exchange"]).to_dict()
                if name in payload})
            values = series_values(payload["symbol"], payload["interval"], payload["exchange"], payload["market_type"], identity)
            if payload.get("derived"):
                # A target may not exist yet when its input is repaired/deleted.
                # Check its semantic family, including those source revisions.
                family = [(name, value) for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval"]
                changes = conn.execute("SELECT * FROM kline_series_changes WHERE " +
                    " AND ".join(f"{name}=?" for name, _ in family), tuple(value for _, value in family)).fetchall()
            else:
                change = series_change(conn, values)
                changes = [change] if change is not None else []
            for change in changes:
                if change["revision"] <= record["observed_revision"]:
                    continue
                predecessor = conn.execute("SELECT 1 FROM bar_delivery WHERE sequence<? AND committed_revision=?",
                                           (record["sequence"], change["revision"])).fetchone()
                if change["delete_revision"] > record["observed_revision"] or predecessor is None:
                    conn.execute("UPDATE bar_delivery SET phase='rejected',recovery_required=1 WHERE event_id=?", (event_id,))
                    record["phase"] = "rejected"
                    record["recovery_required"] = 1
                    return self._canonical(conn, record)
            if payload.get("derived"):
                register_derived(conn, series_values(payload["symbol"], payload["interval"],
                    payload["exchange"], payload["market_type"], identity))
            affected = self._write(payload["symbol"], payload["interval"], [payload["storage_row"]],
                                   payload["bar"]["source"], exchange=payload["exchange"],
                                   market_type=payload["market_type"], series_identity=identity, _connection=conn)
            record["phase"] = "committed" if affected else "rejected"
            record["committed_revision"] = current_revision(conn)
            conn.execute("UPDATE bar_delivery SET phase=?,committed_revision=? WHERE event_id=?",
                         (record["phase"], record["committed_revision"], event_id))
            self._prune(conn)
            return self._canonical(conn, record)

    def acknowledge(self, event_id):
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE bar_delivery SET phase='published' WHERE event_id=? AND phase='committed'", (event_id,))
            conn.execute("UPDATE bar_delivery SET recovery_required=0 WHERE event_id=? AND phase='rejected'", (event_id,))
            # Pending receipts and unpublished commits are never pruned.
            self._prune(conn)

    def watch(self, owner, series, from_ms):
        encoded = _json(series)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            watch_id = owner + ":" + encoded
            existing = conn.execute("SELECT * FROM bar_delivery_watches WHERE watch_id=?", (watch_id,)).fetchone()
            if existing is not None and not self._watch_superseded(conn, self._record_watch(existing)):
                from_ms = min(from_ms, existing["from_ms"])
                revision = existing["observed_revision"]
            else:
                revision = current_revision(conn)
            conn.execute("""INSERT INTO bar_delivery_watches(watch_id,owner,series,from_ms,observed_revision)
                VALUES (?,?,?,?,?) ON CONFLICT(watch_id) DO UPDATE SET from_ms=excluded.from_ms,
                observed_revision=excluded.observed_revision""", (watch_id, owner, encoded, from_ms, revision))

    @staticmethod
    def _record_watch(row):
        return {**dict(row), "series": json.loads(row["series"])}

    @staticmethod
    def _watch_superseded(conn, watch):
        series = watch["series"]
        exchange = series.get("exchange", "binance")
        identity = KlineSeriesIdentity.for_exchange(exchange, **{
            name: series[name] for name in KlineSeriesIdentity.for_exchange(exchange).to_dict() if name in series})
        values = series_values(series["symbol"], series["interval"], exchange,
                               series.get("market_type", "spot"), identity)
        family = [(name, value) for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval"]
        return conn.execute("SELECT 1 FROM kline_series_changes WHERE " +
            " AND ".join(f"{name}=?" for name, _ in family) + " AND delete_revision>? LIMIT 1",
            (*[value for _, value in family], watch.get("observed_revision", 0))).fetchone() is not None

    def watch_superseded(self, watch):
        with closing(self._connect()) as conn:
            return self._watch_superseded(conn, watch)

    def recovery_watches(self, owner, through_ms, limit=32, after=None):
        """Read a bounded page; a value cursor remains valid after acknowledgement."""
        where = "owner<>?"
        params = [owner]
        if after is not None:
            where += " AND (from_ms,watch_id)>(?,?)"
            params.extend(after)
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE bar_delivery_watches SET through_ms=? WHERE owner<>? AND through_ms IS NULL", (through_ms, owner))
            return [{**dict(row), "series": json.loads(row["series"])} for row in conn.execute(
                f"SELECT * FROM bar_delivery_watches WHERE {where} ORDER BY from_ms,watch_id LIMIT ?", (*params, limit))]

    def recovery_pending_count(self, owner):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM bar_delivery_watches WHERE owner<>?", (owner,)).fetchone()[0]

    def finish_recovery(self, watch_id):
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM bar_delivery_watches WHERE watch_id=?", (watch_id,))

    def capture_failed_watches(self, owner):
        with closing(self._connect()) as conn, conn:
            conn.execute("""INSERT INTO bar_delivery_watches(watch_id,owner,series,from_ms,through_ms,observed_revision)
                SELECT 'retry:' || watch_id,'retry:' || owner,series,from_ms,NULL,observed_revision
                FROM bar_delivery_watches WHERE owner=?
                ON CONFLICT(watch_id) DO UPDATE SET from_ms=MIN(from_ms,excluded.from_ms),through_ms=NULL""", (owner,))

    def release_watches(self, owner):
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM bar_delivery_watches WHERE owner=?", (owner,))
