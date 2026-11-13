"""Bounded selected-source window receipts, distinct from canonical revisions.

These values grant no publication or deletion permission. The caller still
owns source/storage binding, target generation, and durable-commit fences.
"""
from dataclasses import dataclass
from typing import Any

MAX_SOURCE_WINDOW_ROWS = 65536
MAX_SOURCE_PAGE_ROWS = 128
MAX_SOURCE_DATA_BYTES = 8192
MAX_SOURCE_SUMMARY_PARTS = 32
SOURCE_SUMMARY_BYTES = 32 * 1024


@dataclass(frozen=True, slots=True)
class SourceWindowVersion:
    series: str
    start_ms: int
    through_ms: int
    source_width_ms: int
    closed_count: int
    revision_sum: int
    acquisition_revision: int
    permission_floor: int = 0

    def __post_init__(self):
        if (not isinstance(self.series,str) or not 0<len(self.series)<=1024
                or any(type(v) is not int for v in (self.start_ms,self.through_ms,
                    self.source_width_ms,self.closed_count,self.revision_sum,self.acquisition_revision,self.permission_floor))
                or not 0<=self.start_ms<self.through_ms<2**63
                or self.source_width_ms<=0 or (self.through_ms-self.start_ms)%self.source_width_ms
                or not 0<=self.closed_count<=(self.through_ms-self.start_ms)//self.source_width_ms<=MAX_SOURCE_WINDOW_ROWS
                or self.revision_sum<self.closed_count or not 0<=self.permission_floor<=self.acquisition_revision
                or (self.closed_count==0 and self.revision_sum!=0)):
            raise ValueError('bounded selected-source version required')


@dataclass(frozen=True, slots=True)
class SourceWindowPage:
    version: SourceWindowVersion
    position_ms: int
    next_position_ms: int | None
    components: tuple[Any, ...]


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

    def covers(self, opened):
        return any(part.first <= opened < part.end for part in self.parts)

    def merge(self, rows):
        from app.data_engine.bar_aggregator.component_accumulator import _Summary, _combine
        parts = [*self.parts, *(_Summary.leaf(row) for row in rows)]
        parts.sort(key=lambda part: part.first)
        result = None
        for part in parts:
            if result is not None and result.end > part.first:
                raise ValueError('selected-source runs overlap live components')
            result = _combine(result, part)
        return result
