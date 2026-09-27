"""
Event Bus — topic-based pub/sub for Data Manager events.

The event bus sits at the center of the Data Manager, connecting
producers (ingestion → bar_aggregator, backfill, cache) to consumers
(WebSocket hub, indicator engine, strategy engine, logging, etc.).

Features:
  * **Topic routing** — events are keyed by ``SeriesKey`` (symbol@interval).
    Subscribers can listen to a specific topic or to all topics (wildcard).
  * **Callback delivery** — registered async callbacks are isolated behind
    per-subscriber bounded queues.
  * **Async-iterator delivery** — ``subscribe_iter()`` returns an
    ``AsyncIterator[DataEvent]`` backed by a bounded queue.
  * **Type filtering** — subscribers can filter by ``DataEventType``.
  * **Middleware** — pluggable pre-emit hooks for metrics, logging, etc.

Design constraints:
  * The bus is **in-process only** — no network transport.
  * Callbacks should still be reasonably fast, but a slow callback no longer
    blocks producers or other subscribers.
  * Queue-based subscribers that fall behind keep only the latest pending
    ``BAR_UPDATED`` event per topic.  Closed bars, historical amendments, and
    other events use a shared bounded replay log. Exhaustion terminates the
    affected subscription explicitly; producers never await consumer capacity.

Usage::

    bus = DataEventBus(config)

    # Callback style
    handle = bus.subscribe(
        key=SeriesKey("BTCUSDT", "1m"),
        event_types={DataEventType.BAR_CLOSED},
        callback=my_handler,
    )
    bus.unsubscribe(handle)

    # Async iterator style
    async for event in bus.subscribe_iter(
        key=SeriesKey("BTCUSDT", "1m"),
    ):
        process(event)

    # Wildcard — all events
    handle = bus.subscribe(callback=my_global_handler)

    # Emit an event
    await bus.emit(event)
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from copy import deepcopy
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Awaitable

from app.data_engine.consumer_recovery import ConsumerRecoveryRequired, RecoveryCallback

from .config import EventBusConfig
from .models import (
    DataEvent,
    DataEventType,
    EventCallback,
    SeriesKey,
    SubscriptionHandle,
)

logger = logging.getLogger("data_manager.event_bus")

# Type for middleware hooks
MiddlewareHook = Callable[[DataEvent], Awaitable[DataEvent | None]]


# Only these events are replaceable snapshots. Lifecycle/control events must
# either arrive in order or explicitly invalidate the subscription.
_REPLACEABLE_TYPES = frozenset({DataEventType.BAR_UPDATED, DataEventType.PRICE_UPDATED})


@dataclass(slots=True)
class _QueuedEvent:
    event: DataEvent
    enqueued_at: float
    sequence: int = 0


class _SubscriberQueue(asyncio.Queue[_QueuedEvent | None]):
    """Bounded pending events; overflow recovery belongs to the bus journal."""

    def __init__(self, maxsize: int = 1000) -> None:
        if maxsize <= 0:
            raise ValueError("subscriber_queue_size must be positive")
        super().__init__(maxsize=maxsize)
        self._latest_forming: dict[tuple[SeriesKey, DataEventType], _QueuedEvent] = {}
        self._closed = False
        self._delivery_ids: OrderedDict[str, None] = OrderedDict()
        self.replay_next: int | None = None
        self.replayed = 0
        self.confirmed_sequence = 0
        self.confirmed_delivery_id: str | None = None
        self.recovery_error: ConsumerRecoveryRequired | None = None

    def _remember_delivery(self, event):
        delivery_id = event.detail.get("delivery_id")
        if delivery_id:
            self._delivery_ids[delivery_id] = None
            while len(self._delivery_ids) > max(1024, self.maxsize * 2):
                self._delivery_ids.popitem(last=False)

    def offer(self, event: DataEvent, sequence: int = 0) -> str:
        if self._closed:
            return "closed"
        if event.detail.get("delivery_id") in self._delivery_ids:
            return "duplicate"
        if event.event_type in _REPLACEABLE_TYPES:
            pending = self._latest_forming.get((event.key, event.event_type))
            if pending is not None:
                pending.event = event
                pending.enqueued_at = time.perf_counter()
                return "coalesced"
        item = _QueuedEvent(event=event, enqueued_at=time.perf_counter(), sequence=sequence)
        try:
            self.put_nowait(item)
            self._remember_delivery(event)
            if event.event_type in _REPLACEABLE_TYPES:
                self._latest_forming[(event.key, event.event_type)] = item
            else:
                # Seal an older forming slot only after the final/correction or
                # lifecycle event is safely queued.  On QueueFull the old slot
                # remains replaceable instead of losing its routing index.
                self._seal_previews(event.key)
            return "queued"
        except asyncio.QueueFull:
            if event.event_type not in _REPLACEABLE_TYPES:
                # Prefer reclaiming pending previews before switching to replay.
                # Removing previews is safe because their latest state is
                # replaceable; correction barriers are not.
                while self.full() and self._evict_oldest_forming_update():
                    pass
                try:
                    self.put_nowait(item)
                    self._remember_delivery(event)
                except asyncio.QueueFull:
                    return "critical_full"
                # The correction now follows any older forming update for the
                # same series, so that slot must no longer be replaceable by a
                # later preview.
                self._seal_previews(event.key)
                return "queued"
            return "full"

    def _seal_previews(self, key: SeriesKey) -> None:
        for kind in _REPLACEABLE_TYPES:
            self._latest_forming.pop((key, kind), None)

    def close_nowait(self) -> None:
        """Discard a detached subscriber's backlog and enqueue one sentinel."""
        self._closed = True
        while True:
            try:
                super().get_nowait()
            except asyncio.QueueEmpty:
                break
        self._latest_forming.clear()
        self._delivery_ids.clear()
        # Queue consumers in this module do not use join()/task_done().  Reset
        # the inherited bookkeeping as part of terminal cleanup so a detached
        # queue cannot retain stale unfinished state either.
        self._unfinished_tasks = 0
        self._finished.set()
        super().put_nowait(None)

    def _evict_oldest_forming_update(self) -> bool:
        """Remove one pending live preview while preserving all other order."""
        for index, pending in enumerate(self._queue):
            if (
                pending is None
                or pending.event.event_type not in _REPLACEABLE_TYPES
            ):
                continue
            del self._queue[index]
            if self._latest_forming.get((pending.event.key, pending.event.event_type)) is pending:
                self._latest_forming.pop((pending.event.key, pending.event.event_type), None)
            if self._unfinished_tasks > 0:
                self._unfinished_tasks -= 1
                if self._unfinished_tasks == 0:
                    self._finished.set()
            self._wakeup_next(self._putters)
            return True
        return False

    def get_nowait(self) -> _QueuedEvent | None:
        item = super().get_nowait()
        if (
            item is not None
            and self._latest_forming.get((item.event.key, item.event.event_type)) is item
        ):
            self._latest_forming.pop((item.event.key, item.event.event_type), None)
        return item


