"""The host credential vault: CandleScope's one store for secrets in the OS.

Each record is one secret under a feature namespace (``okx-readonly``,
``data-sources``) and a data folder. macOS keeps it as a Keychain generic
password; Windows keeps it in Credential Manager through keyring's WinVault
backend, the same backend proxy subscriptions use. Nothing falls back to a
plaintext file, an environment variable or the command line.

Record IDs are random and written once: a new secret gets a new record and the
caller retires the old one, so a crash between the two never leaves a record
that is half old and half new.
"""
from __future__ import annotations

import ctypes
import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Protocol

_RECORD = re.compile(r"^[0-9a-f]{32}$")
_NAMESPACE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
# Windows Credential Manager holds at most 2,560 bytes and keyring stores
# UTF-16, so 1,024 ASCII characters fit on both systems.
MAX_SECRET_CHARS = 1024
_MAX_READ_BYTES = 4096
_MAC_ITEM_NOT_FOUND = -25300


class CredentialVaultError(ValueError):
    """A bounded error code; secrets and OS messages never reach it."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class CredentialStore(Protocol):
    def store(self, record_id: str, secret: str) -> None: ...

    def read(self, record_id: str) -> str: ...

    def delete(self, record_id: str) -> None: ...


def vault_supported(platform: str | None = None) -> bool:
    return (platform or sys.platform) in {"darwin", "win32"}


def record_name(record_id: Any) -> str:
    if not isinstance(record_id, str) or _RECORD.fullmatch(record_id) is None:
        raise CredentialVaultError("CREDENTIAL_RECORD_INVALID")
    return record_id


def _secret_bytes(secret: Any) -> bytearray:
    if (not isinstance(secret, str) or not 1 <= len(secret) <= MAX_SECRET_CHARS
            or any(ord(char) < 32 or ord(char) > 126 for char in secret)):
        raise CredentialVaultError("CREDENTIAL_SECRET_INVALID")
    return bytearray(secret.encode("ascii"))


def _decode(raw: bytes) -> str:
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError:
        raise CredentialVaultError("CREDENTIAL_RECORD_INVALID") from None
    if not value or any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise CredentialVaultError("CREDENTIAL_RECORD_INVALID")
    return value


def namespace_service(root: Path, namespace: str) -> str:
    """The OS service name for one feature's records in one data folder."""
    if _NAMESPACE.fullmatch(namespace) is None:
        raise CredentialVaultError("CREDENTIAL_NAMESPACE_INVALID")
    # The namespace follows the data folder when it moves (see secret_namespace_origin).
    from app.core.profile_relocation import secret_namespace_origin

    context = hashlib.sha256(secret_namespace_origin(root).encode()).hexdigest()[:32]
    return f"io.candlescope.{namespace}.{context}"


class MacKeychainStore:
    """Generic passwords: service is the namespace, account is the record ID."""

    def __init__(self, service: str):
        if sys.platform != "darwin":
            raise CredentialVaultError("CREDENTIAL_VAULT_UNAVAILABLE")
        self.service = service.encode("ascii")
        self.security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        self.core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        uint, pointer = ctypes.c_uint32, ctypes.c_void_p
        self.security.SecKeychainAddGenericPassword.argtypes = [pointer, uint, ctypes.c_char_p, uint, ctypes.c_char_p, uint, pointer, ctypes.POINTER(pointer)]
        self.security.SecKeychainFindGenericPassword.argtypes = [pointer, uint, ctypes.c_char_p, uint, ctypes.c_char_p, ctypes.POINTER(uint), ctypes.POINTER(pointer), ctypes.POINTER(pointer)]
        self.security.SecKeychainItemFreeContent.argtypes = [pointer, pointer]
        self.security.SecKeychainItemDelete.argtypes = [pointer]
        for name in ["SecKeychainAddGenericPassword", "SecKeychainFindGenericPassword", "SecKeychainItemFreeContent", "SecKeychainItemDelete"]:
            getattr(self.security, name).restype = ctypes.c_int32
        self.core.CFRelease.argtypes = [pointer]
        self.core.CFRelease.restype = None

    def store(self, record_id: str, secret: str) -> None:
        name = record_name(record_id).encode("ascii")
        data = _secret_bytes(secret)
        buffer = (ctypes.c_ubyte * len(data)).from_buffer(data)
        item = ctypes.c_void_p()
        try:
            # Adding an existing record fails (errSecDuplicateItem): records are write-once.
            status = self.security.SecKeychainAddGenericPassword(None, len(self.service), self.service,
                len(name), name, len(data), buffer, ctypes.byref(item))
            if status:
                raise CredentialVaultError("CREDENTIAL_STORE_FAILED")
        finally:
            for index in range(len(data)):
                data[index] = 0
            if item.value:
                self.core.CFRelease(item)

    def read(self, record_id: str) -> str:
        name = record_name(record_id).encode("ascii")
        length, content, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
        try:
            status = self.security.SecKeychainFindGenericPassword(None, len(self.service), self.service,
                len(name), name, ctypes.byref(length), ctypes.byref(content), ctypes.byref(item))
            if status == _MAC_ITEM_NOT_FOUND:
                raise CredentialVaultError("CREDENTIAL_NOT_FOUND")
            if status or not content.value or not 1 <= length.value <= _MAX_READ_BYTES:
                raise CredentialVaultError("CREDENTIAL_READ_FAILED")
            return _decode(ctypes.string_at(content, length.value))
        finally:
            if content.value:
                ctypes.memset(content, 0, length.value)
                self.security.SecKeychainItemFreeContent(None, content)
            if item.value:
                self.core.CFRelease(item)

    def delete(self, record_id: str) -> None:
        name = record_name(record_id).encode("ascii")
        item = ctypes.c_void_p()
        try:
            status = self.security.SecKeychainFindGenericPassword(None, len(self.service), self.service,
                len(name), name, None, None, ctypes.byref(item))
            if status == _MAC_ITEM_NOT_FOUND:  # This exact record does not exist.
                return
            if status or not item.value or self.security.SecKeychainItemDelete(item):
                raise CredentialVaultError("CREDENTIAL_DELETE_FAILED")
        finally:
            if item.value:
                self.core.CFRelease(item)


