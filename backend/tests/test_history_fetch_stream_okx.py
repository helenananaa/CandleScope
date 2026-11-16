"""Qualified OKX REST receipts, reverse pages and the native range writer fence."""
import asyncio
import time

import ccxt.async_support as ccxt
import pytest

from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillStatus, FetchReceipt
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import RawMessage,DataSource,StreamType,StreamDescriptor
from app.data_engine.storage import kline_sources
from app.data_engine.storage.revisions import acquisition_scope
from app.exchanges.ccxt_ext.fork_kline import prepare_source_messages
from tests.test_ccxt_source_extensions import SPOT,qualified_fork
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_plan import engine_for

START = 1772323200000
STEP = 60_000


@pytest.mark.parametrize('mutation', ['none','append','delete','amend'])
def test_reverse_receipted_pages_keep_unknown_fields_and_do_not_renew_invalidated_permission(mixed_query,mutation):
    class Transport:
        def __init__(self):
            self.parser = ccxt.okx()
            self.parser.set_markets([SPOT])
            self.calls = 0

        async def http_fetch(self,request):
            self.calls += 1
            if self.calls == 2 and mutation != 'none':
                with acquisition_scope(None):
                    if mutation == 'delete':
                        mixed_query.storage.delete_bars('BTC-USDT','1m',START+31*STEP,START+31*STEP,
                            exchange='okx',market_type='spot')
                    elif mutation == 'amend':
                        # The native projection correctly refuses an unsourced
                        # manual overwrite. Exercise an actual external SQL
                        # mutation, including the existing revision triggers.
                        from app.data_engine.storage import klines_repo
                        with klines_repo._connect() as conn:
                            conn.execute("UPDATE klines SET volume=91 WHERE exchange='okx' AND market_type='spot' "
                                "AND symbol='BTC-USDT' AND interval='1m' AND open_time=?",(START+31*STEP,))
                    else:
                        at = START+200*STEP
                        mixed_query.storage.upsert_bars('BTC-USDT','1m',[dict(open_time=at,
                            close_time=at+STEP-1,open=100,high=103,low=99,close=102,volume=1,
                            quote_volume=102,trades=None,taker_buy_base=None,taker_buy_quote=None)],
                            source='data_manager_closed',exchange='okx',market_type='spot')
            times = [START+i*STEP for i in range(32)
                     if request.start_ms <= START+i*STEP <= request.end_ms]
            messages = [RawMessage(self.parser.parse_candlescope_kline([
                str(at),'100.00000001','103.1','99.3','102.2','0.12345678','0','12.3456789','1'],
                SPOT,'1m'),DataSource.HTTP,StreamType.KLINE,int(time.time()*1000))
                for at in sorted(times,reverse=True)[:11]]
            await prepare_source_messages(messages,request.descriptor,
                watermark=kline_sources.rest_watermark(),history_projection=request.history_projection)
            return messages

    async def check():
        engine = engine_for(mixed_query)
        engine.config.fetch_batch_size = 1000
        engine.config.fetch_okx_rate_limit_delay = 0
        transport = Transport()
        engine._fetcher = HistoricalFetcher(engine.config,transport,IngestionConfig())
        # This controlled transport tests source receipts and writer fencing,
        # not endpoint quota. Quota/deferral has its own real admission cases.
        async def no_network_quota(): pass
        engine._fetcher.set_rate_limiter(no_network_quota)
        report = await engine.run_receipt('BTC-USDT',intervals=['1m'],range_start_ms=START,
            range_end_ms=START+31*STEP,exchange='okx',market_type='spot',metadata=dict(
                requester='klines_range',history_calendar_id='crypto.24x7.utc',requires_trusted_finality=True))
        assert report.metadata['fetch_payload_mode'] == 'receipt'
        assert all(isinstance(item,FetchReceipt) for item in report.fetch_results)
        rows = mixed_query.storage.query_bars('BTC-USDT','1m',START,START+31*STEP,
            limit=100,exchange='okx',market_type='spot')
        if mutation in {'none','append'}:
            assert report.status == BackfillStatus.COMPLETED, report.errors
            assert len(rows) == report.reconcile_result.bars_written == 32
            assert report.fetch_results[0].pages_fetched == 3
            descriptor = StreamDescriptor('BTC-USDT',StreamType.KLINE,interval='1m',exchange='okx',market_type='spot')
            assert not kline_sources.pending(descriptor,include_history=True)
        else:
            assert report.status == BackfillStatus.PARTIAL and report.reconcile_result.write_errors
            assert len(rows) == (10 if mutation == 'delete' else 11)
            if mutation == 'delete': assert all(row['open_time'] != START+31*STEP for row in rows)
            else: assert next(row for row in rows if row['open_time'] == START+31*STEP)['volume'] == 91
        for row in rows:
            if mutation != 'amend' or row['open_time'] != START+31*STEP:
                assert (row['open'],row['high'],row['low'],row['close'],row['volume'],row['quote_volume']) == (
                    100.00000001,103.1,99.3,102.2,0.12345678,12.3456789)
            assert all(row[name] is None for name in ('trades','taker_buy_base','taker_buy_quote'))
        assert mixed_query.memory_budget.snapshot()['reserved_bytes'] == 0
        await engine.close()
        await transport.parser.close()
    asyncio.run(check())
