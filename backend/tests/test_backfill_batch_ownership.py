"""B459 scheduler contracts through the existing async dispatch owner."""
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


def test_four_chart_bursts_and_maintenance_keep_bounded_turns_and_concurrency():
    from types import SimpleNamespace
    async def run():
        entered, release=asyncio.Event(),asyncio.Event()
        calls=[]; running=0;peak=0
        async def execute(req):
            nonlocal running,peak
            running+=1;peak=max(peak,running);calls.append(req.interval)
            try:
                if len(calls)==1:
                    entered.set();await release.wait()
                await asyncio.sleep(0)
                return RepairOutcome(req,'completed',verified_contiguous=True,
                    report=SimpleNamespace(network_free=True,elapsed_ms=1,reconcile_result=SimpleNamespace(elapsed_ms=1)))
            finally:
                running-=1
        scheduler=scheduler_for(execute,concurrency=2)
        futures=[]
        try:
            for period in [89,97,101,10007]:
                r=request(0,202,name=f'chart-{period}',interval=f'{period}m',metadata={
                    'bounded_history_batch_contract':scheduler._interval_resolver.history_composition_routes(
                        exchange='binance',market_type='futures',interval=f'{period}m')[0].contract_id})
                _,f=scheduler.submit(r);futures.append(f)
                if period==89:await entered.wait()
            maintenance=request(0,0,name='maintenance',interval='1m')
            maintenance.reason,maintenance.priority='background_gap_audit',100
            _,f=scheduler.submit(maintenance);futures.append(f)
            release.set();await asyncio.wait_for(asyncio.gather(*futures),5)
            assert peak<=2
            assert all(calls.index(f'{period}m')<=scheduler.max_dispatch_bypass+4 for period in [89,97,101,10007]), calls
            assert calls.index('1m')<=scheduler.max_dispatch_bypass+4
            receipts=scheduler.snapshot()['recent_chunks']
            assert all(r['planned_source_rows']<=r['source_row_budget'] for r in receipts)
            assert all(r['finished_at_ms']>=r['started_at_ms']>=r['queued_at_ms'] for r in receipts)
            assert all(r['ready_queue_ms']>=0 and r['worker_elapsed_ms']>=0 for r in receipts)
        finally:
            release.set();await scheduler.shutdown()
    asyncio.run(run())


def test_shared_consumers_keep_surviving_lease_and_progress_after_one_closes():
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        calls=[]
        async def execute(req):
            calls.append(req)
            if len(calls)==1:entered.set();await release.wait()
            return RepairOutcome(req,'completed',verified_contiguous=True)
        scheduler=scheduler_for(execute,chunk_bars=1)
        try:
            first,done=scheduler.submit(request(0,2,name='a',metadata={'demand_owner_id':'pane-a','demand_scope':'a','demand_generation':1}))
            await entered.wait()
            second,other=scheduler.submit(request(0,2,name='b',metadata={'demand_owner_id':'pane-b','demand_scope':'b','demand_generation':1}))
            assert first==second and done is other
            await scheduler.release_demand(first,owner_id='pane-a',cancel_if_unobserved=True)
            active=scheduler.snapshot()['active'][0]
            assert active['demand_count']==1 and active['demand_details'][0]['owner_id']=='pane-b'
            assert not active['cancel_requested']
            release.set();outcome=await asyncio.wait_for(other,2)
            assert outcome.verified_contiguous and len(calls)==3
            assert scheduler.snapshot()['recent_chunks'][-1]['demand_owner_ids']==['pane-b']
        finally:
            release.set();await scheduler.shutdown()
    asyncio.run(run())


def test_chunk_observation_ring_is_bounded_and_cannot_be_mutated_through_snapshot():
    async def run():
        async def execute(req):
            return RepairOutcome(req,'completed',verified_contiguous=True)
        scheduler=scheduler_for(execute,chunk_bars=1)
        try:
            _,done=scheduler.submit(request(0,259,name='many',metadata={'demand_owner_id':'pane','demand_scope':'scope','demand_generation':1}))
            await asyncio.wait_for(done,10)
            snapshot=scheduler.snapshot()
            assert len(snapshot['recent_chunks'])==snapshot['chunk_receipt_limit']==256
            assert snapshot['chunk_receipt_sequence']==260 and snapshot['chunk_receipts_dropped']==4
            snapshot['recent_chunks'][-1]['status']='modified'
            snapshot['recent_chunks'][-1]['demand_owner_ids'].clear()
            fresh=scheduler.snapshot()['recent_chunks'][-1]
            assert fresh['status']=='completed' and fresh['demand_owner_ids']==['pane']
        finally:
            await scheduler.shutdown()
    asyncio.run(run())


def test_public_admission_deferral_keeps_queue_and_ineligible_time_separate():
    from tests.test_backfill_coordinator import _quota_deferral
    async def run():
        calls=[]
        async def execute(req):
            calls.append(req)
            if len(calls)==1:raise _quota_deferral(.02)
            return RepairOutcome(req,'completed',verified_contiguous=True)
        scheduler=scheduler_for(execute)
        try:
            _,done=scheduler.submit(request(0,0,name='deferred'))
            await asyncio.wait_for(done,2)
            rows=scheduler.snapshot()['recent_chunks']
            assert [r['status'] for r in rows]==['public_admission_deferred','completed']
            assert rows[0]['defer_reason']=='cooldown' and rows[0]['retry_at_ms'] is not None
            assert rows[1]['not_eligible_wait_ms']>0 and rows[1]['ready_queue_ms']>=0
            assert rows[1]['dispatch_attempt']==2
        finally:
            await scheduler.shutdown()
    asyncio.run(run())
