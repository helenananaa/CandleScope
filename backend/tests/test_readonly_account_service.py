import asyncio
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.plugin_security_v2.management import LocalManagementGuard
from app.readonly_accounts.api import router
from app.readonly_accounts.normalization import AccountDataError
from app.readonly_accounts.service import ReadOnlyAccountService
from app.readonly_accounts import service as service_module


CREDENTIALS = {"apiKey": "fixture-key", "secret": "fixture-secret", "password": "fixture-passphrase"}


class Vault:
    def __init__(self):
        self.records = {}
        self.fail_store = False
        self.entered = None
        self.release = None

    def store(self, key, value):
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(5)
        if self.fail_store:
            raise AccountDataError("KEYCHAIN_STORE_FAILED")
        self.records[key] = dict(value)

    def delete(self, key):
        self.records.pop(key, None)

    def read(self, key):
        return dict(self.records[key])


class Client:
    uid = "123"
    closed = False

    async def privateGetAccountConfig(self):
        return {"code": "0", "data": [{"uid": self.uid, "perm": "read_only", "posMode": "long_short_mode"}]}

    async def close(self):
        self.closed = True


def fixture_service(tmp_path):
    vault, clients, workers = Vault(), [], []

    def client_factory(credentials, **kwargs):
        client = Client()
        clients.append(client)
        return client

    service = ReadOnlyAccountService(tmp_path, vault_factory=lambda root: vault, client_factory=client_factory)

    async def worker():
        workers.append(True)
        await asyncio.Event().wait()

    service._run = worker
    return service, vault, clients, workers


def test_rotation_failure_keeps_old_key_account_and_facts(tmp_path):
    async def run():
        service, vault, clients, workers = fixture_service(tmp_path)
        try:
            await service.connect(CREDENTIALS)
            old = service.repository.account(credential_reference=True)["credential_id"]
            vault.fail_store = True
            with pytest.raises(AccountDataError, match="KEYCHAIN_STORE_FAILED"):
                await service.connect(CREDENTIALS)
            await asyncio.sleep(0)
            assert service.repository.account(credential_reference=True)["credential_id"] == old
            assert list(vault.records) == [old]
            assert not service.repository.retired_credentials()
            assert service._task is not None and not service._task.done()
            assert len(workers) == 2 and all(client.closed for client in clients)
        finally:
            await service.close()
    asyncio.run(run())


def test_cancellation_during_keychain_write_finishes_tracked_mutation(tmp_path):
    async def run():
        service, vault, clients, _ = fixture_service(tmp_path)
        vault.entered, vault.release = threading.Event(), threading.Event()
        task = asyncio.create_task(service.connect(CREDENTIALS))
        try:
            assert await asyncio.to_thread(vault.entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            vault.release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            account = service.repository.account(credential_reference=True)
            assert set(vault.records) == {account["credential_id"]}
            assert service.repository.retired_credentials() == []
            assert clients[0].closed
        finally:
            vault.release.set()
            await service.close()
    asyncio.run(run())


def test_restart_cleans_only_staged_records_even_without_bound_account(tmp_path):
    async def run():
        service, vault, _, _ = fixture_service(tmp_path)
        service.repository.stage_credential("a" * 32)
        vault.records.update({"a" * 32: dict(CREDENTIALS), "unrelated": {"retained": True}})
        await service.start()
        assert vault.records == {"unrelated": {"retained": True}}
        assert service.repository.retired_credentials() == []
        await service.close()
    asyncio.run(run())


def test_rotate_disconnect_forget_retains_journal_and_excludes_key_references(tmp_path):
    async def run():
        service, vault, _, _ = fixture_service(tmp_path)
        try:
            await service.connect(CREDENTIALS)
            old = next(iter(vault.records))
            service.repository.save_note("a" * 32, 0, {"text": "prior plan"}, event_ms=10)
            await service.connect(CREDENTIALS)
            assert old not in vault.records and len(vault.records) == 1
            state = await service.state()
            assert "credential_id" not in json.dumps(state)
            assert not any(secret in json.dumps(state) for secret in CREDENTIALS.values())
            await service.disconnect(forget=True)
            assert not vault.records
            assert service.repository.notes()[0]["payload"]["text"] == "prior plan"
            with pytest.raises(AccountDataError, match="CREDENTIAL_REQUIRED"):
                await service.resume()
        finally:
            await service.close()
    asyncio.run(run())


def test_account_routes_require_exact_desktop_origin_session_and_write_csrf(tmp_path):
    async def run():
        service, _, clients, _ = fixture_service(tmp_path)
        app = FastAPI()
        guard = LocalManagementGuard(["http://127.0.0.1:61234"])
        app.state.plugin_platform_v2_management_guard = guard
        app.state.readonly_account_service = service
        app.include_router(router, prefix="/api/v1")
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 61235))
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
                assert (await api.get("/api/v1/readonly-accounts/status")).status_code == 403
                assert (await api.get("/api/v1/readonly-accounts/reconciliation")).status_code == 403
                headers = guard.trusted_headers(user_action="account.connect")
                for name in ("Origin", "X-CandleScope-Plugin-Session", "X-CandleScope-CSRF", "X-CandleScope-User-Action"):
                    invalid = {key: value for key, value in headers.items() if key != name}
                    response = await api.post("/api/v1/readonly-accounts/connect", json=CREDENTIALS, headers=invalid)
                    assert response.status_code == 403
                assert clients == []
                response = await api.post("/api/v1/readonly-accounts/connect", json=CREDENTIALS, headers=headers)
                assert response.status_code == 200
                response = await api.get("/api/v1/readonly-accounts/status", headers=headers)
                assert response.status_code == 200 and response.json()["historyMonths"] == 3
                for secret in CREDENTIALS.values():
                    assert secret not in response.text
                response = await api.post("/api/v1/readonly-accounts/connect", content='{"secret":"SENTINEL","secret":"second"}', headers=headers)
                assert response.status_code == 409 and "SENTINEL" not in response.text
                response = await api.post("/api/v1/readonly-accounts/connect", content="SENTINEL" * 600, headers=headers)
                assert response.status_code == 409 and response.json()["error"]["code"] == "ACCOUNT_REQUEST_TOO_LARGE"
        finally:
            await service.close()
    asyncio.run(run())


