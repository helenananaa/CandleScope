"""Request-scoped proxy leases for public archive HTTP, separate from API weights."""
from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from app.core.proxy_pool import get_proxy_pool
from app.exchanges.archive import ArchiveDataError, ArchiveHttpResponse, ArchiveRequestContext, ArchiveTransportError

ArchiveAttempt = Callable[[str | None, Callable[[int], None]], Awaitable[ArchiveHttpResponse]]


def _retry_after(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        seconds = float(value)
        return max(0.0, seconds) if math.isfinite(seconds) else 0.0
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0.0


async def request_archive(
    config: Any, proxy_resolver: Callable[[], str | None], exchange: str, url: str,
    attempt: ArchiveAttempt, *, timeout_seconds: float, context: ArchiveRequestContext | None = None,
) -> ArchiveHttpResponse:
    """Retry each eligible route at most once within one total time budget."""
    if not getattr(config, "archive_downloads_enabled", True):
        raise ArchiveTransportError("archive network downloads disabled")
    context = context or ArchiveRequestContext()
    host = (urlsplit(url).hostname or "").lower()
    pool = get_proxy_pool()
    tried: set[str] = set()
    last_response: ArchiveHttpResponse | None = None
    try:
        async with asyncio.timeout(timeout_seconds) as deadline:
            for _ in range(16):
                if config.proxy_mode == "pool" and not exchange:
                    raise ArchiveTransportError("archive request is missing exchange context")
                try:
                    lease = await pool.acquire_archive(
                        config, exchange, host, exclude_urls=tried,
                        source_id=context.source_id, object_key=context.object_key, priority=context.priority,
                        non_pool_proxy=proxy_resolver() if config.proxy_mode != "pool" else None,
                    )
                except ValueError:
                    if last_response is not None:
                        return last_response
                    raise ArchiveTransportError("no usable archive route or admission capacity") from None
                if lease is None:
                    continue
                tried.add(lease.route.url)
                started, received = time.monotonic(), 0
                response = None
                failed = cancelled = False
                status = None
                def observe(size: int) -> None:
                    nonlocal received
                    received += size
                try:
                    response = await attempt(lease.route.url or None, observe)
                    status = response.status
                    last_response = response
                    failed = status in {407, 408, 425} or status >= 500
                    if not failed and status not in {418, 429}:
                        return response
                except asyncio.CancelledError:
                    cancelled = not deadline.expired()
                    failed = deadline.expired()
                    raise
                except (aiohttp.ClientError, TimeoutError) as exc:
                    failed = True
                    status = getattr(exc, "status", None)
                    # Do not expose proxy credentials from connector exceptions.
                except ArchiveDataError:
                    raise  # Invalid archive input must not trigger route retries.
                except OSError:
                    raise  # A local file write failure is not a broken proxy.
                finally:
                    pool.finish_archive(
                        lease, elapsed=time.monotonic() - started, received_bytes=received,
                        status=status, failed=failed, cancelled=cancelled,
                        retry_after=_retry_after(response.headers.get("retry-after")) if response else 0,
                    )
            if last_response is not None:
                return last_response
            raise ArchiveTransportError("archive proxy attempts exhausted")
    except TimeoutError:
        raise ArchiveTransportError("archive request exceeded its total time budget") from None
