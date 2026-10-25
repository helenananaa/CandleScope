"""Atomic read-only observations, facts and durable backfill checkpoints."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .normalization import AccountDataError

SCHEMA_VERSION = 1
KINDS = frozenset({"fills", "bills", "orders"})
_SECRET_KEYS = frozenset({"apikey", "secret", "password", "passphrase", "ok-access-key", "ok-access-sign"})


def canonical(value: Any) -> str:
    def inspect(item):
        if isinstance(item, Mapping):
            if any(str(key).lower() in _SECRET_KEYS for key in item):
                raise AccountDataError("SECRET_IN_PERSISTENT_PAYLOAD")
            for child in item.values():
                inspect(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                inspect(child)
    inspect(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class AccountRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "account-facts.sqlite3"
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, SCHEMA_VERSION}:
                raise AccountDataError("ACCOUNT_SCHEMA_UNSUPPORTED")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS account(
                  id TEXT PRIMARY KEY CHECK(id='okx'), venue_uid TEXT NOT NULL,
                  credential_id TEXT NOT NULL, enabled INTEGER NOT NULL,
                  created_ms INTEGER NOT NULL, requested_from_ms INTEGER NOT NULL,
                  status TEXT NOT NULL, error_code TEXT, last_success_ms INTEGER);
                CREATE TABLE IF NOT EXISTS raw_fact(
                  kind TEXT NOT NULL, external_key TEXT NOT NULL, body_hash TEXT NOT NULL,
                  body TEXT NOT NULL, first_received_ms INTEGER NOT NULL, last_received_ms INTEGER NOT NULL,
                  source TEXT NOT NULL, PRIMARY KEY(kind,external_key,body_hash));
                CREATE TABLE IF NOT EXISTS fact(
                  kind TEXT NOT NULL, external_key TEXT NOT NULL, event_ms INTEGER NOT NULL,
                  payload TEXT NOT NULL, raw_hash TEXT NOT NULL,
                  PRIMARY KEY(kind,external_key));
                CREATE INDEX IF NOT EXISTS fact_time ON fact(kind,event_ms,external_key);
                CREATE TABLE IF NOT EXISTS sync_scan(
                  kind TEXT PRIMARY KEY, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                  cursor TEXT, complete INTEGER NOT NULL, pages INTEGER NOT NULL DEFAULT 0,
                  updated_ms INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS coverage(
                  kind TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                  completed_ms INTEGER NOT NULL, PRIMARY KEY(kind,start_ms,end_ms));
                CREATE TABLE IF NOT EXISTS snapshot(
                  kind TEXT PRIMARY KEY, received_ms INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS gap(
                  kind TEXT NOT NULL,start_ms INTEGER NOT NULL,end_ms INTEGER NOT NULL,reason TEXT NOT NULL,
                  PRIMARY KEY(kind,start_ms,end_ms,reason));
                CREATE TABLE IF NOT EXISTS retired_credential(id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS journal_version(
                  note_id TEXT NOT NULL, version INTEGER NOT NULL, recorded_ms INTEGER NOT NULL,
                  event_ms INTEGER NOT NULL, fill_id TEXT, payload TEXT NOT NULL,
                  PRIMARY KEY(note_id,version));
                PRAGMA user_version=1;
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def account(self, *, credential_reference: bool = False) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM account WHERE id='okx'").fetchone()
        if row is None:
            return None
        value = dict(row)
        if not credential_reference:
            value.pop("credential_id")
        return value

    def bind(self, venue_uid: str, credential_id: str, requested_from_ms: int) -> None:
        now = int(time.time() * 1000)
        with self.transaction() as db:
            old = db.execute("SELECT * FROM account WHERE id='okx'").fetchone()
            if old is not None and old["venue_uid"] != venue_uid:
                raise AccountDataError("DIFFERENT_ACCOUNT_REQUIRES_SEPARATE_PROFILE")
            if old is None:
                db.execute("INSERT INTO account VALUES('okx',?,?,1,?,?,'syncing',NULL,NULL)",
                           (venue_uid, credential_id, now, requested_from_ms))
            else:
                if old["credential_id"] and old["credential_id"] != credential_id:
                    db.execute("INSERT OR IGNORE INTO retired_credential VALUES(?)",(old["credential_id"],))
                db.execute("UPDATE account SET credential_id=?,enabled=1,status='syncing',error_code=NULL WHERE id='okx'",
                           (credential_id,))
            db.execute("DELETE FROM retired_credential WHERE id=?", (credential_id,))

    def stage_credential(self, record_id: str) -> None:
        # Record the cleanup intent before Keychain is touched. A process crash
        # can then leave neither an untracked new key nor a deleted active key.
        with self.transaction() as db:
            active = db.execute("SELECT credential_id FROM account WHERE id='okx'").fetchone()
            if active is not None and active[0] == record_id:
                raise AccountDataError("CREDENTIAL_ALREADY_ACTIVE")
            db.execute("INSERT INTO retired_credential VALUES(?)", (record_id,))

    def status(self, state: str, *, error: str | None = None, success: bool = False,
               enabled: bool | None = None) -> None:
        with self.transaction() as db:
            db.execute("UPDATE account SET status=?,error_code=?,last_success_ms=CASE WHEN ? THEN ? ELSE last_success_ms END,enabled=COALESCE(?,enabled) WHERE id='okx'",
                       (state, error, success, int(time.time()*1000), enabled))

    def forget_credential(self) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO retired_credential SELECT credential_id FROM account WHERE id='okx' AND credential_id!=''")
            db.execute("UPDATE account SET credential_id='',enabled=0,status='disconnected',error_code=NULL WHERE id='okx'")

    def retired_credentials(self) -> list[str]:
        with self.connection() as db:
            return [row[0] for row in db.execute("SELECT id FROM retired_credential")]

    def credential_removed(self, record_id: str) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM retired_credential WHERE id=?",(record_id,))

    def counts(self) -> dict[str,int]:
        with self.connection() as db:
            return {row[0]:row[1] for row in db.execute("SELECT kind,COUNT(*) FROM fact GROUP BY kind")}

    def scans(self) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM sync_scan ORDER BY kind")]

    def start_scan(self, kind: str, start_ms: int, end_ms: int) -> dict:
        if kind not in KINDS or start_ms > end_ms:
            raise AccountDataError("SYNC_RANGE_INVALID")
        with self.transaction() as db:
            old = db.execute("SELECT * FROM sync_scan WHERE kind=?", (kind,)).fetchone()
            if old is not None and not old["complete"]:
                return dict(old)
            db.execute("INSERT OR REPLACE INTO sync_scan VALUES(?,?,?,NULL,0,0,?)",
                       (kind,start_ms,end_ms,int(time.time()*1000)))
            return dict(db.execute("SELECT * FROM sync_scan WHERE kind=?", (kind,)).fetchone())

    @staticmethod
    def _raw(db, kind: str, key: str, value: dict, received_ms: int, source: str) -> str:
        body = canonical(value)
        if len(body.encode()) > 256 * 1024:
            raise AccountDataError("ACCOUNT_RECORD_TOO_LARGE")
        digest = hashlib.sha256(body.encode()).hexdigest()
        db.execute("INSERT INTO raw_fact VALUES(?,?,?,?,?,?,?) ON CONFLICT(kind,external_key,body_hash) DO UPDATE SET last_received_ms=excluded.last_received_ms",
                   (kind,key,digest,body,received_ms,received_ms,source))
        return digest

    def page(self, kind: str, expected_cursor: str | None,
             rows: Sequence[tuple[str, dict, dict]], *, next_cursor: str | None, complete: bool) -> None:
        if kind not in KINDS or len(rows) > 100:
            raise AccountDataError("SYNC_PAGE_INVALID")
        if not complete and (not next_cursor or next_cursor == expected_cursor):
            raise AccountDataError("SYNC_CURSOR_STALLED")
        now = int(time.time()*1000)
        # Observation durability precedes projection. A conflicting fact must
        # retain both raw versions while its financial projection/cursor stays put.
        with self.transaction() as db:
            digests = [self._raw(db,kind,key,raw,now,"REST") for key,raw,_ in rows]
        with self.transaction() as db:
            scan = db.execute("SELECT * FROM sync_scan WHERE kind=?", (kind,)).fetchone()
            if scan is None or scan["complete"] or scan["cursor"] != expected_cursor:
                raise AccountDataError("SYNC_CURSOR_CONFLICT")
            for (key, raw, normalized), digest in zip(rows, digests, strict=True):
                payload = canonical(normalized)
                previous = db.execute("SELECT * FROM fact WHERE kind=? AND external_key=?", (kind,key)).fetchone()
                if previous is not None:
                    if kind != "orders" and previous["payload"] != payload:
                        raise AccountDataError("EXCHANGE_FACT_CONFLICT")
                    if normalized["eventTimeMs"] < previous["event_ms"]:
                        continue
                    if kind == "orders" and normalized["eventTimeMs"] == previous["event_ms"] and previous["payload"] != payload:
                        raise AccountDataError("EXCHANGE_FACT_CONFLICT")
                db.execute("INSERT OR REPLACE INTO fact VALUES(?,?,?,?,?)",
                           (kind,key,normalized["eventTimeMs"],payload,digest))
            db.execute("UPDATE sync_scan SET cursor=?,complete=?,pages=pages+1,updated_ms=? WHERE kind=?",
                       (next_cursor,complete,now,kind))
            if complete:
                db.execute("INSERT OR REPLACE INTO coverage VALUES(?,?,?,?)", (kind,scan["start_ms"],scan["end_ms"],now))

    def observe_rest(self, kind: str, rows: Sequence[dict], identity_key: str) -> None:
        if kind not in KINDS or len(rows) > 100:
            raise AccountDataError("SYNC_PAGE_INVALID")
        now = int(time.time()*1000)
        with self.transaction() as db:
            for raw in rows:
                key = raw.get(identity_key)
                if not isinstance(key, str) or not 1 <= len(key) <= 128:
                    key = "unidentified:" + hashlib.sha256(canonical(raw).encode()).hexdigest()
                self._raw(db,kind,key,raw,now,"REST")

    def ingest_recent(self, kind: str, rows: Sequence[tuple[str, dict, dict]]) -> None:
        """Update latest facts without touching the durable historical cursor."""
        if kind not in KINDS or len(rows) > 100:
            raise AccountDataError("SYNC_PAGE_INVALID")
        now = int(time.time()*1000)
        with self.transaction() as db:
            digests = [self._raw(db,kind,key,raw,now,"REST") for key,raw,_ in rows]
        with self.transaction() as db:
            for (key, raw, normalized), digest in zip(rows,digests,strict=True):
                payload = canonical(normalized)
                previous = db.execute("SELECT * FROM fact WHERE kind=? AND external_key=?",(kind,key)).fetchone()
                if previous is not None:
                    if kind != "orders" and previous["payload"] != payload:
                        raise AccountDataError("EXCHANGE_FACT_CONFLICT")
                    if normalized["eventTimeMs"] < previous["event_ms"]:
                        continue
                    if normalized["eventTimeMs"] == previous["event_ms"] and previous["payload"] != payload:
                        raise AccountDataError("EXCHANGE_FACT_CONFLICT")
                db.execute("INSERT OR REPLACE INTO fact VALUES(?,?,?,?,?)",(kind,key,normalized["eventTimeMs"],payload,digest))

    def observe(self, channel: str, rows: Sequence[dict], *, received_ms: int) -> None:
        if channel not in {"orders", "positions", "account"} or len(rows) > 1000:
            raise AccountDataError("ACCOUNT_EVENT_INVALID")
        with self.transaction() as db:
            for row in rows:
                key = str(row.get("ordId") or row.get("posId") or row.get("uTime") or received_ms)
                self._raw(db,"ws:"+channel,key,row,received_ms,"WS")

    def save_snapshot(self, kind: str, payload: dict | list, received_ms: int) -> None:
        if kind not in {"positions", "open_orders", "balances", "contracts"}:
            raise AccountDataError("SNAPSHOT_KIND_INVALID")
        with self.transaction() as db:
            if kind == "contracts":
                for item in payload:
                    self._raw(db,"contract",item["normalized"]["instrument"],item["raw"],received_ms,"REST")
            db.execute("INSERT OR REPLACE INTO snapshot VALUES(?,?,?)", (kind,received_ms,canonical(payload)))

    def snapshots(self) -> dict:
        with self.connection() as db:
            return {row["kind"]:{"receivedMs":row["received_ms"],"data":json.loads(row["payload"])}
                    for row in db.execute("SELECT * FROM snapshot")}

    def facts(self, kind: str, *, before: tuple[int, str] | None = None, limit: int = 100) -> list[dict]:
        if kind not in KINDS or not 1 <= limit <= 500:
            raise AccountDataError("FACT_QUERY_INVALID")
        with self.connection() as db:
            if before:
                rows = db.execute("SELECT payload FROM fact WHERE kind=? AND (event_ms,external_key)<(?,?) ORDER BY event_ms DESC,external_key DESC LIMIT ?", (kind,*before,limit))
            else:
                rows = db.execute("SELECT payload FROM fact WHERE kind=? ORDER BY event_ms DESC,external_key DESC LIMIT ?", (kind,limit))
            return [json.loads(row[0]) for row in rows]

    def coverage(self) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM coverage ORDER BY kind,start_ms,end_ms")]

    def mark_gap(self, kind: str, start_ms: int, end_ms: int, *, abandon_scan: bool = False) -> None:
        if kind not in KINDS or start_ms > end_ms:
            raise AccountDataError("SYNC_RANGE_INVALID")
        with self.transaction() as db:
            overlaps = db.execute("SELECT start_ms,end_ms FROM gap WHERE kind=? AND reason='EXCHANGE_RETENTION_LIMIT' AND start_ms<=? AND end_ms>=?",(kind,end_ms+1,start_ms-1)).fetchall()
            if overlaps:
                start_ms = min(start_ms,*(row["start_ms"] for row in overlaps))
                end_ms = max(end_ms,*(row["end_ms"] for row in overlaps))
                db.execute("DELETE FROM gap WHERE kind=? AND reason='EXCHANGE_RETENTION_LIMIT' AND start_ms<=? AND end_ms>=?",(kind,end_ms+1,start_ms-1))
            db.execute("INSERT OR IGNORE INTO gap VALUES(?,?,?,'EXCHANGE_RETENTION_LIMIT')",(kind,start_ms,end_ms))
            if abandon_scan:
                db.execute("DELETE FROM sync_scan WHERE kind=?",(kind,))

    def gaps(self) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM gap ORDER BY kind,start_ms")]

    def discard_expired_scan(self, kind: str, expected_end_ms: int) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM sync_scan WHERE kind=? AND complete=0 AND end_ms=?",(kind,expected_end_ms))

    def save_note(self, note_id: str, expected_version: int, payload: dict, *, event_ms: int,
                  fill_id: str | None = None) -> dict:
        now = int(time.time()*1000)
        body = canonical(payload)
        if len(body.encode()) > 32*1024:
            raise AccountDataError("JOURNAL_RECORD_TOO_LARGE")
        with self.transaction() as db:
            if fill_id is not None and db.execute("SELECT 1 FROM fact WHERE kind='fills' AND external_key=?",(fill_id,)).fetchone() is None:
                raise AccountDataError("JOURNAL_FILL_NOT_FOUND")
            current = db.execute("SELECT MAX(version) FROM journal_version WHERE note_id=?",(note_id,)).fetchone()[0] or 0
            if expected_version != current:
                raise AccountDataError("JOURNAL_VERSION_CONFLICT")
            version = current + 1
            db.execute("INSERT INTO journal_version VALUES(?,?,?,?,?,?)", (note_id,version,now,event_ms,fill_id,body))
        return {"noteId":note_id,"version":version,"recordedMs":now,"eventMs":event_ms,"fillId":fill_id,"payload":payload}

    def notes(self, *, before: tuple[int, str, int] | None = None, limit: int = 200) -> list[dict]:
        if not 1 <= limit <= 500:
            raise AccountDataError("JOURNAL_QUERY_INVALID")
        with self.connection() as db:
            clause = "WHERE (recorded_ms,note_id,version)<(?,?,?)" if before is not None else ""
            rows = db.execute(f"SELECT * FROM journal_version {clause} ORDER BY recorded_ms DESC,note_id DESC,version DESC LIMIT ?", (*before,limit) if before is not None else (limit,))
            return [{"noteId":row["note_id"],"version":row["version"],"recordedMs":row["recorded_ms"],
                     "eventMs":row["event_ms"],"fillId":row["fill_id"],"payload":json.loads(row["payload"])} for row in rows]
