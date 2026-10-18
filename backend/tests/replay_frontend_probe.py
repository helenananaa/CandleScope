"""Shared real-HTTP / Node probe for replay source and UI integration tests."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import uvicorn

from tests.test_replay_v2_training_api import _app

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


async def frontend_probe(service, tmp_path, cases, script="scripts/replay-history-service-probe.ts"):
    # Real production routes and parser/transport in separate Python/Node
    # processes; only the upstream market provider is a deterministic fixture.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(
        uvicorn.Config(_app(service), log_level="error", lifespan="off")
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    process = None
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        request = tmp_path / "frontend-probe.json"
        request.write_text(json.dumps({"origin": origin, "cases": cases}))
        process = await asyncio.create_subprocess_exec(
            "node",
            "--import",
            "./scripts/monaco-esm-loader.mjs",
            "--import",
            "tsx",
            script,
            str(request),
            cwd=FRONTEND,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=45)
        assert process.returncode == 0, stderr.decode()
        return json.loads(stdout)
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        sock.close()
