"""Owned numeric observations over the existing strict DataManager stream."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace

from app.core.executors import run_storage
from app.core.async_cleanup import finish_cleanup
from app.data_engine.data_manager.models import DataEvent, DataEventType, SeriesKey
from .query_contracts import NumericIndicatorSnapshot


@dataclass(frozen=True, slots=True)
class NumericIndicatorObservation:
    snapshot: NumericIndicatorSnapshot
    event: DataEvent
    baseline: bool


class NumericIndicatorSubscription:
    def __init__(self, service, request, callback, *, on_recovery, consumer_id, event_types=None,
                 subscription_tier='indicators'):
        key = request.source
        if key != SeriesKey(key.symbol, key.interval, exchange=key.exchange, market_type=key.market_type):
            raise ValueError('Live numeric subscriptions currently require the default series identity')
        if request.through_ms is not None or request.expected_bar is not None:
            raise ValueError('Live numeric subscriptions require a moving frontier')
        self.service, self.request, self.callback = service, request, callback
        self.manager = service.inputs.manager
        self.on_recovery, self.consumer_id = on_recovery, consumer_id
        self.subscription_tier = subscription_tier
        self.event_types = ({DataEventType.BAR_CREATED, DataEventType.BAR_UPDATED,
                            DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED}
                            if event_types is None else event_types)
        self.handle = None
        self.snapshot = NumericIndicatorSnapshot(key, 'warming')
        self._ready = asyncio.Event()
        self._active = set()
        self._closed = False
        self._close_task = None
        self._close_initiator = None
        self._failed = False
        self._claimed = False
        self._baseline = False
        self._initial_version = {}
        self.backfill_request_ids = []

    def _target(self):
        key = self.request.source
        return dict(symbol=key.symbol, interval=key.interval, exchange=key.exchange, market_type=key.market_type)

    async def start(self):
        # Register first. Existing strict queues bound the events arriving
        # during stream acquisition and the canonical snapshot; no shadow bus.
        self.handle = await self.manager.subscribe_async(self._receive,
            on_recovery=self._recover, event_types=set(self.event_types) | {DataEventType.BACKFILL_COMPLETED},
            **self._target())
        await self.manager.ensure_stream(**self._target(), focus_scope='background',
            subscription_tier=self.subscription_tier, consumer_id=self.consumer_id)
        self._claimed = True
        result = await run_storage(self.service.inputs.warmup, self.request)
        self.backfill_request_ids = list(result.metadata.get('backfill_request_ids') or [])
        self.snapshot = await self.service.query(self.request)
        if self._failed:
            raise RuntimeError('Numeric subscription requires recovery during startup')
        self._initial_version = dict(self.snapshot.stream_version)
        self._baseline = self.snapshot.status == 'ready'
        self._ready.set()

    async def refresh(self):
        if self._closed or self._failed:
            return NumericIndicatorSnapshot(self.request.source, 'unavailable',
                reason='consumer_recovery_required' if self._failed else 'subscription_closed')
        self.snapshot = await self.service.query(self.request)
        self._baseline = self.snapshot.status == 'ready'
        return self.snapshot

    async def _receive(self, event):
        task = asyncio.current_task()
        self._active.add(task)
        try:
            await self._ready.wait()
            if self._closed or self._failed:
                return
            version = event.detail.get('stream_version', {})
            if (self._initial_version and all(version.get(k) == self._initial_version[k]
                    for k in ('epoch', 'generation'))
                    and version.get('sequence', 0) <= self._initial_version['sequence']):
                return
            correction = (event.event_type in {DataEventType.BAR_AMENDED, DataEventType.BACKFILL_COMPLETED}
                          or bool(event.detail.get('continuity_replayed')))
            if event.bar is None and not correction:
                return
            revision = event.detail.get('storage_revision', 0)
            request = replace(self.request,
                through_ms=None if correction or event.bar is None else event.bar.time_ms,
                expected_bar=None if correction else event.bar,
                minimum_revision=revision if type(revision) is int and revision >= 0 else 0)
            snapshot = await self.service.query(request)
            if self._closed:
                return
            baseline = correction or not self._baseline
            self._baseline = snapshot.status == 'ready'
            self.snapshot = snapshot
            await self.callback(NumericIndicatorObservation(snapshot, event, baseline))
        finally:
            self._active.discard(task)

    async def _recover(self, error):
        self._failed = True
        self._baseline = False
        self.snapshot = NumericIndicatorSnapshot(self.request.source, 'stale', reason='consumer_recovery_required')
        if not self._closed:
            await self.on_recovery(error)

    async def close(self):
        current = asyncio.current_task()
        if self._close_task is None:
            self._closed = True
            self._ready.set()
            self._close_initiator = current
            self._close_task = asyncio.create_task(self._close(current), name='numeric-subscription-close')
        # An external closer drains active callbacks. A callback's own finally
        # must not join that closer while it is waiting for this callback.
        if current in self._active and current is not self._close_initiator:
            return
        await finish_cleanup(asyncio.shield(self._close_task))

    async def _close(self, initiator):
        if self.handle is not None:
            # Preserve self-unsubscribe semantics when this owned task runs
            # on behalf of the callback that initiated close.
            await self.manager.unsubscribe_async(self.handle, originating_task=initiator)
            self.handle = None
        # unsubscribe cancels the worker, but it does not await it. Drain the
        # calculations/callbacks owned here before releasing the stream lease.
        active = [task for task in self._active if task is not initiator]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        if self._claimed:
            await self.manager.release_stream(**self._target(), focus_scope='background',
                subscription_tier=self.subscription_tier, consumer_id=self.consumer_id)
            self._claimed = False
        self.service.subscriptions.discard(self)
