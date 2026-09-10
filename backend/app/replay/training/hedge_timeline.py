"""Immutable HEDGE input lanes indexed by their authoritative cursor/time."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import cached_property
from types import MappingProxyType
from typing import Any, Mapping

from ..broker.interval_index import PriceRangeIndex


def event_key(event):
    return (
        event.event_time_ms,
        event.event_phase,
        event.stable_track_id,
        event.event_sequence,
    )


@dataclass(frozen=True)
class InputLane:
    source_kind: str
    track_id: str | None
    events: tuple[Any, ...]
    sequences: tuple[int, ...]
    times: tuple[int, ...]
    mark_sequences: tuple[int, ...]
    marks: tuple[Decimal, ...]
    mark_run_ends: tuple[int, ...]

    @cached_property
    def price_index(self) -> PriceRangeIndex:
        # A non-price event is an unconditional boundary. Build lazily so the
        # constant-mark lane does not pay for an unused general envelope tree.
        return PriceRangeIndex(
            tuple(
                (Decimal(str(e.payload["mark_price"])),) * 2
                if self.source_kind == "PUBLIC"
                and e.event_kind == "MARK_INDEX"
                and e.event_phase == 30
                else (Decimal("-Infinity"), Decimal("Infinity"))
                for e in self.events
            )
        )

    @classmethod
    def build(cls, kind, track_id, values):
        events = tuple(values)
        sequences = tuple(e.event_sequence for e in events)
        times = tuple(e.event_time_ms for e in events)
        if any(a >= b for a, b in zip(sequences, sequences[1:])) or any(
            a > b for a, b in zip(times, times[1:])
        ):
            raise ValueError("HEDGE input lane is not monotone")
        prices = tuple(
            Decimal(str(e.payload["mark_price"]))
            if kind == "PUBLIC" and e.event_kind == "MARK_INDEX" and e.event_phase == 30
            else None
            for e in events
        )
        ends = list(range(1, len(events) + 1))
        for i in range(len(events) - 2, -1, -1):
            if prices[i] is not None and prices[i] == prices[i + 1]:
                ends[i] = ends[i + 1]
        return cls(
            kind,
            track_id,
            events,
            sequences,
            times,
            tuple(e.event_sequence for e, p in zip(events, prices) if p is not None),
            tuple(p for p in prices if p is not None),
            tuple(ends),
        )

    def cursor(self, public: Mapping[str, int], simulation: int) -> int:
        return (
            public.get(self.track_id, 0)
            if self.source_kind == "PUBLIC" and self.track_id is not None
            else simulation
        )

    def span(self, cursor: int, target: int, *, exact: bool = False):
        start = bisect_right(self.sequences, cursor)
        if exact:
            start = max(start, bisect_left(self.times, target))
        end = bisect_right(self.times, target)
        return self.events[start : max(start, end)]


class IndexedHedgeSnapshot(tuple):
    """Keep the existing two-tuple contract while indexing verified inputs once."""

    def __new__(cls, public, simulation):
        # MARK_INDEX payloads are schema-validated scalar objects. Own and
        # freeze them so caller mutation cannot invalidate the price-run index.
        owned_public = tuple(
            replace(event, payload=MappingProxyType(dict(event.payload)))
            if event.event_kind == "MARK_INDEX"
            else event
            for event in public
        )
        result = super().__new__(cls, (owned_public, tuple(simulation)))
        groups = {}
        for event in result[0]:
            groups.setdefault(event.track_id, []).append(event)
        result.lanes = tuple(
            InputLane.build("PUBLIC", track, events) for track, events in groups.items()
        ) + (InputLane.build("SIMULATION", None, result[1]),)
        return result

    def events_through(self, public, simulation, target, *, exact=False):
        return tuple(
            sorted(
                (
                    event
                    for lane in self.lanes
                    for event in lane.span(
                        lane.cursor(public, simulation), target, exact=exact
                    )
                ),
                key=event_key,
            )
        )

    def next_time(self, public, simulation, target):
        times = []
        for lane in self.lanes:
            if lane.source_kind == "PUBLIC" and lane.track_id is None:
                continue
            i = bisect_right(lane.sequences, lane.cursor(public, simulation))
            if i < len(lane.events) and lane.times[i] <= target:
                times.append(lane.times[i])
        return min(times) if times else None

    def stable_mark_prefix(self, public, simulation, track_id, target):
        """Return the current mark and inclusive bound before any input change."""
        lane = next(
            (
                lane
                for lane in self.lanes
                if lane.source_kind == "PUBLIC" and lane.track_id == track_id
            ),
            None,
        )
        if lane is None:
            return None
        cursor = lane.cursor(public, simulation)
        if lane.sequences and cursor > lane.sequences[-1]:
            return None
        mark_index = bisect_right(lane.mark_sequences, cursor) - 1
        if mark_index < 0:
            return None
        mark = lane.marks[mark_index]
        end = target
        for candidate in self.lanes:
            i = bisect_right(candidate.sequences, candidate.cursor(public, simulation))
            if i >= len(candidate.events):
                continue
            event = candidate.events[i]
            if (
                candidate is lane
                and event.event_kind == "MARK_INDEX"
                and event.event_phase == 30
                and Decimal(str(event.payload["mark_price"])) == mark
            ):
                i = candidate.mark_run_ends[i]
            if i < len(candidate.events):
                end = min(end, candidate.times[i] - 1)
        return mark, end

    def mark_envelope_prefix(self, public, simulation, track_id, target, *, low, high):
        """Bound a caller-certified envelope by the first price or input event.

        This is a screen, not a risk certificate: its caller must establish
        account safety for every price inside the supplied inclusive envelope.
        """
        lane = next(
            (
                item
                for item in self.lanes
                if item.source_kind == "PUBLIC" and item.track_id == track_id
            ),
            None,
        )
        if lane is None:
            return None
        cursor = lane.cursor(public, simulation)
        mark_index = bisect_right(lane.mark_sequences, cursor) - 1
        if mark_index < 0 or cursor > lane.sequences[-1]:
            return None
        mark = lane.marks[mark_index]
        if not low <= mark <= high:
            return None
        end = target
        for candidate in self.lanes:
            start = bisect_right(
                candidate.sequences, candidate.cursor(public, simulation)
            )
            stop = bisect_right(candidate.times, target)
            if start >= stop:
                continue
            first = (
                candidate.price_index.first_outside(low, high, start=start, end=stop)
                if candidate is lane
                else start
            )
            if first < stop:
                end = min(end, candidate.times[first] - 1)
        return mark, end
