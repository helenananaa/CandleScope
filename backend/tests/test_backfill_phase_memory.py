"""Fair phase and page claims under real bounded memory, without larger limits."""
import asyncio
import pytest
from app.core.resource_wait import claim_owner
from app.data_engine.memory_budget import MemoryBudget,work_pool


def budget(size):
    owner=MemoryBudget(size)
    owner.register('history-backfill',limit_bytes=size,usage=lambda:dict(estimated_bytes=0))
    return owner


def test_memory_grants_rotate_chart_owners_before_serving_another_chunk():
    async def run():
        owner=budget(10)
        held=owner.reserve('history-backfill',10);held.__enter__()
        order=[]
        async def wait(chart,index):
            token=claim_owner.set((10,chart))
            try:
                async with work_pool(owner,10,maximum=10):
                    order.append((chart,index))
                    await asyncio.sleep(0)
            finally:
                claim_owner.reset(token)
        tasks=[asyncio.create_task(wait('A',i)) for i in range(12)]
        tasks.extend(asyncio.create_task(wait(c,0)) for c in ['B','C','D'])
        await asyncio.sleep(.01)
        held.__exit__(None,None,None)
        await asyncio.wait_for(asyncio.gather(*tasks),2)
        assert [c for c,_ in order[:4]]==['A','B','C','D']
        assert owner.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_independent_planners_can_release_scratch_and_grow_without_deadlock():
    async def run():
        owner=budget(64)
        ready=asyncio.Event();count=0
        async def plan(chart):
            nonlocal count
            token=claim_owner.set((10,chart))
            try:
                async with work_pool(owner,20,maximum=20) as pool:
                    count+=1
                    if count==3:ready.set()
                    await ready.wait()
                    await pool.stage(4,52)
                    # Pages may complete before a large compute phase.
                    async with work_pool(owner,8,maximum=8):
                        await asyncio.sleep(0)
                    await pool.resize(52)
                    await asyncio.sleep(0)
            finally:claim_owner.reset(token)
        await asyncio.wait_for(asyncio.gather(*(plan(c) for c in ['A','B','C'])),2)
        assert owner.snapshot()['reserved_bytes']==0 and not owner._work_pools
    asyncio.run(run())


def test_cancelled_phase_handoff_releases_retained_plan_claim():
    async def run():
        owner=budget(64)
        pool=await owner._acquire_pool('history-backfill',20,20)
        held=owner.reserve('history-backfill',44);held.__enter__()
        task=asyncio.create_task(pool.stage(4,60))
        await asyncio.sleep(.01)
        assert not task.done() and owner.snapshot()['reserved_bytes']==48
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        held.__exit__(None,None,None)
        assert owner.snapshot()['reserved_bytes']==0 and not owner._work_pools
    asyncio.run(run())


def test_all_planners_return_scratch_before_large_execution_waits():
    async def run():
        owner=budget(64)
        owner.register('plans',limit_bytes=8,usage=lambda:dict(estimated_bytes=0))
        all_planned=asyncio.Event();count=0
        async def execute():
            nonlocal count
            async with work_pool(owner,1,owner='plans',maximum=1),work_pool(owner,20,maximum=20) as pool:
                count+=1
                if count==3:all_planned.set()
                await all_planned.wait()
                await pool.stage(0,0,retained=0)
                await pool.stage(60,60,retained=0)
                await asyncio.sleep(0)
        await asyncio.wait_for(asyncio.gather(*(execute() for _ in range(3))),2)
        assert owner.snapshot()['reserved_bytes']==0 and not owner._work_pools
    asyncio.run(run())


def test_zero_scratch_handoff_keeps_owner_alive_until_work_scope_exits():
    async def run():
        owner=budget(10)
        pool=await owner._acquire_pool('history-backfill',1,1)
        await pool.stage(0,0,retained=0)
        assert owner.snapshot()['reserved_bytes']==0
        with pytest.raises(RuntimeError):owner.unregister('history-backfill')
        pool.close()
        owner.unregister('history-backfill')
    asyncio.run(run())


def test_a_holder_that_can_finish_grows_while_a_larger_holder_waits():
    # Seen in a cold four-chart load: one execution holds 152 of 192 and needs
    # 172; another holds 29 and needs 33; new planners want 20 each. The small
    # growth is safe and lets the large one finish later, so it must not wait
    # behind the blocked one.
    async def run():
        owner=budget(192)
        large=await owner._acquire_pool('history-backfill',152,172)
        small=await owner._acquire_pool('history-backfill',29,33)
        planners=[asyncio.create_task(owner._acquire_pool('history-backfill',20,20)) for _ in range(3)]
        await asyncio.sleep(0)
        growth=asyncio.create_task(large.resize(172))
        await asyncio.sleep(0)
        await asyncio.wait_for(small.resize(33),1)
        assert not growth.done()
        small.close()
        await asyncio.wait_for(growth,1)
        large.close()
        for pool in await asyncio.wait_for(asyncio.gather(*planners),1):
            pool.close()
        assert owner.snapshot()['reserved_bytes']==0 and not owner._work_pools
    asyncio.run(run())


