"""Run this unchanged probe against full baseline and product backends."""
import asyncio
import gc
import weakref
from app.data_engine.backfill.models import BackfillStatus
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_pipeline import Upstream,META
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_history_reader import MINUTE

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

