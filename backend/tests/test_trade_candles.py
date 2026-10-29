"""Trade fallback route, cursor completeness, provenance and restart-safe gaps."""
from decimal import Decimal

import pytest

from app.data_engine.interval_resolution import IntervalResolver, IntervalResolutionError
from app.data_engine.ingestion.models import StreamDescriptor, StreamType, TransportRequest, RawMessage, DataSource
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.normalize import NormalizeLayer
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillTask
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig, CoordinatorConfig
from app.data_engine.data_manager.query import QueryEngine
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.storage import klines_repo, trade_empty_buckets
from app.data_engine.manual_history.planner import ManualHistoryPlanner
from app.exchanges import bootstrap_default_adapters
from app.exchanges.ccxt_ext import trade_candles as provider
from app.exchanges.ccxt_ext.trade_candles import CandleTrade, reduce_trades, fetch_kraken_trade_candles

START = 1_793_232_000_000


def request(interval="1s", start=START, end=START + 4000, limit=1000):
    return TransportRequest(StreamDescriptor("BTC/USD", StreamType.KLINE, interval=interval, exchange="kraken", market_type="spot"),
                            start_ms=start, end_ms=end, limit=limit)


def trade(index, ms, price="10", quantity="1"):
    return [price, quantity, str(Decimal(ms) / 1000), "b", "m", "", index]


class Exchange:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []
    def market(self, symbol):
        return {"id": "XXBTZUSD"}
    async def public_get_trades(self, params):
        self.calls.append(params)
        return next(self.pages)


def page(rows, cursor):
    return {"error": [], "result": {"XXBTZUSD": rows, "last": str(cursor)}}


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "bars.sqlite")
    klines_repo.init_klines_storage()
    trade_empty_buckets.invalidate()
    return klines_repo.KlinesRepoAdapter()


def test_source_priority_and_fixed_interval_boundaries():
    bootstrap_default_adapters()
    r = IntervalResolver()
    def route(ex, interval): return r.resolve(exchange=ex, market_type="spot", interval=interval, purpose="history")
    assert route("kraken", "1m").kind.value == "native"
    assert route("kraken", "13m").base_interval == "1m"
    assert route("kraken", "7s").kind.value == "trade"
    assert route("kraken", "61s").source_interval == "61s"
    assert route("binance", "7s").base_interval == "1s"
    with pytest.raises(IntervalResolutionError): route("bybit", "7s")
    plan = ManualHistoryPlanner(archive_enabled=False, disk_snapshot=lambda: {"free_bytes": 10**12, "physical_size_bytes": 0}).plan(
        exchange="kraken", market_type="spot", symbols=["BTC/USD"], intervals=["7s"], start_ms=START, now_ms=START + 70000)
    assert plan["can_start"] and plan["targets"][0]["source_interval"] == "7s"


def test_deterministic_ohlcv_handles_order_duplicates_and_boundaries():
    def t(i, offset, p, q="0.1"): return CandleTrade(str(i), (START + offset) * 1_000_000, Decimal(p), Decimal(q))
    a, b, c, outside = t(9, 100, "12"), t(10, 100, "10"), t("opaque-id", 999, "11"), t(12, 1000, "999")
    assert reduce_trades([c, b, a, a, outside], "1s", START, START + 1000) == [[START, "12", "12", "10", "11", "0.3"]]
    with pytest.raises(ValueError, match="Conflicting"):
        reduce_trades([a, t(9, 100, "13")], "1s", START, START + 1000)
    with pytest.raises(ValueError, match="price"):
        reduce_trades([t(1, 0, "NaN")], "1s", START, START + 1000)


@pytest.mark.anyio
async def test_cursor_pagination_preserves_same_timestamp_and_empty_seconds(monkeypatch):
    monkeypatch.setattr(provider, "PAGE_SIZE", 2)
    cursor = (START + 100) * 1_000_000 + 3
    ex = Exchange([page([trade(1, START, "11"), trade(2, START + 100, "9")], cursor),
                   page([trade(3, START + 100, "10"), trade(4, START + 2000, "12")], (START + 2000) * 1_000_000),
                   page([], (START + 2000) * 1_000_000)])
    result = await fetch_kraken_trade_candles(ex, "BTC/USD", request(), now_ms=START + 10000)
    assert ex.calls[1]["since"] == str(cursor)
    assert result[0]["value"] == [START, "11", "11", "9", "10", "3"]
    assert result[-1]["empty_ranges"] == [[START + 1000, START + 1000], [START + 3000, START + 4000]]
    assert all(row["trade_coverage_verified"] for row in result[:-1])


