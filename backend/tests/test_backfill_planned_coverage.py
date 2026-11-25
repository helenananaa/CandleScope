"""Scheduler dedupe and merge follow the work a request plans, not its envelope.

A request with history_fetch_ranges fetches only those windows. Treating
its start/end envelope as coverage swallowed a later request for a hole
between them, so that hole was never fetched. Overlapping windows fetched
the same opens twice, and a parent without a history contract absorbed a
consumer that required one. ADR-DATA-001 S3, salvaged from the parked #467
(9258f0d2f); its aged-dispatch fairness and chunk diagnostics are not taken.
"""
import asyncio
from collections import Counter

import pytest

from app.data_engine.data_manager.backfill_contracts import RepairRequest, RepairOutcome
from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler

MINUTE = 60_000


def request(first, last, *, name, interval='1m', metadata=None):
    width = int(interval[:-1])*MINUTE
    return RepairRequest('BTCUSDT', interval, first*width, last*width,
        market_type='futures', reason='visible_range_gap', request_id=name,
        metadata=dict(metadata or {}))


def scheduler_for(execute, *, chunk_bars=1000, concurrency=1):
    futures = {}
    def future_for(req):
        return futures.setdefault(req.request_id, asyncio.get_running_loop().create_future())
    def complete(req, result):
        future = future_for(req)
        if not future.done():
            future.set_result(result)
    async def finalize(*_):
        pass
    return BackfillScheduler(execute=execute, future_for=future_for, complete=complete,
        finalize=finalize, on_queued=lambda _:None, max_concurrency=concurrency, chunk_bars=chunk_bars)


def windows():
    return {'history_fetch_ranges':[{'start_ms':0,'end_ms':9*MINUTE},
                                    {'start_ms':20*MINUTE,'end_ms':29*MINUTE}]}


def test_active_envelope_cannot_swallow_a_hole_outside_its_actual_plan():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def execute(req):
            calls.append(req)
            if len(calls)==1:
                entered.set(); await release.wait()
            return RepairOutcome(req, 'completed', verified_contiguous=True)
        scheduler = scheduler_for(execute)
        try:
            first, done = scheduler.submit(request(0,29,name='parent',metadata=windows()))
            await entered.wait()
            second, other = scheduler.submit(request(15,15,name='hole'))
            assert first != second, 'envelope coverage is not planned coverage'
            release.set()
            await asyncio.wait_for(asyncio.gather(done,other),2)
            opened = {at for r in calls for at in range(r.start_ms,r.end_ms+1,MINUTE)}
            assert 15*MINUTE in opened and 10*MINUTE not in opened
        finally:
            release.set(); await scheduler.shutdown()
    asyncio.run(run())


def test_pending_envelope_merge_keeps_incoming_hole_in_actual_work():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def execute(req):
            calls.append(req)
            if req.request_id=='blocker':
                entered.set(); await release.wait()
            return RepairOutcome(req,'completed',verified_contiguous=True)
        scheduler = scheduler_for(execute)
        try:
            _, blocker = scheduler.submit(request(100,100,name='blocker'))
            await entered.wait()
            first, done = scheduler.submit(request(0,29,name='parent',metadata=windows()))
            second, other = scheduler.submit(request(15,15,name='hole'))
            assert first == second and done is other
            chunks=[c.request for c in scheduler._chunks.values() if c.parent_id==first]
            assert any(c.start_ms<=15*MINUTE<=c.end_ms for c in chunks), 'covered consumer hole was dropped'
            release.set()
            await asyncio.wait_for(asyncio.gather(blocker,done),2)
        finally:
            release.set(); await scheduler.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize('incoming_contract',['required_history_composition','bounded_history_batch_contract'])
def test_active_plain_parent_cannot_consume_a_different_execution_contract(incoming_contract):
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        calls=[]
        async def execute(req):
            calls.append(req)
            if len(calls)==1:
                entered.set();await release.wait()
            return RepairOutcome(req,'completed',verified_contiguous=True)
        scheduler=scheduler_for(execute)
        contract=scheduler._interval_resolver.history_composition_routes(
            exchange='binance',market_type='futures',interval='89m')[0].contract_id
        try:
            first,done=scheduler.submit(request(0,3,name='plain',interval='89m'))
            await entered.wait()
            second,other=scheduler.submit(request(0,3,name='qualified',interval='89m',metadata={incoming_contract:contract}))
            assert first!=second, 'source/batch contract was lost to envelope dedupe'
            release.set();await asyncio.wait_for(asyncio.gather(done,other),2)
            assert any(c.metadata.get(incoming_contract)==contract for c in calls)
            assert incoming_contract not in calls[0].metadata
        finally:
            release.set();await scheduler.shutdown()
    asyncio.run(run())


def test_overlapping_planned_ranges_execute_each_requested_open_once():
    async def run():
        calls=[]
        async def execute(req):
            calls.append(req)
            return RepairOutcome(req,'completed',verified_contiguous=True)
        scheduler=scheduler_for(execute)
        try:
            _,done=scheduler.submit(request(0,8,name='overlap',metadata={'history_fetch_ranges':[
                {'start_ms':0,'end_ms':4*MINUTE},{'start_ms':2*MINUTE,'end_ms':8*MINUTE}]}))
            await asyncio.wait_for(done,2)
            counts=Counter(at for r in calls for at in range(r.start_ms,r.end_ms+1,MINUTE))
            assert counts == Counter({i*MINUTE:1 for i in range(9)})
        finally:
            await scheduler.shutdown()
    asyncio.run(run())



@pytest.mark.parametrize('period',[89,97,101,10007])
@pytest.mark.parametrize('count',[1,7,16,128,203])
@pytest.mark.parametrize('contract_key',[None,'bounded_history_batch_contract','required_history_composition'])
def test_page_chunks_keep_exact_target_coverage_and_honest_source_budget(period,count,contract_key):
    scheduler=scheduler_for(None)
    metadata={}
    if contract_key:
        contract=scheduler._interval_resolver.history_composition_routes(
            exchange='binance',market_type='futures',interval=f'{period}m')[0].contract_id
        metadata[contract_key]=contract
    chunks=scheduler._split_request(request(0,count-1,name='page',interval=f'{period}m',metadata=metadata))
    width=period*MINUTE
    assert Counter(at for c in chunks for at in range(c.request.start_ms,c.request.end_ms+1,width)) == Counter({i*width:1 for i in range(count)})
    for chunk in chunks:
        r=chunk.request; plan=r.metadata['interval_work_plan']; actual=(r.end_ms-r.start_ms)//width+1
        assert plan['effective_target_bars']==actual
        assert plan['planned_source_rows']==(actual+plan['source_padding_bars'])*plan['source_factor']
        assert plan['planned_source_rows']<=plan['source_row_budget']
        assert r.metadata['ledger_range']=={'start_ms':0,'end_ms':(count-1)*width}
        assert bool(r.metadata.get('required_history_composition')) == (contract_key=='required_history_composition')


