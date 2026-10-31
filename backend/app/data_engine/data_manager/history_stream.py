"""Bounded reduction of newest-to-oldest source pages for fixed intervals."""
from __future__ import annotations

from collections.abc import Callable

from app.data_engine.kline_quality import source_rank

from .models import BarData


class StreamingOrderError(ValueError):
    """An older page revises a bucket already reduced by this reader."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.read_metrics: dict[str, int | float] = {}


class FixedHistoryStream:
    """Keep one cross-page bucket, reducing the rest before the next read.

    Components are still summed in chronological order by the canonical
    reducer. Keeping one bucket avoids changing Python's float summation or
    enhanced-field normalization when pages arrive in reverse time order.
    No target is persisted here: the caller owns quality checks and writes.
    """

    def __init__(
        self,
        width_seconds: int,
        reduce: Callable[[list[BarData]], list[BarData]],
        *,
        lower_bound_ms: int | None = None,
        upper_bound_ms: int | None = None,
        phase_seconds: int = 0,
    ) -> None:
        self.width_seconds = width_seconds
        self.phase_seconds = phase_seconds
        self.reduce = reduce
        self.lower_bound_ms = lower_bound_ms
        self.upper_bound_ms = upper_bound_ms
        self.pending: dict[int, BarData] = {}
        self.targets_desc: list[BarData] = []
        self.unique_rows = 0
        self.aggregated_rows = 0
        self.peak_buffered_rows = 0
        self.oldest_ms: int | None = None
        self._oldest_bucket: int | None = None

    def push(self, bars: list[BarData]) -> None:
        # Validate the entire page before changing state. Inclusive overlaps
        # within the held bucket are safe; a revision to a flushed bucket
        # requires the caller's bounded legacy fallback, not double counting.
        if self._oldest_bucket is not None and any(
            self._bucket(bar.time) > self._oldest_bucket for bar in bars
        ):
            raise StreamingOrderError("older page overlaps an already reduced bucket")
        previous_size = len(self.pending)
        for bar in bars:
            existing = self.pending.get(bar.time)
            if existing is None or source_rank(bar.source) > source_rank(existing.source):
                self.pending[bar.time] = bar
            if self.oldest_ms is None or bar.time_ms < self.oldest_ms:
                self.oldest_ms = bar.time_ms
        self.unique_rows += len(self.pending) - previous_size
        self.peak_buffered_rows = max(self.peak_buffered_rows, len(self.pending))
        if not self.pending:
            return
        assert self.oldest_ms is not None
        oldest_bucket = self._bucket(self.oldest_ms // 1000)
        if oldest_bucket == self._oldest_bucket:
            # A large target may span many small pages. Do not repeatedly sort
            # its growing prefix until a previous bucket actually arrives.
            return
        self._oldest_bucket = oldest_bucket
        if all(self._bucket(bar.time) == oldest_bucket for bar in bars):
            # This is only sufficient on the first page (otherwise the held
            # newer bucket must be flushed together with this page).
            if previous_size == 0:
                return
        ordered = sorted(self.pending.values(), key=lambda bar: bar.time)
        cut = 0
        while cut < len(ordered) and self._bucket(ordered[cut].time) == self._oldest_bucket:
            cut += 1
        self.pending = {bar.time: bar for bar in ordered[:cut]}
        self._reduce(ordered[cut:])

    def _bucket(self, time_seconds: int) -> int:
        return (time_seconds - self.phase_seconds) // self.width_seconds

    def _bounded(self, bars: list[BarData]) -> list[BarData]:
        return [bar for bar in bars if (
            (self.lower_bound_ms is None or bar.time_ms >= self.lower_bound_ms)
            and (self.upper_bound_ms is None or bar.time_ms <= self.upper_bound_ms)
        )]

    def _reduce(self, bars: list[BarData]) -> None:
        bounded = self._bounded(bars)
        self.aggregated_rows += len(bounded)
        if bounded:
            self.targets_desc.extend(reversed(self.reduce(bounded)))

    def finish(self) -> tuple[list[BarData], list[BarData]]:
        # The last bucket may be a partial prefix or a proven listing boundary.
        # Return its components for the caller's existing finality proof only.
        boundary = self._bounded(sorted(self.pending.values(), key=lambda bar: bar.time))
        self._reduce(boundary)
        self.pending.clear()
        return list(reversed(self.targets_desc)), boundary
