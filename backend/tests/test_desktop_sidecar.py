from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app import desktop_sidecar


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