@dataclass(slots=True)
class _CallbackSubscription:
    queue: _SubscriberQueue
    handle: SubscriptionHandle
    task: asyncio.Task | None = None
    on_recovery: RecoveryCallback | None = None
    recovery_task: asyncio.Task | None = None
    recovery_notification_error: str | None = None
    dropped: int = 0
    last_error: str | None = None
    delivered: int = 0
    total_lag_ms: float = 0.0
    max_lag_ms: float = 0.0
    last_lag_ms: float = 0.0
    coalesced: int = 0
    replay_entries: int = 0


@dataclass(slots=True)
class _QueueSubscription:
    queue: _SubscriberQueue
    handle: SubscriptionHandle
    dropped: int = 0
    delivered: int = 0
    total_lag_ms: float = 0.0
    max_lag_ms: float = 0.0
    last_lag_ms: float = 0.0
    coalesced: int = 0
    replay_entries: int = 0


class DataEventBus:
    """In-process, topic-based event bus for Data Manager events.

    Central nervous system of the Data Manager — all bar lifecycle
    events, stream events, and system events flow through here.

    Thread-safety: the bus is designed to be used from a single asyncio
    event loop.  ``emit()`` is async and should be awaited.
    """

    def __init__(
        self,
        config: EventBusConfig | None = None,
        *,
        protection_lock: Any | None = None,
        on_subscription_change: Callable[[], None] | None = None,
    ) -> None:
        self._cfg = config or EventBusConfig()
        if self._cfg.subscriber_queue_size <= 0 or self._cfg.replay_capacity <= 0:
            raise ValueError("event bus queue and replay capacities must be positive")
        self._epoch = uuid.uuid4().hex
        self._sequence = 0
        self._journal: OrderedDict[int, _QueuedEvent] = OrderedDict()
        self._delivery_ids: OrderedDict[str, None] = OrderedDict()
        self._recovery_required = 0
        self._closed = False
        self._protection_lock = protection_lock or threading.RLock()
        self._worker_tasks: set[asyncio.Task] = set()
        self._on_subscription_change = on_subscription_change

        # Callback subscriptions: handle.id → SubscriptionHandle
        self._subscriptions: dict[str, SubscriptionHandle] = {}

        # Callback subscriptions delivered through per-subscriber worker queues.
        self._callback_subs: dict[str, _CallbackSubscription] = {}
        self._callback_ids_by_key: dict[SeriesKey, set[str]] = {}
        self._callback_wildcard_ids: set[str] = set()

        # Queue-based subscriptions: handle.id → (queue, handle)
        self._queue_subs: dict[str, _QueueSubscription] = {}
        self._queue_ids_by_key: dict[SeriesKey, set[str]] = {}
        self._queue_wildcard_ids: set[str] = set()

        # Middleware chain (pre-emit hooks)
        self._middleware: list[MiddlewareHook] = []

        # Metrics
        self._events_emitted = 0
        self._events_dropped = 0
        self._callback_errors = 0

    # ── Public: Subscription (callback) ──────────────────────

    def subscribe(
        self,
        callback: EventCallback,
        key: SeriesKey | None = None,
        event_types: set[DataEventType] | None = None,
        *,
        on_recovery: RecoveryCallback | None = None,
    ) -> SubscriptionHandle:
        """Register a callback to receive events.

        Args:
            callback:    Async function called for each matching event.
            key:         Filter to this (symbol, interval).  None = all.
            event_types: Filter to these event types.  None = all types.

        Returns:
            A ``SubscriptionHandle`` — pass to ``unsubscribe()`` to stop.

        Example::

            async def on_bar_closed(event: DataEvent):
                print(f"Bar closed: {event.bar}")

            handle = bus.subscribe(
                callback=on_bar_closed,
                key=SeriesKey("BTCUSDT", "1m"),
                event_types={DataEventType.BAR_CLOSED},
            )
        """
        if self._closed:
            raise RuntimeError("event bus is closed")
        handle = SubscriptionHandle(
            key=key,
            event_types=event_types,
            callback=callback,
        )
        queue = _SubscriberQueue(
            maxsize=self._cfg.subscriber_queue_size,
        )
        sub = _CallbackSubscription(queue=queue, handle=handle, on_recovery=on_recovery)
        with self._protection_lock:
            self._subscriptions[handle.id] = handle
            self._callback_subs[handle.id] = sub
            self._index_subscription(
                handle,
                keyed=self._callback_ids_by_key,
                wildcard=self._callback_wildcard_ids,
            )
            if self._on_subscription_change is not None:
                self._on_subscription_change()
        self._ensure_callback_worker(sub)
        logger.debug(
            "Subscription added: id=%s key=%s types=%s",
            handle.id, key, event_types,
        )
        return handle

    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        """Remove a callback subscription."""
        with self._protection_lock:
            removed = self._subscriptions.pop(handle.id, None)
            callback_entry = self._callback_subs.pop(handle.id, None)
            entry = self._queue_subs.pop(handle.id, None)
            if callback_entry is not None:
                self._deindex_subscription(
                    callback_entry.handle,
                    keyed=self._callback_ids_by_key,
                    wildcard=self._callback_wildcard_ids,
                )
            if entry is not None:
                self._deindex_subscription(
                    entry.handle,
                    keyed=self._queue_ids_by_key,
                    wildcard=self._queue_wildcard_ids,
                )
            if (
                (removed is not None or callback_entry is not None or entry is not None)
                and self._on_subscription_change is not None
            ):
                self._on_subscription_change()
        if removed:
            logger.debug("Subscription removed: id=%s", handle.id)

        if callback_entry:
            self._put_sentinel(callback_entry.queue)
            try:
                current_task = asyncio.current_task()
            except RuntimeError:
                current_task = None
            for task in (callback_entry.task, callback_entry.recovery_task):
                if task is not None and task is not current_task:
                    task.cancel()
            logger.debug("Callback subscription removed: id=%s", handle.id)

        # Also check queue subscriptions
        if entry:
            self._put_sentinel(entry.queue)
            logger.debug("Queue subscription removed: id=%s", handle.id)

    # ── Public: Subscription (async iterator) ────────────────

    async def subscribe_iter(
        self,
        key: SeriesKey | None = None,
        event_types: set[DataEventType] | None = None,
    ) -> AsyncIterator[DataEvent]:
        """Subscribe as an async iterator.

        Yields ``DataEvent`` objects matching the optional filters.
        Break out of the loop to unsubscribe.

        Usage::

            async for event in bus.subscribe_iter(
                key=SeriesKey("BTCUSDT", "1m"),
                event_types={DataEventType.BAR_CLOSED, DataEventType.BAR_UPDATED},
            ):
                push_to_websocket(event)
        """
        if self._closed:
            raise RuntimeError("event bus is closed")
        queue = _SubscriberQueue(
            maxsize=self._cfg.subscriber_queue_size,
        )
        handle = SubscriptionHandle(
            key=key,
            event_types=event_types,
        )
        sub = _QueueSubscription(queue=queue, handle=handle)
        with self._protection_lock:
            self._queue_subs[handle.id] = sub
            self._index_subscription(
                handle,
                keyed=self._queue_ids_by_key,
                wildcard=self._queue_wildcard_ids,
            )
            if self._on_subscription_change is not None:
                self._on_subscription_change()
        logger.debug(
            "Iterator subscription added: id=%s key=%s", handle.id, key,
        )

        try:
            while True:
                item = await self._next_item(sub)
                if item is None:
                    break
                self._record_queue_lag(sub, item.enqueued_at)
                yield deepcopy(item.event) if item.sequence else item.event
                self._confirm(sub, item)
        finally:
            removed = None
            with self._protection_lock:
                removed = self._queue_subs.pop(handle.id, None)
                if removed is not None:
                    self._deindex_subscription(
                        removed.handle,
                        keyed=self._queue_ids_by_key,
                        wildcard=self._queue_wildcard_ids,
                    )
                if removed is not None and self._on_subscription_change is not None:
                    self._on_subscription_change()
            if removed is not None:
                self._put_sentinel(removed.queue)
            logger.debug(
                "Iterator subscription removed: id=%s", handle.id,
            )

    # ── Public: Emit ─────────────────────────────────────────

    async def emit(self, event: DataEvent) -> None:
        """Emit an event to all matching subscribers.

        The event flows through the middleware chain first.  If any
        middleware returns ``None``, the event is suppressed.

        Then it is delivered to callback and iterator subscribers via bounded
        queues and a shared bounded replay window. Exhaustion requires a fresh
        snapshot and subscription. No queue-capacity wait occurs in emit().
        """
        # Apply config-level filters
        if not self._should_emit(event):
            return

        # Middleware chain
        processed: DataEvent | None = event
        for mw in self._middleware:
            try:
                processed = await mw(processed)
            except Exception as exc:
                logger.error("Middleware error: %s", exc, exc_info=True)
                processed = event  # fall through on error
            if processed is None:
                return  # middleware suppressed the event

        if self._closed:
            raise RuntimeError("event bus is closed")
        event = processed
        delivery_id = event.detail.get("delivery_id")
        if delivery_id and delivery_id in self._delivery_ids:
            return
        self._events_emitted += 1
        sequence = 0
        if event.event_type not in _REPLACEABLE_TYPES:
            # A single immutable copy is shared by the replay window and queues.
            # Callbacks receive a copy, so mutation cannot corrupt later replay.
            event = deepcopy(event)
            self._sequence += 1
            sequence = self._sequence
            self._journal[sequence] = _QueuedEvent(event, time.perf_counter(), sequence)
            if delivery_id:
                self._delivery_ids[delivery_id] = None
                while len(self._delivery_ids) > max(1024, self._cfg.replay_capacity * 2):
                    self._delivery_ids.popitem(last=False)
            while len(self._journal) > self._cfg.replay_capacity:
                evicted_sequence, evicted = self._journal.popitem(last=False)
                callbacks, queues = self._matching_subscriptions(evicted.event.key)
                for _, sub in callbacks + queues:
                    cursor = sub.queue.replay_next
                    if cursor is not None and cursor <= evicted_sequence and sub.handle.matches(evicted.event):
                        self._require_recovery(sub, "replay_window_exhausted", cursor)

        callbacks, queues = self._matching_subscriptions(event.key)
        for _, sub in callbacks + queues:
            if not sub.handle.matches(event) or sub.queue.recovery_error is not None:
                continue
            if isinstance(sub, _CallbackSubscription):
                self._ensure_callback_worker(sub)
            if sub.queue.replay_next is not None:
                # Reliable events already live in the shared log. Previews are
                # dispensable while catching up, and cannot overtake finality.
                if not sequence:
                    sub.dropped += 1
                    self._events_dropped += 1
                continue
            offer = sub.queue.offer(event, sequence)
            if offer == "coalesced":
                sub.coalesced += 1
            elif offer == "critical_full":
                sub.replay_entries += 1
                sub.queue.replay_next = sequence
            elif offer == "full":
                sub.dropped += 1
                self._events_dropped += 1

    async def emit_many(self, events: list[DataEvent]) -> None:
        """Emit multiple events in sequence."""
        for event in events:
            await self.emit(event)

    # ── Public: Middleware ────────────────────────────────────

    def add_middleware(self, hook: MiddlewareHook) -> None:
        """Register a pre-emit middleware hook.

        Middleware runs **before** subscribers receive the event.
        The hook receives a ``DataEvent`` and must return either:
          * The same or modified ``DataEvent`` — continue delivery
          * ``None`` — suppress the event entirely

        Use cases:
          * Logging / metrics
          * Event transformation
          * Rate limiting
          * Access control

        Example::

            async def log_middleware(event: DataEvent) -> DataEvent:
                logger.info("Event: %s %s", event.event_type, event.key)
                return event

            bus.add_middleware(log_middleware)
        """
        self._middleware.append(hook)

    def remove_middleware(self, hook: MiddlewareHook) -> None:
        """Remove a previously registered middleware hook."""
        self._middleware = [m for m in self._middleware if m is not hook]

    # ── Public: Close ────────────────────────────────────────

    async def close(self) -> None:
        """Send sentinel to all queue subscribers and clear everything."""
        self._closed = True
        callback_tasks: list[asyncio.Task] = []
        for sub_id, sub in list(self._callback_subs.items()):
            self._put_sentinel(sub.queue)
            for task in (sub.task, sub.recovery_task):
                if task is not None and task is not asyncio.current_task():
                    task.cancel()
                    callback_tasks.append(task)
            logger.debug("Callback subscription closed: id=%s", sub_id)
        # A recovery hook can unsubscribe itself before awaiting snapshot work.
        # Its task still belongs to this bus and must be drained on shutdown.
        for task in tuple(self._worker_tasks):
            if task is not asyncio.current_task() and task not in callback_tasks:
                task.cancel()
                callback_tasks.append(task)
        if callback_tasks:
            await asyncio.gather(*callback_tasks, return_exceptions=True)
        for sub_id, sub in list(self._queue_subs.items()):
            self._put_sentinel(sub.queue)
        with self._protection_lock:
            changed = bool(
                self._callback_subs or self._queue_subs or self._subscriptions
            )
            self._callback_subs.clear()
            self._queue_subs.clear()
            self._subscriptions.clear()
            self._callback_ids_by_key.clear()
            self._callback_wildcard_ids.clear()
            self._queue_ids_by_key.clear()
            self._queue_wildcard_ids.clear()
            if changed and self._on_subscription_change is not None:
                self._on_subscription_change()
        self._journal.clear()
        self._delivery_ids.clear()
        logger.info("Event bus closed")

    # ── Public: Introspection ────────────────────────────────

    def get_subscriber_count(self, key: SeriesKey | None = None) -> int:
        """Count active subscribers, optionally filtered by key."""
        with self._protection_lock:
            if key is None:
                return len(self._callback_subs) + len(self._queue_subs)
            return (
                len(self._callback_wildcard_ids)
                + len(self._callback_ids_by_key.get(key, ()))
                + len(self._queue_wildcard_ids)
                + len(self._queue_ids_by_key.get(key, ()))
            )

    def get_direct_subscriber_count(self, key: SeriesKey) -> int:
        """Count subscribers that explicitly retain one series.

        Wildcard subscriptions are event observers.  They receive matching
        events for every series, but they do not express lifecycle ownership
        of every cache entry or upstream stream.
        """
        with self._protection_lock:
            return len(self._callback_ids_by_key.get(key, ())) + len(
                self._queue_ids_by_key.get(key, ())
            )

    def get_all_subscribed_keys(self) -> set[SeriesKey]:
        """Return all SeriesKeys that have at least one subscriber."""
        with self._protection_lock:
            return set(self._callback_ids_by_key) | set(self._queue_ids_by_key)

    # ── Public: Snapshot ─────────────────────────────────────

    def snapshot(self) -> dict:
        """JSON-serializable diagnostic snapshot."""
        with self._protection_lock:
            direct_subscriptions_by_key = {
                str(key): len(self._callback_ids_by_key.get(key, ()))
                + len(self._queue_ids_by_key.get(key, ()))
                for key in sorted(
                    set(self._callback_ids_by_key) | set(self._queue_ids_by_key),
                    key=str,
                )
            }
        return {
            "callback_subscriptions": len(self._subscriptions),
            "queue_subscriptions": len(self._queue_subs),
            "middleware_count": len(self._middleware),
            "epoch": self._epoch,
            "replay_capacity": self._cfg.replay_capacity,
            "replay_size": len(self._journal),
            "sequence": self._sequence,
            "recovery_required_total": self._recovery_required,
            "consumer_states": {
                sub_id: {
                    "state": ("recovery_required" if sub.queue.recovery_error else
                              "replaying" if sub.queue.replay_next is not None else "live"),
                    "confirmed_sequence": sub.queue.confirmed_sequence,
                    "confirmed_delivery_id": sub.queue.confirmed_delivery_id,
                    "replay_next": sub.queue.replay_next,
                    "replayed": sub.queue.replayed,
                    "recovery": sub.queue.recovery_error.to_dict() if sub.queue.recovery_error else None,
                    "notification_error": getattr(sub, "recovery_notification_error", None),
                }
                for sub_id, sub in [*self._callback_subs.items(), *self._queue_subs.items()]
            },
            "events_emitted": self._events_emitted,
            "events_dropped": self._events_dropped,
            "callback_errors": self._callback_errors,
            "callback_queue_drops": {
                sub_id: sub.dropped
                for sub_id, sub in self._callback_subs.items()
                if sub.dropped
            },
            "callback_last_errors": {
                sub_id: sub.last_error
                for sub_id, sub in self._callback_subs.items()
                if sub.last_error
            },
            "callback_lag": {
                sub_id: self._lag_snapshot(sub)
                for sub_id, sub in self._callback_subs.items()
                if sub.delivered or sub.dropped or sub.queue.qsize()
            },
            "queue_lag": {
                sub_id: self._lag_snapshot(sub)
                for sub_id, sub in self._queue_subs.items()
                if sub.delivered or sub.dropped or sub.queue.qsize()
            },
            "subscribed_keys": [
                str(k) for k in self.get_all_subscribed_keys()
            ],
            "direct_subscriptions_by_key": direct_subscriptions_by_key,
        }

    # ── Internal ─────────────────────────────────────────────

    @staticmethod
    def _index_subscription(
        handle: SubscriptionHandle,
        *,
        keyed: dict[SeriesKey, set[str]],
        wildcard: set[str],
    ) -> None:
        if handle.key is None:
            wildcard.add(handle.id)
            return
        keyed.setdefault(handle.key, set()).add(handle.id)

    @staticmethod
    def _deindex_subscription(
        handle: SubscriptionHandle,
        *,
        keyed: dict[SeriesKey, set[str]],
        wildcard: set[str],
    ) -> None:
        if handle.key is None:
            wildcard.discard(handle.id)
            return
        ids = keyed.get(handle.key)
        if ids is None:
            return
        ids.discard(handle.id)
        if not ids:
            keyed.pop(handle.key, None)

    def _matching_subscriptions(
        self,
        key: SeriesKey,
    ) -> tuple[
        list[tuple[str, _CallbackSubscription]],
        list[tuple[str, _QueueSubscription]],
    ]:
        """Snapshot only wildcard and exact-topic subscribers for one emit."""
        with self._protection_lock:
            callback_ids = (
                self._callback_wildcard_ids
                | self._callback_ids_by_key.get(key, set())
            )
            queue_ids = (
                self._queue_wildcard_ids
                | self._queue_ids_by_key.get(key, set())
            )
            callbacks = [
                (sub_id, sub)
                for sub_id in callback_ids
                if (sub := self._callback_subs.get(sub_id)) is not None
            ]
            queues = [
                (sub_id, sub)
                for sub_id in queue_ids
                if (sub := self._queue_subs.get(sub_id)) is not None
            ]
        return callbacks, queues

    def _should_emit(self, event: DataEvent) -> bool:
        """Apply config-level event filters."""
        et = event.event_type
        if et == DataEventType.BAR_UPDATED and not self._cfg.emit_bar_updated:
            return False
        if et == DataEventType.BAR_CREATED and not self._cfg.emit_bar_created:
            return False
        return True

    def _ensure_callback_worker(self, sub: _CallbackSubscription) -> None:
        if sub.queue.recovery_error is not None or sub.queue._closed:
            return
        if sub.task is not None and not sub.task.done():
            return
        try:
            asyncio.get_running_loop()
            sub.task = asyncio.create_task(
                self._callback_worker(sub),
                name=f"event-bus-callback:{sub.handle.id}",
            )
            self._track_task(sub.task)
        except RuntimeError:
            # subscribe() may run during setup before an event loop exists.
            # The worker will be started on the first emit inside a loop.
            sub.task = None

    async def _callback_worker(self, sub: _CallbackSubscription) -> None:
        handle = sub.handle
        while True:
            try:
                item = await self._next_item(sub)
            except ConsumerRecoveryRequired:
                return
            if item is None:
                return
            if handle.callback is None:
                continue
            self._record_queue_lag(sub, item.enqueued_at)
            try:
                await handle.callback(deepcopy(item.event) if item.sequence else item.event)
                self._confirm(sub, item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                sub.last_error = str(exc)
                self._callback_errors += 1
                logger.error(
                    "Event callback error (sub=%s): %s",
                    handle.id, exc, exc_info=True,
                )

                self._require_recovery(sub, "callback_failed", item.sequence or None)
                return

    async def _next_item(self, sub: _CallbackSubscription | _QueueSubscription) -> _QueuedEvent | None:
        queue = sub.queue
        if queue.recovery_error is not None:
            raise queue.recovery_error
        if not queue.empty():
            return queue.get_nowait()
        if queue.replay_next is not None:
            for sequence, item in self._journal.items():
                if sequence < queue.replay_next:
                    continue
                queue.replay_next = sequence + 1
                if sub.handle.matches(item.event):
                    queue.replayed += 1
                    return item
            queue.replay_next = None
        item = await queue.get()
        if queue.recovery_error is not None:
            raise queue.recovery_error
        return item

    @staticmethod
    def _confirm(sub: _CallbackSubscription | _QueueSubscription, item: _QueuedEvent) -> None:
        # Callback return / iterator next() confirms local handling only. A
        # downstream task, socket peer or side effect has its own acknowledgement.
        if sub.queue.recovery_error is None and item.sequence:
            sub.queue.confirmed_sequence = item.sequence
            sub.queue.confirmed_delivery_id = item.event.detail.get("delivery_id")

    def _require_recovery(self, sub, reason: str, first_missing: int | None) -> None:
        queue = sub.queue
        if queue.recovery_error is not None:
            return
        error = ConsumerRecoveryRequired(
            reason, subscription_id=sub.handle.id, epoch=self._epoch,
            confirmed_sequence=queue.confirmed_sequence,
            first_missing_sequence=first_missing,
        )
        queue.recovery_error = error
        queue.replay_next = None
        queue.close_nowait()
        self._recovery_required += 1
        logger.error("Consumer recovery required: %s", error.to_dict())
        if isinstance(sub, _CallbackSubscription) and sub.on_recovery is not None:
            # Separate bounded task: a hung callback must not hide the gap.
            sub.recovery_task = asyncio.create_task(
                self._notify_recovery(sub, error),
                name=f"event-bus-recovery:{sub.handle.id}",
            )
            self._track_task(sub.recovery_task)

    def _track_task(self, task: asyncio.Task) -> None:
        self._worker_tasks.add(task)
        task.add_done_callback(self._worker_tasks.discard)

    async def _notify_recovery(self, sub: _CallbackSubscription, error: ConsumerRecoveryRequired) -> None:
        try:
            await sub.on_recovery(error)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            sub.recovery_notification_error = str(exc)
            logger.exception("Consumer recovery notification failed: %s", sub.handle.id)

    @staticmethod
    def _put_sentinel(queue: _SubscriberQueue) -> None:
        queue.close_nowait()

    @staticmethod
    def _record_queue_lag(
        sub: _CallbackSubscription | _QueueSubscription,
        enqueued_at: float,
    ) -> None:
        lag_ms = max(0.0, (time.perf_counter() - enqueued_at) * 1000)
        sub.delivered += 1
        sub.total_lag_ms += lag_ms
        sub.max_lag_ms = max(sub.max_lag_ms, lag_ms)
        sub.last_lag_ms = lag_ms

    @staticmethod
    def _lag_snapshot(sub: _CallbackSubscription | _QueueSubscription) -> dict[str, Any]:
        avg = sub.total_lag_ms / sub.delivered if sub.delivered else 0.0
        return {
            "queue_size": sub.queue.qsize(),
            "queue_max_size": sub.queue.maxsize,
            "delivered": sub.delivered,
            "dropped": sub.dropped,
            "coalesced": sub.coalesced,
            "backpressured": 0,  # retained diagnostic key; publishers never wait
            "replay_entries": sub.replay_entries,
            "avg_lag_ms": round(avg, 2),
            "max_lag_ms": round(sub.max_lag_ms, 2),
            "last_lag_ms": round(sub.last_lag_ms, 2),
        }
