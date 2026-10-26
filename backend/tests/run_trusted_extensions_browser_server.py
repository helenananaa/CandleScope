"""Production frontend + existing deterministic market fixture, isolated extension state."""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--port", type=int, default=18187)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "backend"))
    sys.path.insert(0, str(repo / "packages" / "candlescope-plugin-sdk" / "src"))
    origin = f"http://127.0.0.1:{args.port}"
    os.environ.update({"PHASE12_BROWSER_PLATFORM_ROOT": str(args.root / "platform"),
        "PHASE12_BROWSER_BUNDLE_DIRECTORY": str(args.root / "bundles" / uuid.uuid4().hex),
        "PHASE12_BROWSER_ORIGIN": origin, "PHASE12_BROWSER_MANAGEMENT_API_ORIGIN": f"http://localhost:{args.port}"})
    from tests.plugin_platform_phase12_browser_server import app, PLATFORM
    from app.trusted_extensions.api import create_extension_router
    from app.trusted_extensions.runtime import ExtensionHost, extension_store
    mount = app.router.routes.pop()
    app.include_router(create_extension_router())
    from fastapi import WebSocket, WebSocketDisconnect

    async def batch_stream(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"type": "connected"})
        try:
            while True:
                message = await websocket.receive_json()
                for item in message.get("items", []):
                    await websocket.send_json({"type": "subscription_ack", "client_id": item["clientId"],
                        "action": message.get("action"), "status": "subscribed", "intervals": item.get("intervals", [])})
        except WebSocketDisconnect:
            pass
    # Type is imported locally, so resolve its annotation before FastAPI inspects it.
    batch_stream.__annotations__["websocket"] = WebSocket
    app.add_api_websocket_route("/api/v1/stream/klines_batch", batch_stream)
    app.router.routes.append(mount)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            store = extension_store(application, PLATFORM.root)
            host = ExtensionHost(application, store)
            application.state.trusted_extension_host = host
            await host.prepare()
            await host.activate()
            try:
                yield
            finally:
                await host.stop()
    app.router.lifespan_context = lifespan
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
