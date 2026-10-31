"""Bounded, full-series snapshot/stream watermarks (wire protocol v1).

Sequence counts accepted publication attempts; barrier counts non-replaceable
facts. Forming updates may be coalesced, but a lost close/correction cannot be
hidden by a later forming update. This is a delivery clock, not source rank.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
import threading
import uuid

from app.data_engine.interval_policy import parse_interval_spec
from .models import DataEvent, DataEventType, SeriesKey


@dataclass
class _Cursor:
    generation: int
    sequence: int = 0
    barrier: int = 0
    pending: int = 0
    observed_at_ms: int = 0


class StreamVersionClock:
    def __init__(self, capacity: int = 4096) -> None:
        self.epoch = uuid.uuid4().hex
        self._capacity = max(1, capacity)
        self._generation = 0
        self._entries: OrderedDict[SeriesKey, _Cursor] = OrderedDict()
        self._lock = threading.RLock()

    def _entry(self, key: SeriesKey) -> _Cursor:
        cursor = self._entries.get(key)
        if cursor is None:
            self._generation += 1
            cursor = _Cursor(self._generation)
            self._entries[key] = cursor
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
        return cursor

    def invalidate(self, key: SeriesKey) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self.epoch = uuid.uuid4().hex
            self._entries.clear()

    def snapshot(self, key: SeriesKey) -> dict:
        with self._lock:
            cursor = self._entry(key)
            return {"protocol": 1, "epoch": self.epoch,
                    "generation": cursor.generation, "sequence": cursor.sequence,
                    "barrier": cursor.barrier, "series": asdict(key),
                    "observed_at_ms": cursor.observed_at_ms, "stable": cursor.pending == 0}

    def begin(self, event: DataEvent) -> tuple[SeriesKey, _Cursor] | None:
        if event.event_type not in {
            DataEventType.BAR_CREATED, DataEventType.BAR_UPDATED,
            DataEventType.BAR_CLOSED, DataEventType.BAR_AMENDED,
            DataEventType.BACKFILL_COMPLETED,
        }:
            return None
        with self._lock:
            cursor = self._entry(event.key)
            cursor.sequence += 1
            if event.event_type != DataEventType.BAR_UPDATED:
                cursor.barrier += 1
            cursor.pending += 1
            if event.bar is not None:
                cursor.observed_at_ms = event.timestamp_ms
            version = self.snapshot(event.key)
            version.pop("stable")
            event.detail = {**event.detail, "stream_version": version}
            if event.bar is not None:
                start = int(event.bar.time * 1000)
                # Calendar arithmetic belongs here. Other session calendars
                # deliberately receive no automatic coverage-extension proof.
                spec = parse_interval_spec(event.key.interval)
                previous = (spec.previous_ms(start) if spec is not None
                            and event.key.asset_class == "crypto"
                            and event.key.session_variant == "continuous" else None)
                event.detail["affected_range"] = {"from_ms": start, "to_ms": start}
                event.detail["previous_open_ms"] = previous
            else:
                detail = event.detail
                start = detail.get("range_start_ms", detail.get("request_start_ms"))
                end = detail.get("range_end_ms", detail.get("request_end_ms"))
                if start is None and isinstance(detail.get("earliest"), (int, float)):
                    start = int(detail["earliest"] * 1000)
                if end is None and isinstance(detail.get("latest"), (int, float)):
                    end = int(detail["latest"] * 1000)
                event.detail["affected_range"] = {"from_ms": start, "to_ms": end}
                if start is not None and end is not None:
                    event.detail.setdefault("range_start_ms", start)
                    event.detail.setdefault("range_end_ms", end)
            return event.key, cursor

    def finish(self, ticket: tuple[SeriesKey, _Cursor] | None) -> None:
        if ticket is not None:
            with self._lock:
                ticket[1].pending -= 1

    def finish_snapshot(self, key: SeriesKey, before: dict, *, final_only: bool = False) -> dict:
        after = self.snapshot(key)
        same_barrier = all(before[name] == after[name] for name in ("epoch", "generation", "barrier"))
        stable = before["stable"] and after["stable"] and same_barrier and (final_only or before == after)
        return {**before, "stable": stable}
