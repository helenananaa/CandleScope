"""Archive route health and urgent REST-first routing (ADR-DATA-001 §4).

RC 2026-11-23: on a network where the archive host never answered, every
archive-routed range waited the whole 60 s transport budget before REST began,
and each new object waited again.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.data_engine.backfill import fetcher as fetcher_module
from app.data_engine.backfill.archive_cache import HistoricalArchiveCache
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillStatus
from app.data_engine.backfill.route_health import (
    ArchiveRouteHealth,
    counts_against_health,
    is_urgent_history_demand,
)
from app.data_engine.backfill.source_router import HistoricalSourceRouter
from app.data_engine.ingestion.config import IngestionConfig
from app.exchanges.archive import (
    ArchiveDataError,
    ArchiveHttpResponse,
    ArchiveHttpStatusError,
    ArchiveTransportError,
)
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider
from app.exchanges.rate_limits import RateLimitAdmission, RateLimitDeferred, RateLimitManager
from tests.test_history_archive_routing import (
    _ArchiveHttp,
    _RestTransport,
    _archive_payload,
    _config,
    _january_ref,
    _rest_rows,
    _task,
)


@pytest.fixture(autouse=True)
def _binance_archive_only(monkeypatch) -> None:
    class _Plugin:
        @staticmethod
        def history_archive_provider(_config=None):
            return BinanceKlineArchiveProvider()

    class _Registry:
        @staticmethod
        def get_plugin(exchange: str):
            if exchange != "binance":
                raise KeyError(exchange)
            return _Plugin()

    monkeypatch.setattr("app.data_engine.backfill.fetcher.get_shared_rate_limit_manager",
                        lambda: RateLimitManager())
    monkeypatch.setattr("app.data_engine.backfill.source_router.get_exchange_registry",
                        lambda: _Registry())


class _StalledArchive:
    """An archive host that accepts the connection and never answers in time."""

    def __init__(self, stall_s: float) -> None:
        self.stall_s = stall_s
        self.calls = 0
        self.first_call: float | None = None

    async def _stall(self):
        self.calls += 1
        if self.first_call is None:
            self.first_call = time.monotonic()
        await asyncio.sleep(self.stall_s)
        raise ArchiveTransportError("archive request exceeded its total time budget")

    async def get_bytes(self, url, *, allowed_hosts, max_bytes):
        return await self._stall()

    async def download(self, url, destination, *, allowed_hosts, max_bytes):
        return await self._stall()

    async def head(self, url, *, allowed_hosts):
        return ArchiveHttpResponse(200, {})


class _TimedRest(_RestTransport):
    def __init__(self, rows) -> None:
        super().__init__(rows)
        self.at: list[float] = []

    async def http_fetch(self, request):
        self.at.append(time.monotonic())
        return await super().http_fetch(request)


def _parts(tmp_path, http, rows):
    config = _config(tmp_path)
    router = HistoricalSourceRouter(
        config,
        cache=HistoricalArchiveCache(tmp_path, max_bytes=config.history_archive_cache_max_bytes),
        http=http,
        deferred_prefetch_delay_seconds=0,
    )
    rest = _TimedRest(rows)
    return router, rest, HistoricalFetcher(config, rest, IngestionConfig(), source_router=router)


def _urgent(task, *, priority: int = 10, reason: str = "initial_history"):
    task.metadata.update({"priority": priority, "reason": reason})
    return task


def _own_range(task):
    """The chart's own range, without a larger scheduler parent."""
    task.metadata.pop("ledger_range", None)
    return task


def test_urgency_follows_scheduler_priority_and_reasons() -> None:
    assert is_urgent_history_demand({"priority": 10})
    assert is_urgent_history_demand({"priority": 25})
    assert not is_urgent_history_demand({"priority": 90, "reason": "initial_history"})
    assert is_urgent_history_demand({"reason": "active_history_hydration+visible_load_more"})
    assert not is_urgent_history_demand({"reason": "full_subscription_warmup"})
    assert not is_urgent_history_demand({"priority": 10, "source": "background-prefetch"})
    assert not is_urgent_history_demand({"priority": True})
    assert not is_urgent_history_demand(None)


def test_only_transport_trouble_counts_against_a_host() -> None:
    assert counts_against_health(ArchiveTransportError("budget"))
    assert counts_against_health(ArchiveHttpStatusError(503, "download"))
    assert counts_against_health(ArchiveHttpStatusError(429, "download"))
    assert counts_against_health(TimeoutError())
    assert not counts_against_health(ArchiveHttpStatusError(404, "checksum request"))
    assert not counts_against_health(ArchiveDataError("archive SHA-256 does not match provider checksum"))
    assert not counts_against_health(asyncio.CancelledError())
    assert not counts_against_health(RateLimitDeferred(RateLimitAdmission(
        allowed=False, bucket_key="b", cost=1, reason="cooldown", retry_after_seconds=1,
        retry_at_monotonic=time.monotonic() + 1, retry_at_ms=0, rule_name="r",
        status_code=429, body_code=None, circuit_key=None)))


def test_breaker_skips_a_failing_host_for_the_cooldown_then_retries() -> None:
    now = [100.0]
    health = ArchiveRouteHealth(clock=lambda: now[0], unhealthy_after=2, cooldown_seconds=300)
    assert health.available("binance")
    assert not health.record_failure("binance", "budget")
    assert health.available("binance")
    assert health.record_failure("binance", "budget")
    assert not health.available("binance")
    assert health.available("okx")
    now[0] += 299
    assert not health.available("binance")
    now[0] += 2
    assert health.available("binance")  # one more try after the cooldown
    assert health.record_failure("binance", "budget")  # still failing: skip again at once
    assert not health.available("binance")
    now[0] += 301
    health.record_success("binance", 40)
    assert not health.record_failure("binance", "budget")
    assert health.snapshot()["binance"]["consecutive_failures"] == 1


