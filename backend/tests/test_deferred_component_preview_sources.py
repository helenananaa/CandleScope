"""Actual CCXT/OKX receipts through the default DataManager preview path."""
import asyncio
import threading

import ccxt.async_support as ccxt
import pytest

from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillTask
from app.data_engine.data_manager.models import DataEventType
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType
from app.data_engine.storage import klines_repo, kline_sources
from app.exchanges.ccxt_ext.fork_kline import normalize_fork_kline, prepare_source_messages
from tests.test_ccxt_source_extensions import SPOT
from tests.test_shared_blocks_integration import dm


@pytest.mark.parametrize('mutation', ['none', 'superseded', 'delete', 'external', 'cancel', 'detach'])
def test_actual_receipts_validate_before_delayed_publication(dm, monkeypatch, mutation):
    clock = [361000]
    monkeypatch.setattr('time.time', lambda: clock[0]/1000)
    exchange = ccxt.okx()
    exchange.set_markets([SPOT])
    desc = StreamDescriptor('BTC-USDT', StreamType.KLINE, interval='1m', exchange='okx', market_type='spot')

    async def source(opened, volume, closed=False):
        row = [str(opened), '100', '103', '99', '102', str(volume), '1', str(volume*101), '1' if closed else '0']
        payload = exchange.parse_candlescope_ws_klines(
            {'arg': {'channel':'candle1m', 'instId':'BTC-USDT'}, 'data':[row]})[0]
        message = RawMessage(payload, DataSource.WEBSOCKET, StreamType.KLINE, clock[0])
        await prepare_source_messages([message], desc, watermark=kline_sources.rest_watermark(), history_projection=False)
        return normalize_fork_kline(message, desc)

    class Ingestion:
        async def start(self, *, on_market_event, **_):
            self.send = on_market_event
            return self
        async def stop(self): pass

    async def run():
        observed, recovery = [], []
        ingestion = Ingestion()
        dm.set_ingestion_factory(ingestion)
        dm.bar_aggregator.publisher.set_update_throttle_ms(1000)
        # This observes the existing recovery owner, without adding a producer.
        dm.aggregator_bridge._require_recovery = recovery.append
        async def receive(event): observed.append((event.event_type, event.bar.volume))
        try:
            for i in range(6):
                event = await source(i*60000, 100, True)
                bar = HistoricalFetcher._event_to_bar(event, BackfillTask(symbol='BTC-USDT', interval='1m',
                    exchange='okx', market_type='spot', start_ms=i*60000, end_ms=i*60000))
                assert klines_repo.upsert_klines('BTC-USDT','1m',[bar.to_storage_dict()],
                    exchange='okx', source='data_manager_exchange_closed') == 1
            await dm.start()
            await dm.subscribe_async(receive, symbol='BTC-USDT', interval='7m', exchange='okx', market_type='spot',
                continuity='gap_aware', preserve_updates=False,
                event_types={DataEventType.BAR_UPDATED, DataEventType.BAR_CLOSED})
            await dm.ensure_stream('BTC-USDT','7m',exchange='okx', market_type='spot')
            for volume in range(101,106): await ingestion.send(await source(360000,volume))
            agg = dm.bar_aggregator
            engine = agg.get_pipeline('7m',exchange='okx').bar_state
            state = engine.get_active('okx','spot','BTC-USDT',0)
            assert state._preview_dirty and state.source_refs
            scheduler = agg._previews
            if mutation == 'superseded':
                later = await source(360000,106)
            elif mutation == 'delete':
                dm.query_engine.storage.delete_bars('BTC-USDT','1m',0,0,exchange='okx')
            elif mutation == 'external':
                with klines_repo._connect() as conn:
                    conn.execute("UPDATE klines SET volume=99 WHERE symbol='BTC-USDT' AND open_time=0")
            clock[0] += 2000
            for entry in scheduler.pending.values(): entry.due = asyncio.get_running_loop().time()
            before = scheduler.metrics['published']
            if mutation in {'cancel','detach'}:
                entered, released = threading.Event(), threading.Event()
                storage = dm.query_engine.storage
                original = storage.validate_component_preview
                def held(*args, **kwargs):
                    entered.set()
                    assert released.wait(10)
                    return original(*args, **kwargs)
                monkeypatch.setattr(storage,'validate_component_preview',held)
                scheduler._wake()
                task = scheduler.task
                try:
                    async with asyncio.timeout(5):
                        while not entered.is_set(): await asyncio.sleep(.01)
                    reserved = dm.memory_budget.snapshot()['reserved_bytes']
                    assert reserved > 16384*2
                    if mutation == 'detach': agg.remove_target('BTC-USDT','7m',exchange='okx',market_type='spot')
                    else: task.cancel()
                    await asyncio.sleep(.02)
                    assert not task.done() and dm.memory_budget.snapshot()['reserved_bytes'] >= reserved
                finally: released.set()
                if mutation == 'cancel':
                    with pytest.raises(asyncio.CancelledError): await task
                else: await task
                assert not recovery and scheduler.metrics['published'] == before
                assert not scheduler.pending and not scheduler.inflight
                return
            await scheduler._drain()
            assert scheduler.metrics['source_checks'] >= 1
            if mutation == 'none':
                assert scheduler.metrics['published'] == before+1
                assert state.volume == 705 and state.preview_published_version == state.preview_input_version
                assert not recovery
            else:
                assert scheduler.metrics['published'] == before
                assert bool(recovery) == (mutation in {'delete','external'})
            if mutation in {'none','superseded'}:
                if mutation == 'superseded': await ingestion.send(later)
                clock[0] = 421000
                await ingestion.send(await source(360000,107,True))
                closed = engine.get_state('okx','spot','BTC-USDT',0)
                assert closed.status.value == 'closed' and closed.finality.value == 'authoritative'
                assert closed.volume == 707
                async with asyncio.timeout(5):
                    while (DataEventType.BAR_CLOSED,707) not in observed: await asyncio.sleep(.01)
                stored = dm.query_engine.storage.query_bars('BTC-USDT','7m',0,0,exchange='okx')
                assert stored and stored[0]['volume'] == 707, (closed.source_refs, closed.acquisition_revision, dm.aggregator_bridge.delivery.snapshot(), kline_sources.latest(desc,360000), dm.query_engine.storage.revision_store.head())
                assert not recovery
        finally:
            await dm.shutdown()
            await exchange.close()
        assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
    asyncio.run(run())
