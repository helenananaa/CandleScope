"""OKX read-only keys in the host credential vault; no plaintext or command-line fallback.

The records live in the ``okx-readonly`` namespace, so the Keychain service is
``io.candlescope.okx-readonly.<data folder>`` as before and saved keys stay readable.
Windows support (#575 PL-5) only needs this class to accept win32 and the
account panel to say so: the vault already stores records in Credential Manager.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

from app.host_credentials import CredentialVaultError, open_host_vault
from app.host_credentials.vault import record_name

from .normalization import AccountDataError

NAMESPACE = "okx-readonly"


def validate_credentials(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"apiKey", "secret", "password"}:
        raise AccountDataError("CREDENTIAL_FIELDS_INVALID")
    for item in value.values():
        if (not isinstance(item, str) or not 1 <= len(item) <= 256 or item != item.strip()
                or any(ord(char) < 32 or ord(char) > 126 for char in item)):
            raise AccountDataError("CREDENTIAL_FIELDS_INVALID")
    return dict(value)


class MacKeychainVault:
    """Only open this feature's known record ID in its data-directory namespace."""

    def __init__(self, root: Path, *, store=None):
        if store is None:
            if sys.platform != "darwin":
                raise AccountDataError("MACOS_KEYCHAIN_REQUIRED")
            try:
                store = open_host_vault(root, NAMESPACE)
            except CredentialVaultError:
                raise AccountDataError("MACOS_KEYCHAIN_REQUIRED") from None
        self._store = store

    @staticmethod
    def _record(record_id: str) -> str:
        try:
            return record_name(record_id)
        except CredentialVaultError:
            raise AccountDataError("CREDENTIAL_RECORD_INVALID") from None

    def store(self, record_id: str, credentials: Mapping[str, str]) -> None:
        record = self._record(record_id)
        secret = json.dumps(validate_credentials(credentials), separators=(",", ":"))
        try:
            self._store.store(record, secret)
        except CredentialVaultError:
            raise AccountDataError("KEYCHAIN_STORE_FAILED") from None

    def read(self, record_id: str) -> dict[str, str]:
        record = self._record(record_id)
        try:
            raw = self._store.read(record)
        except CredentialVaultError as exc:
            # A missing record is a failed read, as before; unreadable content is an invalid record.
            raise AccountDataError("KEYCHAIN_RECORD_INVALID" if exc.code == "CREDENTIAL_RECORD_INVALID"
                                   else "KEYCHAIN_READ_FAILED") from None
        try:
            return validate_credentials(json.loads(raw))
        except (ValueError, TypeError):
            raise AccountDataError("KEYCHAIN_RECORD_INVALID") from None

    def delete(self, record_id: str) -> None:
        record = self._record(record_id)
        try:
            self._store.delete(record)
        except CredentialVaultError:
            raise AccountDataError("KEYCHAIN_DELETE_FAILED") from None
