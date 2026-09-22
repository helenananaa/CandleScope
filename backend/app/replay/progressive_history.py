"""Durable append-only market segments for a fixed progressive BAR horizon.

Only market references live here. A segment binds an immutable archive revision;
consumer clocks and account state remain in their existing session stores.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

from .canonical import canonical_json, canonical_sha256
from .catalog import ReplaySeriesIdentity
from .dataset import validate_replay_repository_bar
from .errors import ReplayDomainError, ReplayErrorCode

MANIFEST_SCHEMA = "replay.progressive-bar-manifest.v1"


def retained_revisions(archive_root):
    path = Path(archive_root) / "progressive-index.sqlite3"
    if not path.exists():
        return ()
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        references = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='progressive_bar_refs'").fetchone()
        query = "SELECT DISTINCT archive_revision FROM progressive_bar_segments"
        if references:
            query += " WHERE feed_id IN (SELECT feed_id FROM progressive_bar_refs)"
        return tuple(row[0] for row in db.execute(query))
    finally:
        db.close()


def validate_manifest(payload, dataset):
    fields = {"schema_version", "data_epoch", "feed_id", "terminal_open_ms", "terminal_kind", "page_rows", "manifest_hash"}
    if set(payload) != fields or payload.get("schema_version") != MANIFEST_SCHEMA:
        raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Progressive manifest fields are incompatible")
    material = dict(payload)
    claimed = material.pop("manifest_hash")
    feed_id = material["feed_id"]
    terminal = material["terminal_open_ms"]
    page_rows = material["page_rows"]
    if (claimed != canonical_sha256(material) or material["data_epoch"] != dataset.data_epoch
            or not isinstance(feed_id, str) or len(feed_id) != 71 or not feed_id.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in feed_id[7:])
            or type(terminal) is not int or terminal % 60_000 or terminal < dataset.replay_end_open_ms
            or dataset.interval != "1m" or material["terminal_kind"] != "REQUESTED_HORIZON"
            or type(page_rows) is not int or not 1 <= page_rows <= 4096):
        raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Progressive manifest identity or range is invalid")
    return dict(payload)


class ProgressiveBarHistory:
    def __init__(self, path: Path, archive, *, now_ms=lambda: int(time.time() * 1000)):
        self.path, self.archive, self.now_ms = Path(path), archive, now_ms
        if self.path.resolve() != (Path(archive.root) / "progressive-index.sqlite3").resolve():
            raise ValueError("Progressive history index must live inside its owning archive for GC retention")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from .history_archive import _archive_mutation_lock
        with _archive_mutation_lock(Path(self.archive.root) / ".mutation.lock"), self.connect() as db:
            legacy = not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='progressive_bar_refs'").fetchone()
            db.executescript("""
                PRAGMA journal_mode=WAL;
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS progressive_bar_feeds (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    identity TEXT NOT NULL, start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL, ready_end_ms INTEGER NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS progressive_bar_segments (
                    feed_id TEXT NOT NULL REFERENCES progressive_bar_feeds(id),
                    start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                    archive_revision TEXT NOT NULL,
                    PRIMARY KEY(feed_id,start_ms)
                );
                CREATE TABLE IF NOT EXISTS progressive_bar_refs (
                    feed_id TEXT NOT NULL REFERENCES progressive_bar_feeds(id),
                    owner TEXT NOT NULL,
                    PRIMARY KEY(feed_id,owner)
                );
            """)
            if legacy:
                db.execute("INSERT OR IGNORE INTO progressive_bar_refs SELECT id, 'legacy:' || id FROM progressive_bar_feeds")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, request_key, identity: ReplaySeriesIdentity, start_ms, end_ms):
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 128:
            raise ValueError("progressive request key must contain 8-128 characters")
        if (type(start_ms) is not int or type(end_ms) is not int or start_ms < 0
                or end_ms <= start_ms or start_ms % 60_000 or end_ms % 60_000
                or end_ms - start_ms > 366 * 86_400_000
                or end_ms > self.now_ms() // 60_000 * 60_000):
            raise ValueError("progressive horizon must contain closed, minute-aligned historical bars")
        market = {"exchange": identity.exchange, "market_type": identity.market_type, "symbol": identity.symbol}
        feed_id = canonical_sha256({"schema": "replay.progressive-bar.v1", "request_key": request_key,
                                    "identity": market, "start_ms": start_ms, "end_ms": end_ms})
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT id FROM progressive_bar_feeds WHERE request_key=?", (request_key,)).fetchone()
            if previous and previous["id"] != feed_id:
                raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Progressive request key belongs to a different horizon")
            db.execute("INSERT OR IGNORE INTO progressive_bar_feeds VALUES (?,?,?,?,?,?,0)",
                       (feed_id, request_key, canonical_json(market), start_ms, end_ms, start_ms))
            db.execute("INSERT OR IGNORE INTO progressive_bar_refs VALUES (?,?)", (feed_id, "preparation:" + request_key))
        return self.status(feed_id)

    def pin(self, feed_id, owner):
        from .history_archive import _archive_mutation_lock
        with _archive_mutation_lock(Path(self.archive.root) / ".mutation.lock"), self.connect() as db:
            self._feed(db, feed_id)
            db.execute("INSERT OR IGNORE INTO progressive_bar_refs VALUES (?,?)", (feed_id, owner))

    def release(self, owner):
        from .history_archive import _archive_mutation_lock
        with _archive_mutation_lock(Path(self.archive.root) / ".mutation.lock"), self.connect() as db:
            db.execute("DELETE FROM progressive_bar_refs WHERE owner=?", (owner,))

    def reconcile_sessions(self, scope, session_ids):
        """Startup-only cleanup for one database; unknown owners stay pinned."""
        from .history_archive import _archive_mutation_lock
        prefix = "session:" + scope + ":"
        retained = {prefix + session_id for session_id in session_ids}
        with _archive_mutation_lock(Path(self.archive.root) / ".mutation.lock"), self.connect() as db:
            owners = {row[0] for row in db.execute("SELECT DISTINCT owner FROM progressive_bar_refs")}
            stale = [(owner,) for owner in owners if owner.startswith(prefix) and owner not in retained]
            db.executemany("DELETE FROM progressive_bar_refs WHERE owner=?", stale)
            return len(stale)

    @staticmethod
    def _feed(db, feed_id):
        row = db.execute("SELECT * FROM progressive_bar_feeds WHERE id=?", (feed_id,)).fetchone()
        if row is None:
            raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Progressive history is unavailable")
        return dict(row)

    def status(self, feed_id):
        with self.connect() as db:
            feed = self._feed(db, feed_id)
        feed["identity"] = json.loads(feed["identity"])
        feed["complete"] = feed["ready_end_ms"] == feed["end_ms"]
        return feed

    def manifest(self, feed_id, dataset, *, page_rows=256):
        feed = self.status(feed_id)
        payload = {"schema_version": MANIFEST_SCHEMA, "data_epoch": dataset.data_epoch,
            "feed_id": feed_id, "terminal_open_ms": feed["end_ms"] - 60_000,
            "terminal_kind": "REQUESTED_HORIZON", "page_rows": page_rows}
        payload["manifest_hash"] = canonical_sha256(payload)
        return validate_manifest(payload, dataset)

    def _read_segment(self, feed, revision, start_ms, end_ms):
        market = feed["identity"]
        if isinstance(market, str):
            market = json.loads(market)
        identity = ReplaySeriesIdentity(**market)
        count = (end_ms - start_ms) // 60_000
        rows = self.archive.query_bars_at_revision(revision, identity.symbol, "1m",
            start_ms=start_ms, end_ms=end_ms - 1, limit=count, order="ASC",
            exchange=identity.exchange, market_type=identity.market_type)
        if len(rows) != count:
            raise ReplayDomainError(ReplayErrorCode.DATASET_INCOMPLETE, "Progressive segment has incomplete archive coverage")
        now = self.now_ms()
        return tuple(validate_replay_repository_bar(row, identity=identity, interval="1m", interval_ms=60_000,
            expected_open_ms=start_ms + index * 60_000, now_ms=now) for index, row in enumerate(rows))

    def publish(self, feed_id, archive_revision, start_ms, end_ms):
        from .history_archive import _archive_mutation_lock
        # GC takes the same archive lock before reading this directory. Pinning
        # a new revision therefore cannot race its physical deletion.
        with _archive_mutation_lock(Path(self.archive.root) / ".mutation.lock"):
            return self._publish_locked(feed_id, archive_revision, start_ms, end_ms)

    def _publish_locked(self, feed_id, archive_revision, start_ms, end_ms):
        feed = self.status(feed_id)
        if (type(start_ms) is not int or type(end_ms) is not int or start_ms % 60_000 or end_ms % 60_000
                or start_ms < feed["start_ms"] or end_ms > feed["end_ms"] or not 0 < end_ms - start_ms <= 86_400_000):
            raise ValueError("progressive publication must be a bounded minute-aligned segment inside the fixed horizon")
        # Validate outside the writer transaction. Publication never makes an
        # absent or corrupt archive revision part of the visible ready prefix.
        self._read_segment(feed, archive_revision, start_ms, end_ms)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._feed(db, feed_id)
            prior = db.execute("SELECT * FROM progressive_bar_segments WHERE feed_id=? AND start_ms=?", (feed_id, start_ms)).fetchone()
            if prior is not None:
                if prior["end_ms"] != end_ms or prior["archive_revision"] != archive_revision:
                    raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Published progressive history cannot be replaced")
            else:
                if start_ms != current["ready_end_ms"]:
                    raise ReplayDomainError(ReplayErrorCode.DATA_GAP, "Progressive history must append a contiguous segment")
                db.execute("INSERT INTO progressive_bar_segments VALUES (?,?,?,?)", (feed_id, start_ms, end_ms, archive_revision))
                db.execute("UPDATE progressive_bar_feeds SET ready_end_ms=?,revision=revision+1 WHERE id=?", (end_ms, feed_id))
        return self.status(feed_id)

    def read(self, feed_id, start_ms, end_ms):
        if (type(start_ms) is not int or type(end_ms) is not int or start_ms % 60_000 or end_ms % 60_000
                or not 0 < end_ms - start_ms <= 4096 * 60_000):
            raise ValueError("progressive reads must contain 1-4096 whole minutes")
        with self.connect() as db:
            feed = self._feed(db, feed_id)
            if start_ms < feed["start_ms"] or end_ms > feed["end_ms"]:
                raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Requested page exceeds the committed progressive horizon")
            if end_ms > feed["ready_end_ms"]:
                # No timestamps in the error: blind training decides what time
                # information its projection is allowed to reveal.
                raise ReplayDomainError(ReplayErrorCode.DATASET_PENDING, "Historical data is still being prepared")
            segments = db.execute("SELECT * FROM progressive_bar_segments WHERE feed_id=? AND start_ms<? AND end_ms>? ORDER BY start_ms",
                                  (feed_id, end_ms, start_ms)).fetchall()
        rows = []
        cursor = start_ms
        for segment in segments:
            stop = min(end_ms, segment["end_ms"])
            if segment["start_ms"] > cursor:
                raise ReplayDomainError(ReplayErrorCode.DATASET_INCOMPLETE, "Progressive segment directory contains a gap")
            rows.extend(self._read_segment(feed, segment["archive_revision"], cursor, stop))
            cursor = stop
        if cursor != end_ms:
            raise ReplayDomainError(ReplayErrorCode.DATASET_INCOMPLETE, "Progressive segment directory is incomplete")
        return tuple(rows)


class ProgressiveHistoryRepository:
    """Read chart pages from the same immutable revisions as the execution feed.

    Pre-start history stays on the initial archive revision. Future portions are
    limited to committed segments; caller still enforces the revealed cursor.
    """
    def __init__(self, history, feed_id, initial_revision):
        self.history = history
        self.feed_id = feed_id
        self.initial_revision = initial_revision
        self.feed = history.status(feed_id)

    def _check(self, revision, symbol, interval, exchange, market_type):
        identity = self.feed["identity"]
        if (revision != self.initial_revision or interval != "1m"
                or (exchange, market_type, symbol) != (
                    identity["exchange"], identity["market_type"], identity["symbol"])):
            raise ReplayDomainError(ReplayErrorCode.DATASET_MISMATCH, "Progressive chart identity changed")

    def get_bounds_at_revision(self, revision, symbol, interval, *, exchange, market_type):
        self._check(revision, symbol, interval, exchange, market_type)
        return self.history.archive.get_bounds_at_revision(revision, symbol, interval,
            exchange=exchange, market_type=market_type)

    def query_bars_at_revision(self, revision, symbol, interval, *, start_ms, end_ms,
                               limit, order, exchange, market_type):
        self._check(revision, symbol, interval, exchange, market_type)
        if end_ms >= self.feed["ready_end_ms"]:
            raise ReplayDomainError(ReplayErrorCode.DATASET_PENDING, "Progressive chart range is not ready")
        ranges = []
        if start_ms < self.feed["start_ms"]:
            ranges.append((start_ms, min(end_ms, self.feed["start_ms"] - 1), revision))
        with self.history.connect() as db:
            rows = db.execute("SELECT start_ms,end_ms,archive_revision FROM progressive_bar_segments "
                "WHERE feed_id=? AND start_ms<=? AND end_ms>? ORDER BY start_ms",
                (self.feed_id, end_ms, start_ms)).fetchall()
        ranges.extend((max(start_ms, row["start_ms"]), min(end_ms, row["end_ms"] - 1), row["archive_revision"])
                      for row in rows)
        if order == "DESC":
            ranges.reverse()
        result = []
        for first, last, bound_revision in ranges:
            if len(result) >= limit:
                break
            result.extend(self.history.archive.query_bars_at_revision(bound_revision, symbol, interval,
                start_ms=first, end_ms=last, limit=limit - len(result), order=order,
                exchange=exchange, market_type=market_type))
        return result

    def scan_gaps_at_revision(self, revision, symbol, interval, *, start_ms, end_ms,
                             exchange, market_type, limit):
        self._check(revision, symbol, interval, exchange, market_type)
        if end_ms >= self.feed["ready_end_ms"]:
            raise ReplayDomainError(ReplayErrorCode.DATASET_PENDING, "Progressive chart range is not ready")
        if start_ms < self.feed["start_ms"]:
            return self.history.archive.scan_gaps_at_revision(revision, symbol, interval,
                start_ms=start_ms, end_ms=min(end_ms, self.feed["start_ms"] - 60_000),
                exchange=exchange, market_type=market_type, limit=limit)
        return {"gaps": [], "truncated": False, "source_revision": revision}


    def query_source_bucket_bars_at_revision(self, revision, symbol, base_interval, display_interval, *,
            actual_start_ms, actual_end_ms, actual_replay_start_ms, public_replay_start_ms, limit,
            include_partial=False, source_bucket_anchor_ms=None, exchange=None, market_type=None):
        from decimal import Decimal
        from .models import normalize_decimal_string
        from .display_time import SourceBucketTimeMapper
        self._check(revision, symbol, base_interval, exchange, market_type)
        mapper = SourceBucketTimeMapper.create(interval=display_interval,
            actual_replay_start_ms=actual_replay_start_ms, public_replay_start_ms=public_replay_start_ms,
            source_bucket_anchor_ms=source_bucket_anchor_ms)
        last_bucket = mapper.actual_containing_bucket_open(actual_end_ms - 1)
        first_bucket = mapper.actual_bucket_open(mapper.actual_bucket_ordinal(last_bucket) - limit - 2)
        first = max(actual_start_ms, first_bucket)
        groups = {}
        cursor = first
        optional = ("quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
        # Stream bounded base pages, retaining only bucket summaries. Calendar
        # months use the mapper's actual exchange grid before time disclosure.
        while cursor < actual_end_ms:
            stop = min(actual_end_ms, cursor + 4096 * 60_000)
            rows = self.query_bars_at_revision(revision, symbol, base_interval,
                start_ms=cursor, end_ms=stop - 1, limit=4096, order="ASC",
                exchange=exchange, market_type=market_type)
            for row in rows:
                timestamp = int(row["open_time"])
                bucket = mapper.actual_containing_bucket_open(timestamp)
                values = {key: None if row.get(key) is None else Decimal(str(row[key]))
                          for key in ("open", "high", "low", "close", "volume", *optional)}
                group = groups.get(bucket)
                if group is None:
                    group = {**values, "first": timestamp, "last": timestamp, "count": 1, "contiguous": True}
                    groups[bucket] = group
                else:
                    group["contiguous"] = group["contiguous"] and timestamp == group["last"] + 60_000
                    group["last"], group["count"] = timestamp, group["count"] + 1
                    group["high"] = max(group["high"], values["high"])
                    group["low"] = min(group["low"], values["low"])
                    group["close"] = values["close"]
                    group["volume"] += values["volume"]
                    for key in optional:
                        group[key] = None if group[key] is None or values[key] is None else group[key] + values[key]
            cursor = stop
        bars = []
        public_revealed = public_replay_start_ms + actual_end_ms - actual_replay_start_ms - 1
        for bucket, group in sorted(groups.items()):
            bucket_end = mapper.actual_bucket_end(bucket)
            expected = (bucket_end - bucket) // 60_000
            complete = group["count"] == expected and group["last"] + 60_000 == bucket_end
            partial = include_partial and group["count"] < expected and group["last"] + 60_000 == actual_end_ms
            if not group["contiguous"] or group["first"] != bucket or not (complete or partial):
                continue
            public = mapper.public_from_actual(bucket)
            public_end = mapper.public_bucket_end(public)
            last_base = min(public_end - 60_000, public + (group["count"] - 1) * 60_000, public_revealed)
            if public < 0 or last_base < public:
                continue
            result = {key: None if group[key] is None else normalize_decimal_string(format(group[key], "f"), field_name=key)
                      for key in ("open", "high", "low", "close", "volume", *optional)}
            result["trades"] = None if group["trades"] is None else int(group["trades"])
            bars.append({**result, "open_time_ms": public, "close_time_ms": public_end - 1,
                "first_base_open_ms": public, "last_base_open_ms": last_base,
                "component_count": group["count"], "expected_components": expected,
                "is_closed": complete, "synthetic": False})
        return {"bars": bars[-(limit + 1):], "has_more": first > actual_start_ms or len(bars) > limit}
