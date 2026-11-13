"""Bounded selected-source window receipts, distinct from canonical revisions.

These values grant no publication or deletion permission. The caller still
owns source/storage binding, target generation, and durable-commit fences.
"""
from dataclasses import dataclass
from typing import Any

MAX_SOURCE_WINDOW_ROWS = 65536
MAX_SOURCE_PAGE_ROWS = 128
MAX_SOURCE_DATA_BYTES = 8192


@dataclass(frozen=True, slots=True)
class SourceWindowVersion:
    series: str
    start_ms: int
    through_ms: int
    source_width_ms: int
    closed_count: int
    revision_sum: int
    acquisition_revision: int

    def __post_init__(self):
        if (not isinstance(self.series,str) or not 0<len(self.series)<=1024
                or any(type(v) is not int for v in (self.start_ms,self.through_ms,
                    self.source_width_ms,self.closed_count,self.revision_sum,self.acquisition_revision))
                or not 0<=self.start_ms<self.through_ms<2**63
                or self.source_width_ms<=0 or (self.through_ms-self.start_ms)%self.source_width_ms
                or not 0<=self.closed_count<=(self.through_ms-self.start_ms)//self.source_width_ms<=MAX_SOURCE_WINDOW_ROWS
                or self.revision_sum<self.closed_count or self.acquisition_revision<0
                or (self.closed_count==0 and self.revision_sum!=0)):
            raise ValueError('bounded selected-source version required')


@dataclass(frozen=True, slots=True)
class SourceWindowPage:
    version: SourceWindowVersion
    position_ms: int
    next_position_ms: int | None
    components: tuple[Any, ...]
