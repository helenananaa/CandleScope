"""Connection control owner; filesystem credentials never enter Run identity."""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from typing import Any

from app.backtest.repository import BacktestRepository
from app.backtest.strategy.protocol import StrategyProviderError
from app.core.config import BacktestSettings

from .contracts import (
    CONNECTION_PROTOCOL,
    EXTERNAL_REVISION,
    ExternalProviderManifest,
    parse_manifest,
)
from .journal import ExternalCallJournal
from .provider import ExternalDecisionProvider
from .repository import ExternalConnectionRepository
from .sample import command, descriptor
from .wire import digest, encode


class ExternalProviderControl:
    def __init__(self, settings: BacktestSettings, revisions: BacktestRepository) -> None:
        self.settings = settings
        self.revisions = revisions
        self.directory = settings.db_path.parent / "external-providers"
        self.endpoint_file = self.directory / "host-endpoint.json"
        self.store = ExternalConnectionRepository(self.directory / "connections.sqlite3", max_record_bytes=settings.max_report_storage_bytes)
        self._gate = threading.RLock()
        self._smokes = threading.BoundedSemaphore(settings.max_active_runs)

    def require_enabled(self) -> None:
        if not self.settings.enabled or not self.settings.external_provider_enabled:
            raise StrategyProviderError("FLAG_DISABLED", "external strategy/model connection is default-off")

    def open(self) -> None:
        self.require_enabled()
        self.store.open()

    def close(self) -> None:
        self.store.close()

    def manifest(self, revision_id: str, *, require_active: bool = True) -> ExternalProviderManifest:
        self.require_enabled()
        row = self.revisions.get_strategy_revision(revision_id)
        if row is None or (require_active and row["archived_at_ms"] is not None) or row["base_revision_id"] != EXTERNAL_REVISION:
            raise StrategyProviderError("SCHEMA_UNKNOWN_FIELD", "select an active external provider revision")
        return parse_manifest(str(row["source_text"]))

    def create(self, *, revision_id: str, dataset_id: str, data_epoch: str, snapshot_hash: str,
               now_ms: int | None = None) -> dict[str, Any]:
        """Caller must verify the selected immutable dataset snapshot first."""
        parsed = self.manifest(revision_id)
        scope = {"strategy_revision_id": revision_id, "dataset_id": dataset_id, "data_epoch": data_epoch,
                 "snapshot_hash": snapshot_hash, "manifest_hash": parsed.identity()["manifest_hash"]}
        self.open()
        token = secrets.token_urlsafe(32)
        stamp = int(time.time() * 1000) if now_ms is None else now_ms
        with self._gate:
            connection_id = self.store.create(scope, token=token, now_ms=stamp)
            path = self.directory / (connection_id + ".json")
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(encode({"schema_version": CONNECTION_PROTOCOL, "connection_id": connection_id,
                                         "token": token, "host_endpoint_file": str(self.endpoint_file), "scope": scope}))
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                self.store.revoke(connection_id, now_ms=stamp)
                path.unlink(missing_ok=True)
                raise
        return {"connection_id": connection_id, "scope": scope, "scope_hash": digest(scope),
                "connection_file": str(path), "ready": False, "example_command": self._example_command(scope, path)}

    def list(self, *, now_ms: int | None = None) -> list[dict[str, Any]]:
        self.require_enabled()
        if not self.store.path.exists():
            return []
        self.open()
        stamp = int(time.time() * 1000) if now_ms is None else now_ms
        with self.store._read() as connection:
            rows = connection.execute(
                "SELECT connection_id FROM external_provider_connections WHERE revoked_ms IS NULL ORDER BY created_ms"
            ).fetchall()
        result = []
        for row in rows:
            scope = self.store.scope(row[0])
            path = self.directory / (row[0] + ".json")
            result.append({"connection_id": row[0], "scope": scope, "scope_hash": digest(scope),
                           "ready": self.store.ready(row[0], now_ms=stamp), "connection_file": str(path),
                           "example_command": self._example_command(scope, path)})
        return result

    def example(self) -> dict[str, Any]:
        self.require_enabled()
        sample = descriptor()
        return {"manifest": sample["manifest"], "manifest_command": command(sample["argv"] + ["--manifest"])}

    def trace(self, run_id: str, *, after: int = 0, limit: int = 200) -> dict[str, Any]:
        self.open()
        with self.store._read() as connection:
            row = connection.execute(
                """SELECT c.scope_json FROM external_provider_sessions s
                   JOIN external_provider_connections c ON c.connection_id = s.connection_id WHERE s.run_id = ?""", (run_id,),
            ).fetchone()
        if row is None:
            raise StrategyProviderError("SCHEMA_UNKNOWN_FIELD", "external decision trace is unavailable")
        from .wire import decode
        scope = decode(row[0])
        parsed = self.manifest(str(scope["strategy_revision_id"]), require_active=False)
        return ExternalCallJournal(self.store, parsed).trace(run_id, after=after, limit=limit)

    @staticmethod
    def _example_command(scope: dict[str, Any], path) -> str | None:
        try:
            sample = descriptor()
        except StrategyProviderError:
            return None
        if sample["manifest_hash"] != scope.get("manifest_hash"):
            return None
        return command(sample["argv"] + ["--connection", str(path)])

    def revoke(self, connection_id: str, *, now_ms: int | None = None) -> None:
        self.open()
        if not connection_id.startswith("epc_") or len(connection_id) != 36 or any(
            char not in "0123456789abcdef" for char in connection_id[4:]
        ):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid external connection identity")
        # Resolve the stored identity before constructing any filesystem path;
        # an already revoked connection remains safe to retry.
        with self.store._read() as connection:
            if self.store._row(connection, connection_id) is None:
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external connection is unavailable")
        self.store.revoke(connection_id, now_ms=int(time.time() * 1000) if now_ms is None else now_ms)
        (self.directory / (connection_id + ".json")).unlink(missing_ok=True)

    def validate_binding(self, payload: Mapping[str, Any], *, require_ready: bool = True) -> dict[str, Any]:
        parsed = self.manifest(str(payload["strategy_revision_id"]))
        connection_id = payload.get("external_connection_id")
        if type(connection_id) is not str or not connection_id:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "select a connection for the frozen external revision and dataset")
        self.open()
        scope = self.store.scope(connection_id)
        expected = {key: str(payload[key]) for key in ("strategy_revision_id", "dataset_id", "data_epoch", "snapshot_hash")}
        expected["manifest_hash"] = parsed.identity()["manifest_hash"]
        if scope != expected:
            raise StrategyProviderError("IDENTITY_MUTATION", "external connection belongs to a different revision or dataset snapshot")
        if require_ready and not self.store.ready(connection_id, now_ms=int(time.time() * 1000)):
            raise StrategyProviderError("PROVIDER_CONNECTION_REQUIRED", "connect the external client before smoke or Run")
        return {"external_connection_id": connection_id, "external_scope_hash": digest(scope),
                "external_provider_identity": parsed.identity()}

    def journal(self, connection_id: str) -> ExternalCallJournal:
        self.open()
        scope = self.store.scope(connection_id)
        parsed = self.manifest(str(scope["strategy_revision_id"]))
        if scope.get("manifest_hash") != parsed.identity()["manifest_hash"]:
            raise StrategyProviderError("IDENTITY_MUTATION", "external connection manifest identity changed")
        return ExternalCallJournal(self.store, parsed, max_state_bytes=self.settings.max_provider_state_bytes,
                                   max_record_bytes=self.settings.max_report_storage_bytes)

    def build_provider(self, record: Mapping[str, Any], config: dict[str, Any], *,
                       check_control: Callable[[], None] | None = None) -> ExternalDecisionProvider:
        frozen = {**config, **{key: record[key] for key in ("strategy_revision_id", "dataset_id", "data_epoch", "snapshot_hash")}}
        identity = self.validate_binding(frozen, require_ready=False)
        if any(config.get(key) != value for key, value in identity.items()):
            raise StrategyProviderError("IDENTITY_MUTATION", "external Run connection identity changed")
        return ExternalDecisionProvider(self.journal(identity["external_connection_id"]),
                                        connection_id=identity["external_connection_id"], host_generation=int(record["generation"]),
                                        step_timeout_s=self.settings.provider_step_timeout_ms / 1000, check_control=check_control)

    def waiting_runs(self, queued: list[tuple[str, str]]) -> tuple[str, ...]:
        if not queued:
            return ()
        if not self.settings.enabled or not self.settings.external_provider_enabled or not self.store.path.exists():
            return tuple(run_id for run_id, _ in queued)
        self.open()
        now = int(time.time() * 1000)
        return tuple(run_id for run_id, connection_id in queued if not self.store.ready(connection_id, now_ms=now))

    def waiting_reason(self, connection_id: str) -> str | None:
        if not self.settings.enabled or not self.settings.external_provider_enabled:
            return "EXTERNAL_PROVIDER_DISABLED"
        if not self.store.path.exists():
            return "EXTERNAL_CONNECTION"
        self.open()
        with self.store._read() as connection:
            row = self.store._row(connection, connection_id)
            if row is None or row["revoked_ms"] is not None:
                return "EXTERNAL_CONNECTION_REVOKED"
            if row["client_id"] is None or row["lease_deadline_ms"] <= int(time.time() * 1000):
                return "EXTERNAL_CONNECTION"
            return None

    def smoke_config_hash(self, payload: Mapping[str, Any]) -> str:
        binding = self.validate_binding(payload)
        return digest({"binding": binding, "parameters": payload.get("parameters") or {},
                       "output_mode": payload.get("output_mode") or "TARGET_POSITION"})

    @contextmanager
    def smoke_slot(self):
        self.require_enabled()
        if not self._smokes.acquire(blocking=False):
            raise StrategyProviderError("BUDGET_EXCEEDED", "external smoke capacity is occupied")
        try:
            yield
        finally:
            self._smokes.release()