def test_provider_errors_never_echo_sensitive_exception_text(tmp_path):
    async def run():
        service, _, _, _ = fixture_service(tmp_path)
        class FailingClient(Client):
            async def privateGetAccountConfig(self):
                raise RuntimeError("SENTINEL credentials in upstream failure")
        service.client_factory = lambda credentials, **kwargs: FailingClient()
        app = FastAPI()
        guard = LocalManagementGuard(["http://127.0.0.1:61234"])
        app.state.plugin_platform_v2_management_guard = guard
        app.state.readonly_account_service = service
        app.include_router(router, prefix="/api/v1")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1234)), base_url="http://127.0.0.1:8000") as api:
            response = await api.post("/api/v1/readonly-accounts/connect", json=CREDENTIALS, headers=guard.trusted_headers(user_action="account.connect"))
            assert response.status_code == 409
            assert response.json() == {"error": {"code": "ACCOUNT_SYNC_FAILED"}}
        await service.close()
    asyncio.run(run())


def test_unavailable_account_store_does_not_abort_host_startup(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("SENTINEL unavailable database")
    monkeypatch.setattr(service_module, "ReadOnlyAccountService", unavailable)
    app = SimpleNamespace(state=SimpleNamespace())
    asyncio.run(service_module.start_account_service(app, tmp_path))
    assert app.state.readonly_account_service is None
    assert app.state.readonly_account_error == "ACCOUNT_SYNC_FAILED"


def test_forget_failure_persists_cleanup_intent_for_restart(tmp_path):
    async def run():
        owner, vault, _, _ = fixture_service(tmp_path)
        try:
            await owner.connect(CREDENTIALS)
            record_id = next(iter(vault.records))
            delete = vault.delete
            def fail(key):
                raise AccountDataError("KEYCHAIN_DELETE_FAILED")
            vault.delete = fail
            with pytest.raises(AccountDataError, match="OLD_KEYCHAIN_RECORD_CLEANUP_FAILED"):
                await owner.disconnect(forget=True)
            assert owner.repository.account(credential_reference=True)["credential_id"] == ""
            assert owner.repository.retired_credentials() == [record_id]
            assert record_id in vault.records
            vault.delete = delete
            await owner.start()
            assert not vault.records and not owner.repository.retired_credentials()
        finally:
            await owner.close()
    asyncio.run(run())


def test_client_close_failure_is_bounded_and_visible_without_secret_text(tmp_path):
    async def run():
        owner, _, _, _ = fixture_service(tmp_path)
        class BrokenClose(Client):
            async def close(self):
                raise RuntimeError("SENTINEL upstream credentials")
        owner.client_factory = lambda credentials, **kwargs: BrokenClose()
        try:
            await owner.connect(CREDENTIALS)
            state = await owner.state()
            assert state["serviceError"] == "ACCOUNT_RESOURCE_CLEANUP_FAILED"
            assert "SENTINEL" not in json.dumps(state)
        finally:
            await owner.close()
    asyncio.run(run())


def test_saved_journal_api_reopens_with_identical_fields_and_complete_pagination(tmp_path):
    async def run():
        owner, _, _, _ = fixture_service(tmp_path)
        app = FastAPI()
        guard = LocalManagementGuard(["http://127.0.0.1:61234"])
        app.state.plugin_platform_v2_management_guard = guard
        app.state.readonly_account_service = owner
        app.include_router(router, prefix="/api/v1")
        saved = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1234)), base_url="http://127.0.0.1:8000") as api:
            headers = guard.trusted_headers(user_action="account.journal")
            for version in range(3):
                response = await api.post("/api/v1/readonly-accounts/journal", headers=headers, json={
                    "noteId":"a"*32,"baseVersion":version,"text":f"plan {version}","tags":["fixture"],"kind":"plan","eventMs":10})
                assert response.status_code == 200
                saved.append(response.json())
            # Re-open the persistent repository through a fresh owner.
            await owner.close()
            app.state.readonly_account_service, _, _, _ = fixture_service(tmp_path)
            rows, params = [], {"limit":1}
            while True:
                response = await api.get("/api/v1/readonly-accounts/journal", headers=headers, params=params)
                assert response.status_code == 200
                page = response.json(); rows.extend(page["versions"])
                if page["next"] is None: break
                cursor = page["next"]
                params = {"limit":1,"before_recorded_ms":cursor["recordedMs"],"before_note_id":cursor["noteId"],"before_version":cursor["version"]}
            assert rows == list(reversed(saved))
            await app.state.readonly_account_service.close()
    asyncio.run(run())
