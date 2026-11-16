"""Fresh-process native-page fence costs, no network or live collision."""
import argparse
import asyncio
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import ccxt.async_support as ccxt
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.backfill.models import BackfillTask
from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType
from app.data_engine.storage import klines_repo, kline_sources
from app.data_engine.storage.native_history_fence import capture_native_history_views
from app.data_engine.storage.revisions import acquisition_scope
from app.exchanges.ccxt_ext.fork_kline import normalize_fork_kline, prepare_source_messages


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('rows', type=int)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    klines_repo.init_klines_storage()
    store = klines_repo.KlinesRepoAdapter()
    exchange = ccxt.okx()
    market = dict(id='BTC-USDT', symbol='BTC/USDT', base='BTC', quote='USDT',
                  type='spot', spot=True, swap=False, contract=False)
    exchange.set_markets([market])
    start = 1772323200000
    task = BackfillTask(symbol='BTC-USDT', interval='1m', exchange='okx', market_type='spot',
                        start_ms=start, end_ms=start+(args.rows-1)*60000)
    desc = StreamDescriptor('BTC-USDT', StreamType.KLINE, interval='1m', exchange='okx', market_type='spot')
    messages = [RawMessage(exchange.parse_candlescope_kline(
        [str(start+i*60000), '100', '103', '99', '102', '100', '1', '101', '1'], market, '1m'),
        DataSource.HTTP_BACKFILL, StreamType.KLINE, start+args.rows*60000) for i in range(args.rows)]
    await prepare_source_messages(messages, desc, watermark=kline_sources.rest_watermark(), history_projection=True)
    rows = [HistoricalFetcher._event_to_bar(normalize_fork_kline(m, desc), task).to_storage_dict() for m in messages]
    samples = []
    for repeat in range(9):
        store.delete_bars('BTC-USDT', '1m', task.start_ms, task.end_ms, exchange='okx')
        scope = store.revision_store.acquisition()
        before = time.process_time_ns()
        capture_native_history_views(store.revision_store, scope, [task])
        captured = time.process_time_ns()
        with acquisition_scope(scope):
            assert klines_repo.upsert_klines('BTC-USDT', '1m', rows, source='backfill', exchange='okx') == args.rows
        after = time.process_time_ns()
        if repeat >= 2:
            samples.append({'capture_us': (captured-before)/1000, 'commit_us': (after-captured)/1000,
                            'total_us': (after-before)/1000})
    actual = store.query_bars('BTC-USDT', '1m', exchange='okx')
    payload = [{k: r[k] for k in ('open_time', *kline_sources._VALUES)} for r in actual]
    args.output.write_text(json.dumps({'backend': klines_repo.__file__, 'python': sys.version,
        'platform': platform.platform(), 'rows': args.rows, 'samples': samples,
        'median_us': {key: statistics.median(s[key] for s in samples) for key in samples[0]},
        'output_hash': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        'scope': 'source setup outside timing; 2 warm + 7 writes; no live collision; not network/native/RSS or stable performance qualification'}, indent=2)+'\n')


if __name__ == '__main__':
    asyncio.run(main())
