"""macOS Keychain credential storage; no plaintext or command-line fallback."""
from __future__ import annotations

import ctypes
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .normalization import AccountDataError

_RECORD = re.compile(r"^[0-9a-f]{32}$")


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

    def __init__(self, root: Path):
        if sys.platform != "darwin":
            raise AccountDataError("MACOS_KEYCHAIN_REQUIRED")
        context = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:32]
        self.service = ("io.candlescope.okx-readonly." + context).encode()
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

    @staticmethod
    def _name(record_id: str) -> bytes:
        if not isinstance(record_id, str) or _RECORD.fullmatch(record_id) is None:
            raise AccountDataError("CREDENTIAL_RECORD_INVALID")
        return record_id.encode("ascii")

    def store(self, record_id: str, credentials: Mapping[str, str]) -> None:
        name = self._name(record_id)
        secret = bytearray(json.dumps(validate_credentials(credentials), separators=(",", ":")).encode())
        buffer = (ctypes.c_ubyte * len(secret)).from_buffer(secret)
        item = ctypes.c_void_p()
        try:
            status = self.security.SecKeychainAddGenericPassword(None, len(self.service), self.service,
                len(name), name, len(secret), buffer, ctypes.byref(item))
            if status:
                raise AccountDataError("KEYCHAIN_STORE_FAILED")
        finally:
            for index in range(len(secret)):
                secret[index] = 0
            if item.value:
                self.core.CFRelease(item)

    def read(self, record_id: str) -> dict[str, str]:
        name = self._name(record_id)
        length, content, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
        try:
            status = self.security.SecKeychainFindGenericPassword(None, len(self.service), self.service,
                len(name), name, ctypes.byref(length), ctypes.byref(content), ctypes.byref(item))
            if status or not content.value or not 1 <= length.value <= 4096:
                raise AccountDataError("KEYCHAIN_READ_FAILED")
            try:
                return validate_credentials(json.loads(ctypes.string_at(content, length.value)))
            except (ValueError, TypeError):
                raise AccountDataError("KEYCHAIN_RECORD_INVALID") from None
        finally:
            if content.value:
                ctypes.memset(content, 0, length.value)
                self.security.SecKeychainItemFreeContent(None, content)
            if item.value:
                self.core.CFRelease(item)

    def delete(self, record_id: str) -> None:
        name = self._name(record_id)
        item = ctypes.c_void_p()
        try:
            status = self.security.SecKeychainFindGenericPassword(None, len(self.service), self.service,
                len(name), name, None, None, ctypes.byref(item))
            if status == -25300:  # This exact record does not exist.
                return
            if status or not item.value or self.security.SecKeychainItemDelete(item):
                raise AccountDataError("KEYCHAIN_DELETE_FAILED")
        finally:
            if item.value:
                self.core.CFRelease(item)
