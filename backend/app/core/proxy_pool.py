"""Public-market-data routes, shared egress budgets and bounded health feedback.

Routes are immutable request context. Selection precedes quota reservation;
credentials never appear in the operational snapshot. Private trading does not
use this pool.
"""
from __future__ import annotations

import asyncio
import re
import time
import weakref
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit


def redact_proxy_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError:
        return "(invalid proxy)"
    if not hostname:
        return "(invalid proxy)"
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"{parsed.scheme}://{host}" + (f":{port}" if port else "")


def normalize_proxy_pool(routes: list[dict] | None, strategy: str = "failover") -> tuple[list[dict], str]:
    if strategy not in {"failover", "balanced"}:
        raise ValueError("proxy strategy must be failover or balanced")
    if not isinstance(routes or [], list) or len(routes or []) > 16:
        raise ValueError("at most 16 proxy routes are supported")
    result: list[dict] = []
    ids: set[str] = set()
    url_groups: dict[str, str] = {}
    for raw in routes or []:
        if not isinstance(raw, dict):
            raise ValueError("invalid proxy route")
        route_id = str(raw.get("id", "")).strip()
        group = str(raw.get("egress_group") or "shared").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", route_id) or route_id in ids:
            raise ValueError("proxy route ids must be unique, 1-64 letters, digits, underscores or hyphens")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", group):
            raise ValueError("invalid proxy egress group")
        url = str(raw.get("url", "")).strip()
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port
        except ValueError:
            valid = False
        if not valid or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("proxy routes require an HTTP(S) proxy URL with an explicit port")
        if url in url_groups and url_groups[url] != group:
            raise ValueError("the same proxy address must use the same egress group")
        url_groups[url] = group
        exchanges = raw.get("exchanges") or []
        if not isinstance(exchanges, list) or len(exchanges) > 128:
            raise ValueError("invalid proxy exchange allowlist")
        exchanges = sorted({str(value).strip().lower() for value in exchanges})
        if any(not re.fullmatch(r"[a-z0-9_-]{1,64}", value) for value in exchanges):
            raise ValueError("invalid exchange id")
        concurrency = raw.get("max_concurrency", 4)
        if not isinstance(concurrency, int) or isinstance(concurrency, bool) or not 1 <= concurrency <= 32:
            raise ValueError("proxy concurrency must be between 1 and 32")
        ws_capacity = raw.get("max_ws_subscriptions", 64)
        if not isinstance(ws_capacity, int) or isinstance(ws_capacity, bool) or not 1 <= ws_capacity <= 4096:
            raise ValueError("proxy websocket subscription capacity must be between 1 and 4096")
        if not isinstance(raw.get("enabled", True), bool):
            raise ValueError("proxy enabled must be a boolean")
        result.append({
            "id": route_id, "name": str(raw.get("name") or route_id).strip()[:80],
            "url": url, "egress_group": group, "enabled": bool(raw.get("enabled", True)),
            "exchanges": exchanges, "max_concurrency": concurrency,
            "max_ws_subscriptions": ws_capacity,
        })
        ids.add(route_id)
    return result, strategy


@dataclass(frozen=True, slots=True)
class ProxyRoute:
    id: str
    name: str
    url: str
    egress_group: str
    max_concurrency: int
    max_ws_subscriptions: int = 64

    def bind(self, config: Any) -> Any:
        # A clone prevents one request changing the proxy under another request
        # or a live CCXT websocket. Runtime keys already include proxy URL.
        return replace(config, proxy_mode="custom", http_proxy=self.url,
                       proxy_routes=[], proxy_route_id=self.id,
                       proxy_egress_group=self.egress_group)


@dataclass(slots=True)
class ProxyWsLease:
    """One owned session; multiplexed and duplicate descriptors share capacity."""
    token: str
    route: ProxyRoute
    keys: tuple[tuple[str, str, str], ...]
    kind: str
    queue_size: int = 0
    queue_capacity: int = 0


@dataclass(slots=True)
class _Health:
    failures: int = 0
    successes: int = 0
    latency_ms: float = 250.0
    retry_at: float = 0.0
    last_status: int | None = None
    latency_samples: int = 0


def ws_payload_bytes(payload: Any) -> int:
    """Delivered application payload bytes, excluding wire/compression overhead."""
    if isinstance(payload, str):
        return len(payload.encode("utf-8"))
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return len(payload)
    return 0


