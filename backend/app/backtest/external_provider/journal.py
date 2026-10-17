"""Durable Host calls, client fencing and bounded model-state storage."""

from __future__ import annotations

import sqlite3
import hashlib
import uuid
from typing import Any

from app.backtest.strategy.protocol import StrategyProviderError

from .contracts import ExternalProviderManifest
from .messages import OPERATIONS, validate_reply
from .repository import ExternalConnectionRepository
from .wire import decode, digest, encode


def _fail(message: str, code: str = "PROVIDER_PROTOCOL_VIOLATION") -> None:
    raise StrategyProviderError(code, message)


class ExternalCallJournal:
    def __init__(self, store: ExternalConnectionRepository, manifest: ExternalProviderManifest, *,
                 max_state_bytes: int = 8_388_608, max_record_bytes: int = 268_435_456) -> None:
        if max_state_bytes <= 0 or max_record_bytes <= 0:
            raise ValueError("external journal budgets must be positive")
        self.store = store
        self.manifest = manifest
        self.max_state_bytes = max_state_bytes
        self.max_record_bytes = max_record_bytes

    def start(self, connection_id: str, run_id: str, *, host_generation: int, context: dict[str, Any]) -> None:
        if (type(run_id) is not str or not 1 <= len(run_id) <= 128
                or type(host_generation) is not int or host_generation < 1):
            _fail("invalid external Host session identity")
        frozen = {"provider": self.manifest.identity(), "context": context}
        text = encode(frozen, max_bytes=65_536)
        context_hash = digest(frozen)
        with self.store._transaction() as connection:
            binding = self.store._row(connection, connection_id)
            if binding is None or binding["revoked_ms"] is not None:
                _fail("external connection is unavailable")
            session = self._session(connection, run_id, required=False)
            if session is not None:
                if session["connection_id"] != connection_id or session["context_hash"] != context_hash:
                    _fail("external session identity cannot change", "IDENTITY_MUTATION")
                if host_generation < session["host_generation"]:
                    _fail("external Host generation is stale")
                status = session["status"]
                if host_generation > session["host_generation"] and status == "INTERRUPTED":
                    status = "ACTIVE"
                connection.execute("UPDATE external_provider_sessions SET host_generation = ?, status = ? WHERE run_id = ?",
                                   (host_generation, status, run_id))
                return
            self._reserve(connection, len(text.encode("utf-8")) + 512)
            connection.execute(
                """INSERT INTO external_provider_sessions
                   (run_id, connection_id, host_generation, context_json, context_hash) VALUES (?, ?, ?, ?, ?)""",
                (run_id, connection_id, host_generation, text, context_hash),
            )

    def enqueue(self, run_id: str, *, host_generation: int, cursor: int, operation: str,
                payload: dict[str, Any], now_ms: int) -> dict[str, Any]:
        if operation not in OPERATIONS or type(cursor) is not int or cursor < 1 or type(payload) is not dict:
            _fail("invalid external Host call")
        text = encode(payload)
        input_hash = digest({"run_id": run_id, "cursor": cursor, "operation": operation, "payload": payload})
        with self.store._transaction() as connection:
            session = self._session(connection, run_id)
            self._generation(session, host_generation)
            self._available(connection, session)
            existing = self._call(connection, run_id, cursor)
            if existing is not None:
                if existing["input_hash"] != input_hash:
                    _fail("external call input changed during replay", "IDENTITY_MUTATION")
                return self._record(existing)
            if session["status"] != "ACTIVE" or cursor != session["last_completed"] + 1:
                _fail("external calls must be serialized in Host order")
            self._reserve(connection, len(text.encode("utf-8")) + 512)
            connection.execute(
                """INSERT INTO external_provider_calls
                   (run_id, cursor, call_id, operation, payload_json, input_hash, state_before_hash, created_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, cursor, "epcall_" + uuid.uuid4().hex, operation, text, input_hash,
                 session["state_hash"], now_ms),
            )
            return self._record(self._call(connection, run_id, cursor))

    def recorded(self, run_id: str, cursor: int, *, host_generation: int) -> dict[str, Any]:
        with self.store._read() as connection:
            session = self._session(connection, run_id)
            self._generation(session, host_generation)
            self._available(connection, session)
            row = self._call(connection, run_id, cursor)
            if row is None:
                _fail("external call is unavailable")
            return self._record(row)

    def poll(self, connection_id: str, *, token: str, client_id: str,
             client_generation: int, now_ms: int) -> dict[str, Any] | None:
        with self.store._transaction() as connection:
            binding = self.store._authorize(connection, connection_id, token)
            self.store._require_client(binding, client_id, client_generation, now_ms)
            connection.execute("UPDATE external_provider_connections SET lease_deadline_ms = ? WHERE connection_id = ?",
                               (now_ms + self.store.lease_ms, connection_id))
            row = connection.execute(
                """SELECT c.*, s.host_generation, s.context_json FROM external_provider_calls c
                   JOIN external_provider_sessions s ON s.run_id = c.run_id
                   WHERE s.connection_id = ? AND s.status = 'ACTIVE' AND c.reply_json IS NULL
                   ORDER BY c.created_ms, c.run_id LIMIT 1""", (connection_id,),
            ).fetchone()
            if row is None:
                return None
            self._session(connection, row["run_id"])
            self._record(row)
            state = self._state(connection, row["run_id"], row["state_before_hash"])
            packet = {"connection_id": connection_id, "client_generation": client_generation,
                      "run_id": row["run_id"], "host_generation": row["host_generation"],
                      "cursor": row["cursor"], "call_id": row["call_id"], "input_hash": row["input_hash"],
                      "operation": row["operation"], "payload": decode(row["payload_json"]),
                      "bootstrap": {"context": decode(row["context_json"]), "model_state": state,
                                    "model_state_hash": row["state_before_hash"]}}
            encode(packet)  # Includes bootstrap; never emit an oversized delivery.
            return packet

    def submit(self, connection_id: str, *, token: str, client_id: str, client_generation: int,
               run_id: str, host_generation: int, cursor: int, call_id: str, input_hash: str,
               result: object, now_ms: int) -> dict[str, Any]:
        # Credentials never become semantic model state, diagnostics or trace data.
        text = encode(result)
        if type(token) is str and token in text:
            _fail("external reply contains connection credentials", "PROVIDER_UNAUTHORIZED_WRITE")
        with self.store._transaction() as connection:
            binding = self.store._authorize(connection, connection_id, token)
            self.store._require_client(binding, client_id, client_generation, now_ms)
            session = self._session(connection, run_id)
            self._generation(session, host_generation)
            if session["connection_id"] != connection_id or type(cursor) is not int:
                _fail("external response belongs to another Host session")
            row = self._call(connection, run_id, cursor)
            if row is None or row["call_id"] != call_id or row["input_hash"] != input_hash:
                _fail("external response does not match the Host call")
            self._record(row)
            validated = validate_reply(self.manifest, row["operation"], decode(row["payload_json"]),
                                       result, max_state_bytes=self.max_state_bytes)
            reply_json = encode(validated.recorded)
            reply_hash = digest(validated.recorded)
            if row["reply_json"] is not None:
                if row["reply_hash"] != reply_hash:
                    _fail("external response changed after commit", "IDENTITY_MUTATION")
                return self._record(row)
            if session["status"] != "ACTIVE" or cursor != session["last_completed"] + 1:
                _fail("external response is out of Host order")
            if validated.state_json is not None:
                self._save_state(connection, run_id, validated.state_hash, validated.state_json)
            status = "FAILED" if "error" in validated.recorded else ("CLOSED" if row["operation"] == "close" else "ACTIVE")
            state_hash = validated.state_hash or session["state_hash"]
            connection.execute(
                "UPDATE external_provider_sessions SET last_completed = ?, state_hash = ?, status = ? WHERE run_id = ?",
                (cursor, state_hash, status, run_id),
            )
            self._collect_states(connection, run_id, state_hash)
            self._reserve(connection, len(reply_json.encode("utf-8")) + 128)
            connection.execute(
                """UPDATE external_provider_calls SET reply_json = ?, reply_hash = ?, state_after_hash = ?
                   WHERE run_id = ? AND cursor = ?""", (reply_json, reply_hash, state_hash, run_id, cursor),
            )
            return self._record(self._call(connection, run_id, cursor))

    def snapshot(self, run_id: str, cursor: int, *, host_generation: int) -> dict[str, Any]:
        with self.store._transaction() as connection:
            session = self._session(connection, run_id)
            self._generation(session, host_generation)
            self._available(connection, session)
            if type(cursor) is not int or not 0 <= cursor <= session["last_completed"]:
                _fail("external checkpoint cursor is not committed")
            call = self._call(connection, run_id, cursor) if cursor else None
            state_hash = call["state_after_hash"] if call is not None else None
            self._state(connection, run_id, state_hash)
            if state_hash:
                connection.execute("UPDATE external_provider_states SET pinned = 1 WHERE run_id = ? AND state_hash = ?",
                                   (run_id, state_hash))
            return {"schema_version": "candlescope.external-checkpoint/1", "run_id": run_id, "cursor": cursor,
                    "context_hash": session["context_hash"], "model_state_hash": state_hash,
                    "manifest_hash": self.manifest.identity()["manifest_hash"]}

    def interrupt(self, run_id: str, *, host_generation: int) -> None:
        """Fence unfinished delivery; only a newer Host owner may resume it."""
        with self.store._transaction() as connection:
            session = self._session(connection, run_id)
            self._generation(session, host_generation)
            connection.execute(
                "UPDATE external_provider_sessions SET status = 'INTERRUPTED' WHERE run_id = ? AND status = 'ACTIVE'",
                (run_id,),
            )

    def audit(self, run_id: str, cursor: int, *, host_generation: int) -> dict[str, Any]:
        """Public provenance contains digests and decisions, never model state."""
        with self.store._read() as connection:
            session = self._session(connection, run_id)
            self._generation(session, host_generation)
            if type(cursor) is not int or not 0 <= cursor <= session["last_completed"]:
                _fail("external audit cursor is not committed")
            trace = hashlib.sha256()
            count = decisions = 0
            for row in connection.execute(
                "SELECT * FROM external_provider_calls WHERE run_id = ? AND cursor <= ? ORDER BY cursor", (run_id, cursor)
            ):
                record = self._record(row)
                if record["reply"] is None:
                    _fail("external audit contains an unfinished call")
                if row["operation"] == "close":
                    continue
                trace.update(encode({"cursor": row["cursor"], "operation": row["operation"],
                                     "input_hash": row["input_hash"], "reply_hash": row["reply_hash"]}).encode("utf-8"))
                trace.update(b"\n")
                count += 1
                decisions += record["reply"].get("decision") is not None
            return {**self.manifest.identity(), "context_hash": session["context_hash"],
                    "call_count": count, "decision_count": decisions, "trace_hash": "sha256:" + trace.hexdigest()}

    def _reserve(self, connection: sqlite3.Connection, delta: int) -> None:
        used = connection.execute("SELECT logical_bytes FROM external_provider_usage WHERE singleton = 1").fetchone()[0]
        if delta >= 0 and used + delta > self.max_record_bytes:
            _fail("external journal storage budget exceeded", "BUDGET_EXCEEDED")
        connection.execute("UPDATE external_provider_usage SET logical_bytes = logical_bytes + ? WHERE singleton = 1", (delta,))

    def _save_state(self, connection: sqlite3.Connection, run_id: str, state_hash: str, text: str) -> None:
        existing = connection.execute("SELECT state_json FROM external_provider_states WHERE run_id = ? AND state_hash = ?",
                                      (run_id, state_hash)).fetchone()
        if existing is not None:
            if existing[0] != text:
                _fail("external state digest collision", "IDENTITY_MUTATION")
            return
        size = len(text.encode("utf-8")) + 256
        # Collection and the final budget check occur in this same transaction.
        connection.execute("UPDATE external_provider_usage SET logical_bytes = logical_bytes + ? WHERE singleton = 1", (size,))
        connection.execute("INSERT INTO external_provider_states VALUES (?, ?, ?, ?, 0)", (run_id, state_hash, text, size))

    def _collect_states(self, connection: sqlite3.Connection, run_id: str, current: str | None) -> None:
        rows = connection.execute(
            "SELECT state_hash, logical_bytes FROM external_provider_states WHERE run_id = ? AND pinned = 0 AND state_hash != ?",
            (run_id, current or ""),
        ).fetchall()
        for row in rows:
            connection.execute("DELETE FROM external_provider_states WHERE run_id = ? AND state_hash = ?", (run_id, row[0]))
            self._reserve(connection, -row[1])

    def _session(self, connection: sqlite3.Connection, run_id: str, *, required: bool = True) -> sqlite3.Row | None:
        row = connection.execute("SELECT * FROM external_provider_sessions WHERE run_id = ?", (run_id,)).fetchone()
        if row is None and required:
            _fail("external Host session is unavailable")
        if row is not None:
            frozen = decode(row["context_json"])
            if (type(frozen) is not dict or digest(frozen) != row["context_hash"]
                    or frozen.get("provider") != self.manifest.identity()):
                _fail("external session identity integrity failed", "IDENTITY_MUTATION")
        return row

    @staticmethod
    def _call(connection: sqlite3.Connection, run_id: str, cursor: int) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM external_provider_calls WHERE run_id = ? AND cursor = ?", (run_id, cursor)).fetchone()

    @staticmethod
    def _generation(session: sqlite3.Row, generation: int) -> None:
        if type(generation) is not int or generation != session["host_generation"]:
            _fail("external Host generation is stale")

    def _available(self, connection: sqlite3.Connection, session: sqlite3.Row) -> None:
        binding = self.store._row(connection, session["connection_id"])
        if binding is None or binding["revoked_ms"] is not None:
            _fail("external connection is unavailable")

    @staticmethod
    def _state(connection: sqlite3.Connection, run_id: str, state_hash: str | None) -> dict[str, Any] | None:
        if state_hash is None:
            return None
        row = connection.execute("SELECT state_json FROM external_provider_states WHERE run_id = ? AND state_hash = ?",
                                 (run_id, state_hash)).fetchone()
        if row is None or digest(decode(row[0])) != state_hash:
            _fail("external checkpoint state is unavailable or corrupt", "RECOVERY_NOT_ALLOWED")
        return decode(row[0])

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        expected = digest({"run_id": row["run_id"], "cursor": row["cursor"],
                           "operation": row["operation"], "payload": decode(row["payload_json"])})
        if expected != row["input_hash"]:
            _fail("external recorded input integrity failed", "IDENTITY_MUTATION")
        reply = decode(row["reply_json"]) if row["reply_json"] is not None else None
        if reply is not None and digest(reply) != row["reply_hash"]:
            _fail("external recorded response integrity failed", "IDENTITY_MUTATION")
        return {"run_id": row["run_id"], "cursor": row["cursor"], "call_id": row["call_id"],
                "operation": row["operation"], "input_hash": row["input_hash"],
                "reply": reply, "reply_hash": row["reply_hash"]}
