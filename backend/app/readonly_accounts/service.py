"""One host-owned OKX read-only account and its explicit lifecycle."""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from .credentials import AccountVault, credential_store, validate_credentials
from .normalization import AccountDataError
from .okx import ReadOnlyOkx, account_identity
from .repository import AccountRepository
from .sync import TERMINAL_ERRORS, AccountSynchronizer, RouteFailover, error_code, three_months_before

# Pool health for the private session is kept apart from public REST and WebSocket health.
ROUTE_KIND = "account"


def saved_network_options(current=None) -> dict:
    """How the private session connects, from the saved proxy settings.

    In pool mode it uses a pool route that allows OKX: `current` while it stays healthy,
    otherwise the first healthy route in the configured order (proxy_pool.select_session).
    """
    from app.core.config import get_effective_proxy, load_proxy_settings

    settings = load_proxy_settings()
    if settings.get("mode") != "pool":
        return {"proxy": get_effective_proxy(), "trust_environment": settings.get("mode") == "system"}
    from types import SimpleNamespace
    from app.core.proxy_pool import get_proxy_pool

    config = SimpleNamespace(proxy_mode="pool", proxy_routes=settings.get("routes", []),
                             proxy_strategy=settings.get("strategy", "failover"))
    try:
        route = get_proxy_pool().select_session(config, "okx", kind=ROUTE_KIND, current=current)
    except ValueError:
        raise AccountDataError("ACCOUNT_PROXY_ROUTE_UNAVAILABLE") from None
    return {"proxy": route.url, "trust_environment": False, "route": route}


async def start_account_service(app, root: Path) -> None:
    app.state.readonly_account_service = None
    app.state.readonly_account_error = None
    try:
        owner = await asyncio.to_thread(ReadOnlyAccountService, root, network_options=saved_network_options)
        app.state.readonly_account_service = owner
        core = getattr(app.state, "data_manager_core", None)
        if core is not None:
            core.bind_readonly_account(owner)
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
                 vault_factory=AccountVault, network_options=None):
        self.repository = AccountRepository(root)
        from .review import ReadOnlyReview
        self.review = ReadOnlyReview(self.repository)
        self.root = root
        self.client_factory = client_factory
        self.vault_factory = vault_factory
        self.network_options = network_options or (lambda current=None: {})
        # The pool route the session last used (kept across reconnects) and the
        # (proxy, trust_environment) of the running client, None while not connected.
        self.route = None
        self.network_in_use: tuple | None = None
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
            self.notify_state_changed()

    def _vault(self):
        return self.vault_factory(self.root)

    def _client(self, credentials, current=None):
        options = dict(self.network_options(current))
        route = options.pop("route", None)
        return self.client_factory(credentials, **options), route, (options.get("proxy"), options.get("trust_environment"))

    def network_options_now(self) -> tuple:
        """(proxy, trust_environment) a session started now would use; settings compare it to network_in_use."""
        options = self.network_options()
        return options.get("proxy"), options.get("trust_environment")

    def _route_result(self, route, error) -> bool:
        """Feed the pool's health for the session's route; True when another route should take over."""
        if route is None:
            return False
        from app.core.proxy_pool import get_proxy_pool

        get_proxy_pool().record(route, "okx", error=error, kind=ROUTE_KIND)
        if error is None:
            return False
        try:
            choice = self.network_options(route).get("route")
        except Exception:
            return False
        return choice is not None and (choice.id, choice.url) != (route.id, route.url)

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
        self.notify_state_changed()

    async def close(self) -> None:
        async with self._control:
            self._closed = True
            await self._stop()
            self.review.store.close()

    async def connect(self, payload: dict) -> None:
        credentials = validate_credentials(payload)
        probe = None
        try:
            async with self._control:
                if self._closed:
                    raise AccountDataError("ACCOUNT_SERVICE_STOPPED")
                vault = self._vault()
                probe, _, _ = self._client(credentials)
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
            self.route = None  # Saved settings changed: start again from the configured order.
            account = await asyncio.to_thread(self.repository.account, credential_reference=True)
            if account and account["enabled"] and account["credential_id"]:
                self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        retry = 2
        while not self._closed:
            client = route = None
            failover = False
            try:
                account = await asyncio.to_thread(self.repository.account,credential_reference=True)
                if account is None or not account["enabled"] or not account["credential_id"]:
                    return
                vault = self._vault()
                await self._cleanup_retired_credentials(vault)
                credentials = await asyncio.to_thread(vault.read,account["credential_id"])
                try:
                    client, route, self.network_in_use = self._client(credentials, self.route)
                finally:
                    credentials.clear()
                self.route = route
                sync = AccountSynchronizer(self.repository,client, state_changed=self.notify_state_changed,
                                           network_result=lambda error: self._route_result(route, error))
                client._observe = sync.observe
                self.synchronizer = sync
                self.notify_state_changed()
                await sync.initialize(account["venue_uid"])
                self._route_result(route, None)
                await sync.run()
            except asyncio.CancelledError:
                raise
            except RouteFailover:
                failover = True
            except Exception as exc:
                code = error_code(exc)
                if code == "ACCOUNT_NETWORK_UNAVAILABLE":
                    self._route_result(route, exc)
                await asyncio.to_thread(self.repository.status,"error",error=code)
                if code in TERMINAL_ERRORS or code in {"KEYCHAIN_READ_FAILED","KEYCHAIN_RECORD_INVALID",
                            "OLD_KEYCHAIN_RECORD_CLEANUP_FAILED","CREDENTIAL_STORE_UNAVAILABLE"}:
                    return
            finally:
                self.synchronizer = None
                self.network_in_use = None
                self.notify_state_changed()
                if client is not None:
                    await self._close_client(client)
            if self.service_error == "ACCOUNT_RESOURCE_CLEANUP_FAILED":
                return
            if failover:
                continue  # The next client takes another route at once.
            await asyncio.sleep(retry)
            retry = min(retry*2,60)

    def notify_state_changed(self) -> None:
        self.repository.updates.notify("state")

    async def state(self) -> dict:
        view = await asyncio.to_thread(self.repository.overview)
        sync = self.synchronizer
        return {"schemaVersion":1,"available":credential_store() is not None,"credentialStore":credential_store(),"venue":"okx",
                "product":"perpetual","positionMode":"long_short_mode",
                "settlements":["USDT","coin"],"readOnly":True,"historyMonths":3,
                **view,
                "serviceError":self.service_error,
                # Which proxy pool route the private session uses; null outside pool mode.
                "proxyRoute":({"id":self.route.id,"name":self.route.name}
                              if self.route is not None and self.network_in_use is not None else None),
                "reconciliation":"not_verified",
                "stream":{"state":sync.stream_status if sync else "stopped",
                          "lastReceivedMs":sync.last_ws_received_ms if sync else None,
                          "error":sync.ws_error if sync else None},
                "historyLimitations":["EXCHANGE_RETENTION_LIMIT","UNFILLED_ORDER_RETENTION",
                                      "HISTORICAL_POSITION_BASIS_UNKNOWN","FUNDING_LEG_MAY_BE_UNKNOWN"]}