class WindowsCredentialStore:
    """Generic credentials: one target per record, ``<service>/<record ID>``.

    One target per record keeps keyring from re-saving another record under a
    compound ``user@service`` name, which it does when two records share a target.
    """

    def __init__(self, service: str, *, backend: Any = None):
        if backend is None:
            if sys.platform != "win32":
                raise CredentialVaultError("CREDENTIAL_VAULT_UNAVAILABLE")
            try:
                from keyring.backends.Windows import WinVaultKeyring
                backend = WinVaultKeyring()
            except Exception:
                raise CredentialVaultError("CREDENTIAL_VAULT_UNAVAILABLE") from None
        self.service = service
        self.backend = backend

    def _target(self, record_id: str) -> str:
        return f"{self.service}/{record_name(record_id)}"

    def _get(self, target: str, record_id: str) -> str | None:
        try:
            return self.backend.get_password(target, record_id)
        except Exception:
            raise CredentialVaultError("CREDENTIAL_READ_FAILED") from None

    def store(self, record_id: str, secret: str) -> None:
        target = self._target(record_id)
        data = _secret_bytes(secret)
        try:
            if self._get(target, record_id) is not None:
                raise CredentialVaultError("CREDENTIAL_STORE_FAILED")
            self.backend.set_password(target, record_id, data.decode("ascii"))
        except CredentialVaultError:
            raise
        except Exception:
            raise CredentialVaultError("CREDENTIAL_STORE_FAILED") from None
        finally:
            for index in range(len(data)):
                data[index] = 0

    def read(self, record_id: str) -> str:
        value = self._get(self._target(record_id), record_id)
        if value is None:
            raise CredentialVaultError("CREDENTIAL_NOT_FOUND")
        if not isinstance(value, str) or len(value) > _MAX_READ_BYTES:
            raise CredentialVaultError("CREDENTIAL_READ_FAILED")
        try:
            return _decode(value.encode("ascii"))
        except UnicodeEncodeError:
            raise CredentialVaultError("CREDENTIAL_RECORD_INVALID") from None

    def delete(self, record_id: str) -> None:
        target = self._target(record_id)
        if self._get(target, record_id) is None:
            return
        try:
            self.backend.delete_password(target, record_id)
        except Exception:
            raise CredentialVaultError("CREDENTIAL_DELETE_FAILED") from None
        if self._get(target, record_id) is not None:
            raise CredentialVaultError("CREDENTIAL_DELETE_FAILED")


def open_host_vault(root: Path, namespace: str, *, platform: str | None = None) -> CredentialStore:
    """The OS store for ``namespace`` in this data folder, or CREDENTIAL_VAULT_UNAVAILABLE."""
    platform = platform or sys.platform
    if not vault_supported(platform):
        raise CredentialVaultError("CREDENTIAL_VAULT_UNAVAILABLE")
    service = namespace_service(root, namespace)
    if platform == "darwin":
        return MacKeychainStore(service)
    return WindowsCredentialStore(service)


__all__ = [
    "CredentialStore",
    "CredentialVaultError",
    "MAX_SECRET_CHARS",
    "MacKeychainStore",
    "WindowsCredentialStore",
    "namespace_service",
    "open_host_vault",
    "record_name",
    "vault_supported",
]
