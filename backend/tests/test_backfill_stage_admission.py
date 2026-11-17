"""Resource permits resume existing work; they do not replay the engine."""
import asyncio
import pytest
from app.data_engine.memory_budget import MemoryBudget,work_pool


def budget(size=10):
    result=MemoryBudget(size)
    result.register('history-backfill',limit_bytes=size,usage=lambda:{'estimated_bytes':0})
    return result


def test_staged_claims_cannot_all_hold_planning_memory_and_deadlock_on_growth():
    async def run():
        owner=budget()
        first=await owner._acquire_pool('history-backfill',4,10)
        second=asyncio.create_task(owner._acquire_pool('history-backfill',4,10))
        await asyncio.sleep(.01)
        assert not second.done()
        await asyncio.wait_for(first.resize(8),1)
        assert not second.done()
        first.close()
        other=await asyncio.wait_for(second,1)
        other.close()
        assert owner.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_waiters_receive_exclusive_bytes_before_their_coroutines_resume():
    async def run():
        owner=budget()
        held=owner.reserve('history-backfill',10);held.__enter__()
        waits=[asyncio.create_task(owner._acquire_pool('history-backfill',6,6)) for _ in range(12)]
        await asyncio.sleep(.01)
        held.__exit__(None,None,None)
        await asyncio.sleep(.01)
        assert sum(task.done() for task in waits)==1
        for task in waits:
            grant=await asyncio.wait_for(task,1)
            assert owner.snapshot()['reserved_bytes']==6
            grant.close()
        assert not owner._pool_waiters and owner.snapshot()['reserved_bytes']==0
    asyncio.run(run())


@pytest.mark.parametrize('cancel_after_grant',[False,True])
def test_cancelled_resource_wait_returns_granted_and_queued_capacity(cancel_after_grant):
    async def run():
        owner=budget()
        held=owner.reserve('history-backfill',10);held.__enter__()
        task=asyncio.create_task(owner._acquire_pool('history-backfill',6,6))
        await asyncio.sleep(.01)
        if cancel_after_grant:held.__exit__(None,None,None)
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        if not cancel_after_grant:held.__exit__(None,None,None)
        assert not owner._pool_waiters and owner.snapshot()['reserved_bytes']==0
    asyncio.run(run())


def test_shared_payload_stays_charged_after_original_work_closes():
    async def run():
        owner=budget()
        grant=await owner._acquire_pool('history-backfill',6,6)
        payload=grant.reserve(4)
        grant.close()
        assert owner.snapshot()['reserved_bytes']==4
        payload.close()
        assert owner.snapshot()['reserved_bytes']==0 and not owner._work_pools
    asyncio.run(run())


def test_deferred_attempt_drops_page_loans_before_another_planner_needs_capacity():
    from types import SimpleNamespace
    from app.data_engine.backfill.resource_scope import admitted_work
    from app.data_engine.backfill.input_subscriptions import InputAdoption
    from app.data_engine.memory_budget import current_work_pool
    async def run():
        owner=budget(10*1024*1024)
        engine=SimpleNamespace(memory_budget=owner,_cfg=SimpleNamespace(standard_intervals={'1m'}))
        scope=InputAdoption(SimpleNamespace(metadata={}))
        @admitted_work
        async def attempt(self,**kwargs):
            pool=current_work_pool(owner)
            await pool.resize(8*1024*1024)
            scope.retain(pool.reserve(6*1024*1024).close)
            raise RuntimeError('external quota or view deferral')
        with scope:
            with pytest.raises(RuntimeError):
                await attempt(engine,intervals=['1m'])
            assert not scope._release
            assert owner.snapshot()['reserved_bytes']==0
            other=await asyncio.wait_for(owner._acquire_pool('history-backfill',8*1024*1024,10*1024*1024),1)
            other.close()
        assert not owner._work_pools
    asyncio.run(run())


def test_received_input_credit_survives_reopening_the_work_after_external_deferral():
    async def run():
        owner=budget()
        first=await owner._acquire_pool('history-backfill',6,10)
        payload=first.reserve(4)
        first.close()
        resumed=await owner._acquire_pool('history-backfill',6,10,pool=first)
        assert resumed is first and resumed.available==2
        await resumed.resize(8)
        assert owner.snapshot()['reserved_bytes']==8 and resumed.available==4
        resumed.close();payload.close()
        assert owner.snapshot()['reserved_bytes']==0 and not owner._work_pools
    asyncio.run(run())


def test_executor_permit_wait_cancellation_does_not_queue_physical_work():
    from app.core.bounded_executor import BoundedExecutor
    from app.core.executors import _run
    from app.core.resource_wait import enabled
    import threading
    async def run():
        pool=BoundedExecutor('permit-cancellation-test',max_workers=1,max_pending=0)
        release=threading.Event()
        running=pool.submit(release.wait)
        token=enabled.set(True)
        called=[]
        try:
            for _ in range(50):
                waiting=asyncio.create_task(_run(pool,lambda:called.append(True)))
                await asyncio.sleep(0)
                waiting.cancel()
                await asyncio.gather(waiting,return_exceptions=True)
            assert pool.snapshot()['admission_waiters']==0
            assert pool.snapshot()['submitted']==1 and not called
            release.set();await asyncio.wrap_future(running)
            assert await _run(pool,lambda:42)==42
            assert not pool.snapshot()['reserved_admissions']
        finally:
            enabled.reset(token)
            release.set();pool.shutdown()
    asyncio.run(run())


def test_owner_eviction_without_lease_release_can_wake_one_atomic_grant():
    async def run():
        usage={'estimated_bytes':10}
        owner=MemoryBudget(10)
        owner.register('history-backfill',limit_bytes=10,usage=lambda:usage)
        task=asyncio.create_task(owner._acquire_pool('history-backfill',6,6))
        await asyncio.sleep(.01)
        assert not task.done()
        usage['estimated_bytes']=0
        grant=await asyncio.wait_for(task,2)
        assert owner.snapshot()['reserved_bytes']==6
        grant.close()
        assert not owner._work_pollers
    asyncio.run(run())


def test_live_stage_growth_precedes_reopening_old_work_with_retained_inputs():
    async def run():
        owner=budget()
        previous=await owner._acquire_pool('history-backfill',4,10)
        previous.close()
        active=await owner._acquire_pool('history-backfill',4,10)
        reopened=asyncio.create_task(owner._acquire_pool('history-backfill',4,10,pool=previous))
        await asyncio.sleep(.01)
        assert not reopened.done()
        await asyncio.wait_for(active.resize(6),1)
        resumed=await asyncio.wait_for(reopened,1)
        assert resumed is previous and owner.snapshot()['reserved_bytes']==10
        active.close();resumed.close()
        assert not owner._work_pools and owner.snapshot()['reserved_bytes']==0
    asyncio.run(run())
