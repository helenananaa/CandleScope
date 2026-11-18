"""Admit a bounded working set, then resume the same backfill coroutine."""
from functools import wraps
from contextlib import asynccontextmanager
import math

from app.data_engine.memory_budget import work_pool, current_work_pool, retained_size,MemoryBudgetExceeded
from .input_subscriptions import current_input_adoption
from .fetch_stream import PAGE_BYTES_PER_ROW, stream_grid


def admitted_work(function):
    @wraps(function)
    async def run(self,*args,**kwargs):
        from .mixed_plan import WORK_BYTES,PLAN_BYTES
        intervals = kwargs.get('intervals') or (args[1] if len(args)>1 else ())
        initial = (WORK_BYTES+PLAN_BYTES if any(i not in self._cfg.standard_intervals
                   for i in intervals or ()) else 1024*1024)
        scope = current_input_adoption()
        budget=getattr(self,'memory_budget',None)
        managed=bool(scope and scope.managed)
        if budget is not None and managed:
            budget.ensure_owner('history-backfill-plans',limit_bytes=min(budget.total_bytes,32*1024*1024),
                usage=lambda:dict(estimated_bytes=0))
        carry = scope.memory_pool if scope is not None and scope._release else None
        async with work_pool(budget,64*1024,owner='history-backfill-plans',maximum=WORK_BYTES,
                             managed=managed,phase='plan_metadata') as plan_pool, work_pool(budget,initial,
                             managed=managed,carry=carry,maximum=initial,phase='planning') as pool:
            if scope is not None:
                scope.memory_pool = pool
            if pool is not None:
                pool.plan_pool=plan_pool
            try:
                return await function(self,*args,**kwargs)
            finally:
                # A deferred parent needs a fresh planning grant. Do not pin
                # its old page loans while it waits for that grant: qualified
                # received pages already belong to the source journal.
                if scope is not None and scope.managed:
                    scope.acknowledge()
    return run


def streaming_plan(engine,plan,receipt_mode,native_progress):
    from .fetch_stream import stream_plan
    from .fetcher import HistoricalFetcher
    from .reconciler import Reconciler
    return (receipt_mode and native_progress is None and stream_plan(plan,engine.config.fetch_batch_size)
        and getattr(engine._storage,'revision_store',None) is not None
        and getattr(engine.fetcher.fetch,'__func__',None) is HistoricalFetcher.fetch
        and getattr(engine.reconciler.reconcile,'__func__',None) is Reconciler.reconcile
        and engine.reconciler._custom_dedup_fn is None and engine.reconciler._custom_aggregator is None)


async def retain_execution_plan(engine,plan):
    pool = current_work_pool(getattr(engine,'memory_budget',None))
    if pool is None:
        return
    from .mixed_plan import WORK_BYTES
    # Release the entire scratch claim before waiting on plan accounting or
    # execution. No collection of planners can retain the work capacity that
    # their completed plans need in order to finish.
    await pool.stage(0,0,retained=0)
    plan_bytes=max(64*1024,retained_size((plan,))[0])
    if plan_bytes>WORK_BYTES:
        raise MemoryBudgetExceeded('retained plan exceeds its admitted metadata bound')
    await pool.plan_pool.stage(plan_bytes,WORK_BYTES)
    return pool


async def admit_execution(engine,plan,*,streaming=False):
    from .mixed_plan import WORK_BYTES,PLAN_BYTES
    pool = await retain_execution_plan(engine,plan)
    if pool is None:
        return
    rows = max(1,plan.estimated_bars,plan.metadata.get('mixed_source_rows',0))
    payload = bitmap = 0
    batch = min(1000,engine.config.fetch_batch_size)
    for task in plan.tasks:
        count = max(1,task.estimated_bars)
        pages = math.ceil(count/batch)+1  # allow a final empty/short-page probe
        qualified = task.exchange=='binance' and task.market_type in {'spot','futures'} and stream_grid(task,batch)
        payload += ((2*count if qualified else pages*batch)*PAGE_BYTES_PER_ROW + pages*32*1024)
        bitmap += (count+7)//8+32*1024
    # The qualified reducer reads at most 256 canonical inputs at once and
    # retains at most the admitted target outputs. Native pages already commit
    # before this phase, so their entire row count is not a compute buffer.
    targets=sum(max(1,(d.composition_target_range[1]-d.composition_target_range[0])//d.custom_duration_ms)
        for d in plan.decompositions if getattr(d,'composition_target_range',None))
    retained = ((min(rows,256)+targets) if streaming else rows)*2048
    compute = WORK_BYTES+retained
    if plan.derived_source_windows:
        compute += PLAN_BYTES
    # Streaming pages own independent, short-lived raw+normalization permits.
    # The plan declares only its eventual compute peak, not all HTTP responses.
    base = WORK_BYTES+bitmap
    size = base if streaming else base+retained+payload
    maximum = max(size,compute if streaming else size+compute-retained)
    await pool.stage(size,maximum,retained=0)
    pool.phase='fetch'
    pool.reconcile_bytes=maximum
    pool.normalized_bytes=retained
    plan.metadata['resource_admission']=dict(streaming=bool(streaming),
        retained_plan_bytes=base,fetch_bytes=size,compute_peak_bytes=maximum,
        whole_raw_payload_bytes=payload)


async def admit_reconcile(engine,plan):
    pool=current_work_pool(getattr(engine,'memory_budget',None))
    if pool is not None:
        await pool.resize(pool.reconcile_bytes)
        pool.phase='reconcile'


def normalized_bytes(engine,plan):
    pool=current_work_pool(getattr(engine,'memory_budget',None))
    return (pool.normalized_bytes if pool is not None else
        max(1,plan.estimated_bars,plan.metadata.get('mixed_source_rows',0))*2048)


@asynccontextmanager
async def page_credit(budget,limit):
    scope=current_input_adoption()
    if budget is None or scope is None or not scope.managed or not scope.streaming_page:
        yield None
        return
    size=min(limit,1000)*PAGE_BYTES_PER_ROW*2+64*1024
    async with work_pool(budget,size,maximum=size,phase='page') as pool:
        yield pool
