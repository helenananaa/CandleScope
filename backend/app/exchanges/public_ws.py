"""Public WS physical admission, independent of logical subscription leases.

Binance spot: 300 attempts/5 min/IP and 5 incoming frames/s/connection.
OKX: 3 attempts/s/IP and 480 control requests/hour/connection.
Binance derivatives and unqualified venues retain a conservative local pacing
fallback; it is not advertised as a complete model of their server limits.
"""
from __future__ import annotations

import asyncio
import itertools
import json
from dataclasses import replace
from typing import Any

from .public_admission import PublicDemand, TrafficClass, current_demand, get_public_admission
from .rate_limits import HistoricalRequest, RateLimitDeferred, RateLimitRule, scope_rate_limit_rule

_connection_ids = itertools.count(1)


def connection_rules(exchange: str, egress: str | None) -> list[RateLimitRule]:
    capacity, window = (3, 1.0) if exchange == "okx" else (300, 300.0)
    rules = [
        RateLimitRule(f"{exchange}_ws_connect_window", f"{exchange}:ws_connect:ip",
                      capacity, window, algorithm="sliding_window", max_concurrency=2),
        RateLimitRule(f"{exchange}_ws_connect_pacing", f"{exchange}:ws_connect_pacing:ip",
                      1, 0.5 if exchange == "okx" else 1.05, max_concurrency=2),
    ]
    return [scope_rate_limit_rule(rule, egress) for rule in rules]


async def admit_connection(exchange: str, market_type: str, egress: str | None) -> Any:
    demand = replace(current_demand(), traffic_class=TrafficClass.RECOVERY,
                     purpose="ws_connect", defer=False, alive=None)
    return await get_public_admission().acquire(
        connection_rules(exchange, egress),
        HistoricalRequest(exchange, market_type, "ws_connect", "", egress_group=egress),
        demand=demand,
    )


class AdmittedWebSocket:
    """Delegate a socket while gating outgoing frames once per physical socket."""

    def __init__(self, connection: Any, exchange: str, market_type: str,
                 egress: str | None, *, native: bool = False) -> None:
        self._connection = connection
        self._exchange, self._market_type, self._egress = exchange, market_type, egress
        self._native = native
        self._id = next(_connection_ids)
        self._closing = False
        self._senders: set[asyncio.Task[Any]] = set()
        self._keys: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def __aiter__(self) -> Any:
        return self._connection.__aiter__()

    async def _send(self, method: str, payload: Any = None, *args: Any, **kwargs: Any) -> Any:
        if self._closing:
            raise ConnectionError("websocket closed while waiting for control admission")
        task = asyncio.current_task()
        scheduler = get_public_admission()
        base = f"{self._exchange}:ws_control:connection:{self._id}"
        heartbeat = method in {"ping", "pong"} or payload in ("ping", "pong")
        rules = []
        if self._exchange == "okx":
            if not heartbeat:
                value = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
                if isinstance(value, dict) and value.get("op") in {"subscribe", "unsubscribe", "login"}:
                    rules.append(RateLimitRule("okx_ws_control_hour", base + ":hour", 480, 3600,
                                               algorithm="sliding_window"))
            rules.append(RateLimitRule("okx_ws_control_pacing", base + ":pace", 1, 0.11))
        else:
            # Native websockets handles server pongs below send(); leave one
            # slot per second for that protocol traffic. CCXT ping/pong frames
            # pass through this wrapper and share the full five-frame window.
            capacity = 4 if self._native else 5
            rules.append(RateLimitRule("ws_outgoing_frames", base, capacity, 1,
                                       algorithm="sliding_window"))
        rules = [scope_rate_limit_rule(rule, self._egress) for rule in rules]
        self._keys.update(rule.bucket_key for rule in rules)
        permit = None
        self._senders.add(task)
        try:
            permit = await scheduler.acquire(rules, HistoricalRequest(
                self._exchange, self._market_type, "ws_control", "", egress_group=self._egress,
            ), demand=PublicDemand(TrafficClass.REQUIRED if heartbeat else TrafficClass.RECOVERY,
                                   purpose="ws_heartbeat" if heartbeat else "ws_control"))
            if self._closing:
                raise ConnectionError("websocket closed before control send")
            result = await getattr(self._connection, method)(payload, *args, **kwargs)
            permit.finish(status_code=200)
            return result
        finally:
            if permit is not None and not permit.settled:
                permit.finish(response_unknown=True)
            self._senders.discard(task)

    async def send(self, payload: Any, *args: Any, **kwargs: Any) -> Any:
        return await self._send("send", payload, *args, **kwargs)

    async def send_str(self, payload: Any, *args: Any, **kwargs: Any) -> Any:
        return await self._send("send_str", payload, *args, **kwargs)

    async def ping(self, payload: Any = b"") -> Any:
        return await self._send("ping", payload)

    async def pong(self, payload: Any = b"") -> Any:
        return await self._send("pong", payload)

    async def close(self, *args: Any, **kwargs: Any) -> Any:
        self._closing = True
        pending = [task for task in self._senders if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        try:
            return await self._connection.close(*args, **kwargs)
        finally:
            get_public_admission().manager.release_ephemeral_buckets(self._keys)


def install_ccxt_ws_admission(client: Any, exchange: str, market_type: str,
                              egress: str | None) -> Any:
    if getattr(client, "_candlescope_public_admission", False):
        return client
    client._candlescope_public_admission = True
    original_open, original_create, original_close = client.open, client.create_connection, client.close
    original_send = client.send
    connecting: set[asyncio.Task[Any]] = set()
    closed = False
    permit = None

    async def create_connection(session: Any) -> Any:
        try:
            connection = await original_create(session)
            return AdmittedWebSocket(connection, exchange, market_type, egress)
        except BaseException as exc:
            if permit is not None:
                status = getattr(exc, "status", None)
                permit.finish(status_code=status, response_unknown=status is None)
            raise

    async def open_connection(session: Any, backoff_delay: float = 0) -> None:
        nonlocal permit
        task = asyncio.current_task()
        connecting.add(task)
        attempt = None
        try:
            if closed:
                return
            if backoff_delay:
                await asyncio.sleep(backoff_delay)
            # Wait before CCXT starts its network timeout or opens a socket.
            while not closed:
                try:
                    attempt = await admit_connection(exchange, market_type, egress)
                    break
                except RateLimitDeferred as deferred:
                    # Queue pressure is not a transport failure. Keep the
                    # single physical connect owner, outside network timeout.
                    await asyncio.sleep(deferred.retry_after_seconds)
            permit = attempt
            if closed:
                return
            await original_open(session, 0)
            attempt.finish(status_code=200 if client.isConnected else None,
                          response_unknown=not client.isConnected)
        finally:
            if attempt is not None and not attempt.settled:
                attempt.finish(response_unknown=True)
            connecting.discard(task)

    async def close_connection(*args: Any, **kwargs: Any) -> Any:
        nonlocal closed
        closed = True
        if not client.connected.done():
            client.connected.cancel()
        pending = [task for task in connecting if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        try:
            return await original_close(*args, **kwargs)
        finally:
            if isinstance(client.connection, AdmittedWebSocket):
                await client.connection.close()

    async def send_message(*args: Any, **kwargs: Any) -> Any:
        if closed:
            # Pinned CCXT schedules subscription sends even from a canceled
            # connected Future's callback. Do not revive an old generation.
            raise asyncio.CancelledError
        return await original_send(*args, **kwargs)

    client.open, client.create_connection, client.close = open_connection, create_connection, close_connection
    client.send = send_message
    return client
