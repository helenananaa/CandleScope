"""Immutable bounded history handoff contract shared by readers and live owners."""
from dataclasses import dataclass
from .blocks import BlockUnavailable
from .core import AggregateSummary

MAX_PREFIX_ROWS = 65_536
PREFIX_BYTES = 32 * 1024


class EmptyHistoryPrefix(BlockUnavailable):
    """Qualified canonical range contains no accepted candle; never a zero bar."""


@dataclass(frozen=True, slots=True)
class HistoryPrefix:
    summary: AggregateSummary
    start_ms: int
    through_ms: int
    source_width_ms: int
    pages: int
    storage_rows: int
    cache_hits: int
    acquisition_revision: int = 0
    binding: tuple[int, int, int] = ()

    @property
    def complete(self):
        return self.summary.is_authoritative(self.start_ms, self.through_ms)


