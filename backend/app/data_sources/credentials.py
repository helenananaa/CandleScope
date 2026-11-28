"""Data-source keys in the host credential vault (ADR-DATA-002 §8, D4).

Every (source, field) pair is its own vault record. A small index in the data
folder names the current record of each field and the records waiting to be
deleted; it also keeps the last four characters of a saved key, which is all
the interface ever shows. Keys never leave this process except in requests to
their own data source.

A key saved here takes precedence over the field's environment variable; the
environment variable still works when nothing is saved.

Secrets are read from the OS only at startup and right after a save, on a
worker thread, never on the event loop: a macOS Keychain prompt can wait for
the person indefinitely.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from app.host_credentials import CredentialVaultError, open_host_vault, vault_supported

from .registry import DATA_SOURCES, CredentialField, credential_field

NAMESPACE = "data-sources"
INDEX_FILE = "credentials.json"
SCHEMA_VERSION = 1
_HINT_MIN_LENGTH = 12


class DataSourceCredentialError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _key(source_id: str, field_id: str) -> str:
    return f"{source_id}.{field_id}"


def masked_hint(value: str) -> str | None:
    """The last four characters of a long key; short keys show nothing."""
    return value[-4:] if len(value) >= _HINT_MIN_LENGTH else None


def _default_environment(name: str) -> str:
    from app.core.config import getenv

    return str(getenv(name, "") or "").strip()


def _default_vault(root: Path):
    return open_host_vault(root, NAMESPACE)


class DataSourceCredentials:
    def __init__(self, root: Path, *, vault_factory: Callable[[Path], Any] = _default_vault,
                 environment: Callable[[str], str] = _default_environment,
                 platform_supported: bool | None = None, clock: Callable[[], float] = time.time):
        self.root = Path(root)
        self._vault_factory = vault_factory
        self._environment = environment
        self._supported = vault_supported() if platform_supported is None else platform_supported
        self._clock = clock
        self._lock = threading.Lock()
        self._vault: Any = None
        self._index: dict = {"fields": {}, "retired": []}
        self._secrets: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self.vault_error: str | None = None
        self.index_error: str | None = None
        self.loaded = False

    # -- index ---------------------------------------------------------------

    def _index_path(self) -> Path:
        return self.root / INDEX_FILE

    def _read_index(self) -> dict:
        path = self._index_path()
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return {"fields": {}, "retired": []}
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
                raise ValueError
            fields = value.get("fields")
            retired = value.get("retired")
            if not isinstance(fields, dict) or not isinstance(retired, list):
                raise ValueError
            clean_fields = {}
            for key, entry in fields.items():
                if (isinstance(key, str) and isinstance(entry, dict) and isinstance(entry.get("record"), str)
                        and (entry.get("hint") is None or isinstance(entry.get("hint"), str))
                        and type(entry.get("updatedMs")) is int):
                    clean_fields[key] = {"record": entry["record"], "hint": entry.get("hint"),
                                         "updatedMs": entry["updatedMs"]}
            return {"fields": clean_fields,
                    "retired": [record for record in retired if isinstance(record, str)]}
        except (ValueError, TypeError):
            raise DataSourceCredentialError("CREDENTIAL_INDEX_INVALID") from None

    def _current_index(self) -> dict:
        """The index for a change; an unreadable one is kept aside and replaced."""
        try:
            index = self._read_index()
        except DataSourceCredentialError:
            aside = self.root / f"{INDEX_FILE}.invalid-{int(self._clock() * 1000)}"
            try:
                os.replace(self._index_path(), aside)
            except OSError:
                raise DataSourceCredentialError("CREDENTIAL_INDEX_INVALID") from None
            index = {"fields": {}, "retired": []}
        self.index_error = None
        return index

    def _write_index(self, index: dict) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps({"schemaVersion": SCHEMA_VERSION, **index}, sort_keys=True,
                             separators=(",", ":")).encode()
        descriptor, name = tempfile.mkstemp(dir=self.root, prefix=".credentials-", suffix=".json")
        try:
            with os.fdopen(descriptor, "wb") as out:
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
            try:
                os.chmod(name, 0o600)
            except OSError:
                pass
            os.replace(name, self._index_path())
        finally:
            Path(name).unlink(missing_ok=True)
        self._index = index

    # -- vault ---------------------------------------------------------------

    def _open_vault(self):
        if self._vault is not None:
            return self._vault
        if not self._supported:
            raise DataSourceCredentialError("CREDENTIAL_VAULT_UNAVAILABLE")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self._vault = self._vault_factory(self.root)
        except CredentialVaultError as exc:
            self.vault_error = exc.code
            raise DataSourceCredentialError("CREDENTIAL_VAULT_UNAVAILABLE") from None
        self.vault_error = None
        return self._vault

    def _cleanup_retired(self, vault) -> None:
        index = self._index
        if not index["retired"]:
            return
        remaining = []
        for record in index["retired"]:
            try:
                vault.delete(record)
            except CredentialVaultError as exc:
                if exc.code != "CREDENTIAL_RECORD_INVALID":
                    remaining.append(record)
        if remaining != index["retired"]:
            self._write_index({"fields": index["fields"], "retired": remaining})
        if remaining:
            raise DataSourceCredentialError("OLD_CREDENTIAL_CLEANUP_FAILED")

    # -- lifecycle -----------------------------------------------------------

    def load(self) -> None:
        """Read the index and every saved key; failures are kept per field."""
        with self._lock:
            self._errors = {}
            try:
                self._index = self._read_index()
                self.index_error = None
            except DataSourceCredentialError as exc:
                self.index_error = exc.code
                self.loaded = True
                return
            if not self._index["fields"] and not self._index["retired"]:
                self.loaded = True
                return
            try:
                vault = self._open_vault()
            except DataSourceCredentialError as exc:
                for key in self._index["fields"]:
                    self._errors[key] = exc.code
                self.loaded = True
                return
            try:
                self._cleanup_retired(vault)
            except DataSourceCredentialError:
                pass  # Retried after the next save or removal; the saved keys still load.
            secrets = {}
            for key, entry in self._index["fields"].items():
                try:
                    secrets[key] = vault.read(entry["record"])
                except CredentialVaultError as exc:
                    self._errors[key] = exc.code
            self._secrets = secrets
            self.loaded = True

    def secret(self, source_id: str, field_id: str) -> str | None:
        """The saved key, if it loaded; never reads the OS store."""
        return self._secrets.get(_key(source_id, field_id))

    def effective(self, source_id: str, field: CredentialField) -> str:
        """The value requests use: a saved key first, then the environment variable."""
        return self.secret(source_id, field.id) or self._environment(field.environment)

    def save(self, source_id: str, field_id: str, value: Any) -> dict:
        found = credential_field(source_id, field_id)
        if found is None:
            raise DataSourceCredentialError("DATA_SOURCE_FIELD_UNKNOWN")
        _, field = found
        if not field.valid(value):
            raise DataSourceCredentialError("CREDENTIAL_VALUE_INVALID")
        key = _key(source_id, field_id)
        with self._lock:
            vault = self._open_vault()
            index = self._current_index()
            record = uuid.uuid4().hex
            # Stage the new record as retired first: if the process stops before
            # it is bound, the next start deletes it instead of leaking it.
            self._write_index({"fields": index["fields"], "retired": [*index["retired"], record]})
            try:
                vault.store(record, value)
            except CredentialVaultError:
                try:
                    self._cleanup_retired(vault)
                except DataSourceCredentialError:
                    pass
                raise DataSourceCredentialError("CREDENTIAL_STORE_FAILED") from None
            fields = dict(index["fields"])
            previous = fields.get(key)
            fields[key] = {"record": record, "hint": masked_hint(value),
                           "updatedMs": int(self._clock() * 1000)}
            retired = [*index["retired"], *([previous["record"]] if previous else [])]
            self._write_index({"fields": fields, "retired": retired})
            self._secrets = {**self._secrets, key: value}
            self._errors.pop(key, None)
            try:
                self._cleanup_retired(vault)
            except DataSourceCredentialError:
                pass  # The new key is saved; the old record is retried later.
        return self.field_status(source_id, field)

    def remove(self, source_id: str, field_id: str) -> dict:
        found = credential_field(source_id, field_id)
        if found is None:
            raise DataSourceCredentialError("DATA_SOURCE_FIELD_UNKNOWN")
        _, field = found
        key = _key(source_id, field_id)
        with self._lock:
            index = self._current_index()
            fields = dict(index["fields"])
            previous = fields.pop(key, None)
            retired = [*index["retired"], *([previous["record"]] if previous else [])]
            if previous is not None or retired != index["retired"]:
                # Forget the key in this process before touching the OS store,
                # so nothing uses it again even if the deletion has to be retried.
                self._write_index({"fields": fields, "retired": retired})
            secrets = dict(self._secrets)
            secrets.pop(key, None)
            self._secrets = secrets
            self._errors.pop(key, None)
            if retired:
                try:
                    self._cleanup_retired(self._open_vault())
                except DataSourceCredentialError:
                    pass  # Already unused; the OS record is deleted on a later start or change.
        return self.field_status(source_id, field)

    # -- status --------------------------------------------------------------

    def field_status(self, source_id: str, field: CredentialField) -> dict:
        key = _key(source_id, field.id)
        entry = self._index["fields"].get(key)
        environment = self._environment(field.environment)
        saved = self._secrets.get(key)
        if saved:
            active, hint = "saved", entry["hint"] if entry else masked_hint(saved)
        elif environment:
            active, hint = "environment", masked_hint(environment)
        else:
            active, hint = None, None
        return {
            "id": field.id,
            "saved": entry is not None,
            "savedHint": entry["hint"] if entry else None,
            "savedAtMs": entry["updatedMs"] if entry else None,
            "savedError": self._errors.get(key) if entry else None,
            "environmentVariable": field.environment,
            "environmentSet": bool(environment),
            "active": active,
            "activeHint": hint,
        }

    def status(self) -> dict:
        return {
            "schemaVersion": 1,
            "vaultAvailable": self._supported and self.vault_error is None,
            "error": (self.index_error or self.vault_error
                      or (None if self._supported else "CREDENTIAL_VAULT_UNAVAILABLE")),
            "loaded": self.loaded,
            # Old records the OS store has not deleted yet; they are never used.
            "deletionPending": bool(self._index["retired"]),
            "sources": [{
                "id": source.id,
                "name": source.name,
                "signupUrl": source.signup_url,
                "fields": [self.field_status(source.id, field) for field in source.fields],
            } for source in DATA_SOURCES.values()],
        }


_ACTIVE: DataSourceCredentials | None = None


def activate(service: DataSourceCredentials | None) -> None:
    global _ACTIVE
    _ACTIVE = service


def saved_secret(source_id: str, field_id: str) -> str | None:
    """The key saved in the vault for this process, or None."""
    service = _ACTIVE
    return service.secret(source_id, field_id) if service is not None else None


def resolve_secret(source_id: str, field_id: str, fallback: Any = "") -> str:
    """A saved key first, then the configured (environment) value."""
    return saved_secret(source_id, field_id) or str(fallback or "").strip()


__all__ = [
    "DataSourceCredentialError",
    "DataSourceCredentials",
    "activate",
    "masked_hint",
    "resolve_secret",
    "saved_secret",
]
