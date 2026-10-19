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
from dataclasses import dataclass, replace
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
        if not isinstance(raw.get("enabled", True), bool):
            raise ValueError("proxy enabled must be a boolean")
        result.append({
            "id": route_id, "name": str(raw.get("name") or route_id).strip()[:80],
            "url": url, "egress_group": group, "enabled": bool(raw.get("enabled", True)),
            "exchanges": exchanges, "max_concurrency": concurrency,
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

    def bind(self, config: Any) -> Any:
        # A clone prevents one request changing the proxy under another request
        # or a live CCXT websocket. Runtime keys already include proxy URL.
        return replace(config, proxy_mode="custom", http_proxy=self.url,
                       proxy_routes=[], proxy_route_id=self.id,
                       proxy_egress_group=self.egress_group)


@dataclass(slots=True)
class _Health:
    failures: int = 0
    successes: int = 0
    latency_ms: float = 250.0
    retry_at: float = 0.0
    last_status: int | None = None
    latency_samples: int = 0


class ProxyPool:
    def __init__(self) -> None:
        self._health: dict[tuple[str, str, str], _Health] = {}
        self._active: dict[str, int] = {}
        self._ws_preferred: dict[str, str] = {}

    def routes(self, config: Any, exchange: str) -> list[ProxyRoute]:
        if getattr(config, "proxy_mode", "system") != "pool":
            return []
        values, _ = normalize_proxy_pool(getattr(config, "proxy_routes", []),
                                        getattr(config, "proxy_strategy", "failover"))
        routes = [ProxyRoute(value["id"], value["name"], value["url"],
                             value["egress_group"], value["max_concurrency"])
                  for value in values if value["enabled"] and
                  (not value["exchanges"] or exchange in value["exchanges"])]
        if not routes:
            raise ValueError(f"no enabled proxy route for {exchange}")
        return routes

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
        from app.exchanges.rate_limits import get_shared_rate_limit_manager
        circuits = get_shared_rate_limit_manager().circuit_snapshot()
        for route in routes:
            circuit = circuits.get(f"{exchange}:ip:egress={route.egress_group}", {})
            if circuit.get("open"):
                self.health(route, exchange, "ws").retry_at = max(
                    self.health(route, exchange, "ws").retry_at,
                    now + circuit["cooldown_remaining_seconds"],
                )
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
                health.latency_ms = health.latency_ms * 0.8 + elapsed * 1000 * 0.2
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
            rows.append({"id": value["id"], "name": value["name"], "enabled": value["enabled"],
                         "endpoint": redact_proxy_url(url),
                         "egress_group": value["egress_group"], "active_requests": self._active.get(url, 0),
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