@dataclass(slots=True)
class _WsTraffic:
    # Fixed 30-second window; at most one aggregate per monotonic second.
    buckets: deque = field(default_factory=lambda: deque(maxlen=30))
    messages: int = 0
    payload_bytes: int = 0
    disconnects: int = 0
    last_message_at: float | None = None

    def add(self, now: float, size: int = 0, *, disconnected: bool = False) -> None:
        second = int(now)
        if not self.buckets or self.buckets[-1][0] != second:
            self.buckets.append([second, 0, 0, 0])
        bucket = self.buckets[-1]
        if disconnected:
            bucket[3] += 1
            self.disconnects += 1
        else:
            bucket[1] += 1
            bucket[2] += size
            self.messages += 1
            self.payload_bytes += size
            self.last_message_at = now

    def snapshot(self, now: float) -> dict:
        while self.buckets and self.buckets[0][0] <= int(now) - 30:
            self.buckets.popleft()
        return {"window_seconds": 30, "messages_per_second": sum(b[1] for b in self.buckets) / 30,
                "payload_bytes_per_second": sum(b[2] for b in self.buckets) / 30,
                "messages_total": self.messages, "payload_bytes_total": self.payload_bytes,
                "disconnects_total": self.disconnects, "disconnects_recent": sum(b[3] for b in self.buckets),
                "last_message_age_seconds": max(0, now - self.last_message_at)
                if self.last_message_at is not None else None}


