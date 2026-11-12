"""H127 canonical pages release raw rows and preserve strict K130 results."""
import asyncio
from contextvars import Context
import gc
import math
import weakref

import pytest

from app.data_engine.aggregation.adapters import chart_field_summary
from app.data_engine.backfill.models import BackfillStatus
from app.data_engine.interval_policy import ClosedKlineRowStream, aggregate_kline_rows, parse_interval_spec
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_pipeline import Upstream, META
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_history_reader import row, MINUTE

FIELDS=('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote')


def stream_rows(period,count=2):
    return [{**row(index*MINUTE,MINUTE),'interval':'1m',
        'volume':1e8 if index%17==0 else 3e-8+index/13,
        'quote_volume':5e8 if index%17==0 else 7e-8+index/3}
        for index in range(period*count)]


@pytest.mark.parametrize('period',[89,97,101,10007])
@pytest.mark.parametrize('page_rows',[1,7,256])
def test_pages_match_independent_full_k130_field_reduction(period,page_rows):
    rows=stream_rows(period)
    stream=ClosedKlineRowStream(target_interval=f'{period}m',source_interval=None,
                               now_ms=period*2*MINUTE)
    actual=[]
    for start in range(0,len(rows),page_rows):
        actual.extend(stream.push(rows[start:start+page_rows]))
    actual.extend(stream.finish())
    assert len(actual)==2
    for index,value in enumerate(actual):
        expected=chart_field_summary(rows[index*period:(index+1)*period],validate_ohlcv=True).project()
        for field in FIELDS:
            assert value[field]==pytest.approx(expected[field],rel=1e-12,abs=1e-8)
        assert value['open_time']==index*period*MINUTE
        assert value['close_time']==(index+1)*period*MINUTE-1
        assert value['is_closed'] is True


@pytest.mark.parametrize('fault',['gap','duplicate','forming','close_time','source_grid','nan','unknown'])
def test_invalid_coverage_and_unknown_fields_do_not_taint_later_target(fault):
    rows=stream_rows(89)
    if fault=='gap':del rows[30]
    elif fault=='duplicate':rows.insert(30,dict(rows[30]))
    elif fault=='forming':rows[30]['is_closed']=False
    elif fault=='close_time':rows[30]['close_time']-=1
    elif fault=='source_grid':rows[30]['interval']='5m'
    elif fault=='nan':rows[30]['volume']=math.nan
    elif fault=='unknown':rows[30]['quote_volume']=None
    stream=ClosedKlineRowStream(target_interval='89m',source_interval=None,now_ms=178*MINUTE)
    actual=[]
    for start in range(0,len(rows),7):actual.extend(stream.push(rows[start:start+7]))
    actual.extend(stream.finish())
    assert [x['open_time'] for x in actual]==([0,89*MINUTE] if fault=='unknown' else [89*MINUTE])
    if fault=='unknown':assert actual[0]['quote_volume'] is None
    assert actual[-1]['quote_volume'] is not None
    batch=aggregate_kline_rows(list(reversed(rows)),target_interval='89m',source_interval=None,
                               now_ms=178*MINUTE)
    assert len(batch)==len(actual)
    for a,b in zip(actual,batch):
        assert (a['open_time'],a['close_time'],a['is_closed'])==(b['open_time'],b['close_time'],b['is_closed'])
        for field in FIELDS:
            if b[field] is None:assert a[field] is None
            else:assert a[field]==pytest.approx(b[field],rel=1e-12,abs=1e-8)


def test_stream_does_not_retain_raw_page_objects_or_allow_late_reopening():
    class Watched(dict):pass
    stream=ClosedKlineRowStream(target_interval='10007m',source_interval='1m',now_ms=10007*MINUTE)
    refs=[]
    for start in range(0,10007,256):
        page=[Watched(row(index*MINUTE,MINUTE)) for index in range(start,min(start+256,10007))]
        refs.extend(weakref.ref(value) for value in page)
        assert not stream.push(page)
        del page
        gc.collect()
        assert all(ref() is None for ref in refs)
    result=stream.finish()
    assert len(result)==1 and result[0]['volume']==10007
    with pytest.raises(ValueError,match='finished'):stream.push([])
    with pytest.raises(ValueError,match='finished'):stream.finish()


