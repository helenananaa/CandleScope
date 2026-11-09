"""Durable bar receipt, canonical commit and publication recovery journal.

The receipt precedes processing. Canonical row arbitration and the committed
publication marker share one transaction; bus handoff is acknowledged later.
"""
from __future__ import annotations

import json
import time
from contextlib import closing

from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
from app.data_engine.series_identity import KlineSeriesIdentity
from .revisions import (
    IDENTITY_COLUMNS,
    block_change_receipts,
    current_revision,
    mutation_mode,
    register_derived,
    series_change,
    series_values,
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _has_predecessor(conn, sequence, revision):
    return conn.execute(
        "SELECT 1 FROM bar_delivery WHERE sequence<? AND committed_revision=?",
        (sequence, revision),
    ).fetchone() is not None


def _is_exact_fixed_bucket(interval, start, end):
    spec = parse_interval_spec(interval)
    return (spec is not None and spec.alignment is IntervalAlignment.FIXED_EPOCH
            and spec.floor_ms(start) == start and spec.next_ms(start) == end + 1)


def _changes_allow_delivery(conn, change, receipts, observed_revision, sequence, start, end):
    # Fully contained source components are selected by their open times.
    identity = tuple(change[name] for name in IDENTITY_COLUMNS)
    series = [row for row in receipts if tuple(row[name] for name in IDENTITY_COLUMNS) == identity]
    if (not series or series[-1]["revision"] != change["revision"]
            or series[0]["previous_revision"] > observed_revision
            or any(left["revision"] != right["previous_revision"] for left, right in zip(series, series[1:]))):
        return False
    for row in series:
        if row["start_ms"] > row["end_ms"]:
            return False
        if row["end_ms"] < start or row["start_ms"] > end:
            continue
        # The footprint can overlap only when an earlier delivery actually
        # wrote that revision. Its transaction's head can instead belong to a
        # dependent deletion, or remain unchanged after a no-op upsert.
        if conn.execute(
            "SELECT 1 FROM bar_delivery WHERE sequence<? AND written_revision=? AND phase IN ('committed','published')",
            (sequence, row["revision"]),
        ).fetchone() is None:
            return False
    return True


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
                          ("bar_delivery", "written_revision"),
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
            prefix_revisions = payload.get('history_prefix_revisions', ())
            if len(prefix_revisions) > 32:
                raise ValueError('history prefix requires bounded source revisions')
            for source_interval, acquired_revision in prefix_revisions:
                source_values = series_values(payload['symbol'], source_interval,
                    payload['exchange'], payload['market_type'], identity)
                source_change = series_change(conn, source_values)
                current_source_revision = int(source_change['revision']) if source_change else 0
                if type(acquired_revision) is not int or current_source_revision != acquired_revision:
                    conn.execute("UPDATE bar_delivery SET phase='rejected',recovery_required=1 WHERE event_id=?", (event_id,))
                    record['phase'], record['recovery_required'] = 'rejected', 1
                    return self._canonical(conn, record)
            derived = payload.get("derived")
            if derived:
                # A target may not exist yet when its input is repaired/deleted.
                # Check its semantic family, including those source revisions.
                family = [(name, value) for name, value in zip(IDENTITY_COLUMNS, values) if name != "interval"]
                changes = conn.execute("SELECT * FROM kline_series_changes WHERE " +
                    " AND ".join(f"{name}=?" for name, _ in family), tuple(value for _, value in family)).fetchall()
            else:
                change = series_change(conn, values)
                changes = [change] if change is not None else []
            observed_revision = record["observed_revision"]
            start = payload["storage_row"]["open_time"]
            end = payload["storage_row"].get("close_time")
            valid_window = end is not None and end >= start
            receipts = None
            for change in changes:
                if change["revision"] <= observed_revision:
                    continue
                if not derived:
                    # The durable range encloses every mutation ever observed
                    # for this identity, including empty deletes. A disjoint
                    # native candle cannot depend on those changed rows. This
                    # lets an in-flight forming candle close after older gaps
                    # are repaired, without granting it a newer acquisition.
                    if valid_window and (
                        end < change["start_ms"] or start > change["end_ms"]
                    ):
                        continue
                sequence = record["sequence"]
                if change["delete_revision"] > observed_revision or not _has_predecessor(conn, sequence, change["revision"]):
                    # Older receipts may carry an incomplete interval, and
                    # session bounds require a calendar unavailable here.
                    if derived and valid_window and _is_exact_fixed_bucket(payload["interval"], start, end):
                        if receipts is None:
                            receipts = block_change_receipts(conn, observed_revision, current_revision(conn))
                        if _changes_allow_delivery(conn, change, receipts, observed_revision, sequence, start, end):
                            continue
                    conn.execute("UPDATE bar_delivery SET phase='rejected',recovery_required=1 WHERE event_id=?", (event_id,))
                    record["phase"] = "rejected"
                    record["recovery_required"] = 1
                    return self._canonical(conn, record)
            if derived:
                register_derived(conn, values)
            before_write = current_revision(conn)
            with mutation_mode(conn, "bar_delivery"):
                affected = self._write(payload["symbol"], payload["interval"], [payload["storage_row"]],
                                       payload["bar"]["source"], exchange=payload["exchange"],
                                       market_type=payload["market_type"], series_identity=identity, _connection=conn)
            record["phase"] = "committed" if affected else "rejected"
            record["committed_revision"] = current_revision(conn)
            # Preserve the transaction head for publication and separately
            # attribute the exact revision advanced by this target write.
            written_revision = 0
            if affected and record["committed_revision"] > before_write:
                written = series_change(conn, values)
                if written is not None and written["revision"] > before_write:
                    written_revision = written["revision"]
            record["written_revision"] = written_revision
            conn.execute("UPDATE bar_delivery SET phase=?,committed_revision=?,written_revision=? WHERE event_id=?",
                         (record["phase"], record["committed_revision"], written_revision, event_id))
            self._prune(conn)
            return self._canonical(conn, record)

    def acknowledge(self, event_id):
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE bar_delivery SET phase='published' WHERE event_id=? AND phase='committed'", (event_id,))
            conn.execute("UPDATE bar_delivery SET recovery_required=0 WHERE event_id=? AND phase='rejected'", (event_id,))
            # Pending receipts and unpublished commits are never pruned.
            self._prune(conn)

    def acknowledge_many(self, event_ids):
        """Confirm a bounded published prefix atomically; pending is untouched.

        This only amortizes publication receipts. Canonical arbitration still
        happens per event before publication, preserving close/amend ordering.
        """
        if (not isinstance(event_ids, (tuple, list)) or not 1 <= len(event_ids) <= 64
                or any(not isinstance(value, str) or not value for value in event_ids)
                or sum(len(value.encode('utf-8')) for value in event_ids) > 64 * 1024):
            raise ValueError('bounded delivery identity batch required')
        ids = tuple(dict.fromkeys(event_ids))
        placeholders = ','.join('?' for _ in ids)
        with closing(self._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE bar_delivery SET phase='published' WHERE phase='committed' "
                         f'AND event_id IN ({placeholders})', ids)
            conn.execute("UPDATE bar_delivery SET recovery_required=0 WHERE phase='rejected' "
                         f'AND event_id IN ({placeholders})', ids)
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
