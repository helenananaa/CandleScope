"""Source-gap contracts for DataManager consumers, independent of bus loss.

One registry owns evidence of missing final bars. Each consumer chooses whether
to wait; waiting happens in its existing bounded EventBus worker/replay window,
never in the producer. Historical repair is still owned by BackfillCoordinator.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import AsyncIterator

from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.data_engine.history.exchange_policy import native_kline_calendar
from app.data_engine.interval_policy import parse_interval_spec

from .models import BarData, DataEvent, DataEventType, SeriesKey


from app.data_engine.continuity_policy import ContinuityPolicy


CONTROLS = frozenset({DataEventType.SOURCE_GAP, DataEventType.SOURCE_GAP_RESOLVED})


@dataclass
class SourceGap:
    key: SeriesKey
    start_ms: int
    end_ms: int
    expected: set[int]
    future: asyncio.Future
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    detected_at: float = field(default_factory=time.monotonic)
    repaired: dict[int, BarData] = field(default_factory=dict)
    completed_at: float | None = None
    error: str | None = None

    def event(self, resolved: bool = False) -> DataEvent:
        return DataEvent(
            DataEventType.SOURCE_GAP_RESOLVED if resolved else DataEventType.SOURCE_GAP,
            self.key,
            detail={
                "gap_id": self.id, "range_start_ms": self.start_ms,
                "range_end_ms": self.end_ms,
                "state": "resolved" if resolved else "failed" if self.error else "recovering",
                "missing_bars": len(self.expected - self.repaired.keys()),
                "error": self.error,
            },
        )

    def fail(self, reason: str) -> None:
        self.error = reason
        if not self.future.done():
            self.future.set_result(None)


class SourceGapRegistry:
    def __init__(self, *, max_gaps: int = 256, max_bars: int = 10_000) -> None:
        self.max_gaps, self.max_bars = max_gaps, max_bars
        self.gaps: OrderedDict[str, SourceGap] = OrderedDict()
        self.overflowed = False

    def pending(self, key: SeriesKey | None = None) -> list[SourceGap]:
        return [gap for gap in self.gaps.values()
                if gap.completed_at is None and (key is None or gap.key == key)]

    def open(self, key: SeriesKey, start_ms: int, end_ms: int,
             expected_opens: tuple[int, ...] | None = None) -> tuple[SourceGap, bool]:
        for gap in self.pending(key):
            if (gap.start_ms, gap.end_ms) == (start_ms, end_ms):
                return gap, False
        expected: set[int] = set()
        spec = parse_interval_spec(key.interval)
        if spec is None:
            raise ValueError(f"unsupported continuity interval: {key.interval}")
        calendar = native_kline_calendar(key.exchange, key.market_type, key.interval)
        cursor = start_ms
        while expected_opens is None and cursor <= end_ms and len(expected) <= self.max_bars:
            expected.add(cursor)
            following = (calendar.next_expected_open(cursor, key.interval)
                         if calendar is not None else spec.next_ms(cursor))
            if following is None:
                break
            if following <= cursor:
                raise ValueError("continuity calendar must advance")
            cursor = following
        if expected_opens is not None:
            expected = set(expected_opens[:self.max_bars + 1])
        gap = SourceGap(key, start_ms, end_ms, expected, asyncio.get_running_loop().create_future())
        if len(expected) > self.max_bars:
            gap.expected.clear()
            gap.fail("source_gap_exceeds_replay_limit")
        self.gaps[gap.id] = gap
        while (len(self.gaps) > self.max_gaps
               or sum(len(item.expected) for item in self.gaps.values()) > self.max_bars):
            _, evicted = self.gaps.popitem(last=False)
            evicted.fail("source_gap_history_exhausted")
            if evicted.completed_at is None:
                self.overflowed = True
        if self.overflowed:
            for pending in self.pending():
                pending.fail("source_gap_tracking_exhausted")
        return gap, True

    def retire(self, key: SeriesKey) -> None:
        for gap_id, gap in list(self.gaps.items()):
            if gap.key == key:
                gap.fail("source_stream_restarted")
                del self.gaps[gap_id]

    def snapshot(self) -> dict:
        return {"tracking_exhausted": self.overflowed, "retained_gaps": len(self.gaps),
                "pending": [gap.event().to_dict() for gap in self.pending()]}

    def initial_events(self, key: SeriesKey | None) -> tuple[DataEvent, ...]:
        events = []
        for gap in self.pending(key):
            event = gap.event()
            event.detail["requires_snapshot"] = True
            events.append(event)
        return tuple(events)

    def accept(self, key: SeriesKey, bars: list[BarData]) -> tuple[list[SourceGap], list[tuple[BarData, list[str]]]]:
        resolved: list[SourceGap] = []
        corrections: list[tuple[BarData, list[str]]] = []
        pending = self.pending(key)
        for bar in bars:
            if not bar.is_closed or not bar.trusted_final:
                continue
            opened = int(bar.time) * 1000
            ids = []
            for gap in pending:
                if gap.error or opened not in gap.expected or opened in gap.repaired:
                    continue
                gap.repaired[opened] = deepcopy(bar)
                ids.append(gap.id)
            if ids:
                corrections.append((bar, ids))
        for gap in pending:
            if not gap.error and gap.expected and gap.expected <= gap.repaired.keys():
                gap.completed_at = time.monotonic()
                gap.future.set_result(None)
                resolved.append(gap)
        return resolved, corrections

    def close(self) -> None:
        for gap in self.pending():
            gap.fail("source_stream_closed")
        self.gaps.clear()


class ContinuityConsumer:
    """Adapter inside one bounded callback worker or iterator."""

    def __init__(self, registry: SourceGapRegistry, policy: ContinuityPolicy,
                 event_types: set[DataEventType] | None) -> None:
        self.registry, self.policy = registry, policy
        self.event_types = frozenset(event_types) if event_types is not None else None
        self.handled: OrderedDict[str, None] = OrderedDict()
        self.replayed_through: dict[SeriesKey, int] = {}
        self.terminal = asyncio.Event()
        self.error: ConsumerRecoveryRequired | None = None

    def fail(self, error: ConsumerRecoveryRequired) -> None:
        self.error = error
        self.terminal.set()

    def wants(self, event: DataEvent) -> bool:
        return (self.event_types is None or event.event_type in self.event_types
                or (self.policy.mode == "gap_aware" and event.event_type in CONTROLS))

    async def events(self, event: DataEvent) -> AsyncIterator[DataEvent]:
        if self.error is not None:
            raise self.error
        if self.registry.overflowed and self.policy.mode == "strict":
            raise ConsumerRecoveryRequired("source_gap_tracking_exhausted")
        if event.event_type == DataEventType.SOURCE_GAP and self.policy.mode == "strict":
            gap_id = str(event.detail["gap_id"])
            if gap_id in self.handled:
                return
            gap = self.registry.gaps.get(gap_id)
            if gap is None:
                raise ConsumerRecoveryRequired("source_gap_history_exhausted")
            if self.wants(event):
                yield event
            deadline = gap.detected_at + self.policy.max_wait_seconds
            remaining = deadline - time.monotonic()
            if not gap.future.done() and remaining > 0:
                terminal = asyncio.create_task(self.terminal.wait())
                try:
                    await asyncio.wait({gap.future, terminal}, timeout=remaining,
                                       return_when=asyncio.FIRST_COMPLETED)
                finally:
                    terminal.cancel()
                    await asyncio.gather(terminal, return_exceptions=True)
            if self.error is not None:
                raise self.error
            if gap.error:
                raise ConsumerRecoveryRequired(gap.error)
            if gap.completed_at is None or gap.completed_at > deadline:
                raise ConsumerRecoveryRequired("source_gap_timeout")
            if event.detail.get("requires_snapshot"):
                raise ConsumerRecoveryRequired("source_gap_snapshot_required")
            self.handled[gap_id] = None
            while len(self.handled) > self.registry.max_gaps:
                self.handled.popitem(last=False)
            if gap.key not in self.replayed_through and len(self.replayed_through) >= self.registry.max_gaps:
                raise ConsumerRecoveryRequired("source_gap_history_exhausted")
            for opened, bar in sorted(gap.repaired.items()):
                if int(bar.time) <= self.replayed_through.get(gap.key, -1):
                    continue
                replay = DataEvent(DataEventType.BAR_CLOSED, gap.key, deepcopy(bar), detail={
                    "source_gap_id": gap_id, "continuity_replayed": True,
                    "original_open_time_ms": opened,
                })
                self.replayed_through[gap.key] = int(bar.time)
                if self.wants(replay):
                    yield replay
            return
        if self.policy.mode == "strict":
            if any(gap_id in self.handled for gap_id in event.detail.get("source_gap_ids", [])):
                return
            if (event.bar is not None and event.event_type in {
                    DataEventType.BAR_CREATED, DataEventType.BAR_UPDATED, DataEventType.BAR_CLOSED}
                    and int(event.bar.time) <= self.replayed_through.get(event.key, -1)):
                if event.event_type == DataEventType.BAR_CLOSED and not any(
                    gap.key == event.key and int(event.bar.time) * 1000 in gap.repaired
                    for gap_id in self.handled
                    if (gap := self.registry.gaps.get(gap_id)) is not None
                ):
                    # A deferred durable receipt can arrive behind the repair
                    # control. It is not a duplicate of a repaired missing bar;
                    # never silently discard it or deliver a regressing close.
                    raise ConsumerRecoveryRequired("source_delivery_reordered")
                return
            if event.bar is not None and event.detail.get("source_continuity", {}).get("state") == "gapped":
                # These events were received while waiting, not fresh signals
                # at the instant the backlog is finally delivered.
                event = replace(event, detail={**event.detail, "continuity_replayed": True})
        if self.wants(event):
            yield event
