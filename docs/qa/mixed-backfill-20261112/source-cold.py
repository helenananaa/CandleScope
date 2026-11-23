"""Fresh SQLite + real CCXT HTTP loopback over checksum-pinned official input.
PYTHONPATH=backend python source-cold.py INPUT_ROOT NEW_OUTPUT_ROOT
Run from repository root. No public network latency/native package claim.
"""
import asyncio
import csv
from decimal import Decimal
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
import zipfile

source, output = (Path(p).resolve() for p in sys.argv[1:3])
output.mkdir(parents=True, exist_ok=False)
os.environ['CANDLE_DATA_DIR'] = str(output / 'isolated-data')
from aiohttp import web
from app.core import config as core_config
from app.data_engine.backfill import BackfillEngine, BackfillConfig
from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.transport import TransportLayer
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.storage import klines_repo
from app.exchanges.ccxt_ext import generic
from app.exchanges.rate_limits import RateLimitDeferred
from tests.test_public_transport_loopback import serve, point_at_loopback

fields = ('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')
widths = {'1m':60000,'5m':300000,'15m':900000,'1h':3600000}
inputs = json.loads((source / 'inputs.json').read_text())
raw = {}
for item in inputs:
    archive_path = source / 'archives' / Path(item['url']).name
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == item['sha256']
    with zipfile.ZipFile(archive_path) as archive, archive.open(archive.namelist()[0]) as stream:
        raw[item['interval']] = {int(r[0]): r for r in csv.reader(io.TextIOWrapper(stream)) if r and r[0].isdigit()}
start = min(raw['1m'])

def oracle(at, width):
    rows = [raw['1m'][t] for t in range(at, at + width, 60000)]
    return [Decimal(rows[0][1]), max(Decimal(r[2]) for r in rows), min(Decimal(r[3]) for r in rows),
        Decimal(rows[-1][4]), *[sum((Decimal(r[c]) for r in rows), Decimal(0)) for c in (5,7,8,9,10)]]

async def case(period, enabled):
    database = output / f'{period}-{enabled}.sqlite'
    assert not database.exists()
    core_config.KLINES_DB_PATH = klines_repo.KLINES_DB_PATH = database
    klines_repo.init_klines_storage()
    storage = klines_repo.KlinesRepoAdapter()
    count = 1 if period == 10007 else 12
    width = period * 60000
    first = (start + width - 1) // width * width
    stop = first + count * width
    assert stop <= start + 16 * 86400000
    calls = []
    async def handle(request):
        if request.path.endswith('/time'):
            return web.json_response({'serverTime': int(time.time() * 1000)})
        if request.path.endswith('/exchangeInfo'):
            return web.json_response({'symbols':[dict(symbol='BTCUSDT',pair='BTCUSDT',contractType='PERPETUAL',
                status='TRADING',baseAsset='BTC',quoteAsset='USDT',marginAsset='USDT',
                pricePrecision=2,quantityPrecision=3,filters=[],orderTypes=['LIMIT','MARKET'])]})
        assert request.path == '/fapi/v1/klines'
        q = request.query
        interval, lo, hi, limit = q['interval'], int(q.get('startTime',0)), int(q['endTime']), int(q['limit'])
        rows = [r for t, r in raw[interval].items() if lo <= t <= hi][:limit]
        calls.append(dict(interval=interval, start=lo, end=hi, limit=limit, rows=len(rows)))
        # Archive CSV is textual; Binance REST timestamps and trade count
        # are JSON integers. Preserve all decimal strings verbatim.
        wire = [list(row) for row in rows]
        for row in wire:
            for column in (0, 6, 8):
                row[column] = int(row[column])
        return web.json_response(wire)
    runner, origin = await serve(handle)
    original = generic._create_exchange
    def create(*args, **kwargs):
        client = original(*args, **kwargs)
        point_at_loopback(client, origin)
        return client
    generic._create_exchange = create
    ingestion = IngestionConfig(proxy_mode='none', proxy_egress_group=f'official-cold-{period}-{enabled}')
    transport = TransportLayer(ingestion)
    cfg = BackfillConfig(history_archive_enabled=False, mixed_custom_history=enabled)
    dm = DataManager(DataManagerConfig())
    dm.set_storage(storage)
    engine = BackfillEngine(cfg, klines_repo.AsyncKlinesRepoAdapter(), transport, ingestion_config=ingestion)
    engine.memory_budget = dm.memory_budget
    initial_rows = storage.count_bars('BTCUSDT','1m',first,stop-1,market_type='futures')
    assert initial_rows == 0
    deferred = 0
    began = time.perf_counter()
    try:
        for attempt in range(100):
            try:
                report = await engine.run('BTCUSDT', [f'{period}m'], first, stop-width, market_type='futures',
                    metadata=dict(requires_trusted_finality=True,requester='klines_range',history_calendar_id='crypto.24x7.utc'))
                break
            except RateLimitDeferred as exc:
                deferred += 1
                await asyncio.sleep(max(.01, exc.retry_after_seconds))
        else:
            raise AssertionError('retry exhaustion')
        assert report.status.value == 'completed', report.errors
        assert report.reconcile_result.custom_bars_written == count
        rows = await engine._storage.query_time_range('BTCUSDT',f'{period}m',first,stop-1,market_type='futures')
        assert len(rows) == count
        deltas = dict.fromkeys(fields,0.)
        for row in rows:
            for field, expected in zip(fields,oracle(row['open_time'],width)):
                actual = row[field]
                assert actual is not None and math.isclose(actual,float(expected),rel_tol=1e-12,abs_tol=1e-8),(period,field,actual,expected)
                deltas[field] = max(deltas[field],abs(actual-float(expected)))
        return dict(period=period,enabled=enabled,count=count,range=[first,stop],calls=calls,
            source_rows=sum(c['rows'] for c in calls),deferred=deferred,elapsed_ms=(time.perf_counter()-began)*1000,
            final_minute_rows=storage.count_bars('BTCUSDT','1m',first,stop-1,market_type='futures'),
            max_abs_delta=deltas,plan=report.plan.to_dict(),metadata=report.metadata,memory=dm.memory_budget.snapshot())
    finally:
        await engine.close()
        await transport.stop()
        await dm.shutdown()
        generic._create_exchange = original
        await runner.cleanup()
        assert dm.memory_budget.snapshot()['reserved_bytes'] == 0

async def main():
    results = []
    for period in (89,97,101,10007):
        for enabled in (False,True):
            results.append(await case(period,enabled))
            (output / 'report.json').write_text(json.dumps(dict(inputs=inputs,python=sys.version,
                limitation='Fresh database; real CCXT socket loopback with official recorded payloads; no public/native or stable timing claim',
                tolerance=dict(rel=1e-12,abs=1e-8),results=results),default=str,indent=2)+'\n')
    print(json.dumps([dict(period=r['period'],enabled=r['enabled'],requests=len(r['calls']),source_rows=r['source_rows'],minute_rows=r['final_minute_rows']) for r in results]))
asyncio.run(main())
