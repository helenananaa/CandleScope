"""Source slots of one source interval: what is wanted, by whom, and what is still missing (§3.2).

Every range here is half-open ``[start_ms, end_ms)`` on the source grid. A
demand's target range is converted to source slots before it arrives, so the
89m and 97m charts of a symbol both land on the same 1m slots and their
overlap is fetched once.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import dataclass

from .demands import DemandOwner


class IntervalSet:
    """Disjoint, sorted half-open ranges; adjacent ranges are joined."""

    __slots__ = ("_starts", "_ends")

    def __init__(self, ranges: Iterable[tuple[int, int]] = ()) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []
        for start, end in ranges:
            self.add(start, end)

    def __iter__(self):
        return iter(zip(self._starts, self._ends))

    def __bool__(self) -> bool:
        return bool(self._starts)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, IntervalSet) and list(self) == list(other)

    def __repr__(self) -> str:
        return f"IntervalSet({list(self)!r})"

    @property
    def total(self) -> int:
        return sum(end - start for start, end in self)

    def add(self, start: int, end: int) -> None:
        if start >= end:
            return
        left = bisect_left(self._ends, start)     # first range that ends at or after start
        right = bisect_right(self._starts, end)   # ranges starting at or before end
        if left < right:
            start = min(start, self._starts[left])
            end = max(end, self._ends[right - 1])
        self._starts[left:right] = [start]
        self._ends[left:right] = [end]

    def remove(self, start: int, end: int) -> None:
        if start >= end:
            return
        left = bisect_right(self._ends, start)    # first range that ends after start
        right = bisect_left(self._starts, end)    # ranges starting before end
        if left >= right:
            return
        keep_starts, keep_ends = [], []
        if self._starts[left] < start:
            keep_starts.append(self._starts[left])
            keep_ends.append(start)
        if self._ends[right - 1] > end:
            keep_starts.append(end)
            keep_ends.append(self._ends[right - 1])
        self._starts[left:right] = keep_starts
        self._ends[left:right] = keep_ends

    def covers(self, start: int, end: int) -> bool:
        index = bisect_right(self._starts, start) - 1
        return index >= 0 and self._ends[index] >= end

    def overlaps(self, start: int, end: int) -> bool:
        index = bisect_right(self._ends, start)
        return index < len(self._starts) and self._starts[index] < end

    def minus(self, start: int, end: int) -> list[tuple[int, int]]:
        """The parts of ``[start, end)`` not in this set."""
        out, cursor = [], start
        index = bisect_right(self._ends, start)
        while cursor < end and index < len(self._starts) and self._starts[index] < end:
            if self._starts[index] > cursor:
                out.append((cursor, self._starts[index]))
            cursor = max(cursor, self._ends[index])
            index += 1
        if cursor < end:
            out.append((cursor, end))
        return out


@dataclass(frozen=True, slots=True)
class Segment:
    """Contiguous missing source slots with one urgency and the owners who want them."""

    start_ms: int
    end_ms: int
    urgency: int
    owners: frozenset[DemandOwner]


class SlotMap:
    """Wanted, present, in-flight and handed-back slots of one source grid."""

    def __init__(self, interval: str, width_ms: int) -> None:
        if type(width_ms) is not int or width_ms <= 0:
            raise ValueError("positive source width required")
        self.interval = interval
        self.width_ms = width_ms
        self._wanted: dict[object, tuple[int, int, int, DemandOwner]] = {}
        self.present = IntervalSet()
        self.in_flight = IntervalSet()
        self.handed_back = IntervalSet()

    def align(self, start: int, end: int) -> tuple[int, int]:
        """The source slots a time range touches: floor the start, ceil the end."""
        width = self.width_ms
        return start - start % width, end + (-end) % width

    def want(self, key: object, owner: DemandOwner, start: int, end: int, urgency: int) -> bool:
        """Record one demand's source range; return whether anything changed."""
        start, end = self.align(start, end)
        entry = (start, end, urgency, owner)
        if start >= end:
            return self._wanted.pop(key, None) is not None
        if self._wanted.get(key) == entry:
            return False
        self._wanted[key] = entry
        return True

    def unwant(self, key: object) -> bool:
        return self._wanted.pop(key, None) is not None

    def keys_for(self, owner: DemandOwner) -> list[object]:
        return [key for key, entry in self._wanted.items() if entry[3] == owner]

    @property
    def wanted_count(self) -> int:
        return len(self._wanted)

    def owners_over(self, start: int, end: int) -> frozenset[DemandOwner]:
        return frozenset(owner for first, last, _, owner in self._wanted.values() if first < end and start < last)

    def missing(self) -> list[Segment]:
        """Wanted slots that are not present, in flight or handed back, by urgency and owners.

        A sweep over the demand bounds: each elementary range takes the most
        urgent demand covering it and the union of its owners. Adjacent ranges
        with the same urgency are joined (their owners merged).
        """
        if not self._wanted:
            return []
        bounds = sorted({value for first, last, _, _ in self._wanted.values() for value in (first, last)})
        segments: list[Segment] = []
        for start, end in zip(bounds, bounds[1:]):
            covering = [(urgency, owner) for first, last, urgency, owner in self._wanted.values()
                        if first <= start and end <= last]
            if not covering:
                continue
            urgency = min(item[0] for item in covering)
            owners = frozenset(item[1] for item in covering)
            for piece_start, piece_end in self._unavailable_minus(start, end):
                last = segments[-1] if segments else None
                if last is not None and last.end_ms == piece_start and last.urgency == urgency:
                    segments[-1] = Segment(last.start_ms, piece_end, urgency, last.owners | owners)
                else:
                    segments.append(Segment(piece_start, piece_end, urgency, owners))
        return segments

    def _unavailable_minus(self, start: int, end: int) -> list[tuple[int, int]]:
        ranges = [(start, end)]
        for excluded in (self.present, self.in_flight, self.handed_back):
            ranges = [part for first, last in ranges for part in excluded.minus(first, last)]
        return ranges
