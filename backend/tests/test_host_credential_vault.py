"""The host credential vault on macOS (Keychain) and Windows (Credential Manager)."""
import hashlib
import os
import sys
import uuid

import pytest

from app.core.profile_relocation import secret_namespace_origin
from app.host_credentials import vault as vault_module
from app.host_credentials.vault import (
    CredentialVaultError,
    WindowsCredentialStore,
    namespace_service,
    open_host_vault,
)
from app.readonly_accounts.credentials import MacKeychainVault
from app.readonly_accounts.normalization import AccountDataError

RECORD = "a" * 32
OTHER = "b" * 32


class FakeWinVault:
    """keyring's WinVaultKeyring semantics, including the compound re-save."""

    def __init__(self):
        self.targets = {}
        self.fail = None

    def _check(self, operation):
        if self.fail == operation:
            raise OSError("SENTINEL os failure")

    def get_password(self, service, username):
        self._check("get")
        entry = self.targets.get(service)
        if entry is None or entry[0] != username:
            entry = self.targets.get(f"{username}@{service}")
        return entry[1] if entry else None

    def set_password(self, service, username, password):
        self._check("set")
        existing = self.targets.get(service)
        if existing:
            self.targets[f"{existing[0]}@{service}"] = existing
        self.targets[service] = (username, password)

    def delete_password(self, service, username):
        self._check("delete")
        deleted = False
        for target in (service, f"{username}@{service}"):
            entry = self.targets.get(target)
            if entry and entry[0] == username:
                del self.targets[target]
                deleted = True
        if not deleted:
            raise RuntimeError("not found")


def test_windows_records_round_trip_one_target_each():
    backend = FakeWinVault()
    store = WindowsCredentialStore("io.candlescope.data-sources.ctx", backend=backend)
    store.store(RECORD, "first-secret")
    store.store(OTHER, "second-secret")
    assert store.read(RECORD) == "first-secret"
    assert store.read(OTHER) == "second-secret"
    # One target per record: no compound copies of another record's secret.
    assert set(backend.targets) == {f"io.candlescope.data-sources.ctx/{RECORD}",
                                    f"io.candlescope.data-sources.ctx/{OTHER}"}
    store.delete(RECORD)
    with pytest.raises(CredentialVaultError, match="CREDENTIAL_NOT_FOUND"):
        store.read(RECORD)
    store.delete(RECORD)  # Already gone: nothing to do.
    assert store.read(OTHER) == "second-secret"


def test_windows_records_are_write_once_and_errors_hide_os_text():
    backend = FakeWinVault()
    store = WindowsCredentialStore("svc", backend=backend)
    store.store(RECORD, "first-secret")
    with pytest.raises(CredentialVaultError, match="CREDENTIAL_STORE_FAILED"):
        store.store(RECORD, "replacement")
    assert store.read(RECORD) == "first-secret"
    assert len(backend.targets) == 1
    for operation, call, code in [("set", lambda: store.store(OTHER, "x" * 8), "CREDENTIAL_STORE_FAILED"),
                                  ("get", lambda: store.read(RECORD), "CREDENTIAL_READ_FAILED"),
                                  ("delete", lambda: store.delete(RECORD), "CREDENTIAL_DELETE_FAILED")]:
        backend.fail = operation
        with pytest.raises(CredentialVaultError) as raised:
            call()
        assert raised.value.code == code and "SENTINEL" not in str(raised.value)
        assert raised.value.__cause__ is None and raised.value.__suppress_context__
    backend.fail = None


@pytest.mark.parametrize("record", ["", "A" * 32, "a" * 31, "../" + "a" * 29, None])
def test_record_ids_are_exact(record):
    store = WindowsCredentialStore("svc", backend=FakeWinVault())
    with pytest.raises(CredentialVaultError, match="CREDENTIAL_RECORD_INVALID"):
        store.store(record, "secret-value")


@pytest.mark.parametrize("secret", ["", "é" * 8, "line\nbreak", "x" * 1025, b"bytes"])
def test_secrets_are_bounded_printable_ascii(secret):
    store = WindowsCredentialStore("svc", backend=FakeWinVault())
    with pytest.raises(CredentialVaultError, match="CREDENTIAL_SECRET_INVALID"):
        store.store(RECORD, secret)


