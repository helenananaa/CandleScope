"""129-A: owner-private prefix summaries plus one replaceable tail.

Ordinary tail replacement is constant work. Appends fold a binary prefix
forest (logarithmic work and metadata); old corrections and insertions rebuild
from the owner's accepted snapshots. K130 still owns fields and finality.
No cache, source admission, durable revisions, scheduling or I/O lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any
from app.data_engine.aggregation.source_window import SourceWindowVersion

from app.data_engine.aggregation.adapters import snapshot_aggregation_values, snapshot_field_summary
from app.data_engine.aggregation.semantics import (
    ClosePolicy, FieldSummary, combine_fields, evaluate_coverage, sum_additive,
)

# Bounds additional metadata, not source history. Larger buckets use the
# existing batch path without truncating their composition or correction range.
MAX_COMPONENTS = 65_536
ENHANCED = ('quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote')


@dataclass(frozen=True, slots=True)
class _Summary:
    values: FieldSummary
    raw_enhanced: tuple
    first: int
    last: int
    end: int
    contiguous: bool
    positive: bool
    all_closed: bool
    last_closed: bool
    count: int

    @classmethod
    def history(cls, prefix):
        """Project H127's canonical closed components, retaining gap evidence."""
        summary = prefix.summary
        ranges = summary.coverage.ranges
        if (not ranges or not summary.all_authoritative or not summary.revisions_known
                or ranges[0][0] < prefix.start_ms or ranges[-1][1] > prefix.through_ms):
            raise ValueError('history prefix requires bounded canonical closed components')
        return cls(summary.values, tuple(getattr(summary.values, f) for f in ENHANCED),
                   ranges[0][0], ranges[-1][1] - prefix.source_width_ms,
                   ranges[-1][1], len(ranges) == 1, True, True, True, summary.coverage.count)

    @classmethod
    def leaf(cls, row):
        start, end = int(row['open_time_ms']), int(row['close_time_ms']) + 1
        values = row.get('aggregation_values')
        if values is None:
            values = snapshot_aggregation_values(row)
        return cls(FieldSummary(*values), tuple(row[f] for f in ENHANCED),
                   start, start, end, True, start < end,
                   bool(row['is_closed']), bool(row['is_closed']), 1)

    def coverage(self, start, end):
        return evaluate_coverage(
            has_components=True, starts_at_boundary=self.first == start,
            contiguous=self.contiguous, reaches_end=self.end == end,
            within_bounds=self.positive and self.first >= start and self.end <= end,
            all_closed=self.all_closed, last_closed=self.last_closed,
            close_policy=ClosePolicy.EXPLICIT,
        )

    @classmethod
    def batch(cls, rows):
        """Rebuild an immutable prefix run using K130's batch primitive.

        A correction must not pay one Python combine/allocation per historical
        leaf. Only the O(log n) forest runs are retained after this scan.
        """
        values = snapshot_field_summary(rows)
        raw = tuple(getattr(values, name) if getattr(values, name) is not None else
                    sum_additive((row[name] for row in rows), integer=name == 'trades')
                    for name in ENHANCED)
        previous_end = None
        contiguous = positive = all_closed = True
        for row in rows:
            start, end = int(row['open_time_ms']), int(row['close_time_ms']) + 1
            positive = positive and start < end
            contiguous = contiguous and (previous_end is None or previous_end == start)
            all_closed = all_closed and bool(row['is_closed'])
            previous_end = end
        return cls(values, raw, int(rows[0]['open_time_ms']), int(rows[-1]['open_time_ms']),
                   previous_end, contiguous, positive, all_closed, bool(rows[-1]['is_closed']), len(rows))


def _combine(left, right):
    if left is None:
        return right
    if right is None:
        return left
    return _Summary(
        combine_fields((left.values, right.values)),
        tuple(sum_additive((a, b), integer=i == 1)
              for i, (a, b) in enumerate(zip(left.raw_enhanced, right.raw_enhanced))),
        left.first, right.last, right.end,
        left.contiguous and right.contiguous and left.end == right.first,
        left.positive and right.positive,
        left.all_closed and right.all_closed, right.last_closed,
        left.count + right.count,
    )


