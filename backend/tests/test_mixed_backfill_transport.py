"""Cold mixed repairs through real CCXT HTTP sockets and canonical writers."""
import asyncio
import time
import pytest

from aiohttp import web

from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillStatus
from app.data_engine.backfill.models import FetchReceipt, FetchResult
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.transport import TransportLayer
from app.data_engine.interval_policy import parse_interval_ms
from app.exchanges.rate_limits import RateLimitDeferred
from app.exchanges.ccxt_ext import generic
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_pipeline import repair
from tests.test_mixed_backfill_plan import engine_for
from tests.test_public_transport_loopback import serve, point_at_loopback


@pytest.mark.parametrize('mode,batch', [('full',1000),('receipt',1000),('full',32),('receipt',32)])
def test_cold_mixed_pipeline_uses_real_ccxt_transport_and_preserves_all_fields(mixed_query, monkeypatch, mode, batch):
    async def run():
        calls = []
        async def handle(request):
            calls.append((request.path, dict(request.query)))
            if request.path.endswith('/time'):
                return web.json_response({'serverTime': int(time.time() * 1000)})
            if request.path.endswith('/exchangeInfo'):
                return web.json_response({'symbols': [{
                    'symbol': 'BTCUSDT', 'pair': 'BTCUSDT', 'contractType': 'PERPETUAL',
                    'status': 'TRADING', 'baseAsset': 'BTC', 'quoteAsset': 'USDT',
                    'marginAsset': 'USDT', 'pricePrecision': 2, 'quantityPrecision': 3,
                    'filters': [], 'orderTypes': ['LIMIT', 'MARKET'],
                }]})
            assert request.path == '/fapi/v1/klines'
            assert request.query['symbol'] == 'BTCUSDT'
            width = parse_interval_ms(request.query['interval'])
            first, last = int(request.query.get('startTime', 0)), int(request.query['endTime'])
            first = (first+width-1)//width*width
            limit = int(request.query['limit'])
            return web.json_response([[at, '100', '102', '99', '101', str(width // 60000),
                at + width - 1, str(2 * width // 60000), width // 60000,
                str(width // 60000), str(2 * width // 60000), '0']
                for at in list(range(first, last + 1, width))[:limit]])
        runner, origin = await serve(handle)
        original = generic._create_exchange
        def create(*args, **kwargs):
            exchange = original(*args, **kwargs)
            point_at_loopback(exchange, origin)
            return exchange
        monkeypatch.setattr(generic, '_create_exchange', create)
        config = IngestionConfig(proxy_mode='none', proxy_egress_group='mixed-cold-loopback')
        transport = TransportLayer(config)
        engine = engine_for(mixed_query)
        engine.config.fetch_batch_size = batch
        engine._fetcher = HistoricalFetcher(engine.config, transport, config)
        try:
            async def wait_repair():
                for _ in range(100):
                    try:
                        if mode == 'full':
                            return await repair(engine)
                        from tests.test_mixed_backfill_pipeline import META
                        return await engine.run_receipt('BTCUSDT', intervals=['10007m'],
                            range_start_ms=0,range_end_ms=0,exchange='binance',market_type='futures',metadata=META)
                    except RateLimitDeferred as exc:
                        # The normal scheduler relinquishes its slot while the
                        # shared metadata task continues. Model that retry here.
                        await asyncio.sleep(max(.01, exc.retry_after_seconds))
                raise AssertionError('metadata never became available')
            report = await asyncio.wait_for(wait_repair(), 30)
            assert report.status == BackfillStatus.COMPLETED, report.errors
            assert report.reconcile_result.custom_bars_written == 1
            pages = [query for path, query in calls if path == '/fapi/v1/klines']
            assert len(pages) == (2 if batch == 1000 else 4)
            assert {q['interval'] for q in pages} == (
                {'15m', '1m'} if batch == 1000 else {'1d', '1h', '1m'})
            assert sum(path.endswith('/exchangeInfo') for path, _ in calls) == 1
            if mode == 'receipt':
                assert report.metadata['fetch_payload_mode'] == 'receipt'
                assert all(isinstance(item,FetchReceipt) and not hasattr(item,'bars') for item in report.fetch_results)
                assert report.metadata['stream_reconciliation']['native_pages'] == len(pages)
            else:
                assert all(isinstance(item,FetchResult) and len(item.bars) == item.bars_count for item in report.fetch_results)
            result = mixed_query.query('BTCUSDT', '10007m', start_ms=0,
                end_ms=10007 * 60000 - 1, limit=1, market_type='futures',
                min_revision=mixed_query.storage.revision_store.head())
            assert result.complete and result.bars[0].trusted_final
            bar = result.bars[0]
            assert (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.quote_volume,
                bar.trades, bar.taker_buy_base, bar.taker_buy_quote) == (
                    100, 102, 99, 101, 10007, 20014, 10007, 10007, 20014)
            assert mixed_query.storage.count_bars('BTCUSDT', '1m', 0, 10007 * 60000 - 1,
                market_type='futures') == (2 if batch == 1000 else 47)
        finally:
            await engine.close()
            await transport.stop()
            await runner.cleanup()
    asyncio.run(run())
