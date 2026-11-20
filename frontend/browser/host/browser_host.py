"""Socket-free ASGI host. All HTTP and WS handlers belong to the desktop app."""
import asyncio
import base64
import json
import os
import logging
from pathlib import Path
from urllib.parse import urlsplit

from browser_io import install

# Each interpreter is a single worker. Use the existing in-process execution
# modes instead of spawning a metadata or indicator subprocess.
os.environ.update(
    CANDLE_DATA_DIR="/store", CANDLESCOPE_LOCAL_DATA_DIR="/store/local",
    SYMBOL_CATALOG_WORKER_ENABLED="0", INDICATOR_HISTORY_PROCESS_ENABLED="0",
    INDICATOR_REALTIME_ISOLATED="0", HISTORY_ARCHIVE_ENABLED="0",
    CANDLESCOPE_PLUGIN_HOST_ENABLED="0", CANDLESCOPE_PLUGIN_PLATFORM_V2_ENABLED="0",
    REPLAY_AGG_TRADE_ENABLED="0", BACKTEST_ENABLED="1", BACKTEST_BAR_ENABLED="0",
    BACKTEST_TRADE_TAPE_ENABLED="0", BACKTEST_STUDY_ENABLED="0",
    INGESTION_PROXY_MODE="direct",
)
install()

from app.main import app
from app.research_data.access import require_local_research_access
from fastapi import Request
from js import location as worker_location

sockets = {}
lifespan = None


# A browser-owned SQLite file is isolated by the site's origin. No TCP peer
# exists here. Only the library and history studies use this binding; desktop files and
# other local-only APIs continue to require the original local access policy.
async def browser_storage_access(request: Request):
    if (request.url.path.startswith(("/api/v1/history-studies/", "/api/v1/local/"))
            and request.scope.get("extensions", {}).get("candlescope.worker-origin") == worker_location.origin
            and request.headers.get("origin", worker_location.origin) == worker_location.origin
            and request.headers.get("sec-fetch-site", "same-origin") == "same-origin"):
        return
    return require_local_research_access(request)


app.dependency_overrides[require_local_research_access] = browser_storage_access

from library_download import ReplayLibrary, router as library_download_router
app.state.replay_library = ReplayLibrary()
app.include_router(library_download_router)


async def warm_initial_market():
    """Let the existing shared CCXT catalog finish before consumers queue bars."""
    from app.data_engine.ingestion.config import IngestionConfig
    from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
    from app.exchanges.ccxt_ext.generic import _create_exchange
    from app.exchanges.ccxt_ext.markets import get_shared_ccxt_market_tables

    config = IngestionConfig()
    client = _create_exchange(get_ccxt_catalog_entry("binance"), config, market_type="spot", websocket=False)
    tables = get_shared_ccxt_market_tables()
    try:
        await asyncio.wait_for(tables.load(client), 45)
    except Exception as exc:
        logging.getLogger(__name__).warning("Public metadata warmup unavailable: %s", exc)
    # Keep its table available until the first real chart clients have joined.
    async def release():
        await asyncio.sleep(120)
        tables.release(client)
        await client.close()
    asyncio.create_task(release())


async def start():
    global lifespan
    # Reserve the metadata dependency before the UI opens its independent WS
    # and REST consumers. A restored database can render while it warms.
    warmup = asyncio.create_task(warm_initial_market())
    app.state.replay_library.market_warmup = warmup
    try:
        await asyncio.wait_for(asyncio.shield(warmup), 1 if Path("/store/candlescope.db").exists() else 46)
    except TimeoutError:
        pass
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    if getattr(app.state, "data_manager", None) is None:
        raise RuntimeError("The desktop data engine failed to start")


def scope(kind, path, query, origin, headers):
    origin = str(worker_location.origin)
    target = urlsplit(origin)
    return {"type": kind, "asgi": {"version": "3.0", "spec_version": "2.3"},
            "scheme": target.scheme if kind == "http" else ("wss" if target.scheme == "https" else "ws"),
            "http_version": "1.1", "root_path": "", "path": path,
            "raw_path": path.encode(), "query_string": query.lstrip("?").encode(),
            "headers": [(k.lower().encode(), v.encode("latin1")) for k,v in headers],
            "server": (target.hostname, target.port or (443 if target.scheme == "https" else 80)),
            "client": ("192.0.2.1", 0), "state": {},
            "extensions": {"candlescope.worker-origin": origin}}