@dataclass(slots=True)
class ComponentAccumulator:
    prefixes: list[_Summary | None] = field(default_factory=list)
    prefix: _Summary | None = None
    tail: _Summary | None = None
    result: _Summary | None = None
    tail_key: str = ''
    tail_snapshot: Mapping | None = None
    container_id: int = 0
    count: int = 0
    tail_unique: bool = True
    appends: int = 0
    tail_replacements: int = 0
    rebuilds: int = 0
    rebuilt_components: int = 0

    def current(self, snapshots):
        return (self.container_id == id(snapshots) and self.count == len(snapshots)
                and snapshots.get(self.tail_key) is self.tail_snapshot)

    def _append_prefix(self, part):
        level = 0
        while level < len(self.prefixes) and self.prefixes[level] is not None:
            part = _combine(self.prefixes[level], part)
            self.prefixes[level] = None
            level += 1
        if level == len(self.prefixes):
            self.prefixes.append(part)
        else:
            self.prefixes[level] = part

    def _refresh_prefix(self):
        self.prefix = None
        # Large older runs precede smaller newer runs.
        for part in reversed(self.prefixes):
            self.prefix = _combine(self.prefix, part)

    def update(self, snapshots, key, previous):
        """Called only after the sole state owner accepts one replacement."""
        row = snapshots[key]
        shape_ok = (self.container_id == id(snapshots)
                    and len(snapshots) == self.count + int(previous is None))
        if (shape_ok and self.tail_unique and key == self.tail_key
                and previous is self.tail_snapshot
                and row['open_time_ms'] == self.tail.last
                and row['close_time_ms'] + 1 == self.tail.end):
            self.tail = _Summary.leaf(row)
            self.tail_replacements += 1
        elif (shape_ok and previous is None and self.tail is not None
              and snapshots.get(self.tail_key) is self.tail_snapshot
              and row['open_time_ms'] > self.tail.last):
            self._append_prefix(self.tail)
            self._refresh_prefix()
            self.tail = _Summary.leaf(row)
            self.tail_unique = True
            self.appends += 1
        else:
            def order(key):
                value = snapshots[key]
                return (int(value['open_time_ms']), int(value['close_time_ms']),
                        int(value['sequence']) if value.get('sequence') is not None else -1)
            ordered = sorted(snapshots, key=order)
            prefix_count = len(ordered) - 1
            self.prefixes = [None] * prefix_count.bit_length()
            cursor = 0
            for level in reversed(range(len(self.prefixes))):
                size = 1 << level
                if prefix_count & size:
                    self.prefixes[level] = _Summary.batch([snapshots[k] for k in ordered[cursor:cursor + size]])
                    cursor += size
            self._refresh_prefix()
            key = ordered[-1]
            row = snapshots[key]
            self.tail = _Summary.leaf(row)
            self.tail_unique = len(ordered) == 1 or snapshots[ordered[-2]]['open_time_ms'] < row['open_time_ms']
            self.rebuilds += 1
            self.rebuilt_components += len(ordered)
        self.tail_key, self.tail_snapshot = key, row
        self.container_id, self.count = id(snapshots), len(snapshots)
        self.result = _combine(self.prefix, self.tail)
        return self.result

    def snapshot(self):
        nodes = sum(part is not None for part in self.prefixes) + 3
        return dict(appends=self.appends, tail_replacements=self.tail_replacements,
                    rebuilds=self.rebuilds, rebuilt_components=self.rebuilt_components,
                    prefix_levels=len(self.prefixes), summary_nodes=nodes,
                    estimated_bytes=2048 + nodes * 1024)


@dataclass(frozen=True, slots=True)
class SourceWindowSummary:
    """Closed runs, with exact holes; never a canonical H127 prefix.

    One incoming component is excluded from these runs and remains in the
    existing replaceable leaf index. Runs can surround an interior forming
    leaf, so combining all runs before the overlay would be incorrect.
    """
    version: SourceWindowVersion
    parts: tuple[Any, ...]
    excluded_open_ms: int
    pages: int
    estimated_bytes: int
    binding: Any = None
    capabilities: frozenset[str] = frozenset()

    def covers(self, opened):
        return any(part.first <= opened < part.end for part in self.parts)

    def merge(self, rows):
        parts = [*self.parts, *(_Summary.leaf(row) for row in rows)]
        parts.sort(key=lambda part: part.first)
        result = None
        for part in parts:
            if result is not None and result.end > part.first:
                raise ValueError('selected-source runs overlap live components')
            result = _combine(result, part)
        return result