def test_running_holders_get_page_claims_while_a_larger_holder_waits():
    # Seen next: one execution holds 150 of 192 and needs 170; six fetches
    # hold 4 each (up to 20) and need a 1-unit page claim to finish. Those
    # claims are safe and are what eventually frees room for the large one.
    async def run():
        owner=budget(192)
        large=await owner._acquire_pool('history-backfill',150,170)
        fetches=[await owner._acquire_pool('history-backfill',4,20) for _ in range(6)]
        growth=asyncio.create_task(large.resize(170))
        await asyncio.sleep(0)
        pages=[await asyncio.wait_for(owner._acquire_pool('history-backfill',1,1),1) for _ in fetches]
        assert not growth.done()
        for page,fetch in zip(pages,fetches):
            page.close();fetch.close()
        await asyncio.wait_for(growth,1)
        large.close()
        assert owner.snapshot()['reserved_bytes']==0 and not owner._work_pools
    asyncio.run(run())


from tests.test_backfill_dependency_pipeline import setup_pipeline,request,mixed_query,MINUTE


def test_large_prime_reaches_physical_sources_while_other_chart_is_waiting(mixed_query,monkeypatch):
    async def run():
        coordinator,engine,transport,server,started,release,calls=await setup_pipeline(mixed_query,monkeypatch)
        engine.memory_budget=budget(64*1024*1024)
        pending=[asyncio.create_task(coordinator.request_and_wait(request(89)))]
        try:
            await asyncio.wait_for(started.wait(),5)
            pending.extend(asyncio.create_task(coordinator.request_and_wait(request(p))) for p in [97,101])
            large=request(10007)
            large.metadata['required_history_composition']='binance.usdm.trade-klines/base-utc/1'
            pending.append(asyncio.create_task(coordinator.request_and_wait(large)))
            deadline=asyncio.get_running_loop().time()+10
            while not any(iv in {'1d','1h'} for _,iv,_,_ in calls):
                assert asyncio.get_running_loop().time()<deadline,calls
                await asyncio.sleep(.01)
            assert not pending[0].done(), 'large prime must not wait for the first chart to finish'
            release.set()
            outcomes=await asyncio.wait_for(asyncio.gather(*pending),30)
            assert all(r.status=='completed' for r in outcomes),[r.error for r in outcomes]
            result=mixed_query.query('BTCUSDT','10007m',start_ms=0,end_ms=10007*MINUTE-1,
                market_type='futures',limit=1,min_revision=mixed_query.storage.revision_store.head())
            assert result.complete and result.bars[0].trades==10007
        finally:
            release.set();await coordinator.shutdown()
            await asyncio.gather(*pending,return_exceptions=True)
            await engine.close();await transport.stop();await server.cleanup()
        assert engine.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_ten_thousand_native_rows_stream_within_original_64_mib_budget(mixed_query,monkeypatch):
    async def run():
        from app.data_engine.data_manager.backfill_coordinator import RepairRequest
        coordinator,engine,transport,server,started,release,calls=await setup_pipeline(mixed_query,monkeypatch)
        engine.memory_budget=budget(64*1024*1024)
        release.set()
        req=RepairRequest('BTCUSDT','1m',0,9999*MINUTE,exchange='binance',market_type='futures',
            reason='initial_history',metadata={'requires_trusted_finality':True})
        try:
            outcome=await asyncio.wait_for(coordinator.request_and_wait(req),40)
            assert outcome.status=='completed',outcome.error
            assert mixed_query.storage.count_bars('BTCUSDT','1m',0,9999*MINUTE,market_type='futures')==10000
            assert not any(c.get('defer_reason')=='local_memory_admission' for c in coordinator.snapshot()['recent_chunks'])
        finally:
            await coordinator.shutdown();await engine.close();await transport.stop();await server.cleanup()
        assert engine.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_large_prime_with_finer_canonical_presence_keeps_bounded_page_memory(mixed_query,monkeypatch):
    from tests.test_mixed_history_reader import row
    async def run():
        mixed_query.storage.upsert_bars('BTCUSDT','1m',
            [row(at,MINUTE) for at in range(0,10007*MINUTE,60*MINUTE)],
            source='backfill',market_type='futures')
        coordinator,engine,transport,server,started,release,calls=await setup_pipeline(mixed_query,monkeypatch)
        engine.memory_budget=budget(64*1024*1024)
        release.set()
        req=request(10007)
        req.metadata['required_history_composition']='binance.usdm.trade-klines/base-utc/1'
        try:
            outcome=await asyncio.wait_for(coordinator.request_and_wait(req),40)
            assert outcome.status=='completed',outcome.error
            result=mixed_query.query('BTCUSDT','10007m',start_ms=0,end_ms=10007*MINUTE-1,
                market_type='futures',limit=1,min_revision=mixed_query.storage.revision_store.head())
            assert result.complete and result.bars[0].trades==10007
            assert len(calls)<=11,calls
        finally:
            await coordinator.shutdown();await engine.close();await transport.stop();await server.cleanup()
        assert engine.memory_budget.snapshot()['reserved_bytes']==0
    asyncio.run(run())
