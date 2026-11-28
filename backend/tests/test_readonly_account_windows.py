"""Read-only OKX accounts on Windows: keys in Credential Manager (#575 PL-5)."""
import asyncio
import json
import os
import sys

import pytest

from app.host_credentials import CredentialVaultError, open_host_vault, vault_supported
from app.readonly_accounts import credentials as account_credentials
from app.readonly_accounts.credentials import NAMESPACE, AccountVault, credential_store
from app.readonly_accounts.normalization import AccountDataError
from app.readonly_accounts.service import ReadOnlyAccountService

CREDENTIALS = {"apiKey": "fixture-key", "secret": "fixture-secret", "password": "fixture-passphrase"}


def test_the_panel_names_a_store_exactly_where_the_vault_has_one():
    assert credential_store("darwin") == "macos-keychain"
    assert credential_store("win32") == "windows-credential-manager"
    assert credential_store("linux") is None
    platforms = ("darwin", "win32", "linux", "cygwin", "freebsd14")
    assert {name for name in platforms if vault_supported(name)} == set(account_credentials.STORES)


def test_windows_opens_the_okx_namespace_and_other_systems_refuse(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(account_credentials, "open_host_vault", lambda root, namespace: opened.append((root, namespace)) or "store")
    monkeypatch.setattr(sys, "platform", "win32")
    assert AccountVault(tmp_path)._store == "store" and opened == [(tmp_path, NAMESPACE)]
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(AccountDataError, match="CREDENTIAL_STORE_UNAVAILABLE"):
        AccountVault(tmp_path)
    assert opened == [(tmp_path, NAMESPACE)]


def test_an_unusable_credential_manager_stops_with_its_own_code(monkeypatch, tmp_path):
    def broken(root, namespace):
        raise CredentialVaultError("CREDENTIAL_VAULT_UNAVAILABLE")
    monkeypatch.setattr(account_credentials, "open_host_vault", broken)
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(AccountDataError, match="CREDENTIAL_STORE_UNAVAILABLE"):
        AccountVault(tmp_path)


@pytest.mark.parametrize(("platform", "available", "store"), [
    ("darwin", True, "macos-keychain"), ("win32", True, "windows-credential-manager"), ("linux", False, None)])
def test_the_state_says_which_store_keeps_the_key(monkeypatch, tmp_path, platform, available, store):
    async def run():
        service = ReadOnlyAccountService(tmp_path, vault_factory=lambda root: None, client_factory=lambda *a, **k: None)
        try:
            monkeypatch.setattr(sys, "platform", platform)
            state = await service.state()
            assert (state["available"], state["credentialStore"]) == (available, store)
        finally:
            await service.close()
    asyncio.run(run())


class Client:
    async def privateGetAccountConfig(self):
        return {"code": "0", "data": [{"uid": "123", "perm": "read_only", "posMode": "long_short_mode"}]}

    async def close(self):
        pass


@pytest.mark.skipif(os.environ.get("CANDLESCOPE_REAL_CREDENTIAL_VAULT") != "1",
                    reason="writes an account key to this computer's Keychain or Credential Manager")
def test_real_store_keeps_reads_and_forgets_an_account_key(tmp_path):
    """CI sets CANDLESCOPE_REAL_CREDENTIAL_VAULT=1 on Windows; run it by hand on macOS.

    The service saves the key on connect, the session reads it back from the
    OS store to open its client, and forgetting the account deletes it.
    """
    assert credential_store() is not None, "the real account key check must run on macOS or Windows"
    root = tmp_path / "readonly-accounts"
    session_keys = []

    def client_factory(credentials, **_):
        if not session_keys and not hasattr(client_factory, "probed"):
            client_factory.probed = True
            return Client()  # connect's identity probe
        session_keys.append(dict(credentials))
        # Stop the session here: it has read the key, and no exchange is called.
        raise AccountDataError("READONLY_KEY_REQUIRED")

    async def run():
        service = ReadOnlyAccountService(root, client_factory=client_factory)
        store = open_host_vault(root, NAMESPACE)
        record = None
        try:
            await service.connect(dict(CREDENTIALS))
            record = service.repository.account(credential_reference=True)["credential_id"]
            assert json.loads(store.read(record)) == CREDENTIALS
            await asyncio.wait_for(service._task, 30)
            assert session_keys == [CREDENTIALS]
            await service.disconnect(forget=True)
            assert not service.repository.account(credential_reference=True)["credential_id"]
            with pytest.raises(CredentialVaultError, match="CREDENTIAL_NOT_FOUND"):
                store.read(record)
        finally:
            if record is not None:
                store.delete(record)
            await service.close()
    asyncio.run(run())