@pytest.mark.anyio
async def test_full_stalled_or_budget_exhausted_pages_never_publish(monkeypatch):
    monkeypatch.setattr(provider, "PAGE_SIZE", 1)
    cursor = START * 1_000_000 - 1
    with pytest.raises(ValueError, match="advance"):
        await fetch_kraken_trade_candles(Exchange([page([trade(1, START)], cursor)]), "BTC/USD", request(), now_ms=START + 10000)
    monkeypatch.setattr(provider, "MAX_TRADE_PAGES", 1)
    with pytest.raises(ValueError, match="budget"):
        await fetch_kraken_trade_candles(Exchange([page([trade(1, START)], cursor + 1)]), "BTC/USD", request(), now_ms=START + 10000)


@pytest.mark.anyio
async def test_poll_keeps_current_bucket_forming():
    req = request(start=None, end=None, limit=1)
    ex = Exchange([page([trade(1, START), trade(2, START + 1100)], (START + 1100) * 1_000_000)])
    result = await fetch_kraken_trade_candles(ex, "BTC/USD", req, now_ms=START + 1500)
    assert [row["is_closed"] for row in result] == [True, False]
    assert [row["trade_coverage_verified"] for row in result] == [True, False]


@pytest.mark.anyio
async def test_fetcher_advances_empty_pages_and_carries_verified_source(monkeypatch):
    bootstrap_default_adapters()
    monkeypatch.setattr(provider, "MAX_WINDOW_MS", 2000)
    class Transport:
        def __init__(self): self.requests = []
        async def http_fetch(self, req):
            self.requests.append(req)
            ex = Exchange([page([trade(10, START + 2000)] if req.start_ms == START + 2000 else [], (START + 9000) * 1_000_000)])
            values = await fetch_kraken_trade_candles(ex, "BTC/USD", req, now_ms=START + 10000)
            return [RawMessage(value, DataSource.HTTP_BACKFILL, StreamType.KLINE, START + 10000) for value in values]
    transport = Transport()
    fetcher = HistoricalFetcher(BackfillConfig(history_archive_enabled=False), transport)
    fetcher.set_rate_limiter(lambda: _noop())
    task = BackfillTask(symbol="BTC/USD", interval="1s", exchange="kraken", market_type="spot", start_ms=START, end_ms=START + 4000)
    result = await fetcher._fetch_rest_task(task)
    assert not result.errors
    assert [req.start_ms for req in transport.requests] == [START, START + 2000, START + 4000]
    assert result.bars[0].source == "trade_history_verified"
    assert result.metadata["trade_empty_ranges"] == [[START, START + 1000], [START + 3000, START + 3000], [START + 4000, START + 4000]]


async def _noop(): pass


def test_sparse_evidence_query_invalidation_and_retention(storage):
    key = ("kraken", "spot", "BTC/USD", "1s")
    trade_empty_buckets.record(*key, [[START, START + 5000]])
    row = dict(open_time=START + 3000, close_time=START + 3999, open=10, high=12, low=9, close=11, volume=2, quote_volume=0, trades=0, taker_buy_base=0, taker_buy_quote=0)
    storage.upsert_bars("BTC/USD", "1s", [row], "trade_history_verified", "kraken", "spot")
    # Insertion conservatively invalidates the overlapping proof; fresh proof
    # must exclude the actual candle even after a process/calendar restart.
    trade_empty_buckets.record(*key, [[START, START + 5000]])
    calendar = trade_empty_buckets.make_calendar(*key)
    assert list(calendar.expected_opens(START, START + 5000, "1s")) == [START + 3000]
    query = QueryEngine(BarCache(), storage, QueryConfig(auto_backfill=False))
    result = query.query("BTC/USD", "1s", exchange="kraken", market_type="spot", start_ms=START, end_ms=START + 5000)
    assert result.complete and len(result.bars) == 1
    klines_repo.delete_klines("BTC/USD", "1s", START, START + 1000, exchange="kraken", market_type="spot")
    assert list(calendar.expected_opens(START, START + 5000, "1s")) == [START, START + 1000, START + 3000]


