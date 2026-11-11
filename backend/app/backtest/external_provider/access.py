"""Host operations for the scoped external strategy protocol."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.backtest.errors import BacktestError
from app.backtest.strategy.protocol import StrategyProviderError

from .endpoint import ENDPOINT_SCHEMA, instance_id
from .smoke import run_smoke, verify_snapshot

if TYPE_CHECKING:
    from app.backtest.runtime import BacktestRuntime
    from app.backtest.service import BacktestService


class ExternalProviderAccess:
    def __init__(
        self,
        resolve_service: Callable[[], BacktestService],
        runtime: BacktestRuntime | None,
        *,
        check_owner: Callable[[], None] | None = None,
    ) -> None:
        self._resolve_service = resolve_service
        self._runtime = runtime
        self._check_owner = check_owner

    def _admit(self) -> BacktestService:
        service = self._resolve_service()
        service.external.require_enabled()
        return service

    def require_enabled(self) -> None:
        self._admit()

    def _owned_runtime(self, service: BacktestService) -> BacktestRuntime:
        if self._runtime is None or self._runtime.service is not service:
            raise BacktestError("FLAG_DISABLED", "backtest runtime is not started")
        return self._runtime

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        service = self._admit()
        verify_snapshot(self._owned_runtime(service), values)
        if self._check_owner is not None:
            self._check_owner()
        return service.external.create(
            revision_id=values["strategy_revision_id"], dataset_id=values["dataset_id"],
            data_epoch=values["data_epoch"], snapshot_hash=values["snapshot_hash"],
        )

    def list(self) -> list[dict[str, Any]]:
        return self._admit().external.list()

    def endpoint(self) -> dict[str, str]:
        self.require_enabled()
        return {"schema_version": ENDPOINT_SCHEMA, "instance_id": instance_id()}

    def example(self) -> dict[str, Any]:
        return self._admit().external.example()

    def trace(self, run_id: str, *, after: int, limit: int) -> dict[str, Any]:
        service = self._admit()
        service.get_run(run_id)
        return service.external.trace(run_id, after=after, limit=limit)

    def revoke(self, connection_id: str) -> dict[str, Any]:
        self._admit().revoke_external_connection(connection_id)
        return {"connection_id": connection_id, "revoked": True}

    def smoke(self, connection_id: str, values: dict[str, Any]) -> dict[str, Any]:
        service = self._admit()
        return run_smoke(self._owned_runtime(service), {**values, "external_connection_id": connection_id},
                         check_owner=self._check_owner)

    def connect(self, connection_id: str, *, token: str, client_id: str, manifest_hash: str) -> dict[str, Any]:
        control = self._admit().external
        journal = control.journal(connection_id)
        if manifest_hash != journal.manifest.identity()["manifest_hash"]:
            raise StrategyProviderError("IDENTITY_MUTATION", "external client manifest differs from the selected revision")
        return control.store.connect(connection_id, token=token, client_id=client_id, now_ms=int(time.time() * 1000))

    def poll(self, connection_id: str, *, token: str, values: dict[str, Any]) -> dict[str, Any]:
        journal = self._admit().external.journal(connection_id)
        packet = journal.poll(connection_id, token=token, now_ms=int(time.time() * 1000), **values)
        return {"call": packet, "active_sessions": journal.live_sessions(connection_id)}

    def reply(self, connection_id: str, *, token: str, values: dict[str, Any]) -> dict[str, Any]:
        journal = self._admit().external.journal(connection_id)
        result = journal.submit(connection_id, token=token, now_ms=int(time.time() * 1000), **values)
        return {"call_id": result["call_id"], "reply_hash": result["reply_hash"], "committed": True}