# Native credentials, broker connections and executable runtimes stay outside
# the public browser host, including when a frontend calls an endpoint directly.
DESKTOP_PATHS = (
    "/api/v1/readonly-accounts", "/api/v1/native", "/api/v1/external",
    "/api/v1/backtests/native", "/api/v1/backtests/external",
    "/api/v1/backtests/provider-connections", "/api/v1/backtests/continuous",
    "/api/v1/backtests/strategy-bundles", "/api/v1/backtests/strategy-revisions/python",
    "/api/v1/backtests/studies",
)


def needs_desktop(path, method="GET"):
    runs = "/api/v1/backtests/runs"
    if method == "POST" and (path in (runs, runs + "/validate") or
                             (path.startswith(runs + "/") and path.endswith(("/resume", "/clone")))):
        return True
    if path.startswith("/api/v1/backtests/strategy-revisions/") and path.endswith(("/smoke", "/runtime-receipt")):
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in DESKTOP_PATHS)


def http_task(message, body, emit):
    return asyncio.create_task(http(message, body, emit))


async def http(message, body, emit):
    req = json.loads(message)
    if needs_desktop(req["path"], req["method"]):
        detail = "此操作需要桌面运行时，请下载 CandleScope 桌面版。"
        body = json.dumps({"detail": detail, "error": {"code": "DESKTOP_REQUIRED", "message": detail}}, ensure_ascii=False).encode()
        return json.dumps({"status": 501, "headers": [["content-type", "application/json"]],
                           "body": base64.b64encode(body).decode()})
    incoming = scope("http", req["path"], req["query"], req["origin"], req["headers"])
    incoming["method"] = req["method"]
    result = {"status": 500, "headers": []}
    content = bytearray()
    streaming = False
    offset = 0
    received = False

    async def receive():
        nonlocal offset, received
        if received:
            await asyncio.Future()
        # File imports consume the original ASGI body stream. Move only the
        # current chunk into WASM memory; no base64 copy of the entire upload.
        end = min(offset + 256 * 1024, body.length)
        chunk = bytes(body.subarray(offset, end).to_py())
        offset = end
        received = end == body.length
        return {"type": "http.request", "body": chunk, "more_body": not received}

    async def send(event):
        nonlocal streaming
        if event["type"] == "http.response.start":
            result["status"] = event["status"]
            result["headers"] = [(k.decode("latin1"),v.decode("latin1")) for k,v in event["headers"]]
            streaming = any(k == "content-type" and v.split(";", 1)[0] in ("text/event-stream", "application/x-ndjson",
                                      "application/vnd.candlescope.local-project+zip") for k, v in result["headers"])
            if streaming:
                emit(json.dumps({"type": "start", **result}))
        elif event["type"] == "http.response.body":
            chunk = event.get("body", b"")
            if streaming:
                if chunk:
                    emit(json.dumps({"type": "chunk", "body": base64.b64encode(chunk).decode()}))
            else:
                content.extend(chunk)
    await app(incoming, receive, send)
    if streaming:
        return json.dumps({"type": "end"})
    result["body"] = base64.b64encode(content).decode()
    return json.dumps(result)


def open_socket(identity):
    queue = sockets[identity] = asyncio.Queue()
    queue.put_nowait({"type": "websocket.connect"})


async def websocket(identity, message, emit):
    req = json.loads(message)
    if needs_desktop(req["path"]):
        sockets.pop(identity, None)
        emit(json.dumps({"type": "websocket.close", "code": 1008, "reason": "Desktop runtime required"}))
        return
    incoming = scope("websocket", req["path"], req["query"], req["origin"], [])
    incoming["subprotocols"] = []
    queue = sockets[identity]
    async def send(event):
        emit(json.dumps(event))
    try:
        await app(incoming, queue.get, send)
    finally:
        sockets.pop(identity, None)


def stats():
    """Open application sockets and pending tasks, for page-switch acceptance."""
    return json.dumps({"sockets": len(sockets), "tasks": len(asyncio.all_tasks(asyncio.get_event_loop()))})


def ws_event(identity, payload):
    queue = sockets.get(identity)
    if queue is not None:
        queue.put_nowait(json.loads(payload))
