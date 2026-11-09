"""Exercise the actual service/repository boundary, with counted transport."""
import asyncio
from functools import wraps

import pytest

from app.data_engine.market_data.service import MarketDataService
from app.data_engine.market_data.models import MarketStreamKey, MarketChannel
from app.data_engine.storage.market_metrics_repo import MarketMetricsRepository
from app.data_engine.ingestion.models import MarketEvent, DataSource

STEP = 300_000
NOW = 1_800_000_000_000
START = NOW - 20 * STEP
KEY = MarketStreamKey.build("binance", "futures", "BTCUSDT", MarketChannel.OPEN_INTEREST)


def async_test(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


class Transport:
    def __init__(self):
        self.calls = []
        self.empty = False
        self.points = [START + i * STEP for i in range(6)]
        self.fail = False
        self.block = None
        self.started = asyncio.Event()
        self.cancelled = False

    async def fetch_market(self, descriptor, **kwargs):
        self.calls.append(kwargs)
        self.started.set()
        if self.block is not None:
            try:
                await self.block.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.fail:
            raise RuntimeError("upstream unavailable")
        if self.empty:
            return []
        return [MarketEvent(
            event_type=descriptor.stream_type, symbol=descriptor.symbol,
            exchange=descriptor.exchange, market_type=descriptor.market_type,
            event_time_ms=t, received_at_ms=NOW, source=DataSource.HTTP_BACKFILL,
            data={"open_interest": 200.0}, stream_key=descriptor.key,
        ) for t in self.points if kwargs["start_ms"] <= t <= kwargs["end_ms"]][:500]


def make_service(tmp_path, monkeypatch):
    monkeypatch.setattr("app.data_engine.market_data.service.time.time", lambda: NOW / 1000)
    repo = MarketMetricsRepository(tmp_path / "metrics.sqlite")
    transport = Transport()
    return repo, transport, MarketDataService(transport, metrics_repository=repo)


def seed(repo, times, *, final=True, received=NOW):
    repo.upsert_open_interest([dict(
        exchange="binance", market_type="futures", symbol="BTCUSDT", period="5m",
        event_time_ms=t, open_interest=100, is_final=final,
        received_at_ms=received, source="http_backfill" if final else "http",
    ) for t in times])


async def query(service, **kwargs):
    return await service.history_page(KEY, period="5m", start_ms=START,
                                      end_ms=START + 5 * STEP, **kwargs)


@async_test
async def test_complete_grid_reuses_persisted_receipt_after_restart(tmp_path, monkeypatch):
    repo, transport, service = make_service(tmp_path, monkeypatch)
    assert (await query(service)).complete
    assert len(transport.calls) == 1
    await service.shutdown()
    service = MarketDataService(transport, metrics_repository=repo)
    page = await query(service)
    assert page.complete and [e.event_time_ms for e in page.events] == transport.points
    assert len(transport.calls) == 1
    await service.shutdown()


@async_test
async def test_legacy_rows_and_receipts_cannot_fill_a_missing_scheduled_sample(tmp_path, monkeypatch):
    repo, transport, service = make_service(tmp_path, monkeypatch)
    missing = START + 2 * STEP
    seed(repo, [missing])
    assert repo.record_open_interest_query(
        exchange="binance", market_type="futures", symbol="BTCUSDT", period="5m",
        start_ms=START, end_ms=START + 5 * STEP, policy_revision="binance-oi-range-v1:static",
        expected_rows=[dict(event_time_ms=missing, open_interest=100, is_final=True)],
        observed_at_ms=NOW,
    )
    await service.shutdown()
    repo = MarketMetricsRepository(repo.db_path)
    import sqlite3
    with sqlite3.connect(repo.db_path) as conn:
        assert not conn.execute("SELECT 1 FROM open_interest_query_receipts").fetchone()

    service = MarketDataService(transport, metrics_repository=repo)
    transport.points.remove(missing)
    local = await query(service, mode="local_only")
    assert local.covered_ranges == () and not local.complete and not transport.calls
    assert [event.event_time_ms for event in local.events] == [missing]
    page = await query(service)
    assert not page.complete and page.retryable and len(page.events) == 6
    assert page.missing_ranges == ({"start_ms": missing, "end_ms": missing + STEP - 1},)

    transport.points.append(missing)
    assert (await query(service)).complete
    assert len(transport.calls) == 2
    assert transport.calls[-1]["start_ms"] == missing
    assert transport.calls[-1]["end_ms"] == missing + STEP - 1
    assert (await query(service, mode="local_only")).complete
    assert len(transport.calls) == 2
    await service.shutdown()


@async_test
async def test_off_grid_observations_are_preserved_without_certifying_expected_slots(tmp_path, monkeypatch):
    _, transport, service = make_service(tmp_path, monkeypatch)
    transport.points = [START + 17, START + 2 * STEP + 31, START + 4 * STEP + 59]
    page = await query(service)
    assert [event.event_time_ms for event in page.events] == transport.points
    assert page.covered_ranges == () and page.retryable and not page.complete
    await service.shutdown()


@async_test
async def test_only_unacquired_ranges_are_fetched_and_refresh_is_explicit(tmp_path, monkeypatch):
    _, transport, service = make_service(tmp_path, monkeypatch)
    for left, right in [(START, START + STEP - 1), (START + 3 * STEP, START + 5 * STEP)]:
        assert (await service.history_page(KEY, period="5m", start_ms=left, end_ms=right)).complete
    assert (await query(service)).complete
    assert len(transport.calls) == 3
    assert transport.calls[-1]["start_ms"] == START + STEP
    assert transport.calls[-1]["end_ms"] == START + 3 * STEP - 1
    await query(service, mode="refresh")
    assert len(transport.calls) == 4
    await service.shutdown()


@async_test
async def test_empty_response_keeps_expected_samples_retryable(tmp_path, monkeypatch):
    _, transport, service = make_service(tmp_path, monkeypatch)
    transport.empty = True
    page = await query(service)
    assert not page.complete and page.retryable and not page.events and page.terminal_reason is None
    assert not page.has_more and page.next_end_ms is None
    assert (await query(service)).retryable and len(transport.calls) == 2

    no_sample = await service.history_page(KEY, period="5m", start_ms=START + 1, end_ms=START + STEP - 1)
    assert no_sample.complete and not no_sample.events and len(transport.calls) == 2
    await service.shutdown()


@async_test
async def test_short_refresh_preserves_verified_local_history_and_reports_retry(tmp_path, monkeypatch):
    _, transport, service = make_service(tmp_path, monkeypatch)
    assert (await query(service)).complete
    transport.points.pop(2)
    page = await query(service, mode="refresh")
    assert page.fallback and page.retryable and not page.complete
    assert len(page.events) == 6 and page.covered_ranges
    assert (await query(service, mode="local_only")).complete
    await service.shutdown()


@async_test
async def test_failure_does_not_certify_provisional_or_old_rows(tmp_path, monkeypatch):
    repo, transport, service = make_service(tmp_path, monkeypatch)
    seed(repo, [START], final=False)
    transport.fail = True
    page = await query(service)
    assert page.retryable and not page.complete and page.fallback and page.covered_ranges == ()
    await service.shutdown()


@async_test
async def test_overlap_and_shared_waiter_cancellation(tmp_path, monkeypatch):
    _, transport, service = make_service(tmp_path, monkeypatch)
    transport.block = asyncio.Event()
    a, b = asyncio.create_task(query(service)), asyncio.create_task(query(service))
    await transport.started.wait()
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    assert not transport.cancelled
    c = asyncio.create_task(service.history_page(KEY, period="5m", start_ms=START + STEP, end_ms=START + 4 * STEP))
    transport.block.set()
    assert (await b).complete and (await c).complete
    assert len(transport.calls) == 1 and not service._history_tasks
    await service.shutdown()


@async_test
async def test_last_waiter_and_shutdown_drain_tasks(tmp_path, monkeypatch):
    _, transport, service = make_service(tmp_path, monkeypatch)
    transport.block = asyncio.Event()
    task = asyncio.create_task(query(service))
    await transport.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.cancelled and not service._history_tasks
    transport.started.clear()
    task = asyncio.create_task(query(service))
    await transport.started.wait()
    await service.shutdown()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not service._history_tasks


@async_test
async def test_retention_preserves_local_rows_and_explains_unavailable(tmp_path, monkeypatch):
    repo, transport, service = make_service(tmp_path, monkeypatch)
    old = START - 40 * 86_400_000
    seed(repo, [old])
    page = await service.history_page(KEY, period="5m", start_ms=old, end_ms=old + STEP)
    assert len(page.events) == 1 and not transport.calls
    assert page.complete and not page.retryable
    assert page.excluded_ranges[-1]["reason"] == "outside_upstream_retention"
    await service.shutdown()


@async_test
async def test_digest_detects_deletion_and_tail_receipts_expire(tmp_path, monkeypatch):
    import sqlite3
    repo, transport, service = make_service(tmp_path, monkeypatch)
    assert (await query(service)).complete
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("DELETE FROM open_interest_history WHERE event_time_ms=?", (transport.points[1],))
    assert not (await query(service, mode="local_only")).complete
    assert (await query(service)).complete and len(transport.calls) == 2
    transport.points = [NOW - STEP, NOW]
    assert (await service.history_page(KEY, period="5m", start_ms=NOW - STEP, end_ms=NOW)).complete
    before = len(transport.calls)
    await service.history_page(KEY, period="5m", start_ms=NOW - STEP, end_ms=NOW)
    assert len(transport.calls) == before
    monkeypatch.setattr("app.data_engine.market_data.service.time.time", lambda: (NOW + 61_000) / 1000)
    await service.history_page(KEY, period="5m", start_ms=NOW - STEP, end_ms=NOW)
    assert len(transport.calls) == before + 1
    await service.shutdown()


@async_test
async def test_full_response_is_bisected_without_assuming_order_or_grid(tmp_path, monkeypatch):
    _, transport, service = make_service(tmp_path, monkeypatch)
    transport.points = list(range(START, START + 1000))
    page = await service.history_page(KEY, period="5m", start_ms=START, end_ms=START + 1001, limit=1000)
    assert page.complete and len(page.events) == 1000
    assert len(transport.calls) > 1 and all(c["limit"] == 500 for c in transport.calls)
    await service.shutdown()


@async_test
async def test_real_http_contract_preserves_unknown_ranges(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    import httpx
    from app.api.v1.market import router
    _, transport, service = make_service(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(router)
    app.state.data_manager = SimpleNamespace(market_data_ready=True, market_history_page=service.history_page)
    params = dict(channel="open_interest", symbol="BTCUSDT", period="5m", start_ms=START, end_ms=START + 5 * STEP, mode="local_only")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/market/history", params=params)
        assert response.status_code == 200
        body = response.json()
        assert not body["complete"] and body["coverage"]["ranges"] == [] and not transport.calls
        params["mode"] = "fill_missing"
        assert (await client.get("/market/history", params=params)).json()["complete"]
        assert len(transport.calls) == 1
        params["mode"] = "bad"
        assert (await client.get("/market/history", params=params)).status_code == 422
    await service.shutdown()


@pytest.mark.parametrize("payload", [{}, {"sumOpenInterest": "1"},
    {"symbol": "ETHUSDT", "sumOpenInterest": "1", "timestamp": START},
    {"symbol": "BTCUSDT", "sumOpenInterest": "nan", "timestamp": START},
    {"symbol": "BTCUSDT", "sumOpenInterest": True, "timestamp": START},
    {"symbol": "BTCUSDT", "sumOpenInterest": "1", "timestamp": True}])
@async_test
async def test_real_factory_rejects_malformed_rows_instead_of_certifying_empty(payload):
    from types import SimpleNamespace
    from app.data_engine.ingestion.factory import ExchangeIngestionFactory
    from app.data_engine.ingestion.models import StreamDescriptor, StreamType, RawMessage
    factory = ExchangeIngestionFactory()
    async def fetch(_request):
        return [RawMessage(payload=payload, source=DataSource.HTTP,
                           stream_type=StreamType.OPEN_INTEREST, received_at_ms=NOW)]
    factory._ingress = SimpleNamespace(transport=SimpleNamespace(http_fetch=fetch))
    descriptor = StreamDescriptor(symbol="BTCUSDT", exchange="binance", market_type="futures",
                                  stream_type=StreamType.OPEN_INTEREST, interval="5m")
    with pytest.raises(RuntimeError):
        await factory.fetch_market(descriptor, history=True, start_ms=START, end_ms=NOW)


@async_test
async def test_real_factory_and_durable_writer_reuse_one_qualified_response(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.data_engine.ingestion.factory import ExchangeIngestionFactory
    from app.data_engine.ingestion.models import StreamType, RawMessage
    from app.data_engine.market_data.storage_writer import MarketMetricStorageWriter
    repo, _, _ = make_service(tmp_path, monkeypatch)
    factory = ExchangeIngestionFactory()
    calls = []
    async def fetch(request):
        calls.append(request)
        return [RawMessage(payload={"symbol": "BTCUSDT", "sumOpenInterest": "123.25",
                                    "sumOpenInterestValue": "456.5", "timestamp": START + i * STEP},
                           source=DataSource.HTTP, stream_type=StreamType.OPEN_INTEREST, received_at_ms=NOW)
                for i in range(6)]
    factory._ingress = SimpleNamespace(transport=SimpleNamespace(http_fetch=fetch))
    writer = MarketMetricStorageWriter(repo)
    service = MarketDataService(factory, metrics_repository=repo, metrics_writer=writer)
    for _ in range(2):
        page = await query(service)
        assert page.complete and page.events[0].event_time_ms == START
        assert page.events[0].data["open_interest_value"] == 456.5
    assert len(calls) == 1 and writer.diagnostics()["rows_written"] == 6
    await service.shutdown()
    assert writer.diagnostics()["state"] == "closed"


def test_native_protocol_rejects_non_array_history_before_normalization():
    from app.data_engine.ingestion.models import StreamDescriptor, StreamType
    from app.exchanges.plugins.binance.protocol import BinanceExchangeProtocol
    descriptor = StreamDescriptor(symbol="BTCUSDT", exchange="binance", market_type="futures",
                                  stream_type=StreamType.OPEN_INTEREST, interval="5m")
    protocol = BinanceExchangeProtocol()
    assert protocol.extract_http_rows([], descriptor) == []
    with pytest.raises(RuntimeError, match="array"):
        protocol.extract_http_rows({"sumOpenInterest": "1", "timestamp": START}, descriptor)


@async_test
async def test_limit_and_fetch_work_budget_do_not_hide_unreturned_history(tmp_path, monkeypatch):
    _, transport, service = make_service(tmp_path, monkeypatch)
    page = await query(service, limit=1)
    assert len(page.events) == 1 and page.has_more and not page.complete
    assert page.covered_ranges[0]["start_ms"] == transport.points[-1]
    await service.shutdown()
    _, transport, service = make_service(tmp_path / "many", monkeypatch)
    transport.points = list(range(START, START + 20_000))
    page = await service.history_page(KEY, period="5m", start_ms=START, end_ms=START + 20_000, limit=1000)
    assert len(transport.calls) == 16 and not page.complete
    assert page.retryable and len(page.events) <= 1000
    await service.shutdown()
