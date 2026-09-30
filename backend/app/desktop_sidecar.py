"""Desktop-owned Uvicorn process with portable graceful shutdown over stdin.

The inherited pipe is private to the parent. EOF also shuts down if the host
crashes; no network control endpoint or persistent credential is introduced.
"""
from __future__ import annotations

import argparse
import asyncio
import errno
import json
import os
import socket
import sys
import threading
import time
from collections.abc import Iterator
from typing import Any
from pathlib import Path

import uvicorn


def _parent_chunks() -> Iterator[bytes]:
    if os.name != "nt":
        while chunk := sys.stdin.buffer.read1(4096):
            yield chunk
        return

    # A blocking stdin pipe read can stall NumPy DLL initialization on Windows.
    # Poll availability and read only buffered bytes, leaving no blocked read.
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    read_file = kernel32.ReadFile
    read_file.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    read_file.restype = wintypes.BOOL
    peek_pipe = kernel32.PeekNamedPipe
    peek_pipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                          wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    peek_pipe.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    buffer = ctypes.create_string_buffer(4096)
    count = wintypes.DWORD()
    available = wintypes.DWORD()
    while peek_pipe(handle, None, 0, None, ctypes.byref(available), None):
        if available.value == 0:
            time.sleep(0.05)
            continue
        if not read_file(handle, buffer, min(len(buffer), available.value), ctypes.byref(count), None):
            break
        if count.value:
            yield buffer.raw[:count.value]
    error = ctypes.get_last_error()
    if error != 109:  # ERROR_BROKEN_PIPE is normal parent EOF.
        raise ctypes.WinError(error)


def watch_parent(server: Any) -> None:
    pending = b""
    try:
        for chunk in _parent_chunks():
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()
            if any(line.strip() == b"shutdown" for line in lines):
                break
    finally:
        server.should_exit = True


def bind_desktop_socket(host: str, port: int, *, allow_fallback: bool = True) -> socket.socket:
    """Keep the socket reserved through Uvicorn startup; never probe then rebind."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
        except OSError as error:
            if not allow_fallback:
                raise
            if error.errno not in (errno.EADDRINUSE, errno.EACCES) and getattr(error, "winerror", None) not in (10048, 10013):
                raise
            sock.bind((host, 0))
        sock.listen(128)
        sock.setblocking(False)
        return sock
    except BaseException:
        sock.close()
        raise


def serve(host: str, port: int) -> None:
    endpoint_file = os.environ.get("CANDLESCOPE_DESKTOP_ENDPOINT_FILE")
    bound_port = os.environ.get("CANDLESCOPE_DESKTOP_BOUND_PORT") if endpoint_file else None
    if bound_port:
        port = int(bound_port)
        if not 1 <= port <= 65535:
            raise ValueError("Invalid desktop session port")
    sock = bind_desktop_socket(host, port, allow_fallback=not bound_port) if endpoint_file else None
    if sock is not None:
        port = sock.getsockname()[1]
        os.environ["CANDLE_PORT"] = str(port)
        endpoint = Path(endpoint_file)
        temporary = endpoint.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps({
                "port": port,
                "instanceId": os.environ["CANDLESCOPE_DESKTOP_INSTANCE_ID"],
            }), encoding="utf-8")
            temporary.replace(endpoint)
        except BaseException:
            sock.close()
            raise
    server = uvicorn.Server(uvicorn.Config("app.main:app", host=host, port=port))
    threading.Thread(target=watch_parent, args=(server,), name="desktop-parent-pipe", daemon=True).start()

    async def run() -> None:
        try:
            await server.serve(sockets=[sock] if sock is not None else None)
        finally:
            # Uvicorn returns early if shutdown was requested during startup.
            # Finish lifespan cleanup before asyncio cancels background tasks.
            if server.started and not server.lifespan.shutdown_event.is_set():
                await server.shutdown(sockets=[sock] if sock is not None else None)

    server.config.setup_event_loop()
    try:
        asyncio.run(run())
    finally:
        if sock is not None:
            sock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    serve(args.host, args.port)
