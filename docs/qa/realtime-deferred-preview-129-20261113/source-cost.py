"""Controlled pinned-CCXT receipts/default DataManager/SQLite; no network benchmark."""
import argparse
import asyncio
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--mode', choices=['base','eager','deferred'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source/'backend'))
    import ccxt.async_support as ccxt
    from app.core import config as core_config
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.config import DataManagerConfig
    from app.data_engine.data_manager.models import DataEventType
    from app.data_engine.backfill.fetcher import HistoricalFetcher
    from app.data_engine.backfill.models import BackfillTask
    from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType
    from app.data_engine.storage import klines_repo, kline_sources
    from app.exchanges.ccxt_ext.fork_kline import normalize_fork_kline, prepare_source_messages
    from tests.test_ccxt_source_extensions import SPOT
    fields = ('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')
    clock = [361000]
    time.time = lambda: clock[0]/1000

    async def trial(attempt):
        with tempfile.TemporaryDirectory(prefix='r129-source-cost-') as temporary:
            klines_repo.KLINES_DB_PATH = core_config.KLINES_DB_PATH = Path(temporary)/'bars.sqlite'
            klines_repo.init_klines_storage()
            exchange = ccxt.okx()
            exchange.set_markets([SPOT])
            desc = StreamDescriptor('BTC-USDT', StreamType.KLINE, interval='1m', exchange='okx', market_type='spot')
            def payload(opened, volume, closed):
                row = [str(opened),'100','103','99','102',str(volume),'1',str(volume*101),'1' if closed else '0']
                return exchange.parse_candlescope_ws_klines(
                    {'arg':{'channel':'candle1m','instId':'BTC-USDT'},'data':[row]})[0]
            async def selected(value):
                message = RawMessage(value,DataSource.WEBSOCKET,StreamType.KLINE,clock[0])
                await prepare_source_messages([message],desc,watermark=kline_sources.rest_watermark(),history_projection=False)
                return normalize_fork_kline(message,desc)
            for index in range(6):
                event = await selected(payload(index*60000,100,True))
                bar = HistoricalFetcher._event_to_bar(event,BackfillTask(symbol='BTC-USDT',interval='1m',
                    exchange='okx',market_type='spot',start_ms=index*60000,end_ms=index*60000))
                assert klines_repo.upsert_klines('BTC-USDT','1m',[bar.to_storage_dict()],exchange='okx',
                    source='data_manager_exchange_closed') == 1
            cfg = DataManagerConfig()
            cfg.query.auto_backfill = False
            dm = DataManager(cfg)
            dm.set_storage(klines_repo.KlinesRepoAdapter())
            agg = dm.bar_aggregator
            if hasattr(agg.config,'deferred_component_previews'):
                agg.config.deferred_component_previews = args.mode == 'deferred'
            agg.publisher.set_update_throttle_ms(1000)
            class Ingestion:
                async def start(self, *, on_market_event, **_): self.send=on_market_event; return self
                async def stop(self): pass
            ingestion = Ingestion()
            dm.set_ingestion_factory(ingestion)
            seen = []
            async def observe(event):
                bar=event.bar
                seen.append((event.event_type.value,event.key.exchange,event.key.market_type,event.key.symbol,
                    event.key.interval,event.key.identity.storage_values,bar.time,bar.is_closed,bar.source,
                    *[getattr(bar,name) for name in fields]))
            # Parse immutable input tape before timing; selection/durable journal
            # and default ingestion/writer/fanout remain inside the measured path.
            tape = tuple(payload(360000,volume,False) for volume in range(101,357))
            close = payload(360000,357,True)
            try:
                await dm.start()
                await dm.subscribe_async(observe,symbol='BTC-USDT',interval='7m',exchange='okx',market_type='spot',
                    continuity='gap_aware',preserve_updates=False,
                    event_types={DataEventType.BAR_UPDATED,DataEventType.BAR_CLOSED})
                await dm.ensure_stream('BTC-USDT','7m',exchange='okx',market_type='spot')
                clock[0] = 361000
                gc.collect()
                if attempt==4: tracemalloc.start()
                cpu,wall = time.process_time_ns(),time.perf_counter_ns()
                for index,value in enumerate(tape):
                    clock[0] = 361000+index
                    event = await selected(value)
                    await ingestion.send(event)
                    kline_sources.acknowledge(event.data['source_ref'])
                    if index%32==0: await asyncio.sleep(0)
                state = agg.get_pipeline('7m',exchange='okx').bar_state.get_active('okx','spot','BTC-USDT',0)
                before = [getattr(state,name,None) for name in
                    ('preview_input_version','preview_computed_version','preview_published_version')]
                clock[0] = 421000
                event = await selected(close)
                await ingestion.send(event)
                kline_sources.acknowledge(event.data['source_ref'])
                async with asyncio.timeout(5):
                    while not any(row[0]=='bar.closed' for row in seen): await asyncio.sleep(.001)
                cpu_ms=(time.process_time_ns()-cpu)/1e6
                wall_ms=(time.perf_counter_ns()-wall)/1e6
                allocation=tracemalloc.get_traced_memory() if attempt==4 else None
                if attempt==4: tracemalloc.stop()
                canonical=[]
                for interval in ('1m','7m'):
                    canonical.extend((interval,row['open_time'],row['close_time'],row['source'],
                        *[row[name] for name in fields]) for row in
                        dm.query_engine.storage.query_bars('BTC-USDT',interval,exchange='okx'))
                assert canonical[-1][8]==957, canonical[-1]
                digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                result=dict(attempt=attempt,cpu_ms=cpu_ms,wall_ms=wall_ms,allocation_current_peak=allocation,
                    event_sha256=digest(seen),events_trace=seen,canonical_sha256=digest(canonical),events=len(seen),canonical_rows=len(canonical),
                    forming_inputs=len(tape),source_head=kline_sources.latest(desc,360000)['revision'],
                    target_calculations=getattr(state,'_preview_calculations',None),
                    target_deferred=getattr(state,'_preview_deferred_inputs',0),before_close_watermarks=before,
                    scheduler=agg._previews.snapshot() if hasattr(agg,'_previews') else None)
            finally:
                await dm.shutdown()
                await exchange.close()
            assert dm.memory_budget.snapshot()['reserved_bytes']==0
            return result
    trials=[]
    for attempt in range(5):
        result=asyncio.run(trial(attempt)); trials.append(result)
        print(json.dumps(result),flush=True)
    args.output.write_text(json.dumps(dict(mode=args.mode,scope=__doc__,source=str(args.source),trials=trials,
        cpu_median_ms=statistics.median(row['cpu_ms'] for row in trials[1:4]),
        wall_median_ms=statistics.median(row['wall_ms'] for row in trials[1:4])),indent=2)+'\n')


if __name__=='__main__': main()