@pytest.mark.parametrize('interval,source,start,end',[
    ('89m~a1~3600000','1m',-29*MINUTE,149*MINUTE),
    ('1M','1d',1704067200000,1709251200000), # Jan + leap February 2024
    ('2w','1d',345600000,2764800000), # Monday epoch alignment
])
def test_stream_preserves_anchored_and_calendar_boundaries(interval,source,start,end):
    spec=parse_interval_spec(source)
    values=[]
    while start<end:
        stop=spec.next_ms(start)
        values.append({**row(start,stop-start),'interval':source})
        start=stop
    expected=aggregate_kline_rows(values,target_interval=interval,source_interval=source,now_ms=end)
    stream=ClosedKlineRowStream(target_interval=interval,source_interval=source,now_ms=end)
    actual=[]
    for at in range(0,len(values),7):actual.extend(stream.push(values[at:at+7]))
    actual.extend(stream.finish())
    assert len(actual)==len(expected)==2
    for a,b in zip(actual,expected):
        assert (a['open_time'],a['close_time'])==(b['open_time'],b['close_time'])
        for field in FIELDS:assert a[field]==pytest.approx(b[field],rel=1e-12,abs=1e-8)


def run_repair(engine):
    return engine.run('BTCUSDT',intervals=['20011m'],range_start_ms=0,range_end_ms=0,
                      exchange='binance',market_type='futures',metadata=META)


def test_default_mixed_pipeline_folds_and_releases_each_page_before_next_read(mixed_query,monkeypatch):
    engine=engine_for(mixed_query)
    ready=False
    class Fetched(Upstream):
        async def fetch(self,*args,**kwargs):
            nonlocal ready
            result=await super().fetch(*args,**kwargs)
            ready=True
            return result
    engine._fetcher=Fetched()
    original=engine._storage.query_canonical_page
    refs=[];counts=[]
    class Watched(dict):pass
    async def observed(*args,**kwargs):
        if ready:
            gc.collect()
            assert all(ref() is None for ref in refs),'previous canonical page remains retained'
        values=await original(*args,**kwargs)
        if not ready:return values
        page=[Watched(value) for value in values]
        refs.extend(weakref.ref(value) for value in page)
        counts.append(len(page))
        return page
    monkeypatch.setattr(engine._storage,'query_canonical_page',observed)
    report=asyncio.run(run_repair(engine))
    assert report.status==BackfillStatus.COMPLETED,report.errors
    assert report.reconcile_result.custom_bars_written==1
    assert max(counts)==256 and len(counts)>=2
    assert all(ref() is None for ref in refs)
    values=mixed_query.storage.query_bars('BTCUSDT','20011m',market_type='futures')
    assert len(values)==1 and values[0]['volume']==values[0]['trades']==20011
    assert mixed_query.memory_budget.snapshot()['reserved_bytes']==0
    assert engine.reconciler.metrics.get_counter('custom_canonical_stream_rows')==sum(counts)


@pytest.mark.parametrize('fault',['order','range','oversize','type','exchange','symbol','series_variant',
                                 'rollout','revision','cancel','gap'])
def test_late_page_failure_never_materializes_or_releases_its_fences_early(mixed_query,monkeypatch,fault):
    engine=engine_for(mixed_query)
    ready=False
    class Fetched(Upstream):
        async def fetch(self,*args,**kwargs):
            nonlocal ready
            result=await super().fetch(*args,**kwargs);ready=True;return result
    engine._fetcher=Fetched()
    original=engine._storage.query_canonical_page
    seen=0
    async def changed(*args,**kwargs):
        nonlocal seen
        values=await original(*args,**kwargs)
        if not ready:return values
        seen+=1
        if seen==2:
            if fault=='order':values.reverse()
            elif fault=='range':values[0]={**values[0],'open_time':-1}
            elif fault=='oversize':values=[values[0]]*257
            elif fault=='type':values[0]={**values[0],'open_time':str(values[0]['open_time'])}
            elif fault in {'exchange','symbol','series_variant'}:values[0]={**values[0],fault:'foreign-series'}
            elif fault=='rollout':engine.config.mixed_custom_history=False
            elif fault=='revision':Context().run(mixed_query.storage.upsert_bars,'BTCUSDT','1h',
                [{**row(0,60*MINUTE),'volume':99}],source='data_manager_amended',market_type='futures')
            elif fault=='cancel':raise asyncio.CancelledError()
            elif fault=='gap':values=values[1:]
        return values
    monkeypatch.setattr(engine._storage,'query_canonical_page',changed)
    if fault=='cancel':
        with pytest.raises(asyncio.CancelledError):asyncio.run(run_repair(engine))
    else:
        report=asyncio.run(run_repair(engine))
        assert report.status!=BackfillStatus.COMPLETED,report.errors
        assert report.reconcile_result.custom_bars_written==0
    assert seen>=2
    assert mixed_query.storage.count_bars('BTCUSDT','20011m',0,20011*MINUTE-1,market_type='futures')==0
    assert mixed_query.memory_budget.snapshot()['reserved_bytes']==0
