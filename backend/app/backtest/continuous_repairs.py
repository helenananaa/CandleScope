"""Confirmed, idempotent repair admission and profile-owned physical lifetime."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from functools import partial
import time

from app.core.async_cleanup import finish_cleanup
from app.core.executors import run_storage
from app.data_engine.storage.prefix_watches import PrefixReceipt
from .continuous_repair_plan import preview
from .continuous_repair_stages import RepairStages
from .continuous_repair_worker import RepairWorker
from .continuous_source_identity import source_owner
from .continuous_store import _text, _wire, fail

ACTIVE = {"REQUESTED", "PREPARING", "READY"}


class ContinuousRepairs:
    def __init__(self, owner, *, stage_options=None):
        self.owner = owner
        self.stage_options = stage_options or {}
        self.stages = None
        self.job = None
        self.previews = {}

    @property
    def busy(self): return self.job is not None

    def stage_owner(self):
        # Only the shared preparation worker creates/scans staging storage.
        if self.stages is None: self.stages = RepairStages(self.owner.store, **self.stage_options)
        return self.stages

    async def preview(self, run_id, *, expected, resume_after):
        self.owner._live()
        plan = await run_storage(preview, self.owner.store, self.owner.manager, run_id,
            expected=expected, resume_after=resume_after, now_ms=self.owner.clock_ms())
        self.owner._live()
        now = time.monotonic()
        self.previews = {key: value for key, value in self.previews.items() if value[0] > now}
        self.previews[plan["plan_id"]] = (now+300, plan)
        while len(self.previews) > 8: self.previews.pop(next(iter(self.previews)))
        return deepcopy(plan)

    def _capacity(self, run_id):
        if self.owner.actions or self.owner.jobs or self.job is not None:
            raise fail("BUDGET_EXCEEDED", "Another preparation or control owns history repair capacity")
        occupied = (set(self.owner.runtime.actors) | set(self.owner.runtime.starts)) - {run_id}
        if len(occupied) >= self.owner.runtime.max_active_runs:
            raise fail("BUDGET_EXCEEDED", "Continuous execution capacity is reserved")

    def _start(self, request_key, run_id, plan, *, record=None):
        self._capacity(run_id)
        job = RepairWorker(self, request_key, run_id, plan, record=record)
        self.job = job
        job.task = asyncio.create_task(job.serve())
        job.task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return job

    @staticmethod
    def _same(record, run_id, expected, plan_id, resume_after):
        if (record["run_id"] != run_id or _wire(record["base_identity"], 2048) != _wire(expected, 2048)
                or record["plan"].get("plan_id") != plan_id or record["plan"]["resume_after"] is not resume_after):
            raise fail("CONTINUOUS_COMMIT_CONFLICT", "Repair request key owns a different confirmed plan")

    async def confirm(self, run_id, request_key, *, expected, plan_id, resume_after, confirmed):
        self.owner._live()
        _text(run_id, 128); _text(request_key, 128); _text(plan_id, 64)
        if confirmed is not True or type(resume_after) is not bool:
            raise fail("CONTINUOUS_INPUT_INVALID", "Repair requires explicit confirmation and resume intent")
        prior = await run_storage(self.owner.store.epochs.request, request_key)
        self.owner._live()
        if prior is not None:
            self._same(prior, run_id, expected, plan_id, resume_after)
            if prior["phase"] not in ACTIVE: return prior
            if self.job is not None and self.job.key == request_key: return prior
            job = self._start(request_key, run_id, prior["plan"], record=prior)
        elif self.job is not None and self.job.key == request_key:
            if (self.job.run_id != run_id or self.job.plan["plan_id"] != plan_id
                    or self.job.plan["resume_after"] is not resume_after
                    or _wire(self.job.plan["expected"], 2048) != _wire(expected, 2048)):
                raise fail("CONTINUOUS_COMMIT_CONFLICT", "Repair request owns a different admission")
            job = self.job
        else:
            cached = self.previews.get(plan_id)
            if cached is None or cached[0] <= time.monotonic():
                raise fail("CONTINUOUS_NOT_READY", "Repair preview expired; inspect the current range before confirming")
            plan = cached[1]
            if (_wire(plan["expected"], 2048) != _wire(expected, 2048) or expected.get("id") != run_id
                    or plan["resume_after"] is not resume_after):
                raise fail("CONTINUOUS_COMMIT_CONFLICT", "Repair confirmation differs from the preview")
            current = await run_storage(preview, self.owner.store, self.owner.manager, run_id,
                expected=expected, resume_after=resume_after, now_ms=plan["through_ms"]+1)
            self.owner._live()
            if current["plan_id"] != plan_id:
                raise fail("CONTINUOUS_COMMIT_CONFLICT", "Source changed; inspect the updated repair range before confirming")
            job = self._start(request_key, run_id, plan)
        await asyncio.shield(job.reserved)
        return await run_storage(self.owner.store.epochs.request, request_key)

    async def drain_execution(self, run_id):
        starting = self.owner.runtime.starts.get(run_id)
        if starting is not None: await asyncio.shield(starting)
        actor = self.owner.runtime.actors.get(run_id)
        if actor is not None:
            actor.request_stop()
            if actor.task is not None: await finish_cleanup(asyncio.shield(actor.task))
            else:
                await finish_cleanup(actor.cleanup())
                if self.owner.runtime.actors.get(run_id) is actor: self.owner.runtime.actors.pop(run_id)

    def collect_terminal(self, epoch_id):
        record = self.owner.store.epochs.describe(epoch_id)
        if record["phase"] in ACTIVE: return
        if (record["progress"] or {}).get("resources_released"): return
        if record["phase"] != "COMMITTED": self.owner.store.epochs.discard_unpublished(epoch_id)
        old = PrefixReceipt.from_dict(record["plan"]["source"])
        target = old.owner if record["phase"] == "COMMITTED" else record["source_owner"]
        definition = self.owner.store.describe(record["run_id"])["definition"]
        if source_owner(record["run_id"], definition) == target:
            raise fail("CONTINUOUS_COMMIT_CONFLICT", "Cleanup source is still the active financial owner")
        actual = self.owner.manager.bars.prefixes.inspect(target)
        if actual is not None:
            columns = ("exchange", "market_type", "symbol", "interval", "provider_id", "venue", "asset_class",
                "series_variant", "price_adjustment", "session_variant", "volume_semantics")
            known = old if record["phase"] == "COMMITTED" else (
                PrefixReceipt.from_dict(record["source"]) if record["source"] else None)
            if (actual["from_ms"] != old.from_ms or tuple(actual[name] for name in columns) != old.series
                    or (known is not None and actual["incarnation"] != known.incarnation)):
                raise fail("CONTINUOUS_COMMIT_CONFLICT", "Retired repair source ownership changed")
            receipt = PrefixReceipt(target, actual["incarnation"], old.series, actual["acquisition"],
                actual["version"], actual["registered_storage_revision"], old.from_ms, actual["through_ms"])
            self.owner.manager.bars.prefixes.release(receipt)
        self.stage_owner().remove(record)
        self.owner.store.epochs.cleaned(epoch_id)

    async def cancel(self, request_key, *, expected):
        self.owner._live()
        if self.owner.actions or self.owner.jobs:
            raise fail("CONTINUOUS_NOT_READY", "Another preparation/control is draining")
        task = asyncio.create_task(self._cancel(request_key, expected))
        key = "repair:"+request_key
        self.owner.actions[key] = task
        def done(value):
            if self.owner.actions.get(key) is value: self.owner.actions.pop(key)
            if not value.cancelled(): value.exception()
        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def _cancel(self, request_key, expected):
        record = await run_storage(self.owner.store.epochs.request, request_key)
        if record is None: raise fail("CONTINUOUS_REPAIR_NOT_FOUND", "Unknown history repair request")
        if _wire(record["base_identity"], 2048) != _wire(expected, 2048):
            raise fail("CONTINUOUS_COMMIT_CONFLICT", "Cancellation requires the confirmed repair identity")
        if record["phase"] == "COMMITTED": return record
        # Durable intent precedes physical drain; publication checks the same row
        # under its financial CAS. If publication won, report its actual result.
        if record["phase"] in ACTIVE:
            try:
                await run_storage(self.owner.store.epochs.fail, record["id"], code="CONTINUOUS_REPAIR_CANCELLED",
                    message="History repair cancelled; original account retained", cancelled=True)
            except Exception:
                current = self.owner.store.epochs.describe(record["id"])
                if current["phase"] == "COMMITTED": return current
                raise
        if self.job is not None and self.job.key == request_key:
            self.job.request_stop()
            await self.close_job()
        else:
            future = asyncio.wrap_future(self.owner.executor.submit(partial(self.collect_terminal, record["id"])))
            await asyncio.shield(future)
        return await run_storage(self.owner.store.epochs.describe, record["id"])

    async def restore(self):
        result = {"repairing": [], "not_admitted": {}}
        for record in await run_storage(self.owner.store.epochs.pending):
            if record["phase"] not in ACTIVE:
                try:
                    future = asyncio.wrap_future(self.owner.executor.submit(partial(self.collect_terminal, record["id"])))
                    await asyncio.shield(future)
                except Exception as failure:
                    result["not_admitted"]["repair:"+record["request_key"]] = {"code": str(getattr(failure, "code", "CONTINUOUS_CLEANUP_FAILED")), "message": str(failure)[:256]}
        for record in await run_storage(self.owner.store.epochs.pending):
            if record["phase"] in ACTIVE:
                try:
                    self._start(record["request_key"], record["run_id"], record["plan"], record=record)
                    result["repairing"].append(record["run_id"])
                except Exception as failure:
                    result["not_admitted"]["repair:"+record["request_key"]] = {"code": str(getattr(failure, "code", "CONTINUOUS_REPAIR_FAILED")), "message": str(failure)[:256]}
        return result

    def request_stop(self):
        self.previews.clear()
        if self.job is not None: self.job.request_stop()

    async def close_job(self):
        job = self.job
        if job is None: return
        job.request_stop()
        if job.task is not None: await asyncio.gather(job.task, return_exceptions=True)
        if not job.cleaned: await finish_cleanup(job.cleanup())
        if self.job is job: self.job = None
