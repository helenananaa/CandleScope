"""Shared storage reads must not change a script's individual input domain."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from candlescope_plugin_sdk import ExecuteBatchResult, RenderOutput, LineSeries, LinePoint
from app.api.v1.indicator_range_batch import IndicatorRangeBatchJob, compute_indicator_range_batch_async
from app.data_engine.data_manager.models import BarData
from app.indicator.range_result_service import IndicatorRangeResultService
from app.indicator.series_revision import SeriesRevisionRegistry


def bars():
    return [BarData(time=1700000040+i*60,open=100+i,high=101+i,low=99+i,
                    close=100+i,volume=1,is_closed=True) for i in range(1000)]


def job(rows,index,language='python',warmup=200):
    return IndicatorRangeBatchJob(client_id=str(index),meta=dict(
        kind='script',language=language,script='finite-window-probe',scriptHash='scope',
        name='Window',params={'warmup':warmup},exchange='binance',market_type='spot',
        symbol='BTCUSDT',interval='1m',indicatorId='window'),
        start=rows[index].time,end=rows[index+2].time)


class DataManager:
    def __init__(self,rows):
        self.rows=rows
        self.queries=0
    def query(self,*args,**kwargs):
        self.queries+=1
        return SimpleNamespace(bars=[b for b in self.rows
            if kwargs['start_ms']<=b.time*1000<=kwargs['end_ms']],missing_ranges=[],metadata={})


class Runtime:
    def __init__(self):
        self.inputs=[]
    async def execute(self,request,**adapters):
        self.inputs.append(tuple(b.time for b in request.bars))
        # An opaque public runtime with a finite window and input-origin
        # dependence, exercising both future and excess-prefix contamination.
        points=tuple(LinePoint(b.time,b.close+request.bars[0].close)
                     for b in request.bars[-3:])
        return adapters['adapt_sidecar'](ExecuteBatchResult(ok=True,
            output=RenderOutput(series=(LineSeries(id='main',title='Main',points=points),))))


def service(enabled=True):
    return IndicatorRangeResultService(enabled=enabled,
        revision_registry=SeriesRevisionRegistry(server_epoch='scope'))


@pytest.mark.parametrize('language',['python','pine','community-language'])
@pytest.mark.parametrize('enabled',[True,False])
def test_same_script_result_alone_and_with_later_unequal_warmup_job(language,enabled):
    async def run():
        rows=bars();early=job(rows,600,language,20);late=job(rows,900,language,200)
        solo=Runtime();solo_dm=DataManager(rows)
        baseline=await compute_indicator_range_batch_async(dm=solo_dm,jobs=[early],
            range_service=service(enabled),runtime_service=solo)
        batched=Runtime();dm=DataManager(rows)
        actual=await compute_indicator_range_batch_async(dm=dm,jobs=[early,late],
            range_service=service(enabled),runtime_service=batched)
        assert not any(isinstance(x,BaseException) for x in baseline+actual),repr(baseline+actual)
        assert actual[0]['lines']==baseline[0]['lines']
        assert tuple(b.time for b in rows[580:603]) in batched.inputs
        assert tuple(b.time for b in rows[700:903]) in batched.inputs
        assert solo_dm.queries==1
        assert dm.queries==(1 if enabled else 2)
    asyncio.run(run())


def test_covering_bar_cache_cannot_inject_later_rows_or_excess_prefix():
    async def run():
        rows=bars();dm=DataManager(rows);cache=service();runtime=Runtime()
        large=replace(job(rows,400,warmup=200),end=rows[902].time)
        await compute_indicator_range_batch_async(dm=dm,jobs=[large],range_service=cache,runtime_service=runtime)
        earlier=job(rows,600,warmup=200)
        actual=await compute_indicator_range_batch_async(dm=dm,jobs=[earlier],range_service=cache,runtime_service=runtime)
        solo=await compute_indicator_range_batch_async(dm=DataManager(rows),jobs=[earlier],
            range_service=service(),runtime_service=Runtime())
        assert actual[0]['lines']==solo[0]['lines']
        assert runtime.inputs[-1]==tuple(b.time for b in rows[400:603])
        assert dm.queries==1
    asyncio.run(run())


def test_covering_execution_in_flight_cannot_replace_narrow_script_execution():
    async def run():
        rows=bars();dm=DataManager(rows);cache=service();runtime=Runtime()
        large=replace(job(rows,400),end=rows[902].time)
        earlier=job(rows,600)
        actual=await compute_indicator_range_batch_async(dm=dm,jobs=[large,earlier],
            range_service=cache,runtime_service=runtime)
        solo=await compute_indicator_range_batch_async(dm=DataManager(rows),jobs=[earlier],
            range_service=service(),runtime_service=Runtime())
        assert actual[1]['lines']==solo[0]['lines']
        assert len(runtime.inputs)==2
        assert dm.queries==1
    asyncio.run(run())


def test_script_ws_seed_and_http_warmup_do_not_alias_execution_cache():
    rows=bars();target=job(rows,600);cache=service()
    ws_meta={**target.meta,'historyLimit':500}
    payload={'ok':True,'lines':[{'id':'main','data':[]}]}
    assert cache.put_payload(meta=ws_meta,start=target.start,end=target.end,payload=payload)
    assert cache.lookup_snapshot(ws_meta,target.start,target.end) is not None
    assert cache.lookup_snapshot(target.meta,target.start,target.end) is None
    assert cache.lookup_snapshot({**ws_meta,'historyLimit':1000},target.start,target.end) is None