class ProxyPool:
    def __init__(self) -> None:
        self._health: dict[tuple[str, str, str], _Health] = {}
        self._active: dict[str, int] = {}
        self._ws_preferred: dict[str, str] = {}
        self._ws_leases: dict[str, ProxyWsLease] = {}
        self._ws_load: dict[str, dict[tuple[str, str, str], int]] = {}
        self._ws_history: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self._ws_connected: set[str] = set()
        self._ws_traffic: OrderedDict[str, _WsTraffic] = OrderedDict()

    def record_ws_traffic(self, route: ProxyRoute | str | None, payload: Any = None,
                          *, disconnected: bool = False) -> None:
        if route is None:
            return
        url = route.url if isinstance(route, ProxyRoute) else route
        traffic = self._ws_traffic.setdefault(url, _WsTraffic())
        self._ws_traffic.move_to_end(url)
        # Bound retained observations when proxy configurations change repeatedly.
        while len(self._ws_traffic) > 128:
            self._ws_traffic.popitem(last=False)
        traffic.add(time.monotonic(), ws_payload_bytes(payload), disconnected=disconnected)

    def observe_ws_queue(self, lease: ProxyWsLease | None, size: int, capacity: int) -> None:
        if lease is not None and self._ws_leases.get(lease.token) is lease:
            lease.queue_size = max(0, size)
            lease.queue_capacity = max(0, capacity)

    def record_ws_receive(self, lease: ProxyWsLease, payload: Any) -> None:
        if self._ws_leases.get(lease.token) is lease:
            self.record_ws_traffic(lease.route, payload)

    def ws_traffic(self, url: str, now: float | None = None) -> dict:
        result = (self._ws_traffic.get(url) or _WsTraffic()).snapshot(
            time.monotonic() if now is None else now)
        leases = [lease for lease in self._ws_leases.values() if lease.route.url == url]
        result.update(queue_size=sum(lease.queue_size for lease in leases),
                      queue_capacity=sum(lease.queue_capacity for lease in leases),
                      queue_pressure=max((lease.queue_size / lease.queue_capacity for lease in leases
                                          if lease.queue_capacity), default=0))
        return result

    def routes(self, config: Any, exchange: str) -> list[ProxyRoute]:
        if getattr(config, "proxy_mode", "system") != "pool":
            return []
        values, _ = normalize_proxy_pool(getattr(config, "proxy_routes", []),
                                        getattr(config, "proxy_strategy", "failover"))
        routes = [ProxyRoute(value["id"], value["name"], value["url"],
                             value["egress_group"], value["max_concurrency"], value["max_ws_subscriptions"])
                  for value in values if value["enabled"] and
                  (not value["exchanges"] or exchange in value["exchanges"])]
        if not routes:
            raise ValueError(f"no enabled proxy route for {exchange}")
        return routes

    def _refresh_ws_circuits(self, routes: list[ProxyRoute], exchange: str) -> None:
        from app.exchanges.rate_limits import get_shared_rate_limit_manager
        now = time.monotonic()
        circuits = get_shared_rate_limit_manager().circuit_snapshot()
        for route in routes:
            circuit = circuits.get(f"{exchange}:ip:egress={route.egress_group}", {})
            if circuit.get("open"):
                health = self.health(route, exchange, "ws")
                health.retry_at = max(health.retry_at, now + circuit["cooldown_remaining_seconds"])

    @staticmethod
    def _ws_keys(descriptors: list[Any]) -> tuple[tuple[str, str, str], ...]:
        return tuple(sorted({(item.exchange, item.market_type, item.key) for item in descriptors}))

    @staticmethod
    def _ws_deferred(route: ProxyRoute, reason: str, wait: float):
        from app.exchanges.rate_limits import RateLimitAdmission, RateLimitDeferred
        wait = max(0.05, wait)
        return RateLimitDeferred(RateLimitAdmission(
            False, f"proxy:{route.id}:ws", 1, reason, wait,
            time.monotonic() + wait, int((time.time() + wait) * 1000), "proxy_ws",
        ))

    def acquire_ws(self, config: Any, descriptors: list[Any], *, kind: str = "native",
                   avoid_url: str | None = None) -> ProxyWsLease | None:
        if getattr(config, "proxy_mode", "system") != "pool":
            return None
        keys = self._ws_keys(descriptors)
        if not keys or len({key[:2] for key in keys}) != 1:
            raise ValueError("a websocket lease requires descriptors from one exchange and market")
        exchange = keys[0][0]
        routes = self.routes(config, exchange)
        self._refresh_ws_circuits(routes, exchange)
        now = time.monotonic()
        available = []
        waits = []
        for index, route in enumerate(routes):
            load = self._ws_load.get(route.url, {})
            added = sum(key not in load for key in keys)
            health = self.health(route, exchange, "ws")
            wait = max(0, health.retry_at - now)
            if len(load) + added > route.max_ws_subscriptions:
                waits.append((max(0.25, wait), index, route, "route_capacity"))
            elif wait > 0:
                waits.append((wait, index, route, "route_cooldown"))
            else:
                available.append((index, route, len(load)))
        if not available:
            wait, _index, route, reason = min(waits, key=lambda item: item[:2])
            raise self._ws_deferred(route, reason, wait)
        alternatives = [item for item in available if item[1].url != avoid_url]
        if alternatives:
            available = alternatives
        # Reuse the active descriptor's route before remembered placement.
        preferred = next((route.url for _, route, _ in available
                          if any(key in self._ws_load.get(route.url, {}) for key in keys)), None)
        remembered = next((self._ws_history[key] for key in keys if key in self._ws_history), None)
        if getattr(config, "proxy_strategy", "failover") == "failover":
            preferred = preferred or remembered or self._ws_preferred.get(exchange)
            chosen = min(available, key=lambda item: (item[1].url != preferred, item[0]))
        else:
            traffic = {route.url: self.ws_traffic(route.url, now) for _, route, _ in available}
            max_messages = max((row["messages_per_second"] for row in traffic.values()), default=0)
            max_bytes = max((row["payload_bytes_per_second"] for row in traffic.values()), default=0)

            def pressure(route: ProxyRoute) -> float:
                row = traffic[route.url]
                # Relative traffic is a placement hint, not a measured bandwidth limit.
                flow = max(row["messages_per_second"] / max_messages if max_messages else 0,
                           row["payload_bytes_per_second"] / max_bytes if max_bytes else 0)
                return flow * 0.5 + row["queue_pressure"] + min(0.5, row["disconnects_recent"] * 0.1)

            chosen = min(available, key=lambda item: (
                item[1].url != preferred if preferred else False,
                item[2] / item[1].max_ws_subscriptions + pressure(item[1]),
                item[2], item[1].url != remembered, item[0],
            ))
        route = chosen[1]
        lease = ProxyWsLease(uuid.uuid4().hex, route, keys, kind)
        self._ws_leases[lease.token] = lease
        self._add_ws_keys(route, keys)
        if getattr(config, "proxy_strategy", "failover") == "failover":
            self._ws_preferred[exchange] = route.url
        return lease

    def _add_ws_keys(self, route: ProxyRoute, keys: tuple[tuple[str, str, str], ...]) -> None:
        load = self._ws_load.setdefault(route.url, {})
        for key in keys:
            load[key] = load.get(key, 0) + 1
            self._ws_history[key] = route.url
            self._ws_history.move_to_end(key)
        while len(self._ws_history) > 4096:
            self._ws_history.popitem(last=False)

    def _remove_ws_keys(self, lease: ProxyWsLease) -> None:
        load = self._ws_load.get(lease.route.url, {})
        for key in lease.keys:
            count = load.get(key, 0) - 1
            if count <= 0:
                load.pop(key, None)
            else:
                load[key] = count
        if not load:
            self._ws_load.pop(lease.route.url, None)

    def can_update_ws(self, lease: ProxyWsLease, descriptors: list[Any]) -> bool:
        load = self._ws_load.get(lease.route.url, {})
        keys = self._ws_keys(descriptors)
        retained = {key for key, count in load.items() if count > int(key in lease.keys)}
        return len(retained | set(keys)) <= lease.route.max_ws_subscriptions

    def update_ws(self, lease: ProxyWsLease | None, descriptors: list[Any]) -> None:
        if lease is None or self._ws_leases.get(lease.token) is not lease:
            return
        keys = self._ws_keys(descriptors)
        if keys and (not lease.keys or any(key[:2] != lease.keys[0][:2] for key in keys)):
            raise ValueError("websocket capacity updates must preserve the exchange and market")
        if not self.can_update_ws(lease, descriptors):
            raise self._ws_deferred(lease.route, "route_capacity", 0.25)
        self._remove_ws_keys(lease)
        lease.keys = keys
        self._add_ws_keys(lease.route, lease.keys)

    def mark_ws_connected(self, lease: ProxyWsLease | None) -> None:
        if lease and self._ws_leases.get(lease.token) is lease:
            self._ws_connected.add(lease.token)

    def mark_ws_disconnected(self, lease: ProxyWsLease | None) -> None:
        if lease is not None and lease.token in self._ws_connected:
            self._ws_connected.discard(lease.token)
            self.record_ws_traffic(lease.route, disconnected=True)

    def release_ws(self, lease: ProxyWsLease | None) -> None:
        if lease is None or self._ws_leases.pop(lease.token, None) is None:
            return
        self._ws_connected.discard(lease.token)
        self._remove_ws_keys(lease)

    def health(self, route: ProxyRoute, exchange: str, kind: str = "rest") -> _Health:
        return self._health.setdefault((route.url, exchange, kind), _Health())

    async def select_rest(self, config: Any, request: Any, rule: Any, manager: Any) -> ProxyRoute | None:
        from app.exchanges.rate_limits import scope_rate_limit_rule

        routes = self.routes(config, request.exchange)
        if not routes:
            return None
        now = time.monotonic()
        choices = []
        for index, route in enumerate(routes):
            scoped = scope_rate_limit_rule(rule, route.egress_group)
            admission = await manager.inspect(scoped, request)
            health = self.health(route, request.exchange)
            active = self._active.get(route.url, 0)
            wait = max(admission.retry_after_seconds if not admission.allowed else 0.0,
                       health.retry_at - now, 0.0)
            if active >= route.max_concurrency:
                wait = max(wait, 0.05)
            delay = (active + 1) * health.latency_ms / 1000.0 + health.failures * 0.25
            if getattr(config, "proxy_strategy", "failover") == "failover":
                score = (wait > 0, wait, index)
            else:
                score = (wait > 0, wait + delay, index)
            choices.append((score, route))
        return min(choices, key=lambda item: item[0])[1]

    def select_ws(self, config: Any, exchange: str) -> ProxyRoute | None:
        routes = self.routes(config, exchange)
        if not routes:
            return None
        now = time.monotonic()
        self._refresh_ws_circuits(routes, exchange)
        preferred = self._ws_preferred.get(exchange)
        routes.sort(key=lambda route: route.url != preferred)
        route = min(routes, key=lambda route: (
            self.health(route, exchange, "ws").retry_at > now,
            max(0.0, self.health(route, exchange, "ws").retry_at - now),
            routes.index(route),
        ))
        wait = self.health(route, exchange, "ws").retry_at - now
        if wait > 0:
            from app.exchanges.rate_limits import RateLimitAdmission, RateLimitDeferred
            raise RateLimitDeferred(RateLimitAdmission(
                False, f"proxy:{route.id}:ws", 1, "route_cooldown", wait,
                now + wait, int((time.time() + wait) * 1000), "proxy_ws",
            ))
        self._ws_preferred[exchange] = route.url
        return route

    def begin(self, route: ProxyRoute | None, exchange: str) -> None:
        if route is None:
            return
        health = self.health(route, exchange)
        wait = max(0.0, health.retry_at - time.monotonic())
        if self._active.get(route.url, 0) >= route.max_concurrency:
            wait = max(wait, 0.05)
        if wait:
            from app.exchanges.rate_limits import RateLimitAdmission, RateLimitDeferred
            raise RateLimitDeferred(RateLimitAdmission(
                allowed=False, bucket_key=f"proxy:{route.id}", cost=1,
                reason="route_busy", retry_after_seconds=wait,
                retry_at_monotonic=time.monotonic() + wait,
                retry_at_ms=int((time.time() + wait) * 1000), rule_name="proxy_route",
            ))
        self._active[route.url] = self._active.get(route.url, 0) + 1

    def end(self, route: ProxyRoute | None) -> None:
        if route:
            self._active[route.url] = max(0, self._active.get(route.url, 0) - 1)

    def record(self, route: ProxyRoute | None, exchange: str, *, elapsed: float = 0,
               error: BaseException | None = None, kind: str = "rest") -> None:
        if route is None:
            return
        from app.exchanges.rate_limits import RateLimitDeferred
        if isinstance(error, RateLimitDeferred):
            return
        health = self.health(route, exchange, kind)
        status = getattr(error, "status_code", None)
        health.last_status = status
        if error is None:
            health.successes += 1
            health.failures = 0
            health.retry_at = 0
            if elapsed > 0:
                health.latency_ms = (health.latency_ms * 0.8 + elapsed * 1000 * 0.2
                                     if health.latency_samples else elapsed * 1000)
                health.latency_samples += 1
        elif status in {418, 429} or getattr(error, "body_code", None) in {"-1003", "50011"}:
            # Exchange quota is handled by RateLimitManager, never by health
            # failover or resetting a connection's budget.
            return
        elif status is None or status >= 500:
            health.failures += 1
            if kind == "rest" or health.failures >= 3:
                health.retry_at = time.monotonic() + min(60, 2 ** min(health.failures, 6))

    def snapshot(self, config: Any) -> dict:
        from app.exchanges.rate_limits import get_shared_rate_limit_manager
        budgets = get_shared_rate_limit_manager().snapshot()
        from app.exchanges.ccxt_ext.runtime import get_shared_ccxt_runtime_pool
        runtimes = get_shared_ccxt_runtime_pool().snapshot()["runtimes"].values()
        values = getattr(config, "proxy_routes", [])
        rows = []
        for value in values:
            url = value["url"]
            observations = []
            for (observed_url, exchange, kind), health in self._health.items():
                if observed_url == url:
                    observations.append({"exchange": exchange, "kind": kind,
                                         "successes": health.successes, "failures": health.failures,
                                         "latency_ms": round(health.latency_ms, 1) if health.latency_samples else None,
                                         "cooldown_seconds": round(max(0, health.retry_at - time.monotonic()), 2),
                                         "last_status": health.last_status})
            suffix = ":egress=" + value["egress_group"]
            leases = [lease for lease in self._ws_leases.values() if lease.route.url == url]
            route_runtimes = [runtime for runtime in runtimes
                              if runtime.get("proxy_route_id") == value["id"]
                              and runtime.get("proxy_egress_group") == value["egress_group"]
                              and runtime.get("proxy_endpoint") == redact_proxy_url(url)]
            rows.append({"id": value["id"], "name": value["name"], "enabled": value["enabled"],
                         "endpoint": redact_proxy_url(url),
                         "egress_group": value["egress_group"], "active_requests": self._active.get(url, 0),
                         "ws_subscriptions": len(self._ws_load.get(url, {})),
                         "ws_sessions": len(leases),
                         "max_ws_subscriptions": value.get("max_ws_subscriptions", 64),
                         "native_websockets": sum(lease.kind == "native" and lease.token in self._ws_connected
                                                  for lease in leases),
                         "ccxt_runtimes": len(route_runtimes),
                         "ccxt_physical_websockets": sum(runtime.get("physical_websockets", 0)
                                                         for runtime in route_runtimes),
                         "ws_traffic": self.ws_traffic(url),
                         "observations": observations,
                         "budgets": {key: budget for key, budget in budgets.items() if key.endswith(suffix)}})
        return {"strategy": getattr(config, "proxy_strategy", "failover"), "routes": rows}


_POOLS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def get_proxy_pool() -> ProxyPool:
    loop = asyncio.get_running_loop()
    pool = _POOLS.get(loop)
    if pool is None:
        pool = ProxyPool()
        _POOLS[loop] = pool
    return pool
