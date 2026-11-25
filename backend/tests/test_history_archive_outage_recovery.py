"""RC item 23 (#446): a short outage during a chart's initial history load.

The installed RC stayed on an endless spinner when the network was cut for
10 s right after a chart switched from BTCUSDT to ETHUSDT 4h.  The outage left
the October archive object in the router's negative cache, so the chunk needed
three REST pieces: the two uncovered tails and the archive fallback range.
Binance futures allows one REST request at a time.  The CCXT layer takes that
slot with the chunk's deferrable demand, so the pieces deferred each other;
the routed task then deferred the whole chunk and discarded the piece that had
finished.  Every scheduler retry repeated the same race.

These tests run the real fetcher, source router and public admission with a
CCXT-like transport that acquires its permit exactly as the CCXT mixin does.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import pytest

from app.data_engine.backfill.archive_cache import HistoricalArchiveCache
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillStatus, BackfillTask
from app.data_engine.backfill.source_router import HistoricalSourceRouter
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import (
    DataSource,
    RawMessage,
    StreamType,
    TransportRequest,
)
from app.data_engine.ingestion.transport import TransportError
from app.exchanges.archive import ArchiveTransportError
from app.exchanges.plugins.binance.archive import BinanceKlineArchiveProvider
from app.exchanges.public_admission import (
    PublicDemand,
    TrafficClass,
    acquire_public,
    public_demand,
)
from app.exchanges.rate_limits import (
    HistoricalRequest,
    RateLimitDeferred,
    RateLimitManager,
)
from app.exchanges.registry import bootstrap_default_adapters, get_exchange_registry


UTC = timezone.utc
H4_MS = 4 * 3_600_000
# A closed range whose middle month is complete, like the RC chart's 500 bars.
RANGE_START_MS = int(datetime(2024, 9, 10, tzinfo=UTC).timestamp() * 1_000)
RANGE_END_MS = int(datetime(2024, 11, 10, 20, tzinfo=UTC).timestamp() * 1_000)
EXPECTED_BARS = (RANGE_END_MS - RANGE_START_MS) // H4_MS + 1


@pytest.fixture(autouse=True)
def _isolated_admission(monkeypatch) -> None:
    class _ArchivePlugin:
        @staticmethod
        def history_archive_provider(_config=None):
            return BinanceKlineArchiveProvider()

    class _ArchiveRegistry:
        @staticmethod
        def get_plugin(exchange: str):
            if exchange != "binance":
                raise KeyError(exchange)
            return _ArchivePlugin()

    monkeypatch.setattr(
        "app.data_engine.backfill.fetcher.get_shared_rate_limit_manager",
        lambda: RateLimitManager(),
    )
    monkeypatch.setattr(
        "app.data_engine.backfill.source_router.get_exchange_registry",
        lambda: _ArchiveRegistry(),
    )


class _Network:
    """A switchable path: a cut fails every in-flight transfer and refuses new ones."""

    def __init__(self) -> None:
        self.online = True
        self._cut = asyncio.Event()
        self.inflight = 0
        self.started = asyncio.Event()

    def cut(self) -> None:
        self.online = False
        self._cut.set()

    def restore(self) -> None:
        self.online = True
        self._cut = asyncio.Event()

    async def transfer(self, seconds: float, error: type[Exception]) -> None:
        if not self.online:
            raise error("connection refused by the outage")
        cut = self._cut
        self.inflight += 1
        self.started.set()
        try:
            waiter = asyncio.ensure_future(cut.wait())
            try:
                await asyncio.wait({waiter}, timeout=seconds)
            finally:
                waiter.cancel()
            if cut.is_set():
                raise error("tunnel destroyed by the outage")
        finally:
            self.inflight -= 1


class _ArchiveHttp:
    """data.binance.vision behind the same network; objects never arrive here."""

    def __init__(self, network: _Network) -> None:
        self.network = network
        self.requests = 0

    async def _fail(self) -> None:
        self.requests += 1
        await self.network.transfer(0.2, ArchiveTransportError)
        # Only reachable while online; the tests always cut first.
        raise ArchiveTransportError("no usable archive route or admission capacity")

    async def get_bytes(self, url, *, allowed_hosts, max_bytes):
        del url, allowed_hosts, max_bytes
        await self._fail()

    async def download(self, url, destination, *, allowed_hosts, max_bytes):
        del url, destination, allowed_hosts, max_bytes
        await self._fail()

    async def head(self, url, *, allowed_hosts):
        del url, allowed_hosts
        await self._fail()

    async def post_json(self, *args, **kwargs):
        raise AssertionError("Binance archive routing must not use the OKX resolver")


def _row(open_ms: int) -> list[object]:
    return [open_ms, "100", "110", "90", "105", "1.5", open_ms + H4_MS - 1,
            "157.5", 10, "0.75", "78.75", "0"]


class _CcxtLikeTransport:
    """Physical admission like ``PublicCcxtAdmissionMixin.fetch``.

    The permit is taken with the caller's current public demand, so a chunk's
    deferrable demand defers instead of waiting when the slot is busy.
    """

    def __init__(self, network: _Network, config: BackfillConfig, manager: RateLimitManager,
                 *, latency: float = 0.02) -> None:
        bootstrap_default_adapters()
        self.network = network
        self.policy = get_exchange_registry().get_plugin("binance").rate_limit_policy(config)
        self.manager = manager
        self.latency = latency
        self.requests: list[TransportRequest] = []

    def rule(self, symbol: str = "BTCUSDT"):
        return self.policy.rule_for(HistoricalRequest(
            exchange="binance", market_type="futures", endpoint="/fapi/v1/klines",
            symbol=symbol, interval="4h", limit=1_000,
        ))

    def manages_physical_admission(self, request: TransportRequest) -> bool:
        del request
        return True

    async def http_fetch(self, request: TransportRequest) -> list[RawMessage]:
        descriptor = request.descriptor
        quota_request = HistoricalRequest(
            exchange="binance", market_type="futures", endpoint="/fapi/v1/klines",
            symbol=descriptor.symbol, interval=descriptor.interval, limit=request.limit,
        )
        permit = await acquire_public([self.rule(descriptor.symbol)], quota_request, manager=self.manager)
        try:
            self.requests.append(request)
            await self.network.transfer(self.latency, TransportError)
            permit.finish(status_code=200)
        finally:
            if not permit.settled:
                permit.finish(response_unknown=True)
        start_ms = max(RANGE_START_MS, int(request.start_ms or RANGE_START_MS))
        end_ms = min(RANGE_END_MS, int(request.end_ms or RANGE_END_MS))
        first = start_ms + (-(start_ms - RANGE_START_MS)) % H4_MS
        rows = [_row(open_ms) for open_ms in range(first, end_ms + 1, H4_MS)]
        return [
            RawMessage(payload=row, source=DataSource.HTTP, stream_type=StreamType.KLINE,
                       received_at_ms=int(time.time() * 1_000), endpoint="https://fapi.binance.com")
            for row in rows[: int(request.limit or 1_000)]
        ]


def _config(tmp_path) -> BackfillConfig:
    return BackfillConfig(
        history_archive_enabled=True,
        history_archive_cache_dir=str(tmp_path),
        history_archive_cache_max_bytes=10_000_000,
        history_archive_min_rest_pages=3,
        fetch_rate_limit_delay=0,
        fetch_batch_size=1_000,
        fetch_max_retries=0,
        # Production defaults: two REST tasks at once, one futures request.
        fetch_concurrency=2,
        fetch_binance_futures_concurrency=1,
        reconcile_generate_custom=False,
        reconcile_enable_cache_push=False,
    )


def _task(symbol: str, start_ms: int = RANGE_START_MS, end_ms: int = RANGE_END_MS) -> BackfillTask:
    return BackfillTask(
        symbol=symbol,
        interval="4h",
        start_ms=start_ms,
        end_ms=end_ms,
        estimated_bars=(end_ms - start_ms) // H4_MS + 1,
        exchange="binance",
        market_type="futures",
        metadata={"requester": "klines_range", "reason": "latest_refresh+initial_history"},
    )


def _chunk_demand(symbol: str) -> PublicDemand:
    # The scheduler runs every chunk under a deferrable interactive demand.
    return PublicDemand(TrafficClass.INTERACTIVE, owner=f"chart-cell-1:{symbol}",
                        purpose="latest_refresh+initial_history", defer=True)


def _stack(tmp_path):
    config = _config(tmp_path)
    network = _Network()
    archive_http = _ArchiveHttp(network)
    router = HistoricalSourceRouter(
        config,
        cache=HistoricalArchiveCache(tmp_path, max_bytes=config.history_archive_cache_max_bytes),
        http=archive_http,
        deferred_prefetch_delay_seconds=0,
    )
    fetcher = HistoricalFetcher(config, None, IngestionConfig(), source_router=router)
    transport = _CcxtLikeTransport(network, config, fetcher._rate_limit_manager)
    fetcher.set_transport(transport)
    return network, archive_http, router, fetcher, transport


async def _load_through_outage(fetcher, network, tasks, *, max_attempts: int = 15):
    """Retry a chunk like the scheduler: deferrals and failures run it again."""

    async def outage() -> None:
        await network.started.wait()
        network.cut()  # mid-load: the archive download and a REST page are in flight
        await asyncio.sleep(0.05)
        network.restore()

    network.started = asyncio.Event()
    cutter = asyncio.create_task(outage())
    attempts = deferrals = 0
    reasons: list[str] = []
    results = None
    try:
        while attempts < max_attempts:
            attempts += 1
            try:
                with public_demand(_chunk_demand(tasks[0].symbol)):
                    candidate = await fetcher.fetch(tasks)
            except RateLimitDeferred as exc:
                deferrals += 1
                reasons.append(exc.reason)
                await asyncio.sleep(0.005)
                continue
            if all(item.status is BackfillStatus.COMPLETED for item in candidate):
                results = candidate
                break
            await asyncio.sleep(0.02)  # the outage failed this attempt
    finally:
        await cutter
    return results, attempts, deferrals, reasons


def test_initial_load_interrupted_then_symbol_switch_interrupted_both_complete(tmp_path) -> None:
    async def _run() -> None:
        network, archive_http, router, fetcher, transport = _stack(tmp_path)
        assert transport.rule().max_concurrency == 1  # the premise of the RC hang

        for symbol in ("BTCUSDT", "ETHUSDT"):  # first load, then the chart's symbol switch
            results, attempts, deferrals, reasons = await _load_through_outage(
                fetcher, network, [_task(symbol)],
            )
            assert results is not None, (
                f"{symbol} never completed after the outage: {attempts} attempts, "
                f"{deferrals} deferrals ({sorted(set(reasons))})"
            )
            [result] = results
            assert result.bars_count == EXPECTED_BARS
            opens = [bar.open_time for bar in result.bars]
            assert opens == list(range(RANGE_START_MS, RANGE_END_MS + 1, H4_MS))
            if symbol == "BTCUSDT":
                # The cut left the archive object unavailable; REST filled its month.
                assert result.metadata["rest_fallback_ranges"] == 1
                assert result.metadata["archive_errors"]
            # Pieces of one chunk queue behind each other instead of deferring it.
            assert deferrals == 0, reasons

        assert archive_http.requests == 2  # one per symbol, then the negative cache
        counters = router.snapshot()["metrics"]["counters"]
        # Two archive failures in a row (one per symbol) trip the route breaker:
        # the switched symbol's retry goes straight to REST instead of meeting
        # its object's negative cache again (ADR-DATA-001 §4.2).
        assert not router.route_health.available("binance")
        assert counters["archive_negative_cache_hits"] >= 1
        assert counters["archive_unhealthy_rest_routes"] >= 1

    asyncio.run(_run())


def test_two_gap_plan_after_outage_completes_without_self_deferral(tmp_path) -> None:
    """After an archive import a retry plans the two REST tails as separate tasks."""

    async def _run() -> None:
        network, _archive_http, _router, fetcher, _transport = _stack(tmp_path)
        fetcher._source_router = None  # plain REST tasks, as after the month was imported
        october = int(datetime(2024, 10, 1, tzinfo=UTC).timestamp() * 1_000)
        november = int(datetime(2024, 11, 1, tzinfo=UTC).timestamp() * 1_000)
        tasks = [_task("ETHUSDT", RANGE_START_MS, october - H4_MS),
                 _task("ETHUSDT", november, RANGE_END_MS)]

        results, attempts, deferrals, reasons = await _load_through_outage(fetcher, network, tasks)

        assert results is not None, (
            f"never completed: {attempts} attempts, {deferrals} deferrals ({sorted(set(reasons))})"
        )
        assert [item.bars_count for item in results] == [
            (october - RANGE_START_MS) // H4_MS,
            (RANGE_END_MS - november) // H4_MS + 1,
        ]
        assert deferrals == 0, reasons

    asyncio.run(_run())


def test_slot_held_by_another_owner_still_defers_the_chunk(tmp_path) -> None:
    """Queueing is only among one fetch's own pieces; quota control flow is unchanged."""

    async def _run() -> RateLimitDeferred:
        network, _archive_http, _router, fetcher, transport = _stack(tmp_path)
        release = asyncio.Event()

        async def other_owner() -> None:
            permit = await acquire_public(
                [transport.rule()],
                HistoricalRequest(exchange="binance", market_type="futures",
                                  endpoint="/fapi/v1/premiumIndex", symbol="BTCUSDT"),
                manager=transport.manager,
            )
            try:
                await release.wait()
            finally:
                permit.finish(status_code=200)

        with public_demand(PublicDemand(TrafficClass.NORMAL, owner="market-snapshot")):
            holder = asyncio.create_task(other_owner())
        await asyncio.sleep(0)
        try:
            with public_demand(_chunk_demand("ETHUSDT")):
                with pytest.raises(RateLimitDeferred) as caught:
                    await fetcher.fetch([_task("ETHUSDT")])
        finally:
            release.set()
            await holder
        assert not network.inflight
        return caught.value

    deferred = asyncio.run(_run())
    assert deferred.reason == "endpoint_concurrency"
