"""Per-consumer continuity adapters for replaceable market state.

Strict state means a valid current snapshot, not every historical transition.
Source notifications bypass latest-wins coalescing; waiting never holds a feed.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from collections import OrderedDict
from dataclasses import replace

from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.data_engine.continuity_policy import ContinuityPolicy
from .events import HubRecord, MarketStateEvent


def source_broken(record: HubRecord) -> bool:
    data = record.event.data
    return bool(data.get("stale") or data.get("state") in {"stale", "resyncing", "failed"})


def ingestion_options(factory, *, on_health=None, gap_repair_owner=None):
    """Only older embedded factories omit these optional transport hooks."""
    parameters = inspect.signature(factory.start_market).parameters
    options = {}
    for name, value in {"on_health": on_health, "gap_repair_owner": gap_repair_owner}.items():
        # A **kwargs wrapper may forward into an older factory that lacks the
        # hook. Only an explicitly declared optional capability is reliable.
        if value is not None and name in parameters:
            options[name] = value
    return options


def health_callback(hub, keys):
    async def changed(health, reason):
        value = str(getattr(health, "value", health)).lower()
        if value in {"reconnecting", "unhealthy", "disconnected"}:
            hub.mark_source_gap(keys(), reason=f"ingestion_{value}")
    return changed


class StateContinuitySubscription:
    def __init__(self, subscription, policy):
        self.inner = subscription
        self.policy = ContinuityPolicy.resolve(policy)
        self._gaps = {}
        self._notices = OrderedDict()
        self._restored = set()
        self._changed = asyncio.Event()
        self._error = None
        self._held = None
        self._terminal = None
        subscription._continuity_observer = self
        if len(subscription.keys) > subscription._max_pending:
            self._error = "source_state_capacity_exhausted"
        for key, (reason, detected) in subscription._hub._source_gaps.items():
            if key in subscription.keys:
                self.gap(key, reason, detected)
        for record in subscription._hub.snapshot(subscription.keys):
            if source_broken(record):
                self.offer(record)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def gap(self, key, reason, detected=None):
        if key not in self.inner.keys:
            return
        if key not in self._gaps:
            self._gaps[key] = (time.monotonic() if detected is None else detected, reason)
        if self.policy.mode == "gap_aware" and key not in self._notices:
            now = int(time.time() * 1000)
            self._notices[key] = HubRecord(MarketStateEvent(
                key, now, now, "plugin", {
                    "state": "stale", "stale": True, "live": False,
                    "source_continuity": {"state": "gapped", "reason": reason,
                                          "guarantee": "current_state"},
                },
            ), revision=0)
        self._changed.set()

    def offer(self, record):
        key = record.event.key
        if source_broken(record):
            self.gap(key, str(record.event.data.get("stale_reason") or "source_state_invalid"))
        elif key in self._gaps:
            detected, _reason = self._gaps.pop(key)
            if time.monotonic() > detected + self.policy.max_wait_seconds:
                self._error = "source_gap_timeout"
            self._restored.add(key)
        self._changed.set()

    def source_closed(self):
        self._changed.set()

    def add_keys(self, keys, *, replay=True):
        keys = set(keys)
        if len(keys | self.inner.keys) > self.inner._max_pending:
            raise ValueError("continuity subscription exceeds distinct-state capacity")
        self.inner.add_keys(keys, replay=replay)
        for key in keys:
            if key in self.inner._hub._source_gaps:
                reason, detected = self.inner._hub._source_gaps[key]
                self.gap(key, reason, detected)

    def remove_keys(self, keys):
        keys = set(keys)
        self.inner.remove_keys(keys)
        for key in keys:
            self._gaps.pop(key, None)
            self._notices.pop(key, None)
            self._restored.discard(key)
        if self._held is not None and self._held.event.key in keys:
            self._held = None
        self._changed.set()

    async def receive(self):
        try:
            while True:
                if self._terminal is not None:
                    raise self._terminal
                if self.policy.mode == "strict" and self.inner._hub._source_tracking_exhausted:
                    raise ConsumerRecoveryRequired("source_gap_tracking_exhausted")
                if self._error and (self.policy.mode == "strict" or self._error != "source_gap_timeout"):
                    raise ConsumerRecoveryRequired(self._error)
                if self.policy.mode == "gap_aware" and self._notices:
                    return self._notices.popitem(last=False)[1]
                if self.policy.mode == "strict" and self._gaps:
                    if self.inner.closed:
                        raise ConsumerRecoveryRequired("source_stream_closed")
                    deadline = min(item[0] for item in self._gaps.values()) + self.policy.max_wait_seconds
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ConsumerRecoveryRequired("source_gap_timeout")
                    self._changed.clear()
                    try:
                        await asyncio.wait_for(self._changed.wait(), remaining)
                    except TimeoutError:
                        raise ConsumerRecoveryRequired("source_gap_timeout") from None
                    continue
                self._changed.clear()
                async def read():
                    if self._held is not None:
                        record, self._held = self._held, None
                        return record
                    return await self.inner.receive()
                reading = asyncio.create_task(read())
                changing = asyncio.create_task(self._changed.wait())
                try:
                    await asyncio.wait({reading, changing}, return_when=asyncio.FIRST_COMPLETED)
                    if not reading.done():
                        continue
                    record = reading.result()
                    if record is None:
                        return None
                    if self.policy.mode == "strict" and (self._gaps or source_broken(record)):
                        if not source_broken(record) and record.event.key not in self._gaps:
                            self._held = record
                        continue
                    if self.policy.mode == "gap_aware" and self._notices:
                        self._held = record
                        return self._notices.popitem(last=False)[1]
                    key = record.event.key
                    if key in self._restored:
                        latest = self.inner._hub.snapshot([key])
                        if latest and latest[0].revision > record.revision:
                            record = latest[0]
                    state = "gapped" if key in self._gaps else "restored" if key in self._restored else "current"
                    if self.inner._hub._source_tracking_exhausted:
                        state = "unverified"
                    self._restored.discard(key)
                    return replace(record, event=replace(record.event, data={
                        **record.event.data,
                        "source_continuity": {"state": state, "guarantee": "current_state",
                                              "historical_transitions_replayed": False},
                    }))
                finally:
                    reading.cancel()
                    changing.cancel()
                    await asyncio.gather(reading, changing, return_exceptions=True)
        except ConsumerRecoveryRequired as error:
            self._terminal = error
            await self.close()
            raise
        except asyncio.CancelledError:
            await self.close()
            raise

    async def close(self):
        self._changed.set()
        await self.inner.close()

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        try:
            while (record := await self.receive()) is not None:
                yield record
        finally:
            await self.close()
