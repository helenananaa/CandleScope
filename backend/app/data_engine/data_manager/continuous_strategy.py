"""Profile-owned continuous strategies and bounded committed view consumers."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from functools import partial
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


class ContinuousStrategyAccess:
    def __init__(self,owner):
        self.owner=owner
        self.start_task=None
        self.start_status=None
        self.closed=False
        self.executor=None
        self.pending=set()
        self.operations=set()
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
        return await asyncio.shield(self._submit(partial(function,*args,**kwargs)))

    async def _command(self,function,*args,**kwargs):
        self.ready()
        if len(self.operations)>=MAX_REQUESTS:raise BacktestError("BUDGET_EXCEEDED","Continuous request capacity reached")
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
            row=await controller.control(key,action,expected=expected,**kwargs)
            run=await self.work(controller.store.summary,row["run_id"]) if row["phase"]=="COMMITTED" else None
            return {"creation":{field:row[field] for field in CREATION_FIELDS},"run":run}
        return await self._command(apply)

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
                        "preparations":[{field:row[field] for field in CREATION_FIELDS}
                            for row in controller.store.creations.list_pending()]}
                finally:controller.store.db.execute("ROLLBACK")
        return await self.work(read)

    async def subscribe(self,run_id):
        self.ready()
        if len(self.subscriptions)+len(self.owner._subscriptions)>=self.owner.max_subscriptions:
            raise BacktestError("RUN_CAPACITY_EXCEEDED","strategy subscription capacity reached")
        subscription=ContinuousStrategySubscription(self,run_id)
        self.subscriptions.add(subscription)
        try:
            await subscription.prepare()
            return subscription
        except BaseException:
            subscription.close()
            raise

    def close_views(self):
        self.closed=True
        for subscription in tuple(self.subscriptions):subscription.close()
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
        if page["identity"]==self.last_complete and not page["items"]:return None
        initial=creation is None or page["run"]["event_time_ms"]>=creation["cutoff_ms"]
        event={"schema":SCHEMA,"type":"snapshot" if self.baseline==0 else "update","profile":profile,
            "terminal":page["run"]["phase"]=="CANCELLED" and not page["more"],"initial_result_ready":initial,
            "creation":None if creation is None else {field:creation[field] for field in CREATION_FIELDS},
            **page,"complete":not page["more"],"begin":self.cursor is None,"after_checkpoint":self.baseline}
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
