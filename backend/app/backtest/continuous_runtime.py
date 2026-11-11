"""Bounded backend owners for existing continuing strategy runs.

Every actor owns one serial thread, market demand and a coalesced wake event.
It subscribes before reading; events carry no strategy input/result snapshots.
App lifecycle/control wiring and public creation are separate from this owner.
"""
from __future__ import annotations

import asyncio
from functools import partial
import logging
import threading

from app.core.async_cleanup import finish_cleanup
from app.core.bounded_executor import BoundedExecutor
from app.core.executors import run_storage
from app.data_engine.data_manager.models import DataEventType,SeriesKey
from app.data_engine.series_identity import KlineSeriesIdentity
from .continuous_bar_host import ContinuousBarHost,ContinuousExecutionStopping
from .continuous_bar_source import ContinuousMarketBarSource,STEP
from .continuous_source_identity import affects_protected_prefix
from .errors import BacktestError

logger=logging.getLogger(__name__)
WAKE_EVENTS={DataEventType.BAR_CLOSED,DataEventType.BAR_AMENDED,DataEventType.BACKFILL_COMPLETED,
    DataEventType.SOURCE_GAP,DataEventType.SOURCE_GAP_RESOLVED,DataEventType.STREAM_STARTED,
    DataEventType.STREAM_STOPPED,DataEventType.STREAM_ERROR}


