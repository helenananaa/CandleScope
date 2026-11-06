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
    monkeypatch.setattr(plugin.provider, '_rest_pool', lambda _venue, _config: Pool(exchange))
    return plugin


def test_native_seconds_are_market_scoped():
    registry = bootstrap_default_adapters()
    for exchange, market in [('binance', 'spot'), ('okx', 'spot'), ('okx', 'futures'), ('gate', 'spot'), ('upbit', 'spot')]:
        assert '1s' in registry.get_capabilities(exchange).kline_intervals(market, history=True)
    for exchange, market in [('binance', 'futures'), ('gate', 'swap.linear'), ('bybit', 'spot'), ('kraken', 'spot')]:
        assert '1s' not in registry.get_capabilities(exchange).kline_intervals(market, history=True)
    gate = registry.get_plugin('gate')
    assert not gate.supports_provider_stream(descriptor('gate'))
    assert gate.create_stream_session(IngestionConfig(), descriptor('gate')) is None


@pytest.mark.anyio
@pytest.mark.parametrize('mixed', [False, True])
@pytest.mark.parametrize('interval', ['1s', '7s'])
async def test_closed_source_second_gap_waits_for_local_close_instead_of_finishing_without_fetch(
    sparse_storage, monkeypatch, tmp_path, mixed, interval,
):
    from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator, RepairRequest
    from app.data_engine.storage.gap_ledger import GapLedger
    from tests.test_backfill_coordinator import _DataManager, _RepairReport, _ReconcileResult
    width = int(interval[:-1]) * 1000
    target = NOW // width * width
    clock = [target + width - 500]
    monkeypatch.setattr('app.data_engine.data_manager.backfill_history.time.time', lambda: clock[0] / 1000)
    class Engine:
        def __init__(self): self.calls = []
        async def run(self, **kwargs):
            self.calls.append(kwargs)
            rows = [{**row(at), 'close_time': at + width - 1,
                     'open': 11, 'high': 11, 'low': 11, 'close': 11, 'volume': 0}
                    for at in range(kwargs['range_start_ms'], kwargs['range_end_ms'] + 1, width)]
            sparse_storage.upsert_bars('BTC/USDT', interval, rows, 'backfill', exchange='gate', market_type='spot')
            return _RepairReport(status='completed', reconcile_result=_ReconcileResult(bars_written=len(rows)))
    engine, dm = Engine(), _DataManager()
    ledger = GapLedger(tmp_path / 'bars.sqlite')
    coordinator = BackfillCoordinator(storage=sparse_storage, bars_backfilled=dm.on_bars_backfilled,
        emit_event=dm.event_bus.emit, engine=engine, gap_ledger=ledger, loop=asyncio.get_running_loop())
    request = RepairRequest(symbol='BTC/USDT', interval=interval, exchange='gate', market_type='spot',
        start_ms=target - width if mixed else target, end_ms=target, reason='tail_gap', requester='ingestion_gap',
        metadata={'source_gap_id': 'confirmed-successor', 'requires_trusted_finality': True})
    task = asyncio.create_task(coordinator.request_and_wait(request))
    try:
        await asyncio.sleep(.05)
        assert not task.done(), 'a temporary forming exclusion must not settle source repair'
        assert not engine.calls
        clock[0] = target + width + 500
        outcome = await asyncio.wait_for(task, 2)
        assert outcome.verified_contiguous is True and not outcome.retryable and outcome.attempts == 1
        stored = sparse_storage.query_bars('BTC/USDT', interval, start_ms=target, end_ms=target,
                                          exchange='gate', market_type='spot')
        assert len(stored) == 1 and stored[0]['volume'] == 0
        assert len(engine.calls) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await coordinator.shutdown()


