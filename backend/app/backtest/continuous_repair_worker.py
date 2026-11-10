"""One accepted repair, on the profile's shared serial preparation executor."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from functools import partial
import threading

from app.core.async_cleanup import finish_cleanup
from app.data_engine.data_manager.models import DataEventType, SeriesKey
from app.data_engine.series_identity import KlineSeriesIdentity
from app.data_engine.storage.prefix_watches import PrefixReceipt
from .continuous_bar_host import ContinuousBarHost, ContinuousExecutionStopping
from .continuous_bar_source import ContinuousMarketBarSource
from .continuous_runtime import WAKE_EVENTS
from .continuous_store import _wire, fail


class RepairWorker:
    def __init__(self, repairs, request_key, run_id, plan, *, record=None):
        self.repairs, self.owner = repairs, repairs.owner
        self.key, self.run_id, self.plan, self.record = request_key, run_id, plan, record
        self.stopping = threading.Event()
        self.interrupted = threading.Event()
        self.wake = asyncio.Event()
        self.task = None
        self.host = self.staged = self.source = None
        self.market = None
        self.subscription = None
        self.demand_attempted = False
        self.subscription_lost = self.stream_unavailable = False
        self.cleaned = False
        self.reserved = asyncio.get_running_loop().create_future()
        self.reserved.add_done_callback(lambda done: None if done.cancelled() else done.exception())

    @property
    def consumer_id(self): return "strategy:repair:" + self.record["id"]

    def request_stop(self):
        self.stopping.set()
        if self.source is not None: self.source.request_stop()
        if self.host is not None: self.host.request_stop()
        self.wake.set()

    def check_stopping(self):
        if self.stopping.is_set(): raise ContinuousExecutionStopping()

    def check_input(self):
        self.check_stopping()
        if self.interrupted.is_set():
            raise fail("CONTINUOUS_SOURCE_GAP", "Repair source availability changed during execution")

    async def work(self, function):
        future = asyncio.wrap_future(self.owner.executor.submit(function))
        try: return await asyncio.shield(future)
        except asyncio.CancelledError as cancelled:
            self.request_stop()
            try: await finish_cleanup(future)
            except BaseException: pass
            raise cancelled

    def initialize(self):
        if self.record is None:
            self.record = self.owner.store.epochs.reserve(self.run_id, self.key,
                expected=self.plan["expected"], plan=self.plan)
        description = self.owner.store.describe(self.run_id)
        self.definition = {**description["definition"], "source_owner": self.record["source_owner"]}
        series = self.definition["source_series"]
        self.market = SeriesKey.create(series[2], series[3], exchange=series[0], market_type=series[1],
            identity=KlineSeriesIdentity(*series[4:]))
        self.source = ContinuousMarketBarSource(self.owner.manager, self.owner.inputs.datasets, self.market,
            clock_ms=self.owner.clock_ms, auto_backfill=True)
        return self.record

    def _bind_source(self):
        saved = self.owner.store.epochs.describe(self.record["id"])
        if saved["source"] is not None: return saved
        old = PrefixReceipt.from_dict(self.plan["source"])
        frozen = self.definition.get("initial_snapshot") or {}
        anchor_time = self.plan["from_ms"] - 1
        protected = max(anchor_time, frozen.get("through_ms", anchor_time)) if self.plan["anchor_revision"] else anchor_time
        actual = self.owner.manager.bars.prefixes.inspect(saved["source_owner"])
        if actual is None:
            if self.plan["anchor_revision"]:
                proof = self.owner.manager.bars.prefixes.fork_unchanged(old, saved["source_owner"],
                    through_ms=anchor_time, protected_through_ms=protected,
                    expected_version=self.plan["observed_source"]["version"])
                point = replace(proof, through_ms=anchor_time)
            else:
                point = self.source.register(self.run_id, from_ms=old.from_ms, definition=self.definition)
        else:
            # Crash after watch creation but before the journal acknowledgement.
            # An already acquired/changed watch is never relabeled as fresh.
            columns = ("exchange", "market_type", "symbol", "interval", "provider_id", "venue", "asset_class",
                "series_variant", "price_adjustment", "session_variant", "volume_semantics")
            if (tuple(actual[name] for name in columns) != old.series or actual["from_ms"] != old.from_ms
                    or actual["through_ms"] != protected or actual["committed_through_ms"] != anchor_time
                    or any(actual[name] != 0 for name in ("acquisition", "version", "committed_acquisition"))):
                raise fail("CONTINUOUS_COMMIT_CONFLICT", "Unacknowledged repair source cannot be safely recovered")
            point = PrefixReceipt(saved["source_owner"], actual["incarnation"], old.series, 0, 0,
                actual["registered_storage_revision"], old.from_ms, anchor_time)
        return self.owner.store.epochs.prepare(saved["id"], source=point.to_dict(), progress={"state": "SOURCE_REGISTERED"})

    def _prepare_account(self):
        saved = self._bind_source()
        point = PrefixReceipt.from_dict(saved["source"])
        state = (saved["progress"] or {}).get("state")
        frozen = self.definition.get("initial_snapshot")
        if state == "SOURCE_REGISTERED":
            if self.plan["anchor_revision"]:
                if frozen is not None: frozen = {**frozen, "source_version": point.version}
            elif frozen is not None:
                budget = self.owner.inputs.payload_budget()
                copied = self.source.freeze_initial(point, through_ms=frozen["through_ms"],
                    dataset_id="local-"+saved["id"], max_payload_bytes=budget)
                self.owner.inputs.check_published("local-"+saved["id"])
                point, frozen = copied.receipt, copied.descriptor
            self.check_stopping()
            saved = self.owner.store.epochs.prepare(saved["id"], source=point.to_dict(),
                initial_snapshot=frozen, progress={"state": "SOURCE_READY"})
        if saved["initial_snapshot"] is None: self.definition.pop("initial_snapshot", None)
        else: self.definition["initial_snapshot"] = saved["initial_snapshot"]
        self.check_stopping()
        if self.staged is None: self.staged = self.repairs.stage_owner().open(saved)
        if not self.staged.list_summaries():
            if (saved["progress"] or {}).get("state") not in {"SOURCE_READY", "SOURCE_REGISTERED"}:
                raise fail("CONTINUOUS_CHECKPOINT_UNAVAILABLE", "Private repair recovery account disappeared")
            if self.plan["anchor_revision"]:
                self.owner.store.repair_publication.seed(saved["id"], self.staged, definition=self.definition, proof=point)
            else:
                frozen = self.definition.get("initial_snapshot")
                proof = replace(point, through_ms=frozen["through_ms"]) if frozen else point
                def commit(publish):
                    def guarded(): self.check_stopping(); return publish()
                    return self.owner.manager.bars.prefixes.commit(proof, guarded, committed_through_ms=point.through_ms)
                ContinuousBarHost.create_run(self.staged, self.run_id, definition=self.definition,
                    mode=self.owner.store.summary(self.run_id)["mode"], data_revision=point.incarnation,
                    event_time_ms=point.through_ms, provider_factory=self.owner.runtime.provider_factory,
                    source_receipt=point, commit_checkpoint=commit)
            self.owner.store.epochs.prepare(saved["id"], progress={"state": "RUN_SEEDED"})
        # A crash after a private financial commit may precede progress update.
        # Restore from the actual private checkpoint, never its older journal cursor.
        current = self.staged.describe(self.run_id)
        if (_wire(current["definition"], 1024*1024) != _wire(self.definition, 1024*1024)
                or current["run"]["data_revision"] != point.incarnation):
            raise fail("CONTINUOUS_CHECKPOINT_CORRUPT", "Private repair account differs from its durable source binding")
        if self.host is not None and self.host.closed: self.host.close(); self.host = None
        if self.host is None:
            self.host = ContinuousBarHost.resume(self.staged, self.run_id, self.owner.runtime.provider_factory)
            self.host.input_control = self.check_input

    def step(self, gaps, unavailable):
        self.check_stopping()
        saved = self.owner.store.epochs.describe(self.record["id"])
        if saved["phase"] == "COMMITTED": return "COMMITTED"
        if saved["phase"] not in {"REQUESTED", "PREPARING", "READY"}: return "STOPPED"
        self.owner.store.repair_publication._base(saved)
        if saved["phase"] != "READY":
            if unavailable or any(start <= self.plan["through_ms"] and end >= self.plan["source"]["from_ms"] for start, end in gaps):
                self.owner.store.epochs.prepare(saved["id"], progress={**(saved["progress"] or {}), "waiting": "SOURCE_GAP"})
                return "WAIT"
            try:
                self._prepare_account()
                batch = self.source.acquire(self.host, revealed_through_ms=self.plan["through_ms"])
                batch.apply(self.host, self.owner.manager)
            except Exception as failure:
                if getattr(failure, "code", None) != "CONTINUOUS_SOURCE_GAP": raise
                current = self.owner.store.epochs.describe(saved["id"])
                self.owner.store.epochs.prepare(saved["id"], progress={**(current["progress"] or {}), "waiting": "SOURCE_GAP"})
                return "WAIT"
            self.repairs.stage_owner().check(saved)
            self.owner.store.epochs.prepare(saved["id"], progress={"state": "REPLAYING",
                "sequence": self.host.row["sequence"], "event_time_ms": self.host.row["event_time_ms"],
                "through_ms": self.plan["through_ms"]})
            if not batch.caught_up: return "MORE"
            self.host.close(); self.host = None
            self.owner.store.repair_publication.stage(saved["id"], self.staged, check_stopping=self.check_stopping)
        self.owner.store.repair_publication.publish(saved["id"], self.owner.manager,
            resume_after=self.plan["resume_after"], check_stopping=self.check_stopping)
        return "COMMITTED"

    async def subscribe(self):
        async def changed(event):
            if event.event_type in {DataEventType.STREAM_ERROR, DataEventType.STREAM_STOPPED}:
                self.stream_unavailable = True; self.interrupted.set()
            elif event.event_type == DataEventType.STREAM_STARTED: self.stream_unavailable = False
            elif event.event_type == DataEventType.SOURCE_GAP: self.interrupted.set()
            self.wake.set()
        async def lost(_failure):
            self.subscription_lost = True; self.interrupted.set(); self.wake.set()
        if self.subscription is not None: await self.owner.manager.unsubscribe_async(self.subscription)
        key = self.market
        self.subscription = await self.owner.manager.subscribe_async(changed, symbol=key.symbol, interval=key.interval,
            exchange=key.exchange, market_type=key.market_type, series_identity=key.identity,
            event_types=WAKE_EVENTS, continuity="gap_aware", on_recovery=lost)
        self.subscription_lost = False

    def close_worker(self):
        if self.host is not None: self.host.close(); self.host = None
        if self.staged is not None: self.staged.close(); self.staged = None
        if self.source is not None: self.source.close()

    async def cleanup(self):
        self.request_stop()
        await self.work(self.close_worker)
        if self.subscription is not None:
            await self.owner.manager.unsubscribe_async(self.subscription); self.subscription = None
        if self.demand_attempted:
            key = self.market
            await self.owner.manager.release_stream(key.symbol, key.interval, exchange=key.exchange,
                market_type=key.market_type, series_identity=key.identity, consumer_id=self.consumer_id, focus_scope="background")
            self.demand_attempted = False
        if self.record is not None:
            try: await self.work(partial(self.repairs.collect_terminal, self.record["id"]))
            except Exception as failure:
                self.owner.runtime.record_failure(self.run_id, failure)
                await self.work(partial(self.owner.store.epochs.cleanup_deferred, self.record["id"], failure))
        self.cleaned = True

    async def serve(self):
        try:
            await self.work(self.initialize)
            if not self.reserved.done(): self.reserved.set_result(self.record)
            await self.repairs.drain_execution(self.run_id)
            if self.stopping.is_set(): return
            await self.subscribe()
            self.demand_attempted = True
            key = self.market
            await self.owner.manager.bars.ensure_stream(key.symbol, key.interval, exchange=key.exchange,
                market_type=key.market_type, series_identity=key.identity, consumer_id=self.consumer_id, focus_scope="background")
            self.wake.set()
            while not self.stopping.is_set():
                await self.wake.wait(); self.wake.clear()
                if self.stopping.is_set(): break
                if self.subscription_lost: await self.subscribe()
                gaps = tuple((gap.start_ms, gap.end_ms) for gap in self.owner.manager.source_gaps.pending(key))
                self.interrupted.clear()
                outcome = await self.work(partial(self.step, gaps, self.stream_unavailable))
                if outcome == "MORE": self.wake.set()
                elif outcome in {"COMMITTED", "STOPPED"}:
                    if outcome == "COMMITTED" and self.plan["resume_after"] and not self.owner.closed and not self.stopping.is_set():
                        row = self.owner.store.summary(self.run_id)
                        await self.owner.runtime.start_existing(self.run_id, expected_identity=(row["generation"], row["revision"]))
                    break
        except ContinuousExecutionStopping: pass
        except Exception as failure:
            self.owner.runtime.record_failure(self.run_id, failure)
            if not self.reserved.done(): self.reserved.set_exception(failure)
            if self.record is not None and not self.stopping.is_set():
                current = self.owner.store.epochs.describe(self.record["id"])
                if current["phase"] in {"REQUESTED", "PREPARING", "READY"}:
                    await self.work(partial(self.owner.store.epochs.fail, self.record["id"],
                        code=str(getattr(failure, "code", "CONTINUOUS_REPAIR_FAILED"))[:64], message=str(failure)))
        finally:
            if not self.reserved.done(): self.reserved.set_exception(fail("CONTINUOUS_NOT_READY", "Repair owner is stopping"))
            # Cleanup failure keeps this owner reachable for a physical retry.
            await finish_cleanup(self.cleanup())
            if self.repairs.job is self: self.repairs.job = None
