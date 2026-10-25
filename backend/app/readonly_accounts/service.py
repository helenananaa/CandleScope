"""One host-owned OKX read-only account and its explicit lifecycle."""
from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

from .credentials import MacKeychainVault, validate_credentials
from .normalization import AccountDataError
from .okx import ReadOnlyOkx, account_identity
from .repository import AccountRepository
from .sync import AccountSynchronizer, error_code, three_months_before


def saved_network_options() -> dict:
    from app.core.config import get_effective_proxy, load_proxy_settings

    settings = load_proxy_settings()
    return {"proxy": get_effective_proxy(), "trust_environment": settings.get("mode") == "system"}


async def start_account_service(app, root: Path) -> None:
    app.state.readonly_account_service = None
    app.state.readonly_account_error = None
    try:
        owner = await asyncio.to_thread(ReadOnlyAccountService, root, network_options=saved_network_options)
        app.state.readonly_account_service = owner
        await owner.start()
    except Exception as exc:
        # An unavailable account store or Keychain must not prevent charts from opening.
        app.state.readonly_account_error = error_code(exc)
        owner = app.state.readonly_account_service
        if owner is not None:
            owner.service_error = error_code(exc)


async def finish_mutation(operation):
    """Let the small durable mutation finish before propagating cancellation."""
    task = asyncio.create_task(operation)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            cancelled = True
            if task.done():
                result = task.result()
                break
    if cancelled:
        raise asyncio.CancelledError
    return result


