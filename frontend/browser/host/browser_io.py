"""Network and scheduling adapters for a single Pyodide worker."""
import asyncio
import json
from urllib.parse import urlsplit, urlunsplit

import aiohttp
import anyio.to_thread
from multidict import CIMultiDict, CIMultiDictProxy
from pyodide.ffi import create_proxy
from pyodide.http import pyfetch
from yarl import URL


def public_url(value):
    url = urlsplit(str(value))
    # The market-data-only host exposes the same public spot protocol.
    if url.hostname in {"api.binance.com", *(f"api{i}.binance.com" for i in range(1, 5))} and url.path.startswith("/api/"):
        return urlunsplit(url._replace(netloc="data-api.binance.vision"))
    if url.hostname == "stream.binance.com":
        return urlunsplit(url._replace(netloc="data-stream.binance.vision"))
    return str(value)


class FetchResponse:
    def __init__(self, response, headers):
        self.response = response
        self.status = response.status
        self.reason = response.status_text
        self.url = URL(response.url)
        self.headers = CIMultiDictProxy(CIMultiDict(headers))
        self._body = None

    async def read(self):
        if self._body is None:
            self._body = await self.response.bytes()
        return self._body

    async def text(self, encoding=None, errors="strict"):
        return (await self.read()).decode(encoding or "utf-8", errors)

    async def json(self, **_):
        return json.loads(await self.read())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def release(self):
        pass

    async def wait_for_close(self):
        pass


async def http_request(session, method, url, **options):
    target = URL(public_url(url))
    if target.scheme != "https" or method.upper() != "GET":
        raise aiohttp.ClientConnectionError("The browser host supports public HTTPS market reads")
    if options.get("params"):
        target = target.update_query(options["params"])
    timeout = options.get("timeout") or session.timeout
    total = getattr(timeout, "total", timeout)
    async with asyncio.timeout(total if isinstance(total, (int, float)) else 20):
        if any(str(name).lower() in {"authorization", "x-mbx-apikey", "ok-access-key"} for name in (options.get("headers") or {})):
            raise aiohttp.ClientConnectionError("Private exchange accounts require the desktop runtime")
        try:
            response = await pyfetch(str(target), method="GET", credentials="omit",
                                     headers={"Accept": "application/json"})
        except OSError as exc:
            raise aiohttp.ClientConnectionError(f"Browser Fetch could not reach {target.host}") from exc
        headers = response.js_response.headers
        return FetchResponse(response, [(key, headers.get(key)) for key in headers.keys()])


class PublicSocket:
    _conn = None  # CCXT optionally inspects aiohttp's private TCP receive buffer.

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def ping(self, *_):
        # The browser network stack owns RFC 6455 control frames.
        pass

    pong = ping

    def __init__(self, url):
        from js import WebSocket
        self.socket = WebSocket.new(public_url(url))
        self.socket.binaryType = "arraybuffer"
        self.opened = asyncio.get_running_loop().create_future()
        self.queue = asyncio.Queue(maxsize=1024)
        self.callbacks = []
        def opened(_):
            if not self.opened.done():
                self.opened.set_result(True)
        def message(event):
            data = event.data
            kind = aiohttp.WSMsgType.TEXT if isinstance(data, str) else aiohttp.WSMsgType.BINARY
            if not isinstance(data, str):
                from js import Uint8Array
                data = bytes(Uint8Array.new(data).to_py())
            if self.queue.full():
                self.socket.close()
            else:
                self.queue.put_nowait(aiohttp.WSMessage(kind, data, ""))
        def closed(event):
            if not self.opened.done():
                self.opened.set_exception(aiohttp.ClientConnectionError("WebSocket connection failed"))
            if self.queue.full():
                self.queue.get_nowait()
            self.queue.put_nowait(aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE, getattr(event, "code", 1006), ""))
            for name, callback in self.callbacks:
                self.socket.removeEventListener(name, callback)
                callback.destroy()
            self.callbacks.clear()
        for name, fn in (("open", opened), ("message", message), ("close", closed)):
            proxy = create_proxy(fn)
            self.callbacks.append((name, proxy))
            self.socket.addEventListener(name, proxy)

    @property
    def closed(self):
        return self.socket.readyState >= 2

    async def receive(self, timeout=None):
        if self.closed and self.queue.empty():
            return aiohttp.WSMessage(aiohttp.WSMsgType.CLOSED, None, "")
        return await asyncio.wait_for(self.queue.get(), timeout)

    async def recv(self):
        msg = await self.receive()
        if msg.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
            raise ConnectionError("Market WebSocket closed")
        return msg.data

    async def send_str(self, data):
        self.socket.send(data)

    send = send_str

    async def close(self, **_):
        self.socket.close()
        return True

    def exception(self):
        return None


async def connect(url, **_):
    sock = PublicSocket(url)
    try:
        await asyncio.wait_for(sock.opened, 12)
    except BaseException:
        await sock.close()
        raise
    return sock


def install():
    # Adapt socket operations below CandleScope and CCXT, so both retain their
    # original admission, paging, normalization and retry code.
    import websockets
    async def ws_connect(_session, url, **options):
        return await connect(url, **options)
    aiohttp.ClientSession._request = http_request
    aiohttp.ClientSession._ws_connect = ws_connect
    websockets.connect = connect

    # FastAPI runs sync dependencies through AnyIO. The interpreter already
    # owns a worker; these do not run on the DOM thread.
    async def run_sync(fn, *args, **_):
        await asyncio.sleep(0)
        return fn(*args)
    anyio.to_thread.run_sync = run_sync
