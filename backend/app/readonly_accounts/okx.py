"""CCXT's OKX transport restricted to explicit read-only REST and WS operations."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any
from urllib.parse import parse_qs, urlsplit

import aiohttp
from aiohttp_socks import ProxyConnector
from ccxt.pro.okx import okx as CcxtOkx

from .normalization import AccountDataError

REST_PATHS = {
    "public": frozenset({"public/instruments", "public/time"}),
    "private": frozenset({"account/config", "account/balance", "account/positions",
                           "account/bills-archive", "trade/fills-history", "trade/orders-pending",
                           "trade/orders-history-archive"}),
}
SWAP_PATHS = frozenset({"public/instruments", "account/positions", "trade/fills-history",
                        "trade/orders-pending", "trade/orders-history-archive"})
CHANNELS = frozenset({"orders", "positions", "account"})
# Keep only documented, bounded provider codes. Raw OKX messages can contain
# an API key or an IP address and must never become application diagnostics.
OKX_AUTH_CODES = frozenset({"50100", "50101", "50102", "50103", "50104", "50105",
                            "50106", "50107", "50110", "50111", "50112", "50113",
                            "50114", "50119"})
OKX_AUTH_ERRORS = frozenset("OKX_AUTH_" + code for code in OKX_AUTH_CODES)


def readonly_session(*, connector, loop, trust_env: bool):
    # aiohttp redirects retain custom OK-ACCESS-* headers. Abort before a
    # redirect is followed, for both REST requests and the WS handshake.
    trace = aiohttp.TraceConfig()
    async def deny_redirect(*_args):
        raise AccountDataError("READONLY_REDIRECT_DENIED")
    trace.on_request_redirect.append(deny_redirect)
    return aiohttp.ClientSession(connector=connector,loop=loop,trust_env=trust_env,trace_configs=[trace])


def validate_rest(path: str, api: Any, method: str, params: Mapping[str, Any]) -> None:
    if not isinstance(api, str) or method != "GET" or path not in REST_PATHS.get(api, ()):
        raise AccountDataError("READONLY_OPERATION_DENIED")
    if path in SWAP_PATHS and params.get("instType") != "SWAP":
        raise AccountDataError("PERPETUAL_SCOPE_REQUIRED")


def validate_ws(url: str, message: Any) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "wss" or parsed.hostname != "ws.okx.com" or parsed.port != 8443
            or parsed.path != "/ws/v5/private" or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise AccountDataError("READONLY_WS_DESTINATION_DENIED")
    if message is None:
        return
    if not isinstance(message, Mapping) or message.get("op") not in {"login", "subscribe", "unsubscribe"}:
        raise AccountDataError("READONLY_WS_OPERATION_DENIED")
    args = message.get("args")
    if not isinstance(args, list) or not 1 <= len(args) <= 3:
        raise AccountDataError("READONLY_WS_ARGUMENTS_DENIED")
    if message["op"] == "login":
        if len(args) != 1 or not isinstance(args[0], Mapping) or set(args[0]) != {"apiKey", "passphrase", "timestamp", "sign"}:
            raise AccountDataError("READONLY_WS_ARGUMENTS_DENIED")
        return
    for arg in args:
        if (not isinstance(arg, Mapping) or arg.get("channel") not in CHANNELS
                or set(arg) - {"channel", "instType", "instId"}
                or (arg.get("channel") != "account" and arg.get("instType") != "SWAP")):
            raise AccountDataError("READONLY_WS_CHANNEL_DENIED")


class ReadOnlyOkx(CcxtOkx):
    """Network boundary, not just an application convention about method names."""

    def __init__(self, credentials: Mapping[str, str], *, proxy: str | None = None,
                 trust_environment: bool = True, observe: Callable[[dict], None] | None = None):
        config: dict[str, Any] = {
            "apiKey": credentials["apiKey"], "secret": credentials["secret"],
            "password": credentials["password"], "enableRateLimit": True, "newUpdates": True,
            "timeout": 15_000, "aiohttp_trust_env": trust_environment,
            "options": {"defaultType": "swap", "fetchMarkets": {"types": ["swap"]},
                        "fetchCurrencies": False},
        }
        if proxy:
            if proxy.startswith(("socks4://", "socks5://", "socks5h://")):
                config.update(socksProxy=proxy, wsSocksProxy=proxy)
            else:
                config.update(httpsProxy=proxy, wssProxy=proxy)
        super().__init__(config)
        # CCXT's debug logger includes signed request headers. This instance
        # reports only bounded application error codes through its owner.
        self.logger = logging.Logger("candlescope.readonly.transport")
        self.logger.disabled = True
        self.logger.propagate = False
        self._observe = observe

    def open(self):
        # Keep CCXT's loop, throttler and verified TLS setup, while owning the
        # session construction so every transport receives the redirect guard.
        own = self.own_session
        self.own_session = False
        try:
            super().open()
        finally:
            self.own_session = own
        if self.session is None:
            self.tcp_connector = aiohttp.TCPConnector(ssl=self.ssl_context,loop=self.asyncio_loop,enable_cleanup_closed=True)
            self.session = readonly_session(connector=self.tcp_connector,loop=self.asyncio_loop,trust_env=self.aiohttp_trust_env)

    def get_socks_proxy_session(self, proxy):
        if self.socks_proxy_sessions is None:
            self.socks_proxy_sessions = {}
        if proxy not in self.socks_proxy_sessions:
            self.open()
            remote_dns = proxy.startswith("socks5h://")
            self.aiohttp_socks_connector = ProxyConnector.from_url(proxy.replace("socks5h://", "socks5://"),
                ssl=self.ssl_context,loop=self.asyncio_loop,enable_cleanup_closed=True,rdns=True if remote_dns else None)
            self.socks_proxy_sessions[proxy] = readonly_session(connector=self.aiohttp_socks_connector,
                loop=self.asyncio_loop,trust_env=self.aiohttp_trust_env)
        return self.socks_proxy_sessions[proxy]

    async def request(self, path, api="public", method="GET", params=None, headers=None, body=None, config=None):
        validate_rest(path, api, method, params or {})
        if body is not None:
            raise AccountDataError("READONLY_OPERATION_DENIED")
        return await super().request(path, api, method, params or {}, headers, body, config or {})

    def handle_errors(self, httpCode, reason, url, method, headers, body, response, requestHeaders, requestBody):
        code = response.get("code") if isinstance(response, Mapping) else None
        if isinstance(code, str) and code in OKX_AUTH_CODES:
            raise AccountDataError("OKX_AUTH_" + code)
        return super().handle_errors(httpCode, reason, url, method, headers, body, response, requestHeaders, requestBody)

    async def fetch(self, url, method="GET", headers=None, body=None):
        parsed = urlsplit(url)
        allowed = {"/api/v5/" + path for paths in REST_PATHS.values() for path in paths}
        if (method != "GET" or body is not None or parsed.scheme != "https"
                or parsed.hostname != "www.okx.com" or parsed.port not in {None, 443}
                or parsed.path not in allowed or parsed.username or parsed.password or parsed.fragment):
            raise AccountDataError("READONLY_DESTINATION_DENIED")
        path = parsed.path.removeprefix("/api/v5/")
        api = "private" if path in REST_PATHS["private"] else "public"
        query = parse_qs(parsed.query)
        validate_rest(path, api, method, {key: values[0] if len(values) == 1 else values for key, values in query.items()})
        return await super().fetch(url, method, headers, body)

    async def close(self):
        # CCXT 4.5.60 otherwise closes WS but keeps its REST connector alive.
        try:
            await super().close(clean_instance_data=True)
        finally:
            self.apiKey = self.secret = self.password = ""

    def watch(self, url, message_hash, message=None, subscribe_hash=None, subscription=None):
        validate_ws(url, message)
        return super().watch(url, message_hash, message, subscribe_hash, subscription)

    def watch_multiple(self, url, message_hashes, message=None, subscribe_hashes=None, subscription=None):
        validate_ws(url, message)
        return super().watch_multiple(url, message_hashes, message, subscribe_hashes, subscription)

    def handle_message(self, client, message):
        if isinstance(message, dict) and isinstance(message.get("arg"), dict):
            if message["arg"].get("channel") in CHANNELS and isinstance(message.get("data"), list):
                if self._observe is not None:
                    self._observe(message)
        return super().handle_message(client, message)


def account_identity(response: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(response, Mapping) or response.get("code") != "0":
        raise AccountDataError("ACCOUNT_CONFIGURATION_INVALID")
    rows = response.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise AccountDataError("ACCOUNT_CONFIGURATION_INVALID")
    row = rows[0]
    permission = row.get("perm")
    if not isinstance(permission, str) or {item.strip() for item in permission.split(",")} != {"read_only"}:
        raise AccountDataError("READONLY_KEY_REQUIRED")
    if row.get("posMode") != "long_short_mode":
        raise AccountDataError("HEDGE_ACCOUNT_REQUIRED")
    uid = row.get("uid")
    if not isinstance(uid, str) or not uid.isascii() or not uid.isdigit() or len(uid) > 32:
        raise AccountDataError("ACCOUNT_IDENTITY_INVALID")
    return {"venueUid": uid, "positionMode": "long_short_mode", "accountLevel": str(row.get("acctLv") or "")}
