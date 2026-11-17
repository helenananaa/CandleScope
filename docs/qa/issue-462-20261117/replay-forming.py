"""Real public 1m values through normalization, repair, snapshot and publication.

Historical controlled delivery into existing owners; no exchange timing claim.
"""
import asyncio
import json
import math
from pathlib import Path
import sys
import subprocess
import tempfile

import pytest
from app.api.v1.stream_klines import _serialize_browser_kline_event
from app.data_engine.backfill import BackfillConfig
from app.data_engine.backfill.models import BackfillTask, FetchedBar, FetchResult, BackfillPlan
from app.data_engine.backfill.reconciler import Reconciler
from app.data_engine.data_manager.models import BarData, DataEventType, SeriesKey
from app.data_engine.ingestion.models import RawMessage, DataSource, StreamType
from app.data_engine.interval_policy import parse_interval_spec
from app.data_engine.storage import klines_repo
from tests.test_subscription_continuity import manager
from tests.test_recovery_kline_consumers import IDENTITY, _close
from tests.test_recovery_delivery_integration import _until

ROOT = Path(__file__).resolve().parent
rows = json.loads((ROOT / 'public-source.json').read_text())['rows']
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote')


async def scenario(root, interval):
    clock = [rows[4]['open_time'] + 30_000]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr('time.time', lambda: clock[0] / 1000)
        dm, store, factory, requests = await manager(root, patch)
        await dm.bar_aggregator.start()
        identity = {**IDENTITY, 'interval': interval}
        target, source = SeriesKey(**identity), SeriesKey(**IDENTITY)
        errors, published, stages = [], [], []
        async def recover(error): errors.append(error.reason)
        async def collect(event): published.append(event)
        async def feed(row, closed=True):
            clock[0] = max(clock[0]+1000, row['open_time']+30_000)
            payload = dict(e='kline', E=clock[0], k=dict(
                t=row['open_time'], T=row['close_time'], i='1m', x=closed,
                **{wire: str(row[field]) for wire, field in (
                    ('o','open'),('h','high'),('l','low'),('c','close'),('v','volume'),
                    ('q','quote_volume'),('n','trades'),('V','taker_buy_base'),('Q','taker_buy_quote'))}))
            await factory.pipeline.normalize.ingest(RawMessage(payload, DataSource.WEBSOCKET,
                StreamType.KLINE, clock[0]))
            stages.append({'stage':'source_input','row':row,'closed':closed})
        async def repair(row):
            task = BackfillTask(start_ms=row['open_time'], end_ms=row['open_time'], **IDENTITY)
            bar = FetchedBar(open_time=row['open_time'], close_time=row['close_time'],
                             **IDENTITY, **{f:row[f] for f in FIELDS}, enhanced_fields=frozenset(FIELDS[5:]))
            reconciler = Reconciler(BackfillConfig(), klines_repo.AsyncKlinesRepoAdapter())
            result = await reconciler.reconcile([FetchResult(task=task,bars=[bar])], BackfillPlan(gaps=[]))
            assert result.bars_written == 1 and not result.errors
            canonical = store.query_bars(start_ms=row['open_time'],end_ms=row['open_time'],**IDENTITY)
            await dm.on_bars_backfilled(**IDENTITY,
                bars=[BarData.from_storage_row(r,exchange='binance',market_type='futures') for r in canonical])
            stages.append({'stage':'canonical_repair','open_time':row['open_time'],
                           'pending':dm.source_gaps.snapshot()})
        try:
            spec = parse_interval_spec(interval)
            assert spec.floor_ms(rows[0]['open_time']) == spec.floor_ms(rows[-1]['open_time'])
            await dm.ensure_stream(**identity)
            await feed(rows[0])
            await feed(rows[3])
            dependent = dm.source_gaps.pending(target)[0]
            dm.subscribe(collect, **identity, on_recovery=recover)
            await repair(rows[1])
            assert dm.source_gaps.pending(target) == [dependent] and not dependent.future.done()
            await repair(rows[2])
            await _until(lambda: bool(errors))
            assert errors == ['source_gap_snapshot_required']
            assert not dm.source_gaps.pending(target) and dependent.completed_at is None
            assert dependent.repaired == {}
            await dm._retire_forming_source_dependents(source)
            assert dm.source_gaps.snapshot()['forming_snapshots_required'] == 1
            await dm.warm_start.seed_if_needed('BTCUSDT',interval,exchange='binance',market_type='futures',had_stream=True)
            snapshot = dm.query_latest(**identity,limit=2,auto_backfill=False)
            assert snapshot.bars and not snapshot.bars[-1].is_closed
            resumed=[]
            async def receive(event): resumed.append(event)
            dm.subscribe(receive,**identity,event_types={DataEventType.BAR_CREATED,DataEventType.BAR_UPDATED},on_recovery=recover)
            await feed(rows[4],False)
            await _until(lambda:any(e.bar.close==rows[4]['close'] for e in resumed))
            await feed(rows[4],True)
            await feed(rows[5],False)
            await _until(lambda:any(e.bar.close==rows[5]['close'] for e in resumed))
            bar = resumed[-1].bar
            expected = dict(open=rows[0]['open'],high=max(r['high'] for r in rows),
                            low=min(r['low'] for r in rows),close=rows[-1]['close'])
            expected.update({f:sum(r[f] for r in rows) for f in FIELDS[4:]})
            absent=[]
            for field in FIELDS:
                value=getattr(bar,field)
                if value is None:
                    assert field in FIELDS[5:] and field not in bar.enhanced_fields
                    absent.append(field)
                else:
                    assert math.isclose(value,expected[field],abs_tol=1e-6,rel_tol=1e-12),(interval,field,value,expected[field])
            assert not bar.is_closed and errors == ['source_gap_snapshot_required']
            wire = [_serialize_browser_kline_event(e) for e in resumed]
            assert all(m['type']=='kline' and not m['data']['is_closed'] for m in wire)
            assert {m['data']['close'] for m in wire} >= {rows[4]['close'],rows[5]['close']}
            return {'interval':interval,'source_rows':len(rows),'repair_rows':2,'fields_checked':list(FIELDS),'unproven_fields_absent':absent,
                    'diagnostics':dm.source_gaps.snapshot(),'snapshot':[b.to_dict() for b in snapshot.bars],
                    'wire':wire,'expected':expected,'stages':stages,
                    'requests':[(a,k) for a,k in requests]}
        finally:
            await _close(dm,factory)


async def main():
    evidence=[]
    with tempfile.TemporaryDirectory(prefix='candlescope-462-replay-') as temporary:
        for interval in ('89m','97m','101m','10007m'):
            root=Path(temporary)/interval
            root.mkdir()
            evidence.append(await scenario(root,interval))
    output=Path(sys.argv[1])
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'passed':True,'checkout_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'scope':__doc__,'scenarios':evidence},indent=2)+'\n')
    print(json.dumps({'passed':True,'intervals':[s['interval'] for s in evidence],'field_checks':len(FIELDS)*len(evidence)}))

asyncio.run(main())