class ReadOnlyAccountService:
    def __init__(self, root: Path, *, client_factory=ReadOnlyOkx,
                 vault_factory=MacKeychainVault, network_options=None):
        self.repository = AccountRepository(root)
        self.root = root
        self.client_factory = client_factory
        self.vault_factory = vault_factory
        self.network_options = network_options or (lambda:{})
        self._control = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.synchronizer: AccountSynchronizer | None = None
        self._closed = False
        self.service_error: str | None = None

    async def _close_client(self, client) -> None:
        try:
            await asyncio.wait_for(client.close(), timeout=10)
        except Exception:
            self.service_error = "ACCOUNT_RESOURCE_CLEANUP_FAILED"

    def _vault(self):
        return self.vault_factory(self.root)

    async def _cleanup_retired_credentials(self, vault) -> None:
        for record_id in await asyncio.to_thread(self.repository.retired_credentials):
            try:
                await asyncio.to_thread(vault.delete,record_id)
                await asyncio.to_thread(self.repository.credential_removed,record_id)
            except AccountDataError:
                await asyncio.to_thread(self.repository.status,"error",error="OLD_KEYCHAIN_RECORD_CLEANUP_FAILED")
                raise AccountDataError("OLD_KEYCHAIN_RECORD_CLEANUP_FAILED") from None

    async def start(self) -> None:
        async with self._control:
            if self._closed or (self._task and not self._task.done()):
                return
            if await asyncio.to_thread(self.repository.retired_credentials):
                await self._cleanup_retired_credentials(self._vault())
            account = await asyncio.to_thread(self.repository.account,credential_reference=True)
            if account and account["enabled"] and account["credential_id"]:
                self._task = asyncio.create_task(self._run())

    async def _stop(self) -> None:
        task,self._task = self._task,None
        if task:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        self.synchronizer = None

    async def close(self) -> None:
        async with self._control:
            self._closed = True
            await self._stop()

    async def connect(self, payload: dict) -> None:
        credentials = validate_credentials(payload)
        probe = None
        try:
            async with self._control:
                if self._closed:
                    raise AccountDataError("ACCOUNT_SERVICE_STOPPED")
                vault = self._vault()
                probe = self.client_factory(credentials,**self.network_options())
                identity = account_identity(await probe.privateGetAccountConfig())
                previous = await asyncio.to_thread(self.repository.account,credential_reference=True)
                if previous is not None and previous["venue_uid"] != identity["venueUid"]:
                    raise AccountDataError("DIFFERENT_ACCOUNT_REQUIRES_SEPARATE_PROFILE")
                await finish_mutation(self._commit_connection(vault, identity, credentials))
        finally:
            credentials.clear()
            if probe is not None:
                await self._close_client(probe)

    async def _commit_connection(self, vault, identity: dict, credentials: dict) -> None:
        await self._stop()
        record_id = uuid.uuid4().hex

        def persist():
            self.repository.stage_credential(record_id)
            vault.store(record_id, credentials)
            self.repository.bind(identity["venueUid"], record_id,
                                 three_months_before(int(time.time()*1000)))

        try:
            await asyncio.to_thread(persist)
        finally:
            # Failed writes and retired old keys are still recorded on disk, so
            # even a failed deletion can be retried after a process restart.
            await self._cleanup_retired_credentials(vault)
            account = await asyncio.to_thread(self.repository.account, credential_reference=True)
            if not self._closed and account and account["enabled"] and account["credential_id"]:
                self._task = asyncio.create_task(self._run())

    async def disconnect(self, *, forget: bool = False) -> None:
        async with self._control:
            await finish_mutation(self._disconnect(forget))

    async def _disconnect(self, forget: bool) -> None:
        await self._stop()
        await asyncio.to_thread(self.repository.status,"disconnected",enabled=False)
        if forget:
            # Clear the active reference and persist deletion intent in one
            # transaction; a crash during Keychain deletion is retryable.
            await asyncio.to_thread(self.repository.forget_credential)
            await self._cleanup_retired_credentials(self._vault())

    async def resume(self) -> None:
        async with self._control:
            if self._closed:
                raise AccountDataError("ACCOUNT_SERVICE_STOPPED")
            account = await asyncio.to_thread(self.repository.account,credential_reference=True)
            if account is None or not account["credential_id"]:
                raise AccountDataError("ACCOUNT_CREDENTIAL_REQUIRED")
            if self._task and not self._task.done() and self.synchronizer:
                self.synchronizer.requested_full = True
                self.synchronizer.changed.set()
                return
            await self._stop()
            await self._cleanup_retired_credentials(self._vault())
            await asyncio.to_thread(self.repository.status,"syncing",enabled=True)
            self._task = asyncio.create_task(self._run())

    async def reconfigure_network(self) -> None:
        async with self._control:
            if self._closed:
                return
            await self._stop()
            account = await asyncio.to_thread(self.repository.account, credential_reference=True)
            if account and account["enabled"] and account["credential_id"]:
                self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        retry = 2
        while not self._closed:
            client = None
            try:
                account = await asyncio.to_thread(self.repository.account,credential_reference=True)
                if account is None or not account["enabled"] or not account["credential_id"]:
                    return
                vault = self._vault()
                await self._cleanup_retired_credentials(vault)
                credentials = await asyncio.to_thread(vault.read,account["credential_id"])
                try:
                    client = self.client_factory(credentials,**self.network_options())
                finally:
                    credentials.clear()
                sync = AccountSynchronizer(self.repository,client)
                client._observe = sync.observe
                self.synchronizer = sync
                await sync.initialize(account["venue_uid"])
                await sync.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                code = error_code(exc)
                await asyncio.to_thread(self.repository.status,"error",error=code)
                if code in {"KEYCHAIN_READ_FAILED","KEYCHAIN_RECORD_INVALID","READONLY_KEY_REQUIRED",
                            "HEDGE_ACCOUNT_REQUIRED","ACCOUNT_AUTHENTICATION_FAILED","ACCOUNT_IDENTITY_CHANGED",
                            "OLD_KEYCHAIN_RECORD_CLEANUP_FAILED","MACOS_KEYCHAIN_REQUIRED"}:
                    return
            finally:
                self.synchronizer = None
                if client is not None:
                    await self._close_client(client)
            if self.service_error == "ACCOUNT_RESOURCE_CLEANUP_FAILED":
                return
            await asyncio.sleep(retry)
            retry = min(retry*2,60)

    async def state(self) -> dict:
        repo = self.repository
        account,scans,coverage,gaps,snapshots,counts = await asyncio.gather(
            asyncio.to_thread(repo.account),asyncio.to_thread(repo.scans),
            asyncio.to_thread(repo.coverage),asyncio.to_thread(repo.gaps),
            asyncio.to_thread(repo.snapshots),asyncio.to_thread(repo.counts))
        # Instrument metadata is large and already bound into normalized facts.
        snapshots.pop("contracts",None)
        sync = self.synchronizer
        return {"schemaVersion":1,"available":sys.platform == "darwin","venue":"okx",
                "product":"perpetual","positionMode":"long_short_mode",
                "settlements":["USDT","coin"],"readOnly":True,"historyMonths":3,
                "account":account,"scans":scans,"coverage":coverage,"gaps":gaps,
                "serviceError":self.service_error,
                "snapshots":snapshots,"counts":counts,"reconciliation":"not_verified",
                "stream":{"state":sync.stream_status if sync else "stopped",
                          "lastReceivedMs":sync.last_ws_received_ms if sync else None,
                          "error":sync.ws_error if sync else None},
                "historyLimitations":["EXCHANGE_RETENTION_LIMIT","UNFILLED_ORDER_RETENTION",
                                      "HISTORICAL_POSITION_BASIS_UNKNOWN","FUNDING_LEG_MAY_BE_UNKNOWN"]}