@pytest.mark.anyio
async def test_gate_closed_zero_volume_row_survives_real_normalization_and_fetcher(monkeypatch):
    class Exchange:
        def market(self, _): return {'id': 'BTC_USDT'}
        async def publicSpotGetCandlesticks(self, _params):
            return [[str(START // 1000), '0.0', '11', '11', '11', '11', '0.0', 'true']]
    plugin = bind(monkeypatch, CcxtUnifiedPlugin(get_ccxt_catalog_entry('gate')), Exchange())
    class Transport:
        async def http_fetch(self, request):
            return await plugin.fetch_history_with_config(request, IngestionConfig())
    fetcher = HistoricalFetcher(BackfillConfig(history_archive_enabled=False), Transport())
    result = (await fetcher.fetch([BackfillTask(symbol='BTC/USDT', interval='1s',
        start_ms=START, end_ms=START, exchange='gate', market_type='spot', estimated_bars=1)]))[0]
    assert result.status.value == 'completed', result.errors
    assert len(result.bars) == 1
    assert result.bars[0].open_time == START and result.bars[0].volume == 0


@pytest.mark.anyio
async def test_delayed_source_second_repair_resolves_actual_gap_registry(sparse_storage, monkeypatch):
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.models import SeriesKey
    from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
    from tests.test_backfill_coordinator import _RepairReport, _ReconcileResult
    clock = [NOW + 500]
    monkeypatch.setattr('app.data_engine.data_manager.backfill_history.time.time', lambda: clock[0] / 1000)
    dm = DataManager()
    dm.set_storage(sparse_storage)
    class Engine:
        async def run(self, **kwargs):
            sparse_storage.upsert_bars('BTC/USDT', '1s', [row(NOW)], 'backfill', exchange='gate')
            return _RepairReport(status='completed', reconcile_result=_ReconcileResult(bars_written=1))
    async def loaded(*args, **kwargs): pass
    coordinator = BackfillCoordinator(storage=sparse_storage, bars_backfilled=loaded,
        emit_event=dm.event_bus.emit, source_available=dm.source_storage_available,
        engine=Engine(), loop=asyncio.get_running_loop())
    dm.set_backfill_trigger(coordinator.trigger)
    key = SeriesKey('BTC/USDT', '1s', exchange='gate')
    try:
        await dm._open_source_gap(key, NOW, NOW)
        gap = dm.source_gaps.pending(key)[0]
        await asyncio.sleep(.05)
        assert gap.completed_at is None
        clock[0] = NOW + 1500
        await asyncio.wait_for(asyncio.shield(gap.future), 2)
        assert gap.completed_at is not None and gap.error is None
        assert dm.source_gaps.pending(key) == []
    finally:
        await coordinator.shutdown()
        dm.source_gaps.close()
        await dm.event_bus.close()
        await dm.shutdown()


@pytest.mark.anyio
async def test_binance_ordinary_route_does_not_alias_continuous_seconds(monkeypatch):
    from app.data_engine.interval_resolution import IntervalResolver, IntervalResolutionError
    with pytest.raises(IntervalResolutionError):
        IntervalResolver().resolve(exchange="binance", market_type="futures", interval="1s", purpose="history")
    calls = []
    class Exchange:
        def market(self, _): return {"id": "BTCUSDT"}
        async def fapipublic_get_continuousklines(self, params):
            raise AssertionError("ordinary market must never request continuous contracts")
        async def fapipublic_get_klines(self, params):
            calls.append(params); return []
    plugin = bind(monkeypatch, create_binance_ccxt_plugin(), Exchange())
    req = TransportRequest(StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m", exchange="binance", market_type="futures"), limit=10, start_ms=START, end_ms=NOW)
    await plugin.fetch_history_with_config(req, IngestionConfig(ccxt_fork_kline_enabled=False))
    assert calls[0]["symbol"] == "BTCUSDT" and calls[0]["interval"] == "1m"


def test_continuous_ws_is_not_an_ordinary_contract_candle():
    d = descriptor("binance", "futures", "BTCUSDT")
    normalizer = BinanceNormalizer(IngestionConfig(), d)
    payload = {"e": "continuous_kline", "E": NOW, "ps": "BTCUSDT", "ct": "PERPETUAL",
               "k": {"t": START, "T": START + 999, "i": "1s", "o": "10", "h": "12", "l": "9", "c": "11", "v": "2", "x": True}}
    assert normalizer.parse(RawMessage(payload, DataSource.WEBSOCKET, StreamType.KLINE, NOW)) is None


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
    monkeypatch.setattr('app.exchanges.ccxt_ext.history.time.time', lambda: NOW / 1000)
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


@pytest.mark.parametrize('purpose', ['history', 'realtime'])
def test_gate_minute_admission_and_captured_rows_preserve_native_boundaries(purpose):
    import json
    from pathlib import Path
    from app.data_engine.bar_basis import native_bar_spec
    from app.data_engine.interval_resolution import IntervalResolver
    from app.data_engine.ingestion.normalize import NormalizeLayer
    from app.exchanges.ccxt_ext.unified import CcxtUnifiedNormalizer, CCXT_UNIFIED_MARKER
    fixture = json.loads((Path(__file__).parent / 'fixtures/bar_basis/gate-1m-rest.json').read_text())
    route = IntervalResolver().resolve(exchange='gate', market_type='spot', interval='1m', purpose=purpose)
    assert route.is_native and route.source_interval == '1m'
    contract = native_bar_spec('gate', 'spot', '1m', purpose)
    contract.validate(1606292580000, 1606292639999)  # Official WS 1m example.
    with pytest.raises(ValueError, match='boundary_mismatch'):
        contract.validate(1606292581000, 1606292640999)
    descriptor = StreamDescriptor('BTC/USDT', StreamType.KLINE, interval='1m', exchange='gate')
    layer = NormalizeLayer(IngestionConfig(), descriptor)
    layer._normalizer = CcxtUnifiedNormalizer(descriptor)
    source = DataSource.HTTP_BACKFILL if purpose == 'history' else DataSource.WEBSOCKET
    for raw in fixture['body']:
        at = int(raw[0])*1000
        unified = [at, float(raw[5]), float(raw[3]), float(raw[4]), float(raw[2]), float(raw[6])]
        message = RawMessage(payload={'schema': CCXT_UNIFIED_MARKER, 'kind': 'kline',
            'value': unified, 'is_closed': raw[7] == 'true'}, source=source,
            stream_type=StreamType.KLINE, received_at_ms=fixture['captured_at_ms'])
        events = layer.parse_all(message)
        assert len(events) == 1
        bar = events[0].data
        assert (bar['open_time'], bar['close_time']) == (at, at+59999)
        assert (bar['open'], bar['high'], bar['low'], bar['close'], bar['volume']) == tuple(unified[1:])
        assert bar['is_closed'] is (raw[7] == 'true')
        assert bar['basis_qualification'] == 'fixture_verified'
    # This evidence qualifies neither Gate calendar periods nor other markets/venues.
    for exchange, market, interval in [('gate', 'spot', '7d'), ('gate', 'spot', '30d'),
                                        ('gate', 'swap.linear', '1m'), ('upbit', 'spot', '1m')]:
        assert native_bar_spec(exchange, market, interval, purpose).qualification == 'unknown'
