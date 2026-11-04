"""Profile-owned creation, preparation and execution of continuing BAR runs.

Submission owns backend intent independently of its HTTP/view caller. One serial
preparation worker and a finite Runtime own all work; market events only wake
readers. This private controller is not yet a public API or default live owner.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from functools import partial
from pathlib import Path

from app.core.async_cleanup import finish_cleanup
from app.core import config
from app.core.bounded_executor import BoundedExecutor
from app.core.executors import run_storage
from app.data_engine.data_manager.models import SeriesKey, DataEventType
from app.data_engine.series_identity import KlineSeriesIdentity
from app.data_engine.storage.prefix_watches import PrefixAcquisitionChanged, PrefixReceipt
from .continuous_bar_host import ContinuousBarHost, ContinuousExecutionStopping
from .continuous_bar_source import ContinuousMarketBarSource, STEP
from .continuous_definition import prepare_definition
from .continuous_inputs import ContinuousInputs, ProfileLease
from .continuous_provider import ContinuousProviderFactory
from .continuous_runtime import ContinuousStrategyRuntime, WAKE_EVENTS
from .continuous_store import ContinuousStrategyStore, _wire, MAX_DEFINITION_BYTES
from .errors import BacktestError


def _key(definition):
    series=definition["source_series"]
    return SeriesKey.create(series[2],series[3],exchange=series[0],market_type=series[1],
        identity=KlineSeriesIdentity(*series[4:]))


class _Preparation:
    def __init__(self,owner,key,definition,mode,from_ms,cutoff_ms):
        self.owner,self.key,self.definition=owner,key,deepcopy(definition)
        self.mode,self.from_ms,self.cutoff_ms=mode,from_ms,cutoff_ms
        self.market=_key(definition)
        self.source=ContinuousMarketBarSource(owner.manager,owner.inputs.datasets,self.market,
            clock_ms=owner.clock_ms,auto_backfill=True)
        self.wake=asyncio.Event()
        self.stopping=False
        self.subscription=None
        self.demand_attempted=False
        self.subscription_lost=False
        self.stream_unavailable=False
        self.provider=None
        self.source_refreshes=0
        self.row=None
        self.task=None
        self.reserved=asyncio.get_running_loop().create_future()
        self.reserved.add_done_callback(lambda done:None if done.cancelled() else done.exception())
        self.cleaned=False

    @property
    def consumer_id(self):return "strategy:prepare:"+self.row["run_id"]

    def request_stop(self):
        self.stopping=True
        self.source.request_stop()
        self.wake.set()

    async def work(self,function):
        future=asyncio.wrap_future(self.owner.executor.submit(function))
        try:return await asyncio.shield(future)
        except asyncio.CancelledError as cancelled:
            self.request_stop()
            try:await finish_cleanup(future)
            except BaseException:pass
            raise cancelled

    async def subscribe(self):
        async def changed(event):
            if event.event_type in {DataEventType.STREAM_ERROR,DataEventType.STREAM_STOPPED}:self.stream_unavailable=True
            elif event.event_type==DataEventType.STREAM_STARTED:self.stream_unavailable=False
            self.wake.set()
        async def lost(_error):
            self.subscription_lost=True
            self.wake.set()
        if self.subscription is not None:
            await self.owner.manager.unsubscribe_async(self.subscription)
            self.subscription=None
        key=self.market
        self.subscription=await self.owner.manager.subscribe_async(changed,symbol=key.symbol,
            interval=key.interval,exchange=key.exchange,market_type=key.market_type,
            series_identity=key.identity,event_types=WAKE_EVENTS,continuity="gap_aware",on_recovery=lost)
        self.subscription_lost=False

    def prepare(self,gaps=(),stream_unavailable=False):
        """No await, no event payloads and no financial changes before fences."""
        if self.stopping:raise ContinuousExecutionStopping()
        if self.provider is not None:
            self.provider.close()
            self.provider=None
        journal=self.owner.store.creations
        row=journal.describe(self.key)
        if row["phase"]=="REQUESTED":
            point=self.source.register(row["run_id"],from_ms=row["from_ms"])
            row=journal.register_watch(self.key,revision=row["revision"],receipt=point.to_dict())
        try:
            if stream_unavailable or any(start<=row["cutoff_ms"] and end>=row["from_ms"] for start,end in gaps):
                raise BacktestError("CONTINUOUS_SOURCE_GAP","Wait for Manager source continuity")
            if row["phase"]=="WATCHED":
                budget=self.owner.inputs.payload_budget()
                frozen=self.source.freeze_initial(PrefixReceipt.from_dict(row["watch"]),
                    through_ms=row["cutoff_ms"],dataset_id=row["dataset_id"],max_payload_bytes=budget)
                self.owner.inputs.check_published(row["dataset_id"])
                row=journal.freeze_input(self.key,revision=row["revision"],
                    descriptor=frozen.descriptor,proof=frozen.proof.to_dict())
            if self.stopping:raise ContinuousExecutionStopping()
            if row["phase"]!="READY":return row["phase"]=="COMMITTED"
            context=journal.creation_context(self.key)
            point=context["receipt"]
            def fenced(publish):
                def guarded():
                    if self.stopping:raise ContinuousExecutionStopping()
                    return publish()
                return self.owner.manager.bars.prefixes.commit(context["proof"],guarded,
                    committed_through_ms=point.through_ms)
            def provider_factory(definition):
                self.provider=self.owner.runtime.provider_factory(definition)
                return self.provider
            ContinuousBarHost.create_run(self.owner.store,row["run_id"],definition=context["definition"],
                mode=row["mode"],data_revision=point.incarnation,event_time_ms=point.through_ms,
                source_receipt=point,provider_factory=provider_factory,
                creation_request=(self.key,context["revision"]),commit_checkpoint=fenced)
            self.provider=None  # Host physically closed it before returning.
            return True
        except PrefixAcquisitionChanged as failure:
            # No account exists yet: re-copy its original window, never reset a
            # committed financial account. Retrying once now also handles an
            # amendment whose notification preceded the failed source fence.
            self.source_refreshes+=1
            if self.source_refreshes>3:
                raise BacktestError("CONTINUOUS_INITIAL_SOURCE_UNSTABLE","Initial source kept changing; retry preparation explicitly") from failure
            journal.defer(self.key,revision=row["revision"],code="CONTINUOUS_INITIAL_SOURCE_CHANGED",
                message=str(failure),refresh_input=True)
            self.owner.inputs.collect()
            self.owner.loop.call_soon_threadsafe(self.wake.set)
            return False
        except BacktestError as failure:
            if failure.code!="CONTINUOUS_SOURCE_GAP":raise
            journal.defer(self.key,revision=row["revision"],code=failure.code,message=str(failure))
            return False  # Manager completion/correction wakes the next query.

    async def cleanup(self):
        if self.cleaned:return
        self.request_stop()
        def close_worker():
            if self.provider is not None:
                self.provider.close()
                self.provider=None
            self.source.close()
        await self.work(close_worker)
        if self.subscription is not None:
            await self.owner.manager.unsubscribe_async(self.subscription)
            self.subscription=None
        if self.demand_attempted:
            key=self.market
            await self.owner.manager.release_stream(key.symbol,key.interval,exchange=key.exchange,
                market_type=key.market_type,series_identity=key.identity,
                consumer_id=self.consumer_id,focus_scope="background")
            self.demand_attempted=False
        self.cleaned=True

    async def serve(self):
        try:
            self.row=await self.work(partial(self.owner.store.creations.reserve,self.key,
                definition=self.definition,mode=self.mode,from_ms=self.from_ms,cutoff_ms=self.cutoff_ms))
            self.reserved.set_result(None)
            if self.row["phase"]=="COMMITTED":
                await self.owner._start_committed(self.row)
                return
            if self.row["phase"] in {"PAUSED","CANCELLED","FAILED"} or self.stopping:return
            await self.subscribe()  # Subscribe before demand and the first query.
            self.demand_attempted=True
            key=self.market
            await self.owner.manager.bars.ensure_stream(key.symbol,key.interval,exchange=key.exchange,
                market_type=key.market_type,series_identity=key.identity,
                consumer_id=self.consumer_id,focus_scope="background")
            self.wake.set()
            while not self.stopping:
                await self.wake.wait()
                self.wake.clear()
                if self.stopping:break
                if self.subscription_lost:await self.subscribe()
                gaps=tuple((gap.start_ms,gap.end_ms) for gap in self.owner.manager.source_gaps.pending(self.market))
                committed=await self.work(partial(self.prepare,gaps,self.stream_unavailable))
                if committed:
                    # Runtime owns its demand before the preparation lease ends.
                    if not self.stopping and not self.owner.closed:await self.owner._start_committed(self.row)
                    break
        except ContinuousExecutionStopping:
            pass
        except Exception as failure:
            self.owner.runtime.record_failure(self.row["run_id"] if self.row else self.key,failure)
            if not self.reserved.done():self.reserved.set_exception(failure)
            if self.row is not None and not self.stopping:
                current=await run_storage(self.owner.store.creations.describe,self.key)
                if current["phase"] not in {"COMMITTED","CANCELLED","FAILED","PAUSED"}:
                    await self.work(partial(self.owner.store.creations.fail,self.key,revision=current["revision"],
                        code=str(getattr(failure,"code","CONTINUOUS_PREPARATION_FAILED"))[:64],message=str(failure)))
        finally:
            if not self.reserved.done():self.reserved.set_exception(BacktestError("CONTINUOUS_NOT_READY","Creation owner is stopping"))
            await finish_cleanup(self.cleanup())
            if self.owner.jobs.get(self.key) is self:self.owner.jobs.pop(self.key)


class ContinuousStrategyController:
    def __init__(self,store,manager,inputs,lease,*,clock_ms,max_active_runs=2,provider_factory=None):
        self.store,self.manager,self.inputs,self.lease=store,manager,inputs,lease
        self.clock_ms=clock_ms
        self.runtime_mode=config.RUNTIME_MODE
        self.execution_enabled=self.runtime_mode=="LIVE" and manager is not None
        self.loop=asyncio.get_running_loop()
        self.runtime=ContinuousStrategyRuntime(store,manager,inputs.datasets,
            provider_factory or ContinuousProviderFactory(),clock_ms=clock_ms,max_active_runs=max_active_runs)
        self.executor=BoundedExecutor("continuous-preparation",max_workers=1,max_pending=0)
        self.jobs={}
        self.actions={}
        self.closed=False
        self.resources_closed=False
        self.close_task=None
        self.restore_task=None

    @classmethod
    async def open(cls,path,manager,*,clock_ms,max_active_runs=2,input_options=None,store_options=None,provider_factory=None):
        path=Path(path)
        if not path.is_absolute() or path.is_symlink():
            raise BacktestError("CONTINUOUS_INPUT_OWNERSHIP","Use the absolute owned database path, without a database symlink")
        def acquire():
            lease=ProfileLease(path.parent/"continuous-execution.lock")
            store=None
            try:
                store=ContinuousStrategyStore(path,**(store_options or {}))
                inputs=ContinuousInputs(store,**(input_options or {}))
                return store,inputs,lease
            except BaseException:
                if store is not None:store.close()
                lease.close()
                raise
        task=asyncio.create_task(run_storage(acquire))
        try:store,inputs,lease=await asyncio.shield(task)
        except asyncio.CancelledError as cancelled:
            async def release():
                store,_inputs,lease=await task
                await run_storage(store.close)
                lease.close()
            await finish_cleanup(release())
            raise cancelled
        try:return cls(store,manager,inputs,lease,clock_ms=clock_ms,max_active_runs=max_active_runs,provider_factory=provider_factory)
        except BaseException:
            await run_storage(store.close)
            lease.close()
            raise

    def _ready(self):
        if self.closed:raise BacktestError("CONTINUOUS_NOT_READY","Continuous creation owner is closed")

    def _live(self):
        self._ready()
        if config.RUNTIME_MODE!="LIVE" or not self.execution_enabled:
            raise BacktestError("CONTINUOUS_NOT_READY","Market continuation requires the LIVE profile and its DataManager")
        if self.restore_task is not None and not self.restore_task.done():
            raise BacktestError("CONTINUOUS_NOT_READY","Profile restoration is in progress")

    def _admit(self,key,definition,mode,from_ms,cutoff_ms):
        self._ready()
        if self.actions:raise BacktestError("CONTINUOUS_NOT_READY","Creation control is draining")
        existing=self.jobs.get(key)
        if existing is not None:
            if (_wire(existing.definition,MAX_DEFINITION_BYTES)!=_wire(definition,MAX_DEFINITION_BYTES)
                    or existing.mode!=mode or existing.from_ms!=from_ms):
                raise BacktestError("CONTINUOUS_COMMIT_CONFLICT","Creation key owns different code or conditions")
            if existing.stopping:raise BacktestError("CONTINUOUS_NOT_READY","Creation is draining")
            return existing
        occupied=set(self.runtime.actors)|set(self.runtime.starts)
        if self.jobs or len(occupied)>=self.runtime.max_active_runs:
            raise BacktestError("BUDGET_EXCEEDED","Continuous preparation or execution capacity reached")
        job=_Preparation(self,key,definition,mode,from_ms,cutoff_ms)
        self.jobs[key]=job
        job.task=asyncio.create_task(job.serve())
        job.task.add_done_callback(lambda done:None if done.cancelled() else done.exception())
        return job

    async def create(self,key,*,provider,execution,series,mode,from_ms=None,warmup_bars=0):
        self._live()
        definition=await run_storage(prepare_definition,provider,execution,series,warmup_bars=warmup_bars)
        now=self.clock_ms()
        if type(now) is not int or now<STEP:raise BacktestError("CONTINUOUS_INPUT_INVALID","Backend UTC clock is unavailable")
        cutoff=(now//STEP)*STEP-1
        # Journal validation must run before any reservation, job or demand.
        from .continuous_store import _text
        _text(key,128)
        if (type(mode) is not str or mode not in {"HISTORY_LIVE","LIVE_ONLY"}
                or (mode=="LIVE_ONLY" and from_ms is not None)
                or (mode=="HISTORY_LIVE" and (type(from_ms) is not int or from_ms<STEP or from_ms%STEP))):
            raise BacktestError("CONTINUOUS_INPUT_INVALID","Creation mode and closed input window are invalid")
        try:row=await run_storage(self.store.creations.describe,key)
        except BacktestError as failure:
            if failure.code!="CONTINUOUS_CREATION_NOT_FOUND":raise
            if mode=="HISTORY_LIVE" and not 1<=(cutoff+1-from_ms)//STEP<=200_000:
                raise BacktestError("CONTINUOUS_INPUT_INVALID","Creation history exceeds its closed input budget")
        else:
            if (_wire(row["definition"],MAX_DEFINITION_BYTES)!=_wire(definition,MAX_DEFINITION_BYTES) or row["mode"]!=mode
                    or (mode=="HISTORY_LIVE" and row["from_ms"]!=from_ms)):
                raise BacktestError("CONTINUOUS_COMMIT_CONFLICT","Creation key owns different code or conditions")
            if row["phase"] in {"COMMITTED","FAILED","PAUSED","CANCELLED"}:return row
            cutoff=row["cutoff_ms"]
        job=self._admit(key,definition,mode,from_ms,cutoff)
        await asyncio.shield(job.reserved)
        return await run_storage(self.store.creations.describe,key)

    async def _start_committed(self,creation):
        row=await run_storage(self.store.summary,creation["run_id"])
        if (row["phase"] in {"LIVE","CATCHING_UP"}
                or (row["phase"]=="PAUSED" and row["generation"]==1 and row["revision"]==1)):
            try:return await self.runtime.start_existing(row["id"],expected_identity=(row["generation"],row["revision"]))
            except Exception as failure:
                if not self.closed:
                    current=await run_storage(self.store.summary,row["id"])
                    if (current["generation"],current["revision"])==(row["generation"],row["revision"]):
                        await run_storage(self.store.stop,row["id"],generation=current["generation"],revision=current["revision"],
                            phase="FAILED",error={"code":str(getattr(failure,"code","CONTINUOUS_START_FAILED"))[:64],"message":str(failure)[:256]})
                raise
        return row

    async def wait_initial(self,key):
        """Committed metadata only; result projections are a separate bounded read."""
        subscription=self.store.updates.subscribe("creation:"+key)
        try:
            while True:
                subscription.clear_before_read()
                creation=await run_storage(self.store.creations.describe,key)
                if creation["phase"]=="COMMITTED":break
                if creation["phase"] in {"FAILED","PAUSED","CANCELLED"}:return {"creation":creation,"run":None}
                if self.closed:raise BacktestError("CONTINUOUS_NOT_READY","Creation owner is closed")
                await subscription.wait()
        finally:subscription.close()
        subscription=self.store.updates.subscribe(creation["run_id"])
        try:
            while True:
                subscription.clear_before_read()
                row=await run_storage(self.store.summary,creation["run_id"])
                if row["event_time_ms"]>=creation["cutoff_ms"] or row["phase"] in {"FAILED","REPAIR_REQUIRED","CANCELLED"}:
                    return {"creation":creation,"run":row}
                if row["phase"]=="PAUSED" and not await run_storage(self.store.creations.initial_start_pending,row["id"]):
                    return {"creation":creation,"run":row}
                if self.closed:raise BacktestError("CONTINUOUS_NOT_READY","Creation owner is closed")
                await subscription.wait()
        finally:subscription.close()

    async def _drain_job(self,key):
        job=self.jobs.get(key)
        if job is not None:
            job.request_stop()
            if not job.task.done():await asyncio.shield(job.task)
            if not job.cleaned:await job.cleanup()
            if self.jobs.get(key) is job:self.jobs.pop(key)

    async def control(self,key,action,*,revision,refresh_input=False):
        self._ready()
        if action not in {"pause","resume","retry","cancel"}:raise BacktestError("CONTINUOUS_INPUT_INVALID","Unknown creation control")
        if type(refresh_input) is not bool:raise BacktestError("CONTINUOUS_INPUT_INVALID","Input refresh must be explicit")
        if action in {"resume","retry"}:self._live()
        if self.actions:raise BacktestError("CONTINUOUS_NOT_READY","Creation control is draining")
        if self.jobs and key not in self.jobs:
            raise BacktestError("BUDGET_EXCEEDED","Another initialization owns preparation and cleanup")
        task=asyncio.create_task(self._control(key,action,revision,refresh_input))
        self.actions[key]=task
        def done(value):
            if self.actions.get(key) is value:self.actions.pop(key)
            if not value.cancelled():value.exception()
        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def _control(self,key,action,revision,refresh_input):
        row=await run_storage(self.store.creations.describe,key)
        if type(revision) is not int or row["revision"]!=revision:
            raise BacktestError("CONTINUOUS_COMMIT_CONFLICT","Creation control is stale")
        if action in {"resume","retry"}:
            if row["phase"]=="COMMITTED":
                if action=="retry" and refresh_input:raise BacktestError("CONTINUOUS_NOT_READY","Financial input repair requires separate authorization")
                await self.runtime.start_existing(row["run_id"],retry_failed=action=="retry")
                return await run_storage(self.store.creations.describe,key)
            # Admission before changing durable intent, including executor cleanup.
            self._ready()
            if self.jobs or len(set(self.runtime.actors)|set(self.runtime.starts))>=self.runtime.max_active_runs:
                raise BacktestError("BUDGET_EXCEEDED","Continuous preparation or execution capacity reached")
            mutation=self.store.creations.resume_preparation if action=="resume" else self.store.creations.retry_failed
            row=await run_storage(mutation,key,revision=revision,**({"refresh_input":refresh_input} if action=="retry" else {}))
            self._ready()
            # This control owns admission until its task yields to preparation.
            job=_Preparation(self,key,row["definition"],row["mode"],row["from_ms"] if row["mode"]=="HISTORY_LIVE" else None,row["cutoff_ms"])
            self.jobs[key]=job
            job.task=asyncio.create_task(job.serve())
            job.task.add_done_callback(lambda done:None if done.cancelled() else done.exception())
            return row
        await self._drain_job(key)
        row=await run_storage(self.store.creations.describe,key)
        if row["phase"]=="COMMITTED":
            if action=="pause":await self.runtime.pause(row["run_id"])
            else:
                await self.runtime.cancel(row["run_id"])
            return row
        mutation=self.store.creations.pause_preparation if action=="pause" else self.store.creations.cancel_preparation
        row=await run_storage(mutation,key,revision=row["revision"])
        if action=="cancel":
            await run_storage(self._collect_cancelled,row)
            row=await run_storage(self.store.creations.clear_cancelled_input,key,revision=row["revision"])
        return row

    def _collect_cancelled(self,row):
        proof=row["input"]["proof"] if row["input"] else row["watch"]
        if proof is None:
            # Crash between register and journal persistence: only the same
            # empty watch can be recovered, never a foreign/new acquisition.
            owner="strategy:"+row["run_id"]
            if self.manager.bars.prefixes.inspect(owner) is not None:
                proof=self.manager.bars.prefixes.register(owner,_key(row["definition"]),
                    from_ms=row["from_ms"],committed_through_ms=row["from_ms"]-1).to_dict()
        if proof:
            point=PrefixReceipt.from_dict(proof)
            actual=self.manager.bars.prefixes.inspect(point.owner)
            if actual is not None:
                # A stopped preparation may have acquired beyond its saved
                # receipt. Adopt only its same uncommitted incarnation.
                if (actual["incarnation"]!=point.incarnation or actual["committed_acquisition"]!=0
                        or actual["committed_through_ms"]!=point.from_ms-1):
                    raise BacktestError("CONTINUOUS_COMMIT_CONFLICT","Cancelled source ownership changed")
                self.manager.bars.prefixes.release(replace(point,acquisition=actual["acquisition"]))
        self.inputs.collect()

    async def restore(self):
        self._live()
        if self.jobs or self.actions or self.runtime.actors or self.runtime.starts:
            raise BacktestError("CONTINUOUS_NOT_READY","Restoration requires a newly opened owner")
        self.restore_task=asyncio.create_task(self._restore())
        self.restore_task.add_done_callback(lambda done:None if done.cancelled() else done.exception())
        return await asyncio.shield(self.restore_task)

    async def _restore(self):
        pending=await run_storage(self.store.creations.list_pending)
        for row in pending:
            if row["phase"]=="CANCELLED":
                current=await run_storage(self.store.creations.describe,row["request_key"])
                await run_storage(self._collect_cancelled,current)
                if current["watch"] or current["input"]:
                    await run_storage(self.store.creations.clear_cancelled_input,row["request_key"],revision=current["revision"])
        await run_storage(self.inputs.collect)
        result=await self.runtime.restore_active()
        result["preparing"]=[]
        for row in pending:
            if row["phase"] in {"REQUESTED","WATCHED","READY"}:
                current=await run_storage(self.store.creations.describe,row["request_key"])
                try:
                    self._admit(row["request_key"],current["definition"],row["mode"],
                        row["from_ms"] if row["mode"]=="HISTORY_LIVE" else None,row["cutoff_ms"])
                    result["preparing"].append(row["run_id"])
                except BacktestError as failure:
                    result["not_admitted"][row["run_id"]]={"code":failure.code,"message":str(failure)[:256]}
        return result

    async def close(self):
        if self.resources_closed:return
        self.request_shutdown()
        if self.close_task is None or self.close_task.done():self.close_task=asyncio.create_task(self._close())
        await finish_cleanup(asyncio.shield(self.close_task))

    def request_shutdown(self):
        """Stop producers before their Manager drains outstanding view reads."""
        self.closed=True
        self.runtime._request_shutdown()
        for job in tuple(self.jobs.values()):job.request_stop()

    async def _close(self):
        # This owned task exists before the first await in close, including
        # cancellation while notifying observers or reading durable intent.
        for row in await run_storage(self.store.creations.list_pending):
            self.store.updates.notify("creation:"+row["request_key"])
        for row in await run_storage(self.store.list_summaries):self.store.updates.notify(row["id"])
        if self.restore_task is not None:await asyncio.gather(self.restore_task,return_exceptions=True)
        await asyncio.gather(*tuple(self.actions.values()),return_exceptions=True)
        for key in tuple(self.jobs):await self._drain_job(key)
        await self.runtime.shutdown()
        self.executor.shutdown(wait=True)
        await run_storage(self.store.close)
        self.lease.close()
        self.resources_closed=True
