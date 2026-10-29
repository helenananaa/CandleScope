"""SQLite persistence for trading accounts, practice orders, fills and journal.

One connection guarded by a re-entrant lock; every public mutation is one
transaction. Decimal values are stored as canonical text.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from .models import dec_str

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cash_flows (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    kind TEXT NOT NULL,
    amount TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS cash_flows_account ON cash_flows(account_id, ts_ms);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    exchange TEXT NOT NULL,
    market_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    type TEXT NOT NULL,
    qty TEXT NOT NULL,
    limit_price TEXT,
    stop_price TEXT,
    reduce_only INTEGER NOT NULL DEFAULT 0,
    oco_group TEXT,
    tag TEXT,
    parent_id TEXT,
    bracket_stop TEXT,
    bracket_target TEXT,
    status TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    fill_price TEXT,
    filled_qty TEXT,
    filled_at_ms INTEGER,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS orders_working ON orders(status, exchange, market_type, symbol);
CREATE INDEX IF NOT EXISTS orders_account ON orders(account_id, created_at_ms);
CREATE TABLE IF NOT EXISTS fills (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    exchange TEXT NOT NULL,
    market_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty TEXT NOT NULL,
    price TEXT NOT NULL,
    fee TEXT NOT NULL,
    fee_currency TEXT NOT NULL,
    liquidity TEXT NOT NULL,
    order_id TEXT,
    ts_ms INTEGER NOT NULL,
    source TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS fills_account ON fills(account_id, ts_ms);
CREATE TABLE IF NOT EXISTS practice_cursors (
    exchange TEXT NOT NULL,
    market_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    bar_time INTEGER NOT NULL,
    seen_high TEXT NOT NULL,
    seen_low TEXT NOT NULL,
    last_close TEXT NOT NULL,
    observed_ms INTEGER NOT NULL,
    closes_only INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'live',
    detail TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (exchange, market_type, symbol)
);
CREATE TABLE IF NOT EXISTS journal_entries (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    exchange TEXT NOT NULL,
    market_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    trade_id TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    market_time_ms INTEGER,
    template_id TEXT,
    template_version INTEGER,
    tags_json TEXT NOT NULL DEFAULT '[]',
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS journal_account ON journal_entries(account_id, deleted, created_at_ms);
CREATE INDEX IF NOT EXISTS journal_trade ON journal_entries(trade_id);
CREATE TABLE IF NOT EXISTS journal_revisions (
    entry_id TEXT NOT NULL REFERENCES journal_entries(id),
    revision INTEGER NOT NULL,
    saved_at_ms INTEGER NOT NULL,
    fields_json TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (entry_id, revision)
);
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL REFERENCES journal_entries(id),
    created_at_ms INTEGER NOT NULL,
    image_file TEXT,
    state_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_entry ON snapshots(entry_id, created_at_ms);
"""

_DECIMAL_COLUMNS = {
    "qty", "limit_price", "stop_price", "bracket_stop", "bracket_target", "fill_price",
    "filled_qty", "price", "fee", "amount", "seen_high", "seen_low", "last_close",
}


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key in _DECIMAL_COLUMNS and value is not None:
            value = Decimal(value)
        out[key] = value
    return out


def _rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [item for item in (_row(row) for row in rows) if item is not None]


def _text(value: Any) -> Any:
    if isinstance(value, Decimal):
        return dec_str(value)
    if isinstance(value, bool):
        return int(value)
    return value


class TradingStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        with self.transaction() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(journal_revisions)")}
            if "history_complete" not in columns:
                # Old autosaves overwrote revisions. Preserve their bytes, but
                # never advertise them as a complete historical timeline.
                conn.execute("ALTER TABLE journal_revisions ADD COLUMN history_complete INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self._lock:
            yield

    # ── generic helpers ─────────────────────────────────────────

    def insert(self, conn: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({marks})",
            tuple(_text(value) for value in values.values()),
        )

    def update(
        self,
        conn: sqlite3.Connection,
        table: str,
        values: dict[str, Any],
        where: str,
        params: tuple[Any, ...],
    ) -> int:
        assignments = ", ".join(f"{column} = ?" for column in values)
        cursor = conn.execute(
            f"UPDATE {table} SET {assignments} WHERE {where}",
            tuple(_text(value) for value in values.values()) + params,
        )
        return cursor.rowcount

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            return _row(self._conn.execute(sql, params).fetchone())

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return _rows(self._conn.execute(sql, params).fetchall())

    # ── accounts ────────────────────────────────────────────────

    def account(self, account_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM accounts WHERE id = ?", (account_id,))
        if row is not None:
            row["settings"] = json.loads(row.pop("settings_json"))
            row["archived"] = bool(row["archived"])
        return row

    def accounts(self) -> list[dict[str, Any]]:
        rows = self.all("SELECT * FROM accounts ORDER BY created_at_ms")
        for row in rows:
            row["settings"] = json.loads(row.pop("settings_json"))
            row["archived"] = bool(row["archived"])
        return rows

    def cash_flows(self, account_id: str) -> list[dict[str, Any]]:
        return self.all(
            "SELECT * FROM cash_flows WHERE account_id = ? ORDER BY ts_ms, id",
            (account_id,),
        )

    # ── orders and fills ────────────────────────────────────────

    def order(self, order_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM orders WHERE id = ?", (order_id,))

    def orders(self, account_id: str, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if status:
            return self.all(
                "SELECT * FROM orders WHERE account_id = ? AND status = ? "
                "ORDER BY created_at_ms DESC LIMIT ?",
                (account_id, status, limit),
            )
        return self.all(
            "SELECT * FROM orders WHERE account_id = ? ORDER BY created_at_ms DESC LIMIT ?",
            (account_id, limit),
        )

    def working_orders_for(self, exchange: str, market_type: str, symbol: str) -> list[dict[str, Any]]:
        return self.all(
            "SELECT * FROM orders WHERE status = 'working' AND exchange = ? AND market_type = ? "
            "AND symbol = ? ORDER BY created_at_ms, id",
            (exchange, market_type, symbol),
        )

    def working_instruments(self) -> list[tuple[str, str, str]]:
        rows = self.all(
            "SELECT DISTINCT exchange, market_type, symbol FROM orders WHERE status = 'working'"
        )
        return [(row["exchange"], row["market_type"], row["symbol"]) for row in rows]

    def fills(self, account_id: str) -> list[dict[str, Any]]:
        return self.all(
            "SELECT * FROM fills WHERE account_id = ? ORDER BY ts_ms, seq",
            (account_id,),
        )

    def fill(self, fill_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM fills WHERE id = ?", (fill_id,))

    # ── practice cursors ────────────────────────────────────────

    def cursor(self, exchange: str, market_type: str, symbol: str) -> dict[str, Any] | None:
        row = self.one(
            "SELECT * FROM practice_cursors WHERE exchange = ? AND market_type = ? AND symbol = ?",
            (exchange, market_type, symbol),
        )
        if row is not None:
            row["closes_only"] = bool(row["closes_only"])
        return row

    def upsert_cursor(self, conn: sqlite3.Connection, values: dict[str, Any]) -> None:
        columns = list(values)
        conn.execute(
            f"INSERT INTO practice_cursors ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
            "ON CONFLICT(exchange, market_type, symbol) DO UPDATE SET "
            + ", ".join(f"{column} = excluded.{column}" for column in columns
                        if column not in {"exchange", "market_type", "symbol"}),
            tuple(_text(values[column]) for column in columns),
        )

    # ── journal ─────────────────────────────────────────────────

    def entry(self, entry_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM journal_entries WHERE id = ? AND deleted = 0", (entry_id,))
        if row is not None:
            row["tags"] = json.loads(row.pop("tags_json"))
        return row

    def entries(self, account_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.all(
            "SELECT * FROM journal_entries WHERE account_id = ? AND deleted = 0 "
            "ORDER BY created_at_ms DESC LIMIT ?",
            (account_id, limit),
        )
        for row in rows:
            row["tags"] = json.loads(row.pop("tags_json"))
        return rows

    def revisions(self, entry_id: str) -> list[dict[str, Any]]:
        rows = self.all(
            "SELECT * FROM journal_revisions WHERE entry_id = ? ORDER BY revision",
            (entry_id,),
        )
        for row in rows:
            row["fields"] = json.loads(row.pop("fields_json"))
        return rows

    def revisions_for(self, entry_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {entry_id: [] for entry_id in entry_ids}
        if not entry_ids:
            return out
        for start in range(0, len(entry_ids), 500):
            chunk = entry_ids[start:start + 500]
            rows = self.all(
                f"SELECT * FROM journal_revisions WHERE entry_id IN ({', '.join('?' for _ in chunk)}) "
                "ORDER BY entry_id, revision",
                tuple(chunk),
            )
            for row in rows:
                row["fields"] = json.loads(row.pop("fields_json"))
                out[row["entry_id"]].append(row)
        return out

    def snapshots(self, entry_id: str) -> list[dict[str, Any]]:
        rows = self.all(
            "SELECT * FROM snapshots WHERE entry_id = ? ORDER BY created_at_ms",
            (entry_id,),
        )
        for row in rows:
            row["state"] = json.loads(row.pop("state_json"))
        return rows

    def snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,))
        if row is not None:
            row["state"] = json.loads(row.pop("state_json"))
        return row
