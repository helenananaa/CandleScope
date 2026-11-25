"""Archive route health and urgency for history routing (ADR-DATA-001 §4).

The router used to choose an archive object whenever a range needed at least
three REST pages, whatever the network. A failure was remembered only for that
object, so on a network where the archive host never answered every new object
spent its whole 60 s transport budget before REST started (RC 2026-11-23).

Two rules here change that:

* Urgent demand (the first screen, a page being loaded, the forming bucket)
  uses the archive only for at least ``URGENT_ARCHIVE_MIN_REST_PAGES`` REST
  pages, and waits at most ``URGENT_ARCHIVE_DEADLINE_SECONDS`` for an object
  before fetching the same range over REST. The archive download keeps running
  in the background for later demand.
* An archive host that failed ``UNHEALTHY_AFTER`` times in a row, deadline
  misses included, is skipped for ``COOLDOWN_SECONDS``. After the cooldown the
  next demand tries it again; one more failure skips it again.

Neither rule changes which rows are written or how they are fenced: a range
taken from REST instead of an archive object is an ordinary REST fallback.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import aiohttp

from app.exchanges.archive import ArchiveHttpStatusError, ArchiveTransportError
from app.exchanges.rate_limits import RateLimitDeferred

# BACKFILL_REASON_PRIORITIES: initial_history 10, visible_load_more and
# visible_range_gap 20, visible_seed_gap and tail_gap 25.
URGENT_PRIORITY = 25
URGENT_REASONS = frozenset({
    "initial_history", "visible_load_more", "visible_range_gap", "visible_seed_gap", "tail_gap",
})
URGENT_ARCHIVE_MIN_REST_PAGES = 8
URGENT_ARCHIVE_DEADLINE_SECONDS = 8.0
UNHEALTHY_AFTER = 2
COOLDOWN_SECONDS = 300.0


class ArchiveDeadlineExceeded(ArchiveTransportError):
    """An urgent range stopped waiting for its archive object."""


def is_urgent_history_demand(metadata: dict[str, Any] | None) -> bool:
    """Whether a backfill task serves a chart that is waiting on screen."""
    metadata = metadata or {}
    source = str(metadata.get("source") or "").strip().lower()
    if source == "background-prefetch":
        return False
    priority = metadata.get("priority")
    if isinstance(priority, int) and not isinstance(priority, bool):
        return priority <= URGENT_PRIORITY
    reasons = {part.strip().lower() for part in str(metadata.get("reason") or "").split("+")}
    return bool(reasons & URGENT_REASONS)


def counts_against_health(error: BaseException) -> bool:
    """Transport trouble says the host is unusable; bad or missing data does not."""
    if isinstance(error, (RateLimitDeferred, asyncio.CancelledError)):
        return False
    if isinstance(error, ArchiveHttpStatusError):
        return error.status in {408, 425, 429} or error.status >= 500
    return isinstance(error, (ArchiveTransportError, TimeoutError, aiohttp.ClientError, ConnectionError))


@dataclass(slots=True)
class _Host:
    failures: int = 0
    skip_until: float = 0.0
    last_error: str = ""
    last_success_ms: int | None = None


class ArchiveRouteHealth:
    """Per-provider consecutive-failure breaker, owned by one router."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        unhealthy_after: int = UNHEALTHY_AFTER,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ) -> None:
        self._clock = clock
        self._unhealthy_after = max(1, int(unhealthy_after))
        self._cooldown = max(0.0, float(cooldown_seconds))
        self._hosts: dict[str, _Host] = {}

    def available(self, provider: str) -> bool:
        host = self._hosts.get(provider)
        return host is None or self._clock() >= host.skip_until

    def record_success(self, provider: str, elapsed_ms: int) -> None:
        host = self._hosts.setdefault(provider, _Host())
        host.failures = 0
        host.skip_until = 0.0
        host.last_success_ms = int(elapsed_ms)

    def record_failure(self, provider: str, error: BaseException | str) -> bool:
        """Count one failure; return whether the provider is now skipped."""
        host = self._hosts.setdefault(provider, _Host())
        host.failures += 1
        host.last_error = str(error)[:200]
        if host.failures >= self._unhealthy_after:
            host.skip_until = self._clock() + self._cooldown
            return True
        return False

    def snapshot(self) -> dict[str, dict[str, Any]]:
        now = self._clock()
        return {
            provider: {
                "available": now >= host.skip_until,
                "consecutive_failures": host.failures,
                "skip_remaining_s": round(max(0.0, host.skip_until - now), 1),
                "last_error": host.last_error,
                "last_success_ms": host.last_success_ms,
            }
            for provider, host in sorted(self._hosts.items())
        }
