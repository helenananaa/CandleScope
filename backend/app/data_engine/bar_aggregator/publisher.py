"""
L5: Publisher — broadcasts bar lifecycle events to downstream consumers.

Responsibilities:
  * Emit BarEvent lifecycle events (CREATED, UPDATED, CLOSED, AMENDED, EXPIRED)
  * Support multiple delivery mechanisms:
      - Callback registration (``on_bar_event()``, ``on_bar_closed()``, etc.)
      - Async iterator (``subscribe()`` → ``AsyncIterator[BarEvent]``)
  * Throttle UPDATED events to reduce noise (configurable)
  * Support event filtering by symbol, interval, and event type
  * Bounded subscriber queues with backpressure handling

Usage::

    publisher = BarAggregatorPublisher(config)

    # Callback style
    publisher.on_bar_closed(save_to_storage)
    publisher.on_bar_updated(push_to_websocket)

    # Async iterator style
    async for event in publisher.subscribe(event_filter=BarEventFilter(
        event_types={BarEventType.CLOSED},
    )):
        process(event)
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from copy import deepcopy

import asyncio
import copy
import logging
import sys
import time
from typing import Callable, Awaitable, AsyncIterator

from .config import BarAggregatorConfig
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.consumer_recovery import ConsumerRecoveryRequired, terminate_queue
from .models import (
    BarEvent,
    BarEventType,
    BarEventFilter,
    BarState,
)

logger = logging.getLogger("bar_aggregator.L5_Publisher")

# Type alias
BarEventCallback = Callable[[BarEvent], Awaitable[None]]


@dataclass(slots=True)
class _SourceHandoff:
    # A spawned callback task inherits ContextVars. Keep no payload/callback
    # references here, and deactivate on scope exit to prevent stale observers.
    bar_id: int
    transferred: bool = False
    active: bool = True


class BarAggregatorPublisher:
    """Fan-out publisher for bar lifecycle events.

    Distributes ``BarEvent`` objects to registered callbacks and
    async-iterator subscribers.  Supports throttling of UPDATED events
    to reduce downstream load.
    """

    def __init__(self, config: BarAggregatorConfig) -> None:
        self._cfg = config

        # Callback registrations by event type
        self._all_callbacks: list[BarEventCallback] = []
        self._created_callbacks: list[BarEventCallback] = []
        self._updated_callbacks: list[BarEventCallback] = []
        self._closed_callbacks: list[BarEventCallback] = []
        self._amended_callbacks: list[BarEventCallback] = []
        self._expired_callbacks: list[BarEventCallback] = []

        # Subscriber queues (for async-iterator consumers)
        self._subscribers: list[tuple[asyncio.Queue[BarEvent | None], BarEventFilter | None]] = []

        # Throttle state: {bar_key → last_emit_time_ms}
        self._update_throttle: dict[str, int] = {}

        # Metrics
        self._events_emitted: int = 0
        self._events_throttled: int = 0
        self._callback_errors: int = 0
        self._queue_recovery_required: int = 0
        self._preview_drops: int = 0
        self._pending_source_events: dict[str, BarEvent] = {}
        # References to payloads already held by suspended publisher frames.
        # Registration adds no new snapshot and ends on success/error/cancel.
        self._inflight_payloads: dict[object, tuple[str, object]] = {}
        self._source_handoff_observer = ContextVar("source_handoff_observer", default=None)

    @contextmanager
    def _observe_source_handoff(self, bar):
        """Observe transfer to the existing retry owner in this call context."""
        observer = _SourceHandoff(id(bar))
        token = self._source_handoff_observer.set(observer)
        try:
            yield observer
        finally:
            observer.active = False
            self._source_handoff_observer.reset(token)

    def _hold_payload(self, kind, payload):
        token = object()
        self._inflight_payloads[token] = (kind, payload)
        return token

    def _release_payload(self, token):
        self._inflight_payloads.pop(token, None)
        if not self._inflight_payloads:
            self._inflight_payloads.clear()  # release capacity after a burst

    def _retained_payloads(self):
        frames = list(self._inflight_payloads.values())
        events = [*list(self._pending_source_events.values()),
                  *(payload for _, payload in frames if isinstance(payload, BarEvent))]
        inputs = [bar for kind, payload in frames if kind == "input"
                  for bar in payload if bar is not None]
        counts = {f"inflight_{kind}_frames": sum(k == kind for k, _ in frames)
                  for kind in ("input", "dispatch", "callback", "retry_input", "retry_keys")}
        counts["pending_source_snapshots"] = len(self._pending_source_events)
        counts["publisher_metadata_bytes"] = (
            sys.getsizeof(self._pending_source_events) + sys.getsizeof(self._inflight_payloads)
            + (len(frames) + len(self._pending_source_events)) * 128
            + sum(sys.getsizeof(payload) + sum(sys.getsizeof(key) for key in payload)
                  for kind, payload in frames if kind == "retry_keys")
        )
        return events, inputs, counts

    def _memory_roots(self):
        return [self._pending_source_events, self._inflight_payloads]

    # ── Public: Callback Registration ────────────────────────

    def on_bar_event(self, callback: BarEventCallback) -> None:
        """Register a callback for ALL bar events.

        Example::

            async def log_event(event: BarEvent):
                print(f"{event.event_type.value}: {event.bar.symbol}")
            publisher.on_bar_event(log_event)
        """
        self._all_callbacks.append(callback)

    def on_bar_created(self, callback: BarEventCallback) -> None:
        """Register a callback for CREATED events only."""
        self._created_callbacks.append(callback)

    def on_bar_updated(self, callback: BarEventCallback) -> None:
        """Register a callback for UPDATED events only."""
        self._updated_callbacks.append(callback)

    def on_bar_closed(self, callback: BarEventCallback) -> None:
        """Register a callback for CLOSED events only.

        This is the **most commonly used** hook.  CLOSED events indicate
        a finalized bar ready for storage, indicator calculation, etc.

        Example::

            async def save_bar(event: BarEvent):
                await storage.upsert_bars(
                    event.bar.symbol,
                    event.bar.interval,
                    [event.bar.to_storage_dict()],
                )
            publisher.on_bar_closed(save_bar)
        """
        self._closed_callbacks.append(callback)

    def on_bar_amended(self, callback: BarEventCallback) -> None:
        """Register a callback for AMENDED events (backfill corrections)."""
        self._amended_callbacks.append(callback)

    def on_bar_expired(self, callback: BarEventCallback) -> None:
        """Register a callback for EXPIRED events (memory eviction)."""
        self._expired_callbacks.append(callback)

    # ── Public: Remove Callbacks ─────────────────────────────

    def remove_callback(self, callback: BarEventCallback) -> None:
        """Remove a callback from all registration lists."""
        self._all_callbacks = [cb for cb in self._all_callbacks if cb is not callback]
        self._created_callbacks = [cb for cb in self._created_callbacks if cb is not callback]
        self._updated_callbacks = [cb for cb in self._updated_callbacks if cb is not callback]
        self._closed_callbacks = [cb for cb in self._closed_callbacks if cb is not callback]
        self._amended_callbacks = [cb for cb in self._amended_callbacks if cb is not callback]
        self._expired_callbacks = [cb for cb in self._expired_callbacks if cb is not callback]

    # ── Public: Async Iterator Subscription ──────────────────

    async def subscribe(
        self,
        event_filter: BarEventFilter | None = None,
    ) -> AsyncIterator[BarEvent]:
        """Subscribe as an async iterator with optional filtering.

        Usage::

            # All events
            async for event in publisher.subscribe():
                ...

            # Only closed bars for BTCUSDT
            async for event in publisher.subscribe(
                event_filter=BarEventFilter(
                    symbols={"BTCUSDT"},
                    event_types={BarEventType.CLOSED},
                )
            ):
                ...

        Break out of the loop to unsubscribe.
        """
        queue: asyncio.Queue[BarEvent | None] = asyncio.Queue(
            maxsize=max(1, self._cfg.publisher_queue_size),
        )
        entry = (queue, event_filter)
        self._subscribers.append(entry)
        logger.debug("New subscriber (total=%d)", len(self._subscribers))

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                if isinstance(event, ConsumerRecoveryRequired):
                    raise event
                yield event
        finally:
            self._subscribers = [s for s in self._subscribers if s[0] is not queue]
            logger.debug("Subscriber removed (remaining=%d)", len(self._subscribers))

    async def close_all_subscribers(self) -> None:
        """Send sentinel to all subscriber queues to unblock them."""
        for queue, _ in list(self._subscribers):
            terminate_queue(queue, None)
        self._subscribers.clear()

    # ── Public: Emit Events ──────────────────────────────────

    async def emit(self, event: BarEvent) -> None:
        """Emit a bar lifecycle event to all consumers.

        Handles throttling for UPDATED events and dispatches to both
        callbacks and subscriber queues.
        """
        # Check if this event type should be emitted
        if not self._should_emit(event):
            return

        # Throttle UPDATED events
        if event.event_type == BarEventType.UPDATED:
            if not self._throttle_check(event):
                self._events_throttled += 1
                return

        # Snapshot the single emitted state before the first await. Later
        # ticks may mutate its builder while callbacks are suspended.
        original_bar = event.bar
        event = deepcopy(event)
        self._events_emitted += 1
        token = self._hold_payload("dispatch", event)
        try:
            # Fire type-specific callbacks. A retry keeps the original pending
            # version without constructing a discarded duplicate snapshot.
            if event.bar.source_refs and event.delivery_id not in self._pending_source_events:
                self._pending_source_events[event.delivery_id] = copy.deepcopy(event)
            observer = self._source_handoff_observer.get()
            if (event.bar.source_refs and observer is not None and observer.active
                    and observer.bar_id == id(original_bar)):
                # This is synchronous with registration, before any callback can
                # suspend or a concurrent retry can acknowledge the snapshot.
                observer.transferred = True
            await self._fire_callbacks(event)
            if (self._pending_source_events.pop(event.delivery_id, None) is not None
                    and not self._pending_source_events):
                self._pending_source_events.clear()
            # Push to subscriber queues
            self._enqueue(event)
        finally:
            self._release_payload(token)

    async def _emit_bar_event(self, event_type, bar, previous=None):
        # Convenience-call arguments are real retained builder references even
        # if a callback detaches their target while the publication awaits.
        token = self._hold_payload("input", (bar, previous))
        try:
            await self.emit(BarEvent(event_type=event_type, bar=bar, previous_bar=previous))
        finally:
            self._release_payload(token)

    async def emit_created(self, bar: BarState) -> None:
        """Convenience: emit a CREATED event."""
        await self._emit_bar_event(BarEventType.CREATED, bar)

    async def emit_updated(self, bar: BarState) -> None:
        """Convenience: emit an UPDATED event (subject to throttling)."""
        await self._emit_bar_event(BarEventType.UPDATED, bar)

    async def emit_closed(self, bar: BarState) -> None:
        """Convenience: emit a CLOSED event."""
        await self._emit_bar_event(BarEventType.CLOSED, bar)

    async def emit_amended(
        self, bar: BarState, previous: BarState | None = None,
    ) -> None:
        """Convenience: emit an AMENDED event."""
        await self._emit_bar_event(BarEventType.AMENDED, bar, previous)

    async def emit_expired(self, bar: BarState) -> None:
        """Convenience: emit an EXPIRED event."""
        await self._emit_bar_event(BarEventType.EXPIRED, bar)

    # ── Public: Throttle Configuration ───────────────────────

    def set_update_throttle_ms(self, ms: int) -> None:
        """Change the UPDATED event throttle interval at runtime.

        Args:
            ms: Minimum interval between UPDATED events per bar (ms).
                0 = no throttle.
        """
        self._cfg.update_throttle_ms = ms
        logger.info("Update throttle changed to %d ms", ms)

    # ── Public: Snapshot ─────────────────────────────────────

    def snapshot(self) -> dict:
        _, _, payload_counts = self._retained_payloads()
        return {
            "layer": "L5_Publisher",
            "events_emitted": self._events_emitted,
            "events_throttled": self._events_throttled,
            "callback_errors": self._callback_errors,
            "queue_recovery_required": self._queue_recovery_required,
            "preview_drops": self._preview_drops,
            "all_callbacks": len(self._all_callbacks),
            "created_callbacks": len(self._created_callbacks),
            "updated_callbacks": len(self._updated_callbacks),
            "closed_callbacks": len(self._closed_callbacks),
            "amended_callbacks": len(self._amended_callbacks),
            "expired_callbacks": len(self._expired_callbacks),
            "active_subscribers": len(self._subscribers),
            "update_throttle_ms": self._cfg.update_throttle_ms,
            **payload_counts,
        }

    # ── Internal: Should Emit ────────────────────────────────

    def _should_emit(self, event: BarEvent) -> bool:
        """Check if an event type should be emitted based on config."""
        et = event.event_type
        if et == BarEventType.CREATED and not self._cfg.emit_created_events:
            return False
        if et == BarEventType.UPDATED and not self._cfg.emit_updated_events:
            return False
        if et == BarEventType.EXPIRED and not self._cfg.emit_expired_events:
            return False
        return True

    # ── Internal: Throttle ───────────────────────────────────

    def _throttle_check(self, event: BarEvent) -> bool:
        """Return True if this UPDATED event should pass throttle."""
        throttle_ms = self._cfg.update_throttle_ms
        if throttle_ms <= 0:
            return True

        bar_key = event.bar_key
        now_ms = int(time.time() * 1000)
        last_emit = self._update_throttle.get(bar_key, 0)

        if now_ms - last_emit < throttle_ms:
            return False  # too soon, throttle it

        self._update_throttle[bar_key] = now_ms

        # Clean up stale throttle entries (bars that haven't updated in 60s)
        cutoff = now_ms - 60_000
        self._update_throttle = {
            k: v for k, v in self._update_throttle.items() if v > cutoff
        }

        return True

    # ── Internal: Callback Dispatch ──────────────────────────

    async def retry_source_deliveries(self) -> None:
        keys = tuple(self._pending_source_events)
        if not keys:
            return
        keys_token = self._hold_payload("retry_keys", keys)
        try:
            for key in keys:
                event = self._pending_source_events.get(key)
                if event is None:
                    continue  # Another retry already acknowledged this record.
                token = self._hold_payload("retry_input", event)
                try:
                    await self.emit(event)
                finally:
                    self._release_payload(token)
                    del event
        finally:
            self._release_payload(keys_token)

    async def _fire_callbacks(self, event: BarEvent) -> None:
        """Fire all matching callbacks for this event."""
        et = event.event_type

        # Type-specific callbacks
        specific: list[BarEventCallback] = []
        if et == BarEventType.CREATED:
            specific = self._created_callbacks
        elif et == BarEventType.UPDATED:
            specific = self._updated_callbacks
        elif et == BarEventType.CLOSED:
            specific = self._closed_callbacks
        elif et == BarEventType.AMENDED:
            specific = self._amended_callbacks
        elif et == BarEventType.EXPIRED:
            specific = self._expired_callbacks

        # Fire type-specific + all-events callbacks
        for cb in specific + self._all_callbacks:
            callback_event = token = None
            try:
                callback_event = deepcopy(event)
                token = self._hold_payload("callback", callback_event)
                await cb(callback_event)
            except BarDeliveryUnavailable:
                self._callback_errors += 1
                raise
            except Exception as exc:
                self._callback_errors += 1
                logger.error(
                    "Bar event callback error (%s): %s",
                    et.value, exc, exc_info=True,
                )
                if event.bar.source_refs:
                    raise BarDeliveryUnavailable(str(exc)) from exc
            finally:
                if token is not None:
                    self._release_payload(token)
                del callback_event

    # ── Internal: Queue Dispatch ─────────────────────────────

    def _enqueue(self, event: BarEvent) -> None:
        """Push event to all matching subscriber queues."""
        for queue, event_filter in list(self._subscribers):
            # Apply filter
            if event_filter is not None and not event_filter.matches(event):
                continue
            try:
                queue.put_nowait(deepcopy(event))
            except asyncio.QueueFull:
                if event.event_type == BarEventType.UPDATED:
                    self._preview_drops += 1
                    continue
                self._queue_recovery_required += 1
                self._subscribers = [entry for entry in self._subscribers if entry[0] is not queue]
                terminate_queue(queue, ConsumerRecoveryRequired("bar_publisher_queue_overflow"))
