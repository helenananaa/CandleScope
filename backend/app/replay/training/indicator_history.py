"""Forward, bounded reads from one immutable replay display-history origin."""

from __future__ import annotations

from dataclasses import dataclass

from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.models import ReplaySessionConfig

from .errors import TrainingRunError
from .history import MAX_HISTORY_PAGE_BARS, _decode_bar_snapshot, build_history_page


@dataclass(frozen=True, slots=True)
class IndicatorHistoryChunk:
    start_ms: int
    stop_ms: int
    bars: tuple[ReplayDisplayBar, ...]
    gaps: tuple[tuple[int, int], ...] = ()  # inclusive public bounds


@dataclass(frozen=True, slots=True)
class IndicatorCloseBar:
    open_time_ms: int
    close_time_ms: int
    last_base_open_ms: int
    close: str
    is_closed: bool = True


@dataclass(frozen=True, slots=True)
class IndicatorCloseChunk:
    start_ms: int
    stop_ms: int
    bars: tuple[IndicatorCloseBar, ...]
    gaps: tuple[tuple[int, int], ...] = ()


class IndicatorHistoryPreparing(Exception):
    """A source page progressed, but its closed display bars are not ready."""

    def __init__(self, progress):
        super().__init__("indicator source is preparing")
        self.progress = progress