def test_service_names_keep_the_okx_keychain_namespace(tmp_path):
    root = tmp_path / "readonly-accounts"
    root.mkdir()
    context = hashlib.sha256(secret_namespace_origin(root).encode()).hexdigest()[:32]
    # Saved OKX keys stay readable: the same service the 1.0 Keychain store used.
    assert namespace_service(root, "okx-readonly") == "io.candlescope.okx-readonly." + context
    assert namespace_service(root, "data-sources") == "io.candlescope.data-sources." + context
    with pytest.raises(CredentialVaultError, match="CREDENTIAL_NAMESPACE_INVALID"):
        namespace_service(root, "Bad Namespace")


def test_other_systems_have_no_vault(tmp_path):
    with pytest.raises(CredentialVaultError, match="CREDENTIAL_VAULT_UNAVAILABLE"):
        open_host_vault(tmp_path, "data-sources", platform="linux")


def test_okx_wrapper_keeps_its_error_codes():
    class Store:
        def __init__(self):
            self.records = {}
            self.fail = None

        def store(self, record, secret):
            if self.fail:
                raise CredentialVaultError(self.fail)
            self.records[record] = secret

        def read(self, record):
            if record not in self.records:
                raise CredentialVaultError("CREDENTIAL_NOT_FOUND")
            return self.records[record]

        def delete(self, record):
            if self.fail:
                raise CredentialVaultError(self.fail)
            self.records.pop(record, None)

    store = Store()
    vault = MacKeychainVault(None, store=store)
    credentials = {"apiKey": "k" * 10, "secret": "s" * 10, "password": "p" * 10}
    vault.store(RECORD, credentials)
    assert vault.read(RECORD) == credentials
    with pytest.raises(AccountDataError, match="KEYCHAIN_READ_FAILED"):
        vault.read(OTHER)
    with pytest.raises(AccountDataError, match="CREDENTIAL_RECORD_INVALID"):
        vault.read("not-a-record")
    store.records[OTHER] = '{"apiKey":"only"}'
    with pytest.raises(AccountDataError, match="KEYCHAIN_RECORD_INVALID"):
        vault.read(OTHER)
    store.fail = "CREDENTIAL_STORE_FAILED"
    with pytest.raises(AccountDataError, match="KEYCHAIN_STORE_FAILED"):
        vault.store(OTHER, credentials)
    store.fail = "CREDENTIAL_DELETE_FAILED"
    with pytest.raises(AccountDataError, match="KEYCHAIN_DELETE_FAILED"):
        vault.delete(RECORD)
    with pytest.raises(AccountDataError, match="CREDENTIAL_FIELDS_INVALID"):
        vault.store(RECORD, {"apiKey": "x"})


def test_okx_accounts_stay_macos_only_until_pl5(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(AccountDataError, match="MACOS_KEYCHAIN_REQUIRED"):
        MacKeychainVault(tmp_path)


@pytest.mark.skipif(os.environ.get("CANDLESCOPE_REAL_CREDENTIAL_VAULT") != "1",
                    reason="writes to this computer's Keychain or Credential Manager")
def test_real_os_vault_round_trip(tmp_path):
    """CI sets CANDLESCOPE_REAL_CREDENTIAL_VAULT=1 on Windows; run it by hand on macOS."""
    assert vault_module.vault_supported(), "the real vault check must run on macOS or Windows"
    root = tmp_path / "vault-selftest"
    root.mkdir()
    store = open_host_vault(root, "vault-selftest")
    record, other = uuid.uuid4().hex, uuid.uuid4().hex
    try:
        store.store(record, "candlescope-selftest-0001")
        store.store(other, "candlescope-selftest-0002")
        assert store.read(record) == "candlescope-selftest-0001"
        assert store.read(other) == "candlescope-selftest-0002"
        with pytest.raises(CredentialVaultError, match="CREDENTIAL_STORE_FAILED"):
            store.store(record, "candlescope-selftest-0003")
        assert store.read(record) == "candlescope-selftest-0001"
        store.delete(record)
        with pytest.raises(CredentialVaultError, match="CREDENTIAL_NOT_FOUND"):
            store.read(record)
        store.delete(record)
        # A new instance (as after a restart) reads the same record.
        assert open_host_vault(root, "vault-selftest").read(other) == "candlescope-selftest-0002"
    finally:
        store.delete(record)
        store.delete(other)