def test_urgent_range_takes_rest_when_the_archive_misses_its_deadline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(fetcher_module, "URGENT_ARCHIVE_DEADLINE_SECONDS", 0.2)

    async def run() -> None:
        ref = _january_ref()
        count = 8_001  # nine REST pages: a waiting chart may still use the archive
        archive = _StalledArchive(stall_s=1.0)
        router, rest, fetcher = _parts(tmp_path, archive, _rest_rows(ref.start_ms, count))
        result = (await fetcher.fetch([_urgent(_own_range(_task(ref, 0, count - 1)))]))[0]

        assert result.status is BackfillStatus.COMPLETED
        assert result.bars_count == count
        assert archive.first_call is not None and rest.at
        assert rest.at[0] - archive.first_call < 0.6  # REST did not wait for the 1 s stall
        assert any("not ready within" in error for error in result.metadata["archive_errors"])
        assert result.metadata["rest_fallback_ranges"] == 1
        assert router.route_health.snapshot()["binance"]["consecutive_failures"] == 1
        # The download kept running; its failure is the second strike.
        await asyncio.sleep(1.0)
        assert not router.route_health.available("binance")

    asyncio.run(run())


def test_ordinary_range_still_waits_for_its_archive_object(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(fetcher_module, "URGENT_ARCHIVE_DEADLINE_SECONDS", 0.05)

    async def run() -> None:
        ref = _january_ref()
        count = 3_001
        archive = _StalledArchive(stall_s=0.4)
        _router, rest, fetcher = _parts(tmp_path, archive, _rest_rows(ref.start_ms, count))
        result = (await fetcher.fetch([_own_range(_task(ref, 0, count - 1))]))[0]
        assert result.status is BackfillStatus.COMPLETED
        assert rest.at[0] - archive.first_call >= 0.35  # unchanged: REST after the archive failed

    asyncio.run(run())


def test_unhealthy_host_is_skipped_until_its_cooldown_ends(tmp_path) -> None:
    async def run() -> None:
        ref = _january_ref()
        count = 3_001
        archive = _StalledArchive(stall_s=0.0)
        router, rest, fetcher = _parts(tmp_path, archive, _rest_rows(ref.start_ms, count))
        now = [1_000.0]
        router.route_health = ArchiveRouteHealth(clock=lambda: now[0], cooldown_seconds=300)
        router.route_health.record_failure("binance", "budget")
        router.route_health.record_failure("binance", "budget")

        skipped = (await fetcher.fetch([_own_range(_task(ref, 0, count - 1))]))[0]
        assert skipped.status is BackfillStatus.COMPLETED and skipped.bars_count == count
        assert archive.calls == 0  # straight to REST, no 60 s wait
        counters = router.snapshot()["metrics"]["counters"]
        assert counters["archive_unhealthy_rest_routes"] >= 1

        now[0] += 301
        # A different, uncached object after the cooldown: the host is tried again.
        second = _own_range(_task(ref, count, 2 * count - 1))
        rest.rows = _rest_rows(ref.start_ms, 2 * count)
        retried = (await fetcher.fetch([second]))[0]
        assert retried.status is BackfillStatus.COMPLETED
        assert archive.calls >= 1

    asyncio.run(run())


def test_urgent_range_below_eight_pages_skips_a_download_but_uses_a_local_zip(tmp_path) -> None:
    async def run() -> None:
        ref = _january_ref()
        count = 3_001  # four REST pages: archive for ordinary demand, REST for a waiting chart
        archive = _StalledArchive(stall_s=0.0)
        router, rest, fetcher = _parts(tmp_path, archive, _rest_rows(ref.start_ms, count))
        urgent = (await fetcher.fetch([_urgent(_own_range(_task(ref, 0, count - 1)))]))[0]
        assert urgent.status is BackfillStatus.COMPLETED and urgent.bars_count == count
        assert archive.calls == 0
        assert router.snapshot()["metrics"]["counters"]["archive_urgent_rest_routes"] >= 1

        ordinary = (await fetcher.fetch([_own_range(_task(ref, 0, count - 1))]))[0]
        assert ordinary.status is BackfillStatus.COMPLETED
        assert archive.calls >= 1  # unchanged threshold for ordinary demand

        # With the object already on disk, urgent demand reads it without REST.
        cached_dir = tmp_path / "cached"
        cached_dir.mkdir()
        working = _ArchiveHttp(ref, _archive_payload(ref, count))
        router2, rest2, fetcher2 = _parts(cached_dir, working, _rest_rows(ref.start_ms, count))
        warm = (await fetcher2.fetch([_own_range(_task(ref, 0, count - 1))]))[0]
        assert warm.status is BackfillStatus.COMPLETED and working.downloads == 1
        rest_before = len(rest2.at)
        fresh_router, fresh_rest, fresh_fetcher = _parts(cached_dir, working, _rest_rows(ref.start_ms, count))
        again = (await fresh_fetcher.fetch([_urgent(_own_range(_task(ref, 0, count - 1)))]))[0]
        assert again.status is BackfillStatus.COMPLETED and again.bars_count == count
        assert working.downloads == 1 and not fresh_rest.at
        assert all(bar.source != "backfill" for bar in again.bars)
        del router2, rest_before, fresh_router

    asyncio.run(run())
