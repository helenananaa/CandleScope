"""Exchange reachability per market, derived from ingestion session health.

The browser can only see its own local socket to the backend, which stays up
when the exchange is unreachable. Ingestion sessions already report
``SessionHealth`` for every upstream pipeline; this module turns those reports
plus observed data into one explicit offline/online signal per market so the
UI can say "offline" instead of waiting for a freshness timeout.

Policy (per ingestion pipeline, called a probe here):

* Data delivered, or session ``CONNECTED``: the probe is live.
* ``RECONNECTING`` shortly after the pipeline last delivered data (or started)
  is a connection break. If no data arrives within ``grace_seconds`` the probe
  is offline.
* ``RECONNECTING`` after a long silence is a stale-timeout recycle in a quiet
  market, not evidence of an outage, so it does not go offline by itself.
* ``UNHEALTHY`` (the session spent its consecutive-failure budget and feed
  control moved to HTTP fallback) goes offline after ``grace_seconds`` unless
  the HTTP fallback delivers data first.
* ``CONNECTING`` and ``DISCONNECTED`` are lifecycle noise and do not change
  the probe; owners close probes explicitly when they stop a pipeline.

A market (kind, exchange, market type, symbol) is offline when one of its
probes is offline and none is live. It stays offline until a probe proves the
upstream live again, so restarting a pipeline during an outage does not flash
back online. Timers are one-shot per interruption; nothing polls.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

logger = logging.getLogger("data_manager.upstream_availability")

DEFAULT_GRACE_SECONDS = 6.0
# Below the ingestion stale timeout (30 s): a reconnect that follows a silence
# at least this long is treated as a quiet-market recycle, not a break.
DEFAULT_BREAK_WINDOW_SECONDS = 20.0

LIVE = "live"
PENDING = "pending"
INTERRUPTED = "interrupted"
OFFLINE = "offline"


class _TimerHandle(Protocol):
    def cancel(self) -> Any:
        ...


Scheduler = Callable[[float, Callable[[], None]], _TimerHandle]


def _default_schedule(delay: float, callback: Callable[[], None]) -> _TimerHandle:
    return asyncio.get_running_loop().call_later(delay, callback)


def _health_value(health: Any) -> str:
    return str(getattr(health, "value", health) or "").strip().lower()


@dataclass(frozen=True)
class UpstreamMarket:
    """One market as seen by one kind of consumer (K-lines or prices)."""

    kind: str
    exchange: str
    market_type: str
    symbol: str

    @classmethod
    def create(cls, kind: str, exchange: str, market_type: str, symbol: str) -> "UpstreamMarket":
        return cls(
            str(kind or "").strip().lower(),
            str(exchange or "").strip().lower(),
            str(market_type or "").strip().lower(),
            str(symbol or "").strip().upper(),
        )


@dataclass(frozen=True)
class UpstreamAvailabilityChange:
    market: UpstreamMarket
    offline: bool
    reason: str


class UpstreamProbe:
    """Health observer for one ingestion pipeline of one market."""

    __slots__ = (
        "_owner", "market", "state", "started_at", "last_data_at",
        "reason", "_timer", "closed",
    )

    def __init__(self, owner: "UpstreamAvailability", market: UpstreamMarket, now: float) -> None:
        self._owner = owner
        self.market = market
        self.state = PENDING
        self.started_at = now
        self.last_data_at: float | None = None
        self.reason = ""
        self._timer: _TimerHandle | None = None
        self.closed = False

    async def health(self, health: Any, reason: str = "") -> None:
        """``HealthCallback`` for ingestion pipelines."""
        self.observe_health(health, reason)

    def observe_health(self, health: Any, reason: str = "") -> None:
        if self.closed:
            return
        value = _health_value(health)
        if value == "connected":
            self._become_live()
        elif value == "reconnecting":
            if self.state in (PENDING, LIVE):
                reference = self.last_data_at if self.last_data_at is not None else self.started_at
                broke = self._owner.clock() - reference < self._owner.break_window_seconds
                self._interrupt(reason or value, schedule=broke)
        elif value == "unhealthy":
            if self.state in (PENDING, LIVE):
                self._interrupt(reason or value, schedule=True)
            elif self.state == INTERRUPTED and self._timer is None:
                self.reason = reason or value
                self._timer = self._owner.schedule(self._owner.grace_seconds, self._promote)

    def observe_data(self) -> None:
        """Record delivered upstream data; called on every delivered event."""
        if self.closed:
            return
        self.last_data_at = self._owner.clock()
        if self.state != LIVE:
            self._become_live()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._cancel_timer()
        self._owner._remove(self)

    def _become_live(self) -> None:
        self._cancel_timer()
        if self.state == LIVE:
            return
        self.state = LIVE
        self.reason = ""
        self._owner._recompute(self.market)

    def _interrupt(self, reason: str, *, schedule: bool) -> None:
        self._cancel_timer()
        self.state = INTERRUPTED
        self.reason = reason
        if schedule:
            self._timer = self._owner.schedule(self._owner.grace_seconds, self._promote)
        self._owner._recompute(self.market)

    def _promote(self) -> None:
        self._timer = None
        if self.closed or self.state != INTERRUPTED:
            return
        self.state = OFFLINE
        self._owner._recompute(self.market)

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()


class UpstreamAvailability:
    """Registry of upstream probes and the per-market offline signal."""

    def __init__(
        self,
        *,
        grace_seconds: float = DEFAULT_GRACE_SECONDS,
        break_window_seconds: float = DEFAULT_BREAK_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        schedule: Scheduler = _default_schedule,
    ) -> None:
        self.grace_seconds = float(grace_seconds)
        self.break_window_seconds = float(break_window_seconds)
        self.clock = clock
        self.schedule = schedule
        self._probes: dict[UpstreamMarket, set[UpstreamProbe]] = {}
        self._offline: dict[UpstreamMarket, str] = {}
        self._listeners: list[Callable[[UpstreamAvailabilityChange], None]] = []

    def probe(self, kind: str, exchange: str, market_type: str, symbol: str) -> UpstreamProbe:
        market = UpstreamMarket.create(kind, exchange, market_type, symbol)
        probe = UpstreamProbe(self, market, self.clock())
        self._probes.setdefault(market, set()).add(probe)
        return probe

    def is_offline(self, kind: str, exchange: str, market_type: str, symbol: str) -> bool:
        return UpstreamMarket.create(kind, exchange, market_type, symbol) in self._offline

    def offline_markets(self, kind: str | None = None) -> list[UpstreamMarket]:
        normalized = str(kind or "").strip().lower()
        return [market for market in self._offline if not normalized or market.kind == normalized]

    def subscribe(self, listener: Callable[[UpstreamAvailabilityChange], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def snapshot(self) -> dict[str, Any]:
        return {
            "offline": [
                {"kind": m.kind, "exchange": m.exchange, "market_type": m.market_type,
                 "symbol": m.symbol, "reason": reason}
                for m, reason in self._offline.items()
            ],
            "probes": sum(len(probes) for probes in self._probes.values()),
            "grace_seconds": self.grace_seconds,
        }

    def _remove(self, probe: UpstreamProbe) -> None:
        probes = self._probes.get(probe.market)
        if probes is None:
            return
        probes.discard(probe)
        if not probes:
            self._probes.pop(probe.market, None)
        self._recompute(probe.market)

    def _recompute(self, market: UpstreamMarket) -> None:
        probes: Iterable[UpstreamProbe] = self._probes.get(market, ())
        if not probes:
            # No pipeline is left to observe. Forget the market without
            # announcing recovery: consumers keep what they show until data
            # or a restarted pipeline proves otherwise.
            self._offline.pop(market, None)
            return
        live = any(probe.state == LIVE for probe in probes)
        offline_reason = next((probe.reason for probe in probes if probe.state == OFFLINE), None)
        was_offline = market in self._offline
        # Offline until proven live: a pipeline restarted during an outage has
        # not delivered data yet and must not flash the market back online.
        offline = not live and (offline_reason is not None or was_offline)
        if offline:
            reason = offline_reason or self._offline.get(market) or "upstream_unavailable"
            self._offline[market] = reason
        else:
            self._offline.pop(market, None)
        if offline != was_offline:
            self._notify(UpstreamAvailabilityChange(
                market, offline, self._offline.get(market, "upstream_available"),
            ))

    def _notify(self, change: UpstreamAvailabilityChange) -> None:
        logger.info(
            "Upstream %s %s:%s:%s is %s (%s)",
            change.market.kind, change.market.exchange, change.market.market_type,
            change.market.symbol, "offline" if change.offline else "online", change.reason,
        )
        for listener in tuple(self._listeners):
            try:
                listener(change)
            except Exception:  # noqa: BLE001 - a consumer must not break ingestion
                logger.exception("Upstream availability listener failed")


__all__ = [
    "DEFAULT_BREAK_WINDOW_SECONDS",
    "DEFAULT_GRACE_SECONDS",
    "UpstreamAvailability",
    "UpstreamAvailabilityChange",
    "UpstreamMarket",
    "UpstreamProbe",
]
