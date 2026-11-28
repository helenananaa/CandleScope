"""Forward, bounded reads from one immutable replay display-history origin."""

from __future__ import annotations

from dataclasses import dataclass

from app.data_engine.interval_policy import (
    compute_bucket_end_ms,
    compute_bucket_start_ms,
    parse_interval_ms,
)
from app.data_engine.history.expected_bars import opens_before
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.display_time import SourceBucketTimeMapper
from app.replay.models import ReplaySessionConfig

from .errors import TrainingRunError
from .history import (
    MARKET_CLOSED_REASON,
    MAX_HISTORY_PAGE_BARS,
    _decode_bar_snapshot,
    _snapshot_calendar,
    build_history_page,
)


@dataclass(frozen=True, slots=True)
class IndicatorHistoryChunk:
    start_ms: int
    stop_ms: int
    bars: tuple[ReplayDisplayBar, ...]
    gaps: tuple[tuple[int, int], ...] = ()  # inclusive public bounds
    # ADR-DATA-002 D2: market closures cover time but never restart an indicator.
    closures: tuple[tuple[int, int], ...] = ()


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
    closures: tuple[tuple[int, int], ...] = ()


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
        # ADR-DATA-002 D2: a session-calendar series continues across closures.
        # The calendar runs on the actual timeline; bars are public.
        self.calendar = _snapshot_calendar(snapshot, 0)
        self.public_minus_actual_ms = 0
        if self.calendar is not None:
            mapper = SourceBucketTimeMapper.create(
                interval=display_interval,
                actual_replay_start_ms=int(binding["history_policy"]["actual_replay_start_ms"]),
                public_replay_start_ms=snapshot.replay_start_ms,
                source_bucket_anchor_ms=binding.get("display_source_bucket_anchor_ms"),
            )
            if mapper.monthly_count is None:
                self.public_minus_actual_ms = mapper.public_anchor_ms - mapper.actual_anchor_ms
            else:
                # Every calendar month trades: monthly bars are contiguous.
                self.calendar = None
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

        def clipped(closed):
            return tuple(
                (max(start_ms, gap["start_ms"]), min(stop - 1, gap["end_ms"]))
                for gap in exclusions
                if gap["end_ms"] >= start_ms and gap["start_ms"] < stop
                and (gap["reason"] == MARKET_CLOSED_REASON) == closed
            )

        chunk = IndicatorHistoryChunk(start_ms, stop, bars, clipped(False), clipped(True))
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
    for start, end in (*chunk.gaps, *chunk.closures):
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


def continues(history, last_close_ms: int, open_ms: int) -> bool:
    """Whether a bar opening at ``open_ms`` carries on from one closing at ``last_close_ms``.

    ADR-DATA-002 D2: time in which a session-calendar market trades no minute
    is a closure, so an indicator keeps its state across it. Any traded
    minute in between is missing data and still restarts the indicator.
    """
    if open_ms == last_close_ms + 1:
        return True
    calendar = getattr(history, "calendar", None)
    if calendar is None or open_ms <= last_close_ms + 1:
        return False
    delta = history.public_minus_actual_ms
    try:
        return not calendar.count_expected(last_close_ms + 1 - delta, open_ms - 1 - delta, "1m")
    except (LookupError, ValueError):
        return False


def traded_boundary(history, before_ms: int, count: int) -> int | None:
    """The open of the ``count``-th traded display bucket before ``before_ms``.

    None when the series has no session calendar (the caller keeps the grid).
    The result is not clamped to the history origin.
    """
    calendar = getattr(history, "calendar", None)
    if calendar is None:
        return None
    interval = history.identity["identity"]["display_interval"]
    width = parse_interval_ms(interval)
    delta = history.public_minus_actual_ms
    cursor = before_ms
    try:
        if width <= 60_000:
            return opens_before(calendar, cursor - delta, count, "1m")[0] + delta if count > 0 else cursor
        for _ in range(count):
            if cursor <= history.origin_ms:
                break
            last = opens_before(calendar, cursor - delta, 1, "1m")[0] + delta
            cursor = compute_bucket_start_ms(last, width, interval=interval)
    except LookupError:
        return history.origin_ms
    return cursor
