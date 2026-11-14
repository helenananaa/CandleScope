"""Same-input source-only cold rebuild and correction; full independent backends, no network/RSS qualification."""
import argparse, asyncio, gc, hashlib, json, statistics, sys, tempfile, time, tracemalloc
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True)
p.add_argument('--mode',choices=('base','enabled'),required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
sys.path.insert(0,str(a.source/'backend'))
from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.ingestion.models import MarketEvent,StreamType,DataSource,StreamDescriptor
from app.data_engine.storage import klines_repo,kline_sources
from app.data_engine.memory_budget import retained_size
W=60000
DESC=StreamDescriptor('BTCUSDT',StreamType.KLINE,interval='1m',market_type='futures')
KEY=kline_sources.series(DESC)
FIELDS=('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')
clock=[1000]
time.time=lambda:clock[0]/1000
hashes=lambda:{str(f.relative_to(a.source)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((a.source/'backend/app').rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.suffix not in ('.pyc','.pyo')}
before=hashes()
digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def record(
    index,
    *,
    quote=2.0,
    closed=True,
    sequence=None,
    conn=None,
    high=20.0,
    source=DataSource.WEBSOCKET,
    watermark=None,
):
    opened = index * W
    seq = opened + W + 1 if sequence is None else sequence
    envelope = dict(
        open="10",
        high=str(high),
        low="5",
        close="11",
        volume="1",
        quoteVolume=str(quote),
        trades=1,
        takerBuyBaseVolume="0.5",
        takerBuyQuoteVolume="1",
        closeTime=opened + W - 1,
        eventTime=seq,
    )
    data = dict(
        interval="1m",
        open_time=opened,
        close_time=opened + W - 1,
        is_closed=closed,
        open=10.0,
        high=high,
        low=5.0,
        close=11.0,
        volume=1.0,
        quote_volume=quote,
        trades=1,
        taker_buy_base=0.5,
        taker_buy_quote=1.0,
        source_candle=envelope,
    )
    event = MarketEvent(
        event_type=StreamType.KLINE,
        symbol="BTCUSDT",
        event_time_ms=seq,
        received_at_ms=seq + 1,
        source=source,
        exchange="binance",
        market_type="futures",
        data=data,
    )
    return kline_sources.record(event, DESC, _connection=conn, rest_watermark=watermark)

def incoming(index, *, quote=2.0, closed=True, ref=None):
    from app.data_engine.bar_aggregator.models import (
        BarInput,
        BarInputSource,
        MergeMode,
    )
    from app.data_engine.market_data.kline_metrics import declared_enhanced_fields

    values = dict(
        open=10.0,
        high=20.0,
        low=5.0,
        close=11.0,
        volume=1.0,
        quote_volume=quote,
        trades=1,
        taker_buy_base=0.5,
        taker_buy_quote=1.0,
    )
    return BarInput(
        symbol="BTCUSDT",
        exchange="binance",
        market_type="futures",
        source_interval="1m",
        source=BarInputSource.CORRECTION,
        merge_mode=MergeMode.COMPONENT,
        open_time_ms=index * W,
        close_time_ms=(index + 1) * W - 1,
        is_closed=closed,
        enhanced_fields=declared_enhanced_fields("binance", "futures", values),
        extra={"source_ref": ref or dict(series=KEY, open_time=index * W, revision=1)},
        **values,
    )

async def trial(count, attempt):
    clock[0]=(count+1)*W
    with tempfile.TemporaryDirectory(prefix='r129-source-cost-') as temporary:
        klines_repo.KLINES_DB_PATH=core_config.KLINES_DB_PATH=Path(temporary)/'source.sqlite'
        klines_repo.init_klines_storage()
        with klines_repo._connect() as conn:
            kline_sources._schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            for index in range(count):record(index,conn=conn)
            conn.commit()
        manager=DataManager();manager.set_storage(klines_repo.KlinesRepoAdapter());manager._started=True
        agg=manager.bar_aggregator;interval=f'{count}m'
        agg.add_target('BTCUSDT',interval,market_type='futures')
        events=[]
        async def collect(event):
            bar=event.bar
            events.append((event.event_type.value,event.key.interval,bar.time,bar.is_closed,bar.source,
                           *[getattr(bar,name) for name in FIELDS]))
        manager.event_bus.subscribe(collect)
        phase=[]
        try:
            for index,quote in enumerate((1.0,3.0)):
                clock[0]+=1000
                ref=record(0,quote=quote,sequence=(count+2)*W+index)['ref']
                value=incoming(0,quote=quote,ref=ref)
                gc.collect()
                if attempt==4:tracemalloc.start()
                cpu,wall=time.process_time_ns(),time.perf_counter_ns()
                await agg.ingest_bar_input('binance','futures','BTCUSDT',interval,value)
                await manager.aggregator_bridge.delivery.flush_pending()
                used=(time.process_time_ns()-cpu)/1e6,(time.perf_counter_ns()-wall)/1e6
                allocation=tracemalloc.get_traced_memory() if attempt==4 else None
                if attempt==4:tracemalloc.stop()
                state=agg.get_pipeline(interval).bar_state.get_state('binance','futures','BTCUSDT',0)
                assert state.quote_volume==2*count-2+quote and state.status.value=='closed'
                phase.append(dict(cpu_ms=used[0],wall_ms=used[1],allocation_current_peak=allocation))
            assert [event[0] for event in events]==['bar.updated','bar.closed','bar.amended']
            rows=klines_repo.query_klines('BTCUSDT',interval,market_type='futures')
            assert len(rows)==1 and rows[0]['quote_volume']==2*count+1
            assert not klines_repo.query_klines('BTCUSDT','1m',market_type='futures')
            canonical=[(r['open_time'],r['close_time'],r['source'],*[r[name] for name in FIELDS]) for r in rows]
            with klines_repo._connect() as conn:
                payload=conn.execute('SELECT MAX(length(CAST(payload AS BLOB))) FROM bar_delivery').fetchone()[0]
            result=dict(attempt=attempt,phases=phase,canonical_sha256=digest(canonical),event_sha256=digest(events),events=events,
                retained_components=len(state.source_snapshots),retained_refs=len(state.source_refs),state_retained_bytes=retained_size((state,))[0],
                payload_max_bytes=payload,memory=manager.memory_budget.snapshot(measure_heap=True),
                watermarks=[getattr(state,name) for name in ('preview_input_version','preview_computed_version','preview_published_version')])
        finally:await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes']==0
        return result

results=[]
for count in (2,2048,10007):
    trials=[]
    for attempt in range(5):
        value=asyncio.run(trial(count,attempt));trials.append(value)
        print(json.dumps(dict(count=count,attempt=attempt,cpu_ms=[r['cpu_ms'] for r in value['phases']],retained=value['retained_components'])),flush=True)
    results.append(dict(count=count,trials=trials,cpu_median_ms=[statistics.median(t['phases'][i]['cpu_ms'] for t in trials[1:4]) for i in range(2)]))
assert before==hashes()
a.output.write_text(json.dumps(dict(mode=a.mode,source=str(a.source),scope=__doc__,source_hashes=before,results=results),indent=2)+'\n')
