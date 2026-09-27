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
            pending = conn.execute("SELECT COUNT(*) FROM bar_delivery WHERE phase IN ('pending','committed')").fetchone()[0]
            if pending >= self.max_pending:
                raise BarDeliveryUnavailable("Bar delivery journal is at capacity")
            conn.execute("INSERT INTO bar_delivery(event_id,payload,phase,created_ms) VALUES (?,?,'pending',?)",
                         (event_id, encoded, int(time.time() * 1000)))
            return self._record(conn.execute("SELECT * FROM bar_delivery WHERE event_id=?", (event_id,)).fetchone())

    def pending(self, limit=64):
        with closing(self._connect()) as conn:
            return [self._record(row) for row in conn.execute(
                "SELECT * FROM bar_delivery WHERE phase IN ('pending','committed') ORDER BY sequence LIMIT ?", (limit,))]

    def pending_count(self):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM bar_delivery WHERE phase IN ('pending','committed')").fetchone()[0]

    def _prune(self, conn):
        conn.execute("""DELETE FROM bar_delivery WHERE phase IN ('published','rejected')
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
            affected = self._write(payload["symbol"], payload["interval"], [payload["storage_row"]],
                                   payload["bar"]["source"], exchange=payload["exchange"],
                                   market_type=payload["market_type"], series_identity=identity, _connection=conn)
            record["phase"] = "committed" if affected else "rejected"
            conn.execute("UPDATE bar_delivery SET phase=? WHERE event_id=?", (record["phase"], event_id))
            self._prune(conn)
            return self._canonical(conn, record)

    def acknowledge(self, event_id):
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE bar_delivery SET phase='published' WHERE event_id=? AND phase='committed'", (event_id,))
            # Pending receipts and unpublished commits are never pruned.
            self._prune(conn)

    def watch(self, owner, series, from_ms):
        encoded = _json(series)
        with closing(self._connect()) as conn, conn:
            conn.execute("""INSERT INTO bar_delivery_watches(watch_id,owner,series,from_ms) VALUES (?,?,?,?)
                ON CONFLICT(watch_id) DO UPDATE SET from_ms=MIN(from_ms,excluded.from_ms)""",
                (owner + ":" + encoded, owner, encoded, from_ms))

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
            conn.execute("""INSERT INTO bar_delivery_watches(watch_id,owner,series,from_ms,through_ms)
                SELECT 'retry:' || watch_id,'retry:' || owner,series,from_ms,NULL
                FROM bar_delivery_watches WHERE owner=?
                ON CONFLICT(watch_id) DO UPDATE SET from_ms=MIN(from_ms,excluded.from_ms),through_ms=NULL""", (owner,))

    def release_watches(self, owner):
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM bar_delivery_watches WHERE owner=?", (owner,))
