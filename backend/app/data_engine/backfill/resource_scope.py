"""Admit a bounded working set, then resume the same backfill coroutine."""
from functools import wraps
import math

from app.data_engine.memory_budget import work_pool, current_work_pool
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
        carry = scope.memory_pool if scope is not None and scope._release else None
        async with work_pool(getattr(self,'memory_budget',None),initial,
                             managed=bool(scope and scope.managed),carry=carry) as pool:
            if scope is not None:
                scope.memory_pool = pool
            try:
                return await function(self,*args,**kwargs)
            finally:
                # A deferred parent needs a fresh planning grant. Do not pin
                # its old page loans while it waits for that grant: qualified
                # received pages already belong to the source journal.
                if scope is not None and scope.managed:
                    scope.acknowledge()
    return run


async def admit_execution(engine,plan):
    pool = current_work_pool(getattr(engine,'memory_budget',None))
    if pool is None:
        return
    from .mixed_plan import WORK_BYTES,PLAN_BYTES
    rows = max(1,plan.estimated_bars,plan.metadata.get('mixed_source_rows',0))
    payload = bitmap = 0
    batch = min(1000,engine.config.fetch_batch_size)
    for task in plan.tasks:
        count = max(1,task.estimated_bars)
        pages = math.ceil(count/batch)+1  # allow a final empty/short-page probe
        qualified = task.exchange=='binance' and task.market_type in {'spot','futures'} and stream_grid(task,batch)
        payload += ((2*count if qualified else pages*batch)*PAGE_BYTES_PER_ROW + pages*32*1024)
        bitmap += (count+7)//8+32*1024
    size = pool.children + rows*2048 + payload + bitmap + WORK_BYTES
    if plan.derived_source_windows:
        size += PLAN_BYTES
    await pool.resize(size)
