from __future__ import annotations

import os
import socket
import json
import time
import urllib.request
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app import desktop_sidecar


def test_occupied_preferred_port_falls_back_without_disturbing_listener():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        preferred = occupied.getsockname()[1]
        with desktop_sidecar.bind_desktop_socket("127.0.0.1", preferred) as selected:
            actual = selected.getsockname()[1]
            assert actual != preferred
            assert actual > 0
            with socket.create_connection(("127.0.0.1", preferred), timeout=2):
                connection, _ = occupied.accept()
                connection.close()
            with socket.socket() as competitor:
                with pytest.raises(OSError):
                    competitor.bind(("127.0.0.1", actual))


def test_available_preferred_port_is_retained():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        preferred = probe.getsockname()[1]
    with desktop_sidecar.bind_desktop_socket("127.0.0.1", preferred) as selected:
        assert selected.getsockname()[1] == preferred


def test_invalid_bind_request_is_not_silently_replaced():
    with pytest.raises((OverflowError, OSError)):
        desktop_sidecar.bind_desktop_socket("127.0.0.1", 65536)


def test_restart_refuses_an_occupied_session_port_without_announcing_another(tmp_path, monkeypatch):
    endpoint = tmp_path / "restart.json"
    monkeypatch.setenv("CANDLESCOPE_DESKTOP_ENDPOINT_FILE", str(endpoint))
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        monkeypatch.setenv("CANDLESCOPE_DESKTOP_BOUND_PORT", str(occupied.getsockname()[1]))
        with pytest.raises(OSError):
            desktop_sidecar.serve("127.0.0.1", 0)
        assert not endpoint.exists()


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_session_port_cannot_fall_back(tmp_path, monkeypatch, port):
    monkeypatch.setenv("CANDLESCOPE_DESKTOP_ENDPOINT_FILE", str(tmp_path / "endpoint.json"))
    monkeypatch.setenv("CANDLESCOPE_DESKTOP_BOUND_PORT", port)
    with pytest.raises(ValueError):
        desktop_sidecar.serve("127.0.0.1", 0)


@pytest.mark.parametrize("restart", [False, True])
def test_sidecar_serves_on_announced_socket_when_preferred_port_is_occupied(tmp_path, restart):
    endpoint = tmp_path / "endpoint.json"
    session_port = ""
    if restart:
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            session_port = str(available.getsockname()[1])
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        preferred = occupied.getsockname()[1]
        code = """
import json, os, uvicorn
from app.desktop_sidecar import serve
async def app(scope, receive, send):
    if scope['type'] == 'lifespan':
        while True:
            event = await receive()
            if event['type'] == 'lifespan.startup':
                await send({'type': 'lifespan.startup.complete'})
            else:
                await send({'type': 'lifespan.shutdown.complete'})
                return
    else:
        body = json.dumps({'desktop_instance_id': os.environ['CANDLESCOPE_DESKTOP_INSTANCE_ID']}).encode()
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': body})
original = uvicorn.Config
uvicorn.Config = lambda _, **options: original(app, **options)
serve('127.0.0.1', int(os.environ['TEST_PREFERRED_PORT']))
"""
        child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env={**os.environ, "TEST_PREFERRED_PORT": str(preferred),
                                      "CANDLESCOPE_DESKTOP_BOUND_PORT": session_port,
                                      "CANDLESCOPE_DESKTOP_ENDPOINT_FILE": str(endpoint),
                                      "CANDLESCOPE_DESKTOP_INSTANCE_ID": "test-instance"})
        try:
            deadline = time.monotonic() + 10
            result = None
            while time.monotonic() < deadline and child.poll() is None:
                if endpoint.exists():
                    announcement = json.loads(endpoint.read_text(encoding="utf-8"))
                    assert announcement["instanceId"] == "test-instance"
                    assert announcement["port"] != preferred
                    if restart:
                        assert announcement["port"] == int(session_port)
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{announcement['port']}/health", timeout=1) as response:
                            result = json.load(response)
                        break
                    except OSError:
                        pass
                time.sleep(0.05)
            assert result == {"desktop_instance_id": "test-instance"}
            output, error = child.communicate(b"shutdown\n", timeout=10)
            assert child.returncode == 0, (output + error).decode(errors="replace")
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()


@pytest.mark.parametrize("chunks", [[b"shut", b"down\n"], [], [b"ignored\n"]])
def test_private_pipe_command_and_parent_eof_request_shutdown(monkeypatch, chunks):
    server = SimpleNamespace(should_exit=False)
    monkeypatch.setattr(desktop_sidecar, "_parent_chunks", lambda: iter(chunks))
    desktop_sidecar.watch_parent(server)
    assert server.should_exit


@pytest.mark.skipif(os.name != "nt", reason="Windows CRT descriptor lock regression")
def test_parent_monitor_does_not_block_numpy_dll_initialization():
    code = """
import threading
from types import SimpleNamespace
from app.desktop_sidecar import watch_parent
threading.Thread(target=watch_parent, args=(SimpleNamespace(should_exit=False),), daemon=True).start()
import numpy
print('numpy ready', flush=True)
"""
    child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        child.wait(timeout=15)
        output, error = child.communicate()
        assert child.returncode == 0, error.decode(errors="replace")
        assert b"numpy ready" in output
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()
