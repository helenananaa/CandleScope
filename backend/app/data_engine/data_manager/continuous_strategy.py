"""Profile-owned continuous strategies and bounded committed view consumers."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from functools import partial
import json
import time

from app.backtest.errors import BacktestError
from app.core import config
from app.core.async_cleanup import finish_cleanup
from app.core.bounded_executor import BoundedExecutor

SCHEMA="candlescope.continuous-strategy-events/1"
DATABASE_NAME="continuous-strategy.sqlite3"
MAX_REQUESTS=8
CREATION_FIELDS=("request_key","run_id","mode","from_ms","cutoff_ms","revision","phase","error")


def utc_ms():return time.time_ns()//1_000_000


def json_token(value):return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)


class ContinuousStrategyAccess:
    def __init__(self,owner):
        self.owner=owner
        self.start_task=None
        self.start_status=None
        self.closed=False
        self.executor=None
        self.pending=set()
        self.operations=set()
        self.initial_waiters=set()
        self.ensures={}
        self.subscriptions=set()

    def ready(self):
        if self.closed or self.owner._closed:raise BacktestError("STRATEGY_MANAGER_CLOSED","strategy manager is closed")

    def controller(self):
        self.ready()
        controller=self.owner.continuous
        if controller is None or controller.closed:
            raise BacktestError("CONTINUOUS_NOT_READY","Continuous strategy owner is unavailable")
        return controller

    async def start(self):
        self.ready()
        if self.start_task is None:
            self.start_task=asyncio.create_task(self._start())
            self.start_task.add_done_callback(lambda task:None if task.cancelled() else task.exception())
        return await asyncio.shield(self.start_task)

    async def _start(self):
        from app.backtest.continuous_controller import ContinuousStrategyController
        if not self.owner.service.settings.bar_effective:
            self.start_status={"available":False,"execution_enabled":False,"reason":"BACKTEST_BAR_DISABLED"}
            return self.start_status
        existing=self.owner.continuous
        if existing is not None:
            self.start_status={"available":True,"execution_enabled":bool(getattr(existing,"execution_enabled",False)),
                "restoration":"ALREADY_BOUND"}
            return self.start_status
        controller=None
        try:
            market=self.owner.market_manager if config.RUNTIME_MODE=="LIVE" else None
            path=self.owner.service.settings.db_path.parent.resolve()/DATABASE_NAME
            controller=await ContinuousStrategyController.open(path,market,clock_ms=utc_ms,
                max_active_runs=min(2,self.owner.service.settings.max_active_runs))
            self.owner.bind_continuous(controller)
            self.ready()
            restoration=await controller.restore() if controller.execution_enabled else {
                "started":[],"preparing":[],"not_admitted":{},
                "reason":"LOCAL_OFFLINE" if controller.runtime_mode=="LOCAL_OFFLINE" else "MARKET_UNAVAILABLE"}
            self.start_status={"available":True,"execution_enabled":controller.execution_enabled,"restoration":restoration}
            return self.start_status
        except BaseException:
            if controller is not None:
                # Keep a failed physical owner reachable for shutdown retry.
                await finish_cleanup(controller.close())
                if self.owner.continuous is controller:self.owner.continuous=None
            raise

    def _submit(self,function):
        self.ready()
        if self.executor is None:
            self.executor=BoundedExecutor("continuous-views",max_workers=2,
                max_pending=self.owner.max_subscriptions+MAX_REQUESTS)
        future=asyncio.wrap_future(self.executor.submit(function))
        self.pending.add(future)
        def done(value):
            self.pending.discard(value)
            if not value.cancelled():value.exception()
        future.add_done_callback(done)
        return future

    async def work(self,function,*args,**kwargs):
        future=self._submit(partial(function,*args,**kwargs))
        try:return await asyncio.shield(future)
        except asyncio.CancelledError as cancelled:
            if asyncio.current_task() in self.initial_waiters:
                try:await finish_cleanup(future)
                except BaseException:pass
            raise cancelled

    async def _command(self,function,*args,**kwargs):
        self.ready()
        if len(self.operations)+len(self.initial_waiters)>=MAX_REQUESTS:raise BacktestError("BUDGET_EXCEEDED","Continuous request capacity reached")
        task=asyncio.create_task(function(*args,**kwargs))
        self.operations.add(task)
        def done(value):
            self.operations.discard(value)
            if not value.cancelled():value.exception()
        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def create(self,key,**kwargs):
        controller=self.controller()
        if not hasattr(controller,"create"):raise BacktestError("CONTINUOUS_NOT_READY","Continuous creation controller is unavailable")
        row=await self._command(controller.create,key,**kwargs)
        return {field:row[field] for field in CREATION_FIELDS}

    async def control(self,key,action,*,expected=None,**kwargs):
        controller=self.controller()
        if getattr(controller,"execution_enabled",True) is False:
            raise BacktestError("CONTINUOUS_NOT_READY","This profile exposes saved market accounts read-only")
        if not hasattr(controller,"control"):raise BacktestError("CONTINUOUS_NOT_READY","Continuous control owner is unavailable")
        async def apply():
            creation=await self.work(controller.store.creations.summary,key)
            if creation["phase"]=="COMMITTED":
                current=await self.work(controller.store.summary,creation["run_id"])
                identity=controller.store.results.identity(current)
                if (not isinstance(expected,Mapping) or set(expected)!=set(identity)
                        or any(type(expected[name]) is not type(value) for name,value in identity.items())):
                    raise BacktestError("CONTINUOUS_INPUT_INVALID","Account control requires its full committed identity")
                if expected!=identity:raise BacktestError("CONTINUOUS_COMMIT_CONFLICT","Account changed before control admission")
            elif expected is not None:
                raise BacktestError("CONTINUOUS_INPUT_INVALID","Preparation has no committed account identity")
            row=await controller.control(key,action,**kwargs)
            run=await self.work(controller.store.summary,row["run_id"]) if row["phase"]=="COMMITTED" else None
            return {"creation":{field:row[field] for field in CREATION_FIELDS},"run":run}
        return await self._command(apply)

    async def repair_preview(self,run_id,*,expected,resume_after):
        controller=self.controller()
        async def apply():
            plan=await controller.repair_preview(run_id,expected=expected,resume_after=resume_after)
            fields=("plan_id","expected","resume_after","from_ms","through_ms","anchor_sequence",
                "full_reinitialization","expanded_range_reason","dirty_from_ms","dirty_through_ms")
            return {**{field:plan[field] for field in fields},"schema":"candlescope.continuous-repair-preview/1",
                "original_from_ms":plan["source"]["from_ms"],"expires_in_seconds":300,
                "recompute_bars":(plan["through_ms"]+1-plan["from_ms"])//60000}
        return await self._command(apply)

    async def repair(self,run_id,key,**kwargs):
        controller=self.controller()
        async def apply():
            await controller.repair(run_id,key,**kwargs)
            return await self.work(controller.store.epochs.summary,key)
        return await self._command(apply)

    async def cancel_repair(self,key,*,expected):
        controller=self.controller()
        async def apply():
            await controller.cancel_repair(key,expected=expected)
            return await self.work(controller.store.epochs.summary,key)
        return await self._command(apply)

    async def repair_status(self,key):
        async def read():return await self.work(self.controller().store.epochs.summary,key)
        return await self._command(read)

    async def latest_repair(self,run_id):
        async def read():return await self.work(self.controller().store.epochs.latest_summary,run_id)
        return await self._command(read)

    async def _ensure(self,run_id):
        future=self.ensures.get(run_id)
        if future is None:
            future=self._submit(partial(self.controller().store.results.ensure,run_id))
            self.ensures[run_id]=future
            def done(value):
                if self.ensures.get(run_id) is value:self.ensures.pop(run_id)
            future.add_done_callback(done)
        await asyncio.shield(future)

    async def read(self,run_id,**kwargs):
        return await self._command(self._read_result,run_id,**kwargs)

    async def _read_result(self,run_id,**kwargs):
        controller=self.controller()
        try:return await self.work(controller.store.results.read,run_id,**kwargs)
        except BacktestError as failure:
            if failure.code!="CONTINUOUS_RESULTS_UNAVAILABLE":raise
            await self._ensure(run_id)
            return await self.work(controller.store.results.read,run_id,**kwargs)

    async def status(self,run_id):
        async def read():
            controller=self.controller()
            creation=await self.work(controller.store.creations.summary_for_run,run_id)
            if creation is not None and creation["phase"]!="COMMITTED":
                return {"creation":{field:creation[field] for field in CREATION_FIELDS},"run":None,"initial_result_ready":False}
            page=await self._read_result(run_id)
            return {"creation":None if creation is None else {field:creation[field] for field in CREATION_FIELDS},
                "run":page["run"],"identity":page["identity"],
                "repair":await self.work(controller.store.epochs.latest_summary,run_id),
                "initial_result_ready":creation is not None and page["run"]["event_time_ms"]>=creation["cutoff_ms"]}
        return await self._command(read)

    async def request(self,key):
        async def read():
            row=await self.work(self.controller().store.creations.summary,key)
            return {field:row[field] for field in CREATION_FIELDS}
        return await self._command(read)

    async def initial(self,run_id):
        """HTTP initial result wait is a view, not ownership of the execution."""
        controller=self.controller()
        if len(self.operations)+len(self.initial_waiters)>=MAX_REQUESTS:
            raise BacktestError("BUDGET_EXCEEDED","Continuous request capacity reached")
        # Admit the whole view operation before its first I/O. Cancellation may
        # release this waiter; Controller's accepted creation remains independent.
        task=asyncio.create_task(self._initial(controller,run_id))
        self.initial_waiters.add(task)
        def done(value):
            self.initial_waiters.discard(value)
            if not value.cancelled():value.exception()
        task.add_done_callback(done)
        return await task

    async def _initial(self,controller,run_id):
        creation=await self.work(controller.store.creations.summary_for_run,run_id)
        if creation is None:
            await self.work(controller.store.summary,run_id)
            raise BacktestError("CONTINUOUS_NOT_READY","Legacy account has no creation cutoff; inspect committed results")
        state=await controller.wait_initial(creation["request_key"])
        if state["creation"]["phase"]!="COMMITTED":
            return {"creation":{field:state["creation"][field] for field in CREATION_FIELDS},
                "initial_result_ready":False,"result":None}
        page=await self._read_result(run_id,since_revision=0,limit=100)
        return {"creation":{field:state["creation"][field] for field in CREATION_FIELDS},
            "initial_result_ready":page["run"]["event_time_ms"]>=creation["cutoff_ms"],"result":page}

    async def catalog(self):
        return await self._command(self._catalog)

    async def _catalog(self):
        controller=self.controller()
        def read():
            # Both lists are bounded by the store's run/request capacities.
            with controller.store.lock:
                controller.store.db.execute("BEGIN")
                try:
                    return {"runs":controller.store.list_summaries(),
                        "repairs":controller.store.epochs.summaries(),
                        "preparations":[{field:row[field] for field in CREATION_FIELDS}
                            for row in controller.store.creations.list_pending()]}
                finally:controller.store.db.execute("ROLLBACK")
        return await self.work(read)

    async def subscribe(self,run_id,*,after=None):
        self.ready()
        if len(self.subscriptions)+len(self.owner._subscriptions)>=self.owner.max_subscriptions:
            raise BacktestError("RUN_CAPACITY_EXCEEDED","strategy subscription capacity reached")
        subscription=ContinuousStrategySubscription(self,run_id)
        self.subscriptions.add(subscription)
        try:
            if after is not None:
                cursor=await self.work(self.controller().store.resume_cursor,run_id,after)
                subscription.baseline=cursor["after"]
                subscription.resume_reason=cursor["reason"]
                if cursor["after"]:subscription.last_complete=dict(after)
            await subscription.prepare()
            return subscription
        except BaseException:
            subscription.close()
            raise

    def close_views(self):
        self.closed=True
        for subscription in tuple(self.subscriptions):subscription.close()
        for task in tuple(self.initial_waiters):task.cancel()
        controller=self.owner.continuous
        if controller is not None:
            stop=getattr(controller,"request_shutdown",None) or getattr(controller,"_request_shutdown",None)
            if callable(stop):stop()

    async def shutdown(self):
        self.close_views()
        async def drain():
            if self.start_task is not None and not self.start_task.done():self.start_task.cancel()
            if self.start_task is not None:await asyncio.gather(self.start_task,return_exceptions=True)
            await asyncio.gather(*tuple(self.operations),return_exceptions=True)
            await asyncio.gather(*tuple(self.initial_waiters),return_exceptions=True)
            await asyncio.gather(*tuple(self.pending),return_exceptions=True)
            if self.executor is not None:self.executor.shutdown(wait=True)
            if self.owner.continuous is not None:await self.owner.continuous.close()
        await finish_cleanup(drain())


class ContinuousStrategySubscription:
    def __init__(self,access,run_id):
        from app.backtest.continuous_store import _text
        _text(run_id,128)
        self.access,self.run_id=access,run_id
        self.updates=access.controller().store.updates.subscribe(run_id)
        self.closed=False
        self.iterating=False
        self.first=None
        self.baseline=0
        self.cursor=None
        self.page_identity=None
        self.last_complete=None
        self.last_creation=None
        self.last_initializing=None
        self.resume_reason=None
        self.last_repair=None

    async def _read(self):
        if self.cursor is None:self.updates.clear_before_read()
        controller=self.access.controller()
        profile={"runtime_mode":getattr(controller,"runtime_mode",config.RUNTIME_MODE),
            "execution_enabled":bool(getattr(controller,"execution_enabled",True))}
        creation=await self.access.work(controller.store.creations.summary_for_run,self.run_id)
        if creation is not None and creation["phase"]!="COMMITTED":
            token=creation["revision"]
            if token==self.last_creation:return None
            self.last_creation=token
            return {"schema":SCHEMA,"type":"preparation","profile":profile,"terminal":creation["phase"]=="CANCELLED",
                "creation":{field:creation[field] for field in CREATION_FIELDS},"run":None,
                "initial_result_ready":False,"complete":True}
        if self.cursor is None and creation is not None:
            head=await self.access._read_result(self.run_id)
            if (head["run"]["event_time_ms"]<creation["cutoff_ms"]
                    and head["run"]["phase"] in {"PAUSED","CATCHING_UP","LIVE"}):
                if head["identity"]==self.last_initializing:return None
                self.last_initializing=dict(head["identity"])
                return {"schema":SCHEMA,"type":"initializing","profile":profile,"terminal":False,
                    "creation":{field:creation[field] for field in CREATION_FIELDS},
                    **head,"initial_result_ready":False,"complete":True}
        try:
            page=await self.access._read_result(self.run_id,since_revision=self.baseline,limit=100,
                expected=self.page_identity,change_cursor=self.cursor)
        except BacktestError as failure:
            if failure.code!="CONTINUOUS_COMMIT_CONFLICT" or self.cursor is None:raise
            self.baseline=0;self.cursor=None;self.page_identity=None;self.last_complete=None
            return {"schema":SCHEMA,"type":"reset","terminal":False,"run_id":self.run_id,
                "reason":"COMMITTED_VIEW_CHANGED","complete":False}
        repair=await self.access.work(controller.store.epochs.latest_summary,self.run_id)
        repair_token=json_token(repair)
        if page["identity"]==self.last_complete and not page["items"] and repair_token==self.last_repair:return None
        if (self.baseline and self.last_complete is not None and (
                self.last_complete["generation"],self.last_complete["data_revision"])!=(
                page["identity"]["generation"],page["identity"]["data_revision"])):
            self.baseline=0;self.cursor=None;self.page_identity=None;self.last_complete=None
            return {"schema":SCHEMA,"type":"reset","terminal":False,"run_id":self.run_id,
                "reason":"RUN_GENERATION_CHANGED","complete":False}
        initial=creation is None or page["run"]["event_time_ms"]>=creation["cutoff_ms"]
        event={"schema":SCHEMA,"type":"snapshot" if self.baseline==0 else "update","profile":profile,
            "terminal":page["run"]["phase"]=="CANCELLED" and not page["more"],"initial_result_ready":initial,
            "creation":None if creation is None else {field:creation[field] for field in CREATION_FIELDS},
            "repair":repair,**page,"complete":not page["more"],"begin":self.cursor is None,"after_checkpoint":self.baseline}
        self.last_repair=repair_token
        if self.resume_reason is not None:event["resume_reason"]=self.resume_reason
        if page["more"]:
            self.cursor=list(page["next_cursor"]);self.page_identity=dict(page["identity"])
        else:
            self.baseline=page["identity"]["checkpoint_revision"]
            self.cursor=None;self.page_identity=None;self.last_complete=dict(page["identity"])
        return event

    async def prepare(self):
        self.first=await self._read()
        if self.closed:raise asyncio.CancelledError

    async def events(self):
        if self.iterating:raise RuntimeError("a continuous subscription has one consumer")
        self.iterating=True
        event,self.first=self.first,None
        try:
            while not self.closed:
                if event is None:event=await self._read()
                if self.closed:return
                if event is not None:
                    yield event
                    if event.get("terminal"):return
                    if self.cursor is not None or event["type"]=="reset":
                        event=None
                        continue
                event=None
                while not self.closed:
                    try:
                        if not await asyncio.wait_for(self.updates.wait(),self.access.owner.heartbeat_seconds):return
                        break
                    except TimeoutError:
                        yield {"schema":SCHEMA,"type":"heartbeat","terminal":False}
        except BacktestError as failure:
            if self.closed:return
            yield {"schema":SCHEMA,"type":"error","terminal":True,"run_id":self.run_id,
                "error":{"code":failure.code,"message":failure.message}}
        except Exception:
            if self.closed:return
            yield {"schema":SCHEMA,"type":"error","terminal":True,"run_id":self.run_id,
                "error":{"code":"CONTINUOUS_STREAM_FAILED","message":"Reconnect to inspect the committed account"}}
        finally:self.close()

    def close(self):
        self.closed=True
        self.first=None
        self.updates.close()
        self.access.subscriptions.discard(self)