class _Actor:
    def __init__(self, owner, run_id, definition, *, retry_failed):
        series=definition.get("source_series")
        if (definition.get("source_kind") != "MARKET_BAR" or not isinstance(series,list)
                or len(series)!=11 or any(not isinstance(value,str) or not value for value in series)):
            raise BacktestError("CONTINUOUS_INPUT_INVALID","A persistent complete market series identity is required")
        self.key=SeriesKey.create(series[2],series[3],exchange=series[0],market_type=series[1],
            identity=KlineSeriesIdentity(*series[4:]))
        self.owner,self.run_id=owner,run_id
        self.source=ContinuousMarketBarSource(owner.manager,owner.local_datasets,self.key,
            clock_ms=owner.clock_ms,auto_backfill=True)
        self.executor=BoundedExecutor("continuous-strategy",max_workers=1,max_pending=0)
        self.host=None
        self.retry_failed=retry_failed
        self.stopping=False
        self.wake=asyncio.Event()
        self.close_wakeup: asyncio.TimerHandle | None = None
        self.subscription=None
        self.demand_attempted=False
        self.stream_lost=False
        self.stream_unavailable=False
        self.interrupted=threading.Event()
        self.task=None

    @property
    def consumer_id(self):
        return "strategy:continuous:"+self.run_id

    async def _work(self, function):
        future=asyncio.wrap_future(self.executor.submit(function))
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError as cancelled:
            self.request_stop()
            try:
                await finish_cleanup(future)
            except BaseException:
                pass
            raise cancelled

    def request_stop(self):
        self.stopping=True
        self.source.request_stop()
        if self.close_wakeup is not None:
            self.close_wakeup.cancel()
            self.close_wakeup = None
        if self.host is not None:self.host.request_stop()
        self.wake.set()

    def _wake_after_close(self, boundary_ms: int):
        if self.stopping:
            return
        delay_ms = boundary_ms - self.owner.clock_ms()
        if delay_ms <= 0:
            self.wake.set()
        elif delay_ms <= STEP and self.close_wakeup is None:
            self.close_wakeup = asyncio.get_running_loop().call_later(
                delay_ms / 1000, self._close_boundary_reached, boundary_ms,
            )

    def _close_boundary_reached(self, boundary_ms: int):
        self.close_wakeup = None
        self._wake_after_close(boundary_ms)

    async def subscribe(self):
        async def changed(event):
            if event.event_type in {DataEventType.STREAM_STOPPED,DataEventType.STREAM_ERROR}:
                self.stream_unavailable=True
                self.interrupted.set()
            elif event.event_type==DataEventType.STREAM_STARTED:
                self.stream_unavailable=False
            elif event.event_type==DataEventType.SOURCE_GAP:
                self.interrupted.set()
            elif event.event_type in {DataEventType.BAR_AMENDED, DataEventType.BACKFILL_COMPLETED}:
                if await run_storage(self.mark_revised_prefix):
                    self.request_stop()
            elif event.event_type == DataEventType.BAR_CLOSED and event.bar is not None and event.bar.is_closed:
                # A source close can precede our UTC minute boundary. Wake again
                # when the closed input becomes eligible, without moving the fence.
                boundary_ms = event.bar.time * 1000 + STEP
                if boundary_ms % STEP == 0:
                    self._wake_after_close(boundary_ms)
            self.wake.set()
        async def lost(_error):
            self.stream_lost=True
            self.interrupted.set()
            self.wake.set()
        if self.subscription is not None:
            await self.owner.manager.unsubscribe_async(self.subscription)
        self.subscription=await self.owner.manager.subscribe_async(changed,symbol=self.key.symbol,
            interval=self.key.interval,exchange=self.key.exchange,market_type=self.key.market_type,
            series_identity=self.key.identity,event_types=WAKE_EVENTS,continuity="gap_aware",on_recovery=lost)
        self.stream_lost=False

    def mark_revised_prefix(self):
        """Publish staleness from the durable watch while the strategy worker is busy."""
        host = self.host
        point = host.source_receipt if host is not None else None
        if self.stopping or point is None:
            return False
        watch = self.owner.manager.bars.prefixes.inspect(point.owner)
        if (watch is None or watch["incarnation"] != point.incarnation or watch["version"] <= point.version
                or not affects_protected_prefix(point, host.definition, watch["dirty_from_ms"], watch["dirty_through_ms"])):
            return False
        row = self.owner.store.summary(self.run_id)
        if (row["phase"] not in {"CATCHING_UP", "LIVE"} or row["data_revision"] != point.incarnation
                or row["event_time_ms"] != point.through_ms or row["generation"] != host.row["generation"]):
            return False
        try:
            self.owner.store.stop(self.run_id, generation=row["generation"], revision=row["revision"],
                phase="REPAIR_REQUIRED", error={"code":"CONTINUOUS_HISTORY_REVISED",
                    "message":"Processed input changed; committed result retained"})
        except BacktestError as failure:
            if failure.code not in {"CONTINUOUS_COMMIT_CONFLICT", "CONTINUOUS_NOT_READY"}:
                raise
            return False
        return True

    async def setup(self):
        await self.subscribe()
        self.demand_attempted=True
        await self.owner.manager.bars.ensure_stream(self.key.symbol,self.key.interval,
            exchange=self.key.exchange,market_type=self.key.market_type,series_identity=self.key.identity,
            consumer_id=self.consumer_id,focus_scope="background")
        if self.owner.closed or self.stopping:raise ContinuousExecutionStopping()
        self.wake.set()

    def check_input_control(self):
        if self.interrupted.is_set():
            raise BacktestError("CONTINUOUS_SOURCE_GAP","Market source changed availability during execution")

    def fail_owned(self, failure):
        if self.host is not None:
            self.host.fail_input(failure)
            if self.host.resources_closed:self.host=None
        else:
            try:
                row=self.owner.store.summary(self.run_id)
                if row["phase"] in {"PAUSED","LIVE","CATCHING_UP","FAILED"}:
                    self.owner.store.stop(self.run_id,generation=row["generation"],revision=row["revision"],phase="FAILED",
                        error={"code":str(getattr(failure,"code","CONTINUOUS_RESTORE_FAILED"))[:64],"message":str(failure)[:256]})
            except Exception:
                logger.exception("Could not record continuous restore failure; original recovery data retained")

    def _closed_boundary(self):
        return (self.owner.clock_ms() // STEP) * STEP - 1

    def step(self, gaps, stream_unavailable):
        if self.stopping:raise ContinuousExecutionStopping()
        try:
            if self.host is not None and self.host.closed:
                self.host.close()
                self.host=None
            if self.host is None:
                self.host=ContinuousBarHost.resume(self.owner.store,self.run_id,self.owner.provider_factory,
                    retry_failed=self.retry_failed)
                self.retry_failed=False
                self.host.input_control=self.check_input_control
            # Bridge a stop that raced host construction/restore.
            if self.stopping:self.host.request_stop()
            through=self._closed_boundary()
            point=self.host.source_receipt
            if stream_unavailable or any(start<=through and end>=point.from_ms for start,end in gaps):
                raise BacktestError("CONTINUOUS_SOURCE_GAP","DataManager is repairing a retained source gap")
            batch=self.source.acquire(self.host,revealed_through_ms=through)
            batch.apply(self.host,self.owner.manager,current_source_boundary=self._closed_boundary)
            more = (bool(batch.events) and not batch.caught_up) or through < self._closed_boundary()
            return more,False
        except ContinuousExecutionStopping:
            raise
        except Exception as failure:
            self.owner.record_failure(self.run_id,failure)
            self.fail_owned(failure)
            phase=self.owner.store.summary(self.run_id)["phase"]
            return False,phase!="CATCHING_UP"

    def close_worker(self):
        try:
            if self.host is not None:self.host.close()
        finally:
            self.source.close()

    async def cleanup(self):
        self.request_stop()
        await self._work(self.close_worker)
        if self.subscription is not None:
            await self.owner.manager.unsubscribe_async(self.subscription)
            self.subscription=None
        if self.demand_attempted:
            await self.owner.manager.release_stream(self.key.symbol,self.key.interval,
                exchange=self.key.exchange,market_type=self.key.market_type,series_identity=self.key.identity,
                consumer_id=self.consumer_id,focus_scope="background")
            self.demand_attempted=False
        self.executor.shutdown(wait=True)

    async def serve(self):
        try:
            while not self.stopping:
                await self.wake.wait()
                self.wake.clear()  # Clear before acquiring the committed state.
                if self.stopping:break
                if self.stream_lost:await self.subscribe()
                # Registry inspection stays on its owning event loop.
                gaps=tuple((gap.start_ms,gap.end_ms) for gap in self.owner.manager.source_gaps.pending(self.key))
                self.interrupted.clear()
                more,terminal=await self._work(partial(self.step,gaps,self.stream_unavailable))
                if terminal:break
                if more:self.wake.set()
        except ContinuousExecutionStopping:
            pass
        except Exception as failure:
            self.owner.record_failure(self.run_id,failure)
            await self._work(partial(self.fail_owned,failure))
        finally:
            try:
                await finish_cleanup(self.cleanup())
            except Exception as failure:
                self.owner.record_failure(self.run_id,failure)
                raise  # Retain this actor/lease for an explicit cleanup retry.
            else:
                if self.owner.actors.get(self.run_id) is self:self.owner.actors.pop(self.run_id)


class ContinuousStrategyRuntime:
    def __init__(self, store, manager, local_datasets, provider_factory, *, clock_ms, max_active_runs=2):
        if type(max_active_runs) is not int or not 1<=max_active_runs<=16:
            raise ValueError("continuous strategy capacity must be between 1 and 16")
        self.store,self.manager,self.local_datasets,self.provider_factory=store,manager,local_datasets,provider_factory
        self.clock_ms,self.max_active_runs=clock_ms,max_active_runs
        self.closed=False
        self.actors={}
        self.starts={}
        self.last_failures={}
        self._failure_lock=threading.Lock()

    def record_failure(self,run_id,failure):
        # Only bounded diagnostics cross the worker boundary; no state payloads.
        with self._failure_lock:
            self.last_failures[run_id]={"code":str(getattr(failure,"code",type(failure).__name__))[:64],"message":str(failure)[:256]}
            while len(self.last_failures)>64:self.last_failures.pop(next(iter(self.last_failures)))

    async def start_existing(self,run_id,*,retry_failed=False,expected_identity=None):
        if self.closed:raise BacktestError("CONTINUOUS_NOT_READY","Continuous runtime is closed")
        if run_id in self.starts:return await asyncio.shield(self.starts[run_id])
        if run_id in self.actors:
            if self.actors[run_id].stopping:raise BacktestError("CONTINUOUS_NOT_READY","Previous execution is draining")
            return await run_storage(self.store.summary,run_id)
        if len(set(self.actors)|set(self.starts))>=self.max_active_runs:
            raise BacktestError("BUDGET_EXCEEDED","Continuous strategy execution capacity reached")
        task=asyncio.create_task(self._start(run_id,retry_failed=retry_failed,expected_identity=expected_identity))
        self.starts[run_id]=task
        def finished(done):
            # A setup cancelled before its first coroutine step has no finally.
            if self.starts.get(run_id) is done:self.starts.pop(run_id)
            if not done.cancelled():done.exception()
        task.add_done_callback(finished)
        # Request/view cancellation does not own an already authorized backend run.
        return await asyncio.shield(task)

    async def _start(self,run_id,*,retry_failed,expected_identity=None):
        actor=None
        try:
            description=await run_storage(self.store.describe,run_id)
            if expected_identity is not None and (description["run"]["generation"],description["run"]["revision"])!=expected_identity:
                raise BacktestError("CONTINUOUS_COMMIT_CONFLICT","Execution intent changed before automatic restoration")
            phase=description["run"]["phase"]
            if phase not in {"PAUSED","CATCHING_UP","LIVE"} and not (phase=="FAILED" and retry_failed is True):
                raise BacktestError("CONTINUOUS_NOT_READY","Run requires explicit failure or repair resolution")
            if self.closed:raise ContinuousExecutionStopping()
            actor=_Actor(self,run_id,description["definition"],retry_failed=retry_failed)
            self.actors[run_id]=actor
            await actor.setup()
            actor.task=asyncio.create_task(actor.serve())
            actor.task.add_done_callback(lambda done:None if done.cancelled() else done.exception())
            return await run_storage(self.store.summary,run_id)
        except BaseException:
            if actor is not None:
                if actor.task is not None:
                    actor.request_stop()
                    await finish_cleanup(asyncio.gather(actor.task,return_exceptions=True))
                else:
                    await finish_cleanup(actor.cleanup())
                if self.actors.get(run_id) is actor:self.actors.pop(run_id)
            raise
        finally:
            self.starts.pop(run_id,None)

    async def pause(self,run_id):
        if self.closed:raise BacktestError("CONTINUOUS_NOT_READY","Continuous runtime is closed")
        if run_id in self.starts:await asyncio.shield(self.starts[run_id])
        actor=self.actors.get(run_id)
        if actor is not None:
            actor.request_stop()
            await finish_cleanup(asyncio.shield(actor.task))
        row=await run_storage(self.store.summary,run_id)
        if row["phase"]=="REPAIR_REQUIRED":return row
        if row["phase"]=="PAUSED" and not await run_storage(self.store.creations.initial_start_pending,run_id):return row
        return await run_storage(self.store.stop,run_id,generation=row["generation"],revision=row["revision"])

    async def restore_active(self):
        """Restore durable execution intent, leaving explicitly stopped runs alone."""
        if self.closed:raise BacktestError("CONTINUOUS_NOT_READY","Continuous runtime is closed")
        result={"started":[],"not_admitted":{}}
        for row in await run_storage(self.store.restore_candidates):
            try:
                await self.start_existing(row["id"],expected_identity=(row["generation"],row["revision"]))
                result["started"].append(row["id"])
            except BacktestError as failure:
                result["not_admitted"][row["id"]]={"code":failure.code,"message":str(failure)[:256]}
        return result

    async def cancel(self,run_id):
        """Explicit terminal stop preserves every committed financial result."""
        if self.closed:raise BacktestError("CONTINUOUS_NOT_READY","Continuous runtime is closed")
        if run_id in self.starts:await asyncio.shield(self.starts[run_id])
        actor=self.actors.get(run_id)
        if actor is not None:
            actor.request_stop()
            await finish_cleanup(asyncio.shield(actor.task))
        row=await run_storage(self.store.summary,run_id)
        if row["phase"]=="CANCELLED":return row
        return await run_storage(self.store.stop,run_id,generation=row["generation"],revision=row["revision"],phase="CANCELLED")

    def _request_shutdown(self):
        self.closed=True
        for actor in tuple(self.actors.values()):actor.request_stop()
        for task in tuple(self.starts.values()):task.cancel()

    async def shutdown(self):
        self._request_shutdown()
        async def drain():
            await asyncio.gather(*tuple(self.starts.values()),return_exceptions=True)
            errors=[]
            for actor in tuple(self.actors.values()):
                if self.actors.get(actor.run_id) is not actor:continue
                try:
                    if actor.task is None or actor.task.done():
                        await actor.cleanup()
                        if self.actors.get(actor.run_id) is actor:self.actors.pop(actor.run_id)
                    else:
                        await asyncio.shield(actor.task)
                except Exception as failure:
                    self.record_failure(actor.run_id,failure)
                    errors.append(actor.run_id)
            if errors:
                raise BacktestError("CONTINUOUS_SHUTDOWN_FAILED","Owned cleanup is incomplete for "+",".join(errors))
        await finish_cleanup(drain())

    async def close(self):
        """Close an owned store only after the complete physical shutdown."""
        self._request_shutdown()
        async def close_owned():
            await self.shutdown()
            await run_storage(self.store.close)
        await finish_cleanup(close_owned())

    def diagnostics(self):
        with self._failure_lock:
            return {"closed":self.closed,"active":len(self.actors),"starting":len(self.starts),
                "capacity":self.max_active_runs,"failures":dict(self.last_failures)}