class PinnedIndicatorHistory:
    """Uses the exact history-page authority, including native grids and gaps.

    The origin belongs to the frozen revision/policy, not to the chart's paged
    window or an opportunistic older-context download. A missing revision is
    an error; this reader never silently seeds from the returned tail instead.
    """

    def __init__(
        self,
        *,
        binding,
        persisted,
        repository,
        data_epoch: str,
        display_interval: str,
        revealed_boundary_ms: int,
        progressive_history_factory=None,
        max_chunk_bars: int | None = None,
    ):
        self.max_chunk_bars = (
            MAX_HISTORY_PAGE_BARS - 1 if max_chunk_bars is None else max_chunk_bars
        )
        if not 1 <= self.max_chunk_bars < MAX_HISTORY_PAGE_BARS:
            raise ValueError("invalid indicator history chunk budget")
        self.arguments = {
            "binding": binding,
            "persisted": persisted,
            "repository": repository,
            "data_epoch": data_epoch,
            "display_interval": display_interval,
            "revealed_boundary_ms": revealed_boundary_ms,
            "progressive_history_factory": progressive_history_factory,
        }
        config = ReplaySessionConfig.from_dict(binding["config"])
        snapshot = _decode_bar_snapshot(persisted, config=config)
        self.snapshot, self.config = snapshot, config
        self.interval = display_interval
        self.interval_ms = parse_interval_ms(display_interval)
        self.base_ms = parse_interval_ms(config.base_interval)
        if not self.interval_ms or not self.base_ms:
            raise TrainingRunError(
                "INDICATOR_HISTORY_INVALID",
                "indicator interval is invalid",
                status_code=422,
            )
        page = build_history_page(
            **self.arguments,
            before_ms=snapshot.replay_start_ms,
            limit=1,
            expected_history_epoch=None,
        )
        self.history_epoch = str(page["history_epoch"])
        self.page_loader = build_history_page
        origin = int(page["history_boundary_ms"])
        floor = compute_bucket_start_ms(
            origin, self.interval_ms, interval=self.interval
        )
        self.origin_ms = (
            origin
            if floor == origin
            else compute_bucket_end_ms(floor, self.interval_ms, interval=self.interval)
        )
        self.revealed_boundary_ms = revealed_boundary_ms
        self.identity = {
            "contract": "replay.indicator-origin.v1",
            "run_id": page["run_id"],
            "session_id": page["session_id"],
            "track_id": page["track_id"],
            "data_epoch": data_epoch,
            "history_epoch": self.history_epoch,
            "identity": page["identity"],
            "origin_ms": self.origin_ms,
        }

    def read_indexed(self, start_ms, stop_before_ms, interval, cancelled, *, include_auxiliary=True):
        from .indexed_tape_context import read_indexed_context

        return read_indexed_context(
            self, start_ms, stop_before_ms, interval, cancelled,
            include_auxiliary=include_auxiliary,
        )

    def read(self, start_ms: int, stop_before_ms: int) -> IndicatorHistoryChunk:
        if (
            start_ms < self.origin_ms
            or stop_before_ms <= start_ms
            or stop_before_ms > self.revealed_boundary_ms + 1
        ):
            raise TrainingRunError(
                "INDICATOR_HISTORY_INVALID",
                "indicator prefix boundary is invalid",
                status_code=422,
            )
        # Leave room for a preceding bar, so the ordinary history reader also
        # supplies evidence for a gap at this chunk's left boundary.
        capacity = min(
            self.max_chunk_bars,
            MAX_HISTORY_PAGE_BARS - 1,
            max(1, 8192 // max(1, self.interval_ms // self.base_ms)),
        )
        stop = start_ms
        count = 0
        for _ in range(capacity):
            count += 1
            stop = compute_bucket_end_ms(stop, self.interval_ms, interval=self.interval)
            if stop >= stop_before_ms:
                stop = stop_before_ms
                break
        # A calculation range is usually much smaller than a chart page. Pass
        # its actual bucket count through to the history authority, otherwise
        # a 19-bar MA can prepare/project 1000 earlier bars and discard them.
        # Keep one predecessor for gap evidence and the same source/seam rules.
        # History deliberately ends a page at the native/replay authority seam
        # even when its row limit has room. Follow that public cursor rather
        # than treating the omitted native prefix as a different seed.
        cursor = stop
        collected, exclusions = {}, []
        for _ in range(4):
            page = self.page_loader(
                **self.arguments,
                before_ms=cursor,
                limit=count + 1,
                expected_history_epoch=self.history_epoch,
            )
            for raw in page["bars"]:
                if start_ms <= raw["open_time_ms"] < stop:
                    collected[raw["open_time_ms"]] = ReplayDisplayBar.from_dict(raw)
            exclusions.extend(page["excluded_ranges"])
            next_before = int(page["next_before_ms"])
            if not page["has_more"] or next_before <= start_ms:
                break
            if next_before >= cursor:
                raise ValueError("indicator history cursor did not progress")
            cursor = next_before
        bars = tuple(collected[key] for key in sorted(collected))
        gaps = tuple(
            (max(start_ms, gap["start_ms"]), min(stop - 1, gap["end_ms"]))
            for gap in exclusions
            if gap["end_ms"] >= start_ms and gap["start_ms"] < stop
        )
        chunk = IndicatorHistoryChunk(start_ms, stop, bars, gaps)
        validate_chunk(chunk, self.revealed_boundary_ms)
        return chunk


def validate_chunk(chunk: IndicatorHistoryChunk | IndicatorCloseChunk, revealed_boundary_ms: int) -> None:
    """Do not turn a query's truncated left edge into a different RSI seed."""
    if chunk.stop_ms <= chunk.start_ms or chunk.stop_ms > revealed_boundary_ms + 1:
        raise ValueError("indicator history chunk is outside the revealed prefix")
    previous = chunk.start_ms - 1
    spans = []
    for bar in chunk.bars:
        if (
            not bar.is_closed
            or bar.open_time_ms <= previous
            or bar.open_time_ms < chunk.start_ms
            or bar.close_time_ms >= chunk.stop_ms
            or bar.last_base_open_ms > revealed_boundary_ms
        ):
            raise ValueError("indicator history chunk has an invalid closed bar")
        previous = bar.close_time_ms
        spans.append((bar.open_time_ms, bar.close_time_ms))
    for start, end in chunk.gaps:
        if start < chunk.start_ms or end >= chunk.stop_ms or end < start:
            raise ValueError("indicator history gap is outside its chunk")
        if any(
            start <= bar.close_time_ms and end >= bar.open_time_ms for bar in chunk.bars
        ):
            raise ValueError("indicator history gap overlaps a bar")
        spans.append((start, end))
    cursor = chunk.start_ms
    for start, end in sorted(spans):
        if start > cursor:
            raise ValueError("indicator history omitted an undeclared prefix")
        cursor = max(cursor, end + 1)
    if cursor != chunk.stop_ms:
        raise ValueError("indicator history did not cover its requested prefix")
