"""Native 1s routing, pagination, finality and durable sparse history."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillTask
from app.data_engine.data_manager.cache import BarCache
from app.data_engine.data_manager.config import QueryConfig
from app.data_engine.data_manager.query import QueryEngine
from app.data_engine.history.native_seconds import native_second_history_start
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType, TransportRequest
from app.data_engine.storage import klines_repo, native_empty_seconds
from app.exchanges.ccxt_ext.binance_usdm import CandleScopeBinanceUSDM
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.generic import CcxtUnifiedPlugin, CcxtUnifiedProfile
from app.exchanges.ccxt_ext.primary import create_binance_ccxt_plugin
from app.exchanges.ccxt_ext.profiles.binance_usdm import BinanceUsdmCcxtProfile
from app.exchanges.ccxt_ext.unified import CcxtUnifiedProjector
from app.exchanges.plugins.binance.normalizer import BinanceNormalizer
from app.exchanges.registry import bootstrap_default_adapters
from ccxt.pro.binanceusdm import binanceusdm as CcxtBinanceUSDM

NOW = 1_793_232_000_000  # 2026-10-29 UTC
START = NOW - 10_000


def descriptor(exchange, market='spot', symbol='BTC/USDT'):
    return StreamDescriptor(symbol, StreamType.KLINE, interval='1s', exchange=exchange, market_type=market)


class Pool:
    def __init__(self, exchange):
        self.exchange = exchange

    @asynccontextmanager
    async def request(self, selection):
        yield self.exchange

    async def resolve_symbol(self, *args, **kwargs):
        return 'BTC/USDT'


def bind(monkeypatch, plugin, exchange):
    monkeypatch.setattr(plugin, '_rest_pool', lambda _: Pool(exchange))
    return plugin


def test_native_seconds_are_market_scoped():
    registry = bootstrap_default_adapters()
    for exchange, market in [('binance', 'spot'), ('binance', 'futures'), ('okx', 'spot'), ('okx', 'futures'), ('gate', 'spot'), ('upbit', 'spot')]:
        assert '1s' in registry.get_capabilities(exchange).kline_intervals(market, history=True)
    for exchange, market in [('gate', 'swap.linear'), ('bybit', 'spot'), ('kraken', 'spot')]:
        assert '1s' not in registry.get_capabilities(exchange).kline_intervals(market, history=True)
    gate = registry.get_plugin('gate')
    assert not gate.supports_provider_stream(descriptor('gate'))
    assert gate.create_stream_session(IngestionConfig(), descriptor('gate')) is None


@pytest.mark.anyio
async def test_binance_continuous_rest_does_not_change_minute_route(monkeypatch):
    calls = []
    class Exchange:
        def market(self, _): return {'id': 'BTCUSDT'}
        async def fapipublic_get_continuousklines(self, params):
            calls.append(('continuous', params)); return []
        async def fapipublic_get_klines(self, params):
            calls.append(('ordinary', params)); return []
    plugin = bind(monkeypatch, create_binance_ccxt_plugin(), Exchange())
    req = TransportRequest(descriptor('binance', 'futures', 'BTCUSDT'), limit=10, start_ms=START, end_ms=NOW)
    await plugin.fetch_history_with_config(req, IngestionConfig())
    assert calls[0] == ('continuous', {'pair': 'BTCUSDT', 'contractType': 'PERPETUAL', 'interval': '1s', 'limit': 10, 'startTime': START, 'endTime': NOW})
    req.descriptor = StreamDescriptor('BTCUSDT', StreamType.KLINE, interval='1m', market_type='futures')
    await plugin.fetch_history_with_config(req, IngestionConfig())
    assert calls[1][0] == 'ordinary' and calls[1][1]['symbol'] == 'BTCUSDT'


def test_continuous_ws_preserves_raw_finality_and_rejects_wrong_contract(monkeypatch):
    projected, captured = [], []
    monkeypatch.setattr(CcxtBinanceUSDM, 'handle_ohlcv', lambda self, client, msg: projected.append(msg))
    driver = CandleScopeBinanceUSDM(raw_event_sink=captured.append)
    payload = {'e': 'continuous_kline', 'E': NOW, 'ps': 'BTCUSDT', 'ct': 'PERPETUAL',
               'k': {'t': START, 'T': START + 999, 'i': '1s', 'o': '10', 'h': '12', 'l': '9', 'c': '11', 'v': '2', 'q': '22', 'n': 3, 'V': '1', 'Q': '11', 'x': True}}
    driver.handle_message(None, {'stream': 'btcusdt_perpetual@continuousKline_1s', 'data': payload})
    assert captured[0].payload == payload and 's' not in payload['k']
    assert projected[0]['k']['s'] == 'BTCUSDT'
    d = descriptor('binance', 'futures', 'BTCUSDT')
    assert BinanceUsdmCcxtProfile().matches(captured[0], d)
    normalizer = BinanceNormalizer(IngestionConfig(), d)
    msg = RawMessage(payload, DataSource.WEBSOCKET, StreamType.KLINE, NOW)
    event = normalizer.parse(msg)
    assert event.data['is_closed'] and event.data['trades'] == 3
    for mutation in ({'ct': 'CURRENT_QUARTER'}, {'ps': 'ETHUSDT'}):
        msg.payload = {**payload, **mutation}
        assert normalizer.parse(msg) is None


@pytest.mark.anyio
async def test_gate_range_omits_limit_and_preserves_confirmation(monkeypatch):
    calls = []
    class Exchange:
        def market(self, _): return {'id': 'BTC_USDT'}
        async def publicSpotGetCandlesticks(self, params):
            calls.append(params)
            return [[str(START // 1000), '22', '11', '12', '9', '10', '2', 'true'],
                    [str(START // 1000 + 1), '0', '11', '11', '11', '11', '0', 'false']]
    plugin = bind(monkeypatch, CcxtUnifiedPlugin(get_ccxt_catalog_entry('gate')), Exchange())
    result = await plugin.fetch_history_with_config(TransportRequest(descriptor('gate'), limit=1000, start_ms=START + 1, end_ms=START + 5000), IngestionConfig())
    assert calls == [{'currency_pair': 'BTC_USDT', 'interval': '1s', 'from': START // 1000 + 1, 'to': START // 1000 + 5}]
    assert result[0].payload['value'] == [START, '10', '12', '9', '11', '2']
    assert result[0].payload['is_closed'] is True
    assert result[1].payload['is_closed'] is False
    with pytest.raises(ValueError, match='only for spot'):
        await plugin.fetch_history_with_config(TransportRequest(descriptor('gate', 'swap.linear')), IngestionConfig())


class Upbit:
    def __init__(self): self.calls = []
    def market(self, _): return {'id': 'KRW-BTC'}
    async def public_get_candles_seconds(self, params):
        self.calls.append(params)
        until = int(datetime.fromisoformat(params['to']).timestamp() * 1000)
        # Entire second page is empty; third page must still be fetched.
        return [{'market': 'KRW-BTC', 'candle_date_time_utc': datetime.fromtimestamp(t / 1000, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
                 'opening_price': 10, 'high_price': 12, 'low_price': 9, 'trade_price': 11, 'candle_acc_trade_volume': 2}
                for t in (START + 6000, START) if t < until][:params['count']]


@pytest.mark.anyio
async def test_upbit_bounded_pages_continue_through_empty_window(monkeypatch):
    monkeypatch.setattr('app.exchanges.ccxt_ext.generic.time.time', lambda: NOW / 1000)
    upstream = Upbit()
    plugin = bind(monkeypatch, CcxtUnifiedPlugin(get_ccxt_catalog_entry('upbit')), upstream)
    class Transport:
        async def http_fetch(self, req): return await plugin.fetch_history_with_config(req, IngestionConfig())
    fetcher = HistoricalFetcher(BackfillConfig(fetch_batch_size=3, fetch_rate_limit_delay=0, history_archive_enabled=False), Transport(), IngestionConfig())
    async def no_rate_limit(): pass
    fetcher.set_rate_limiter(no_rate_limit)
    result = (await fetcher.fetch([BackfillTask(symbol='BTC/KRW', interval='1s', start_ms=START, end_ms=START + 8000, exchange='upbit', market_type='spot', estimated_bars=9)]))[0]
    assert result.status.value == 'completed', result.errors
    assert [b.open_time for b in result.bars] == [START, START + 6000]
    assert len(upstream.calls) == 3
    assert result.metadata['native_empty_ranges'] == [[START + 1000, START + 2000], [START + 3000, START + 5000], [START + 7000, START + 8000]]


@pytest.mark.anyio
async def test_upbit_single_ws_row_reaches_projector():
    d = descriptor('upbit', symbol='BTC/KRW')
    profile = CcxtUnifiedProfile(get_ccxt_catalog_entry('upbit'), 'spot')
    class Exchange:
        async def watch_ohlcv(self, *_): return [START, 10, 12, 9, 11, 2]
    value = await profile.watch(Exchange(), d, 'BTC/KRW')
    projector = CcxtUnifiedProjector(exchange_id='upbit', market_type='spot', descriptor=d)
    assert projector.project(value)[0].payload['value'][0] == START
    closed = projector.project([[START + 3000, 11, 11, 11, 11, 1]])
    assert closed[0].payload['is_closed'] and closed[0].payload['value'][0] == START


@pytest.fixture
def sparse_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', tmp_path / 'bars.sqlite')
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def row(open_ms):
    return dict(open_time=open_ms, close_time=open_ms + 999, open=10, high=12, low=9, close=11, volume=2, quote_volume=0, trades=0, taker_buy_base=0, taker_buy_quote=0)


def test_sparse_evidence_cannot_hide_deleted_real_candle(sparse_storage):
    store = sparse_storage
    store.upsert_bars('BTC/KRW', '1s', [row(START), row(START + 6000)], 'backfill', exchange='upbit')
    native_empty_seconds.record('BTC/KRW', [(START + 1000, START + 5000), (START + 7000, START + 8000)])
    assert store.verify_contiguous_range('BTC/KRW', '1s', START, START + 8000, exchange='upbit')['verified_contiguous']
    engine = QueryEngine(cache=BarCache(), storage=store, config=QueryConfig(auto_backfill=False))
    result = engine.query('BTC/KRW', '1s', START, START + 8000, exchange='upbit')
    assert result.complete and len(result.bars) == 2 and not result.missing_ranges
    page = engine.query_before('BTC/KRW', '1s', before_ms=START + 9000, limit=2, exchange='upbit')
    assert [bar.time_ms for bar in page.bars] == [START, START + 6000]
    assert page.complete
    assert not klines_repo.scan_klines_gaps('BTC/KRW', '1s', START, START + 8000, exchange='upbit')['gaps']
    # Simulate a missing real row, bypassing explicit user deletion cleanup.
    with klines_repo._connect() as conn:
        conn.execute("DELETE FROM klines WHERE open_time = ?", (START + 6000,)); conn.commit()
    assert not store.verify_contiguous_range('BTC/KRW', '1s', START, START + 8000, exchange='upbit')['verified_contiguous']
    fresh = QueryEngine(cache=BarCache(), storage=store, config=QueryConfig(auto_backfill=False))
    assert not fresh.query('BTC/KRW', '1s', START, START + 8000, exchange='upbit').complete


def test_all_empty_window_has_no_fabricated_bars(sparse_storage):
    native_empty_seconds.record('BTC/KRW', [(START, START + 8000)])
    result = QueryEngine(cache=BarCache(), storage=sparse_storage, config=QueryConfig(auto_backfill=False)).query('BTC/KRW', '1s', START, START + 8000, exchange='upbit')
    assert result.complete and result.bars == []
    assert sparse_storage.verify_contiguous_range('BTC/KRW', '1s', START, START + 8000, exchange='upbit')['verified_contiguous']
    assert not sparse_storage.verify_contiguous_range('BTC/KRW', '1s', START, START + 9000, exchange='upbit')['verified_contiguous']


def test_retention_is_calendar_months_and_only_seconds():
    now = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
    expected = int(datetime(2026, 2, 28, tzinfo=timezone.utc).timestamp() * 1000)
    assert native_second_history_start('okx', '1s', now) == expected
    assert native_second_history_start('upbit', '1s', now) == expected
    assert native_second_history_start('okx', '1m', now) is None
    assert native_second_history_start('binance', '1s', now) is None


def test_user_delete_and_retention_clear_empty_evidence(sparse_storage):
    store = sparse_storage
    store.upsert_bars('BTC/KRW', '1s', [row(START), row(START + 6000), row(START + 9000)], 'backfill', exchange='upbit')
    native_empty_seconds.record('BTC/KRW', [(START + 1000, START + 5000), (START + 7000, START + 8000)])
    assert klines_repo.delete_oldest_klines_batch('BTC/KRW', '1s', keep=1, batch_size=10, exchange='upbit') == 2
    assert native_empty_seconds.read('BTC/KRW', START, START + 8000) == [(START + 7000, START + 8000)]
    klines_repo.delete_klines('BTC/KRW', '1s', exchange='upbit')
    assert native_empty_seconds.read('BTC/KRW', START, START + 8000) == []


def test_late_native_candle_invalidates_empty_evidence(sparse_storage):
    native_empty_seconds.record('BTC/KRW', [(START, START + 8000)])
    calendar = native_empty_seconds.make_calendar('BTC/KRW')
    assert calendar.first_expected_open(START, START + 8000, '1s') is None
    assert sparse_storage.upsert_bars('BTC/KRW', '1s', [row(START + 3000)], 'backfill', exchange='upbit') == 1
    assert calendar.first_expected_open(START, START + 8000, '1s') == START
    assert not sparse_storage.verify_contiguous_range('BTC/KRW', '1s', START, START + 8000, exchange='upbit')['verified_contiguous']


@pytest.mark.anyio
async def test_failed_upbit_page_cannot_create_empty_evidence(monkeypatch):
    monkeypatch.setattr('app.exchanges.ccxt_ext.generic.time.time', lambda: NOW / 1000)
    class Invalid(Upbit):
        async def public_get_candles_seconds(self, params):
            return [{'market': 'KRW-BTC', 'candle_date_time_utc': 'bad timestamp'}]
    plugin = bind(monkeypatch, CcxtUnifiedPlugin(get_ccxt_catalog_entry('upbit')), Invalid())
    class Transport:
        async def http_fetch(self, req): return await plugin.fetch_history_with_config(req, IngestionConfig())
    fetcher = HistoricalFetcher(BackfillConfig(history_archive_enabled=False), Transport(), IngestionConfig())
    async def no_rate_limit(): pass
    fetcher.set_rate_limiter(no_rate_limit)
    result = (await fetcher.fetch([BackfillTask(symbol='BTC/KRW', interval='1s', start_ms=START, end_ms=START + 8000, exchange='upbit', market_type='spot')]))[0]
    assert result.status.value == 'failed'
    assert result.metadata['native_empty_ranges'] == []


def test_manual_plan_clamps_only_native_second_retention():
    from app.data_engine.manual_history.planner import ManualHistoryPlanner
    planner = ManualHistoryPlanner(clock_ms=lambda: NOW, disk_snapshot=lambda: {'free_bytes': 10**12, 'physical_size_bytes': 0}, archive_enabled=False)
    plan = planner.plan(exchange='okx', market_type='spot', symbols=['BTC-USDT'], intervals=['1s'], start_ms=NOW - 200 * 86400000)
    target = plan['targets'][0]
    assert target['boundary_reason'] == 'provider_retention'
    assert target['effective_start_ms'] == native_second_history_start('okx', '1s', NOW)


def test_retention_preserves_protected_empty_prefix(sparse_storage):
    store = sparse_storage
    store.upsert_bars('BTC/KRW', '1s', [row(START), row(START + 6000)], 'backfill', exchange='upbit')
    native_empty_seconds.record('BTC/KRW', [(START + 1000, START + 5000)])
    assert klines_repo.delete_oldest_klines_batch('BTC/KRW', '1s', keep=1, batch_size=10, delete_before_ms=START + 1000, exchange='upbit') == 1
    assert store.verify_contiguous_range('BTC/KRW', '1s', START + 1000, START + 6000, exchange='upbit')['verified_contiguous']


def test_partial_delete_preserves_adjacent_empty_evidence(sparse_storage):
    native_empty_seconds.record('BTC/KRW', [(START, START + 8000)])
    klines_repo.delete_klines('BTC/KRW', '1s', start_ms=START + 3000, end_ms=START + 4000, exchange='upbit')
    assert native_empty_seconds.read('BTC/KRW', START, START + 8000) == [(START, START + 2000), (START + 5000, START + 8000)]