@pytest.mark.anyio
async def test_verified_trade_candle_uses_durable_bridge(storage):
    bootstrap_default_adapters()
    dm = DataManager(DataManagerConfig(coordinator=CoordinatorConfig(prewarm_symbols=[], prewarm_intervals={})))
    dm.set_storage(storage)
    await dm.start()
    try:
        dm.bar_aggregator.add_target("BTC/USD", "1s", exchange="kraken", market_type="spot")
        values = await fetch_kraken_trade_candles(Exchange([page([trade(1, START)], START * 1_000_000)]), "BTC/USD", request(), now_ms=START + 10000)
        normalizer = NormalizeLayer(IngestionConfig(), request().descriptor)
        event = normalizer.parse_raw(RawMessage(values[0], DataSource.HTTP, StreamType.KLINE, START + 10000))
        await dm.bar_aggregator.on_market_event(event)
        await dm.aggregator_bridge.delivery.flush()
        rows = storage.query_bars("BTC/USD", "1s", exchange="kraken", market_type="spot")
        assert len(rows) == 1 and rows[0]["source"] == "trade_history_verified"
    finally:
        await dm.shutdown()


def test_missing_interval_calendar_and_bounded_trade_work_plan():
    from app.exchanges.trade_candles import uses_trade_candles
    from app.data_engine.history.exchange_policy import ExchangeHistoryPolicyResolver
    from app.data_engine.history.service import HistoryAvailabilityService
    from app.data_engine.interval_work_plan import build_interval_work_plan
    bootstrap_default_adapters()
    assert not uses_trade_candles("kraken", "spot", "")
    resolver = ExchangeHistoryPolicyResolver(HistoryAvailabilityService())
    context = resolver.resolve(resolver.series_key(exchange="kraken", market_type="spot", symbol="BTC/USD"))
    assert context.calendar is not None
    route = IntervalResolver().resolve(exchange="kraken", market_type="spot", interval="7s", purpose="history")
    plan = build_interval_work_plan(route, 1500, 20000)
    assert plan.effective_target_bars == 85 and plan.budget_limited


@pytest.mark.anyio
async def test_empty_trade_buckets_do_not_reenter_gap_scan(storage):
    from app.data_engine.backfill.gap_detector import GapDetector
    bootstrap_default_adapters()
    trade_empty_buckets.record("kraken", "spot", "BTC/USD", "1s", [[START, START + 5000]])
    detector = GapDetector(BackfillConfig(), storage)
    gaps = await detector.detect("BTC/USD", ["1s"], START, START + 5000, exchange="kraken", market_type="spot")
    assert gaps == []


@pytest.mark.anyio
@pytest.mark.parametrize("bad", [None, "", "not-an-id"])
async def test_missing_trade_id_is_not_accepted_as_complete(bad):
    with pytest.raises(ValueError, match="identity"):
        await fetch_kraken_trade_candles(Exchange([page([trade(bad, START)], START * 1_000_000)]), "BTC/USD", request(), now_ms=START + 10000)


@pytest.mark.anyio
async def test_later_page_error_or_cancellation_never_publishes_prefix(monkeypatch):
    import asyncio
    monkeypatch.setattr(provider, "PAGE_SIZE", 1)
    class Failing(Exchange):
        async def public_get_trades(self, params):
            if self.calls:
                raise self.failure
            return await super().public_get_trades(params)
    for failure in (RuntimeError("network lost"), asyncio.CancelledError()):
        ex = Failing([page([trade(1, START)], START * 1_000_000)])
        ex.failure = failure
        with pytest.raises(type(failure)):
            await fetch_kraken_trade_candles(ex, "BTC/USD", request(), now_ms=START + 10000)


def test_gc_keeps_protected_adjacent_trade_empty_evidence(storage):
    start = START // 7000 * 7000
    key = ("kraken", "spot", "BTC/USD", "7s")
    rows = [dict(open_time=t, close_time=t+6999, open=10, high=10, low=10, close=10, volume=1, quote_volume=0, trades=0, taker_buy_base=0, taker_buy_quote=0) for t in (start, start+21000)]
    storage.upsert_bars("BTC/USD", "7s", rows, "trade_history_verified", "kraken", "spot")
    trade_empty_buckets.record(*key, [[start-7000, start-7000], [start+7000, start+14000]])
    count = klines_repo.delete_oldest_klines_batch("BTC/USD", "7s", keep=0, batch_size=10, exchange="kraken", market_type="spot", delete_before_ms=start+7000)
    assert count == 1
    assert trade_empty_buckets.read(*key, start-7000, start+21000) == [(start+7000, start+14000)]
