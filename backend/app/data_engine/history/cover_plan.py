"""H127 pure fixed-grid coverage planning; no reads, downloads or writes.

Source qualification belongs to the provider/field contract owner. A plan is
only a proposed exact tiling: execution must still prove actual rows, finality
and revisions through D126/K130/B130 before adopting any output.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec


class CoverUnavailable(ValueError):
    """The qualified grids cannot exactly cover the requested target."""

    def __init__(self, message, *, explored_positions=0):
        super().__init__(message)
        self.explored_positions = explored_positions


class CoverBudgetExceeded(CoverUnavailable):
    """Planning stopped at its work budget; this is not a source-data gap."""


@dataclass(frozen=True, slots=True)
class FixedHistorySource:
    series: SeriesKey
    width_ms: int
    phase_ms: int
    eligible_ranges: tuple[tuple[int, int], ...]
    fields: frozenset[str]
    qualification: str
    cost_per_row: float = 1.0

    def __post_init__(self):
        if not isinstance(self.series, SeriesKey):
            raise ValueError("canonical source series identity required")
        if (type(self.width_ms) is not int or not 0 < self.width_ms <= (1 << 63) - 1
                or type(self.phase_ms) is not int or not 0 <= self.phase_ms < self.width_ms):
            raise ValueError("positive source width and normalized phase required")
        if (not isinstance(self.qualification, str) or not self.qualification
                or len(self.qualification) > 256):
            raise ValueError("bounded composition qualification reference required")
        if (not isinstance(self.fields, frozenset) or not self.fields
                or len(self.fields) > 9 or any(not isinstance(field, str) for field in self.fields)):
            raise ValueError("bounded immutable source field mask required")
        if (not isinstance(self.eligible_ranges, tuple) or not 1 <= len(self.eligible_ranges) <= 128):
            raise ValueError("bounded immutable source eligibility ranges required")
        previous_end = -1
        ranges = []
        for bounds in self.eligible_ranges:
            if (not isinstance(bounds, tuple) or len(bounds) != 2
                    or any(type(value) is not int for value in bounds)
                    or not 0 <= bounds[0] < bounds[1] <= (1 << 63) - 1
                    or bounds[0] < previous_end):
                raise ValueError("ordered disjoint half-open source ranges required")
            if ranges and bounds[0] == previous_end:
                ranges[-1] = (ranges[-1][0], bounds[1])
            else:
                ranges.append(bounds)
            previous_end = bounds[1]
        object.__setattr__(self, "eligible_ranges", tuple(ranges))
        if (isinstance(self.cost_per_row, bool) or not isinstance(self.cost_per_row, (int, float))
                or not math.isfinite(self.cost_per_row) or self.cost_per_row < 0):
            raise ValueError("finite nonnegative source cost required")

    def admits(self, opened: int, target_end: int) -> bool:
        end = opened + self.width_ms
        return ((opened - self.phase_ms) % self.width_ms == 0 and end <= target_end
                and any(lo <= opened and end <= hi for lo, hi in self.eligible_ranges))


@dataclass(frozen=True, slots=True)
class HistoryReadSpan:
    source: FixedHistorySource
    start_ms: int
    end_ms: int

    @property
    def rows(self) -> int:
        return (self.end_ms - self.start_ms) // self.source.width_ms


@dataclass(frozen=True, slots=True)
class TargetCover:
    target: SeriesKey
    start_ms: int
    end_ms: int
    spans: tuple[HistoryReadSpan, ...]
    planned_rows: int
    estimated_cost: float
    explored_positions: int
    required_fields: frozenset[str]


@dataclass(frozen=True, slots=True)
class TargetCoverBatch:
    """Bounded proposals, not proof that any source has actually been read."""
    target: SeriesKey
    requested_range: tuple[int, int]
    planned_range: tuple[int, int]
    covers: tuple[TargetCover, ...]
    next_start_ms: int | None
    stopped_by: str | None
    planned_rows: int
    explored_positions: int


def plan_fixed_batch(
    target: SeriesKey, start_ms: int, end_ms: int, sources: tuple[FixedHistorySource, ...], *,
    required_fields: frozenset[str] = frozenset({"open", "high", "low", "close", "volume"}),
    max_targets: int = 32, max_source_rows: int = 16_384, max_positions: int = 32_768,
) -> TargetCoverBatch:
    """Plan whole targets until a work/output bound, returning an exact cursor.

    A range cannot be made complete by clipping its final target. Later source
    unavailability and work limits preserve only the already proposed prefix;
    an empty prefix raises the original distinct unavailable/budget error.
    Consumers still qualify actual inputs, revisions and finality before use.
    """
    spec = parse_interval_spec(target.interval) if isinstance(target, SeriesKey) else None
    if (spec is None or spec.alignment is not IntervalAlignment.FIXED_EPOCH
            or type(start_ms) is not int or type(end_ms) is not int
            or not 0 <= start_ms < end_ms <= (1 << 63) - 1
            or spec.floor_ms(start_ms) != start_ms or spec.floor_ms(end_ms) != end_ms):
        raise CoverUnavailable("an aligned whole-target fixed range required")
    if (type(max_targets) is not int or not 1 <= max_targets <= 32
            or type(max_source_rows) is not int or not 1 <= max_source_rows <= 131_072
            or type(max_positions) is not int or not 1 <= max_positions <= 131_072):
        raise ValueError("bounded target, source-row and planning budgets required")
    covers = []
    cursor, rows, explored = start_ms, 0, 0
    stopped = None
    while cursor < end_ms and len(covers) < max_targets:
        remaining = max_positions - explored
        if remaining <= 0:
            stopped = "planning_budget"
            break
        try:
            plan = plan_fixed_target(target, cursor, spec.next_ms(cursor), sources,
                                     required_fields=required_fields, max_positions=remaining)
        except CoverBudgetExceeded as error:
            if not covers:
                raise
            # The abandoned attempt still spent the remaining search budget.
            explored += error.explored_positions
            stopped = "planning_budget"
            break
        except CoverUnavailable as error:
            if not covers:
                raise
            explored += error.explored_positions
            stopped = "source_unavailable"
            break
        explored += plan.explored_positions
        if rows + plan.planned_rows > max_source_rows:
            if not covers:
                raise CoverBudgetExceeded("one target exceeds the source-row work budget")
            stopped = "source_rows"
            break
        covers.append(plan)
        rows += plan.planned_rows
        cursor = plan.end_ms
    if cursor < end_ms and stopped is None:
        stopped = "targets"
    return TargetCoverBatch(target, (start_ms, end_ms), (start_ms, cursor), tuple(covers),
                            cursor if cursor < end_ms else None, stopped, rows, explored)


def plan_fixed_target(
    target: SeriesKey, start_ms: int, end_ms: int,
    sources: tuple[FixedHistorySource, ...], *,
    required_fields: frozenset[str] = frozenset({"open", "high", "low", "close", "volume"}),
    max_positions: int = 32_768,
) -> TargetCover:
    """Propose one exact target cover, preferring lower estimated cost per ms.

    This bounded heuristic is not a global request-cost optimizer. Backtracking
    prevents a cheap/wide first choice from falsely rejecting a cover possible
    with another grid (e.g. 3m/2m into 10m). No coarse bar is clipped or split.
    Call once per target and consume/release each plan before advancing a large
    historical range. Unsupported calendars remain explicit, never 30-day months.
    """
    spec = parse_interval_spec(target.interval)
    if (spec is None or spec.alignment is not IntervalAlignment.FIXED_EPOCH
            or type(start_ms) is not int or type(end_ms) is not int
            or not 0 <= start_ms < end_ms <= (1 << 63) - 1
            or spec.floor_ms(start_ms) != start_ms or spec.next_ms(start_ms) != end_ms):
        raise CoverUnavailable("one aligned fixed-grid target bucket required")
    return plan_fixed_range(target, start_ms, end_ms, sources,
                            required_fields=required_fields, max_positions=max_positions)


def plan_fixed_range(
    target: SeriesKey, start_ms: int, end_ms: int,
    sources: tuple[FixedHistorySource, ...], *,
    required_fields: frozenset[str] = frozenset({"open", "high", "low", "close", "volume"}),
    max_positions: int = 32_768,
) -> TargetCover:
    """Cover an actual fixed-grid subrange, for local failed-coarse refinement.

    This range need not be a full target bucket. Only the final executor's
    K130 coverage evaluation may grant authority for the original target.
    """
    spec = parse_interval_spec(target.interval)
    if (spec is None or spec.alignment is not IntervalAlignment.FIXED_EPOCH
            or type(start_ms) is not int or type(end_ms) is not int
            or not 0 <= start_ms < end_ms <= (1 << 63) - 1):
        raise CoverUnavailable("positive fixed-grid coverage range required")
    if (not isinstance(sources, tuple) or not 1 <= len(sources) <= 32
            or any(not isinstance(source, FixedHistorySource) for source in sources)):
        raise ValueError("between 1 and 32 qualified source grids required")
    if (not isinstance(required_fields, frozenset) or not required_fields
            or len(required_fields) > 9 or any(not isinstance(field, str) for field in required_fields)):
        raise ValueError("bounded immutable required-field mask required")
    if type(max_positions) is not int or not 1 <= max_positions <= 131_072:
        raise ValueError("bounded planning position budget required")
    candidates = [source for source in sources
                  if replace(source.series, interval=target.interval) == target
                  and required_fields <= source.fields]
    # Width is a deterministic tie-breaker, not a substitute for actual cost.
    candidates.sort(key=lambda source: (source.cost_per_row / source.width_ms,
                                       -source.width_ms, source.series.topic, source.qualification))
    dead = set()
    explored = 1
    stack = [(start_ms, iter(candidates))]
    path: list[HistoryReadSpan] = []
    while stack:
        at, choices = stack[-1]
        source = next((source for source in choices
                       if source.admits(at, end_ms) and at + source.width_ms not in dead), None)
        if source is None:
            dead.add(at)
            stack.pop()
            if path:
                path.pop()
            continue
        stop = at + source.width_ms
        path.append(HistoryReadSpan(source, at, stop))
        if stop == end_ms:
            break
        if explored >= max_positions:
            raise CoverBudgetExceeded("fixed-grid coverage planning position budget exhausted",
                                      explored_positions=explored)
        explored += 1
        stack.append((stop, iter(candidates)))
    else:
        raise CoverUnavailable("qualified source grids cannot exactly tile this target",
                               explored_positions=explored)

    spans = []
    for piece in path:
        if spans and spans[-1].source == piece.source and spans[-1].end_ms == piece.start_ms:
            spans[-1] = replace(spans[-1], end_ms=piece.end_ms)
        else:
            spans.append(piece)
    try:
        cost = math.fsum(piece.source.cost_per_row for piece in path)
    except OverflowError as error:
        raise ValueError("coverage cost estimate exceeds finite numeric range") from error
    return TargetCover(target, start_ms, end_ms, tuple(spans), len(path), cost, explored, required_fields)
