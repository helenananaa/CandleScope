"""SQLite owner for external connections, separate from financial records."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.backtest.strategy.protocol import StrategyProviderError, canonical_hash

from .journal_schema import SCHEMA as JOURNAL_SCHEMA

_SCHEMA = """
CREATE TABLE IF NOT EXISTS external_provider_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL
);
INSERT OR IGNORE INTO external_provider_meta VALUES (1, 1);
CREATE TABLE IF NOT EXISTS external_provider_connections (
    connection_id TEXT PRIMARY KEY,
    scope_json TEXT NOT NULL,
    scope_hash TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    client_id TEXT,
    client_generation INTEGER NOT NULL DEFAULT 0,
    lease_deadline_ms INTEGER NOT NULL DEFAULT 0,
    created_ms INTEGER NOT NULL,
    revoked_ms INTEGER
);
"""


class ExternalConnectionRepository:
    """Only Host connection metadata; never opens a market/account database."""

    def __init__(self, path: Path, *, lease_ms: int = 15_000, max_connections: int = 64,
                 max_record_bytes: int = 268_435_456) -> None:
        if lease_ms <= 0 or max_connections <= 0 or max_record_bytes <= 0:
            raise ValueError("external connection limits must be positive")
        self.path = Path(path)
        self.lease_ms = lease_ms
        self.max_connections = max_connections
        self.max_record_bytes = max_record_bytes
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def open(self) -> None:
        with self._lock:
            if self._connection is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            if os.name != "nt":
                self.path.chmod(0o600)
            connection = sqlite3.connect(self.path, check_same_thread=False)
            try:
                connection.row_factory = sqlite3.Row
                has_meta = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'external_provider_meta'"
                ).fetchone()
                if has_meta is not None:
                    version = connection.execute(
                        "SELECT schema_version FROM external_provider_meta WHERE singleton = 1"
                    ).fetchone()
                    if version is None or version[0] != 1:
                        raise StrategyProviderError("SCHEMA_UNKNOWN_FIELD", "unsupported external connection store")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=250")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.executescript(_SCHEMA)
                connection.executescript(JOURNAL_SCHEMA)
                version = connection.execute(
                    "SELECT schema_version FROM external_provider_meta WHERE singleton = 1"
                ).fetchone()[0]
                if version != 1:
                    raise StrategyProviderError("SCHEMA_UNKNOWN_FIELD", "unsupported external connection store")
                connection.commit()
            except BaseException:
                connection.close()
                raise
            self._connection = connection

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._connection is None:
                raise RuntimeError("external connection store is not open")
            yield self._connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._connection is None:
                raise RuntimeError("external connection store is not open")
            connection = self._connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @contextmanager
    def _snapshot_read(self) -> Iterator[sqlite3.Connection]:
        """Keep request/state reads consistent without taking a writer lease."""
        with self._lock:
            if self._connection is None:
                raise RuntimeError("external connection store is not open")
            connection = self._connection
            connection.execute("BEGIN")
            try:
                yield connection
            finally:
                connection.rollback()

    def create(self, scope: dict[str, object], *, token: str, now_ms: int) -> str:
        scope_json = json.dumps(scope, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(scope_json.encode("utf-8")) > 24_576:
            raise StrategyProviderError("BUDGET_EXCEEDED", "external connection scope is too large")
        token_hash = self._token_hash(token)
        connection_id = "epc_" + uuid.uuid4().hex
        with self._transaction() as connection:
            active = connection.execute(
                "SELECT COUNT(*) FROM external_provider_connections WHERE revoked_ms IS NULL"
            ).fetchone()[0]
            if active >= self.max_connections:
                raise StrategyProviderError("BUDGET_EXCEEDED", "external connection ceiling reached")
            size = len(scope_json.encode("utf-8")) + 512
            used = connection.execute("SELECT logical_bytes FROM external_provider_usage WHERE singleton = 1").fetchone()[0]
            if used + size > self.max_record_bytes:
                raise StrategyProviderError("BUDGET_EXCEEDED", "external connection storage budget exceeded")
            connection.execute(
                """INSERT INTO external_provider_connections
                   (connection_id, scope_json, scope_hash, token_hash, created_ms)
                   VALUES (?, ?, ?, ?, ?)""",
                (connection_id, scope_json, canonical_hash(scope), token_hash, now_ms),
            )
            connection.execute("UPDATE external_provider_usage SET logical_bytes = logical_bytes + ? WHERE singleton = 1", (size,))
        return connection_id

    def scope(self, connection_id: str) -> dict[str, object]:
        with self._read() as connection:
            row = self._row(connection, connection_id)
            if row is None or row["revoked_ms"] is not None:
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external connection is unavailable")
            return json.loads(row["scope_json"])

    def ready(self, connection_id: str, *, now_ms: int) -> bool:
        with self._read() as connection:
            row = self._row(connection, connection_id)
            return bool(row is not None and row["revoked_ms"] is None
                        and row["client_id"] and row["lease_deadline_ms"] > now_ms)

    def connect(self, connection_id: str, *, token: str, client_id: str, now_ms: int) -> dict[str, object]:
        if (type(client_id) is not str or not client_id or len(client_id) > 128 or client_id != client_id.strip()
                or (type(token) is str and token in client_id)):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external client identity")
        with self._transaction() as connection:
            row = self._authorize(connection, connection_id, token)
            active = row["client_id"] is not None and row["lease_deadline_ms"] > now_ms
            if active and row["client_id"] != client_id:
                raise StrategyProviderError("PROVIDER_CONNECTION_BUSY", "another external client owns this connection")
            generation = int(row["client_generation"])
            if not active:
                generation += 1
            deadline = now_ms + self.lease_ms
            connection.execute(
                """UPDATE external_provider_connections
                   SET client_id = ?, client_generation = ?, lease_deadline_ms = ?
                   WHERE connection_id = ?""",
                (client_id, generation, deadline, connection_id),
            )
            return {"connection_id": connection_id, "client_id": client_id,
                    "client_generation": generation, "lease_deadline_ms": deadline,
                    "scope": json.loads(row["scope_json"])}

    def touch(self, connection_id: str, *, token: str, client_id: str,
              client_generation: int, now_ms: int) -> None:
        with self._transaction() as connection:
            row = self._authorize(connection, connection_id, token)
            self._require_client(row, client_id, client_generation, now_ms)
            connection.execute(
                "UPDATE external_provider_connections SET lease_deadline_ms = ? WHERE connection_id = ?",
                (now_ms + self.lease_ms, connection_id),
            )

    def renew_if_due(self, connection_id: str, *, token: str, client_id: str,
                     client_generation: int, now_ms: int) -> None:
        with self._read() as connection:
            row = self._authorize(connection, connection_id, token)
            self._require_client(row, client_id, client_generation, now_ms)
            if row["lease_deadline_ms"] - now_ms > self.lease_ms // 2:
                return
        self.touch(connection_id, token=token, client_id=client_id,
                   client_generation=client_generation, now_ms=now_ms)

    def revoke(self, connection_id: str, *, now_ms: int) -> None:
        with self._transaction() as connection:
            connection.execute(
                """UPDATE external_provider_connections
                   SET revoked_ms = ?, client_id = NULL, lease_deadline_ms = 0,
                       client_generation = client_generation + 1
                   WHERE connection_id = ? AND revoked_ms IS NULL""",
                (now_ms, connection_id),
            )

    def reset_client_leases(self) -> None:
        """Called once by the Host runtime owner, never by individual workers."""
        with self._transaction() as connection:
            connection.execute(
                """UPDATE external_provider_connections
                   SET client_id = NULL, lease_deadline_ms = 0,
                       client_generation = client_generation + 1
                   WHERE revoked_ms IS NULL"""
            )
            connection.execute("UPDATE external_provider_sessions SET status = 'INTERRUPTED' WHERE status = 'ACTIVE'")

    @staticmethod
    def _row(connection: sqlite3.Connection, connection_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM external_provider_connections WHERE connection_id = ?", (connection_id,)
        ).fetchone()

    @staticmethod
    def _token_hash(token: str) -> str:
        if not isinstance(token, str) or not 20 <= len(token) <= 256:
            raise StrategyProviderError("PROVIDER_UNAUTHORIZED_WRITE", "external connection credentials are invalid")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def _authorize(cls, connection: sqlite3.Connection, connection_id: str, token: str) -> sqlite3.Row:
        digest = cls._token_hash(token)
        row = cls._row(connection, connection_id)
        if row is None or row["revoked_ms"] is not None or not hmac.compare_digest(row["token_hash"], digest):
            raise StrategyProviderError("PROVIDER_UNAUTHORIZED_WRITE", "external connection credentials are invalid")
        return row

    @staticmethod
    def _require_client(row: sqlite3.Row, client_id: str, generation: int, now_ms: int) -> None:
        if (type(generation) is not int or row["client_id"] != client_id
                or row["client_generation"] != generation or row["lease_deadline_ms"] <= now_ms):
            raise StrategyProviderError("PROVIDER_STALE_GENERATION", "external client lease is stale; reconnect first")
