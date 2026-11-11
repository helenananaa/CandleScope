"""Process-owned leases on stable lock files, separate from day publication."""

from __future__ import annotations

import errno
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


class ReadOnlyLeaseDirectory(OSError):
    """A legacy read-only archive has no lock file for this partition."""


if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _lock_file = _kernel32.LockFileEx
    _lock_file.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(_Overlapped),
    ]
    _lock_file.restype = wintypes.BOOL
    _unlock_file = _kernel32.UnlockFileEx
    _unlock_file.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(_Overlapped),
    ]
    _unlock_file.restype = wintypes.BOOL
    _FAIL_IMMEDIATELY = 0x01
    _EXCLUSIVE_LOCK = 0x02
    _LOCK_VIOLATION = 33

    def _acquire(stream: BinaryIO, *, shared: bool) -> None:
        flags = _FAIL_IMMEDIATELY if shared else _FAIL_IMMEDIATELY | _EXCLUSIVE_LOCK
        handle = msvcrt.get_osfhandle(stream.fileno())
        if not _lock_file(handle, flags, 0, 1, 0, ctypes.byref(_Overlapped())):
            error = ctypes.get_last_error()
            if error == _LOCK_VIOLATION:
                raise BlockingIOError(errno.EAGAIN, "trade partition is leased")
            raise ctypes.WinError(error)

    def _release(stream: BinaryIO) -> None:
        # Closing the handle also releases a lock if explicit unlock fails.
        _unlock_file(msvcrt.get_osfhandle(stream.fileno()), 0, 1, 0, ctypes.byref(_Overlapped()))
else:
    import fcntl

    def _acquire(stream: BinaryIO, *, shared: bool) -> None:
        mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        try:
            fcntl.flock(stream.fileno(), mode | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                raise BlockingIOError(errno.EAGAIN, "trade partition is leased") from exc
            raise

    def _release(stream: BinaryIO) -> None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def partition_lease(
    path: Path, *, shared: bool, create: bool, timeout_seconds: float = 0.0,
) -> Iterator[None]:
    """Keep the OS lease until close. The stable lock file must never be unlinked."""
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        if not create:
            raise
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = path.open("a+b")
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
                raise
            try:
                stream = path.open("rb")
            except FileNotFoundError:
                raise ReadOnlyLeaseDirectory(exc.errno, "trade lease directory is read-only") from exc
    with stream:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                _acquire(stream, shared=shared)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(0.01, remaining))
        try:
            yield
        finally:
            _release(stream)
