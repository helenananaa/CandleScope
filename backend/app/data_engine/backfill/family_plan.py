"""One symbol's cold source fill, planned once for every mixed chart.

See docs/architecture/COLD_FAMILY_FILL_zh.md §4. Each chart's chunks plan
their sources alone today, so finer rows one chart writes later refine (and
invalidate) the coarse spans another chart planned in the same time range.
This module answers, for a set of chart demands of one family: which source
cells must be acquired so that, once they and the stored rows are present,
every target's cover under the planner's own rules uses only stored trusted
rows and those cells.

It is pure and synchronous: no storage, network, revision or fence. The
caller describes what is stored and owns every check of what is actually
written and read. The rules mirror ``_MixedBackfillBuilder.refine``:

- a span is refined (its whole range, by the finer selected sources) when a
  finer precedence series has a row overlapping it, or a deletion history
  that may reach it, or when a stored row of its own grid is not reusable;
- otherwise its cells that are not stored and reusable are acquired.

Cells planned for one chart count as present for every other chart, and
planning repeats until no target needs another cell. Planned cells only
accumulate, so the result converges; a cell a later refinement no longer
needs is still acquired and is accounted for as present.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from bisect import bisect_left

from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import (
    CoverUnavailable,
    FixedHistorySource,
    HistoryReadSpan,
    plan_fixed_range,
    plan_fixed_target,
)
from app.data_engine.interval_policy import parse_interval_spec

MAX_ITERATIONS = 8
MAX_CELLS = 131_072


class FamilyPlanUnavailable(CoverUnavailable):
    """No family plan within these rules or bounds; plan each chart as today."""


@dataclass(frozen=True)
class StoredSeries:
    """What one canonical series holds, as the planner's reads would see it.

    ``reusable``: opens of rows ``reusable_component`` accepts. ``other``:
    opens of every other stored row (untrusted, incomplete, unaligned or
    forming). ``deleted_from``: the earliest open its change history reaches
    when that history includes a deletion, else None.
    """
    reusable: frozenset[int] = frozenset()
    other: frozenset[int] = frozenset()
    deleted_from: int | None = None


@dataclass(frozen=True)
class ChartDemand:
    """Closed targets [start_ms, stop_ms) of one chart, with its planning inputs.

    ``sources`` are the grids its planner selected (for a cold range, after
    ``choose_cold_sources``); ``precedences`` are every canonical series of the
    family that may take precedence, selected or not.
    """
    target: SeriesKey
    start_ms: int
    stop_ms: int
    sources: tuple[FixedHistorySource, ...]
    precedences: tuple[tuple[SeriesKey, int], ...]
    required_fields: frozenset[str]


@dataclass(frozen=True)
class FamilyPlan:
    """``cells``: opens to acquire per interval; ``windows``: the same as merged
    half-open runs; ``covers``: (demand position, target open) -> the spans its
    reader will use once the cells are written; ``refinements``: spans refined
    in the final pass and before."""
    cells: dict[str, frozenset[int]]
    windows: dict[str, tuple[tuple[int, int], ...]]
    covers: dict[tuple[str, int], tuple[HistoryReadSpan, ...]]
    iterations: int
    refinements: int = field(default=0)


def _any_in(opens, lo, hi):
    at = bisect_left(opens, lo)
    return at < len(opens) and opens[at] < hi


class _Present:
    """Sorted opens per interval: stored rows of any quality plus planned cells."""

    def __init__(self, stored):
        self._opens = {interval: sorted(series.reusable | series.other)
                       for interval, series in stored.items()}
        self.unusable = {interval: sorted(series.other) for interval, series in stored.items()}

    def add(self, interval, opens):
        self._opens[interval] = sorted(set(self._opens.get(interval, ())) | set(opens))

    def any_in(self, interval, lo, hi):
        return _any_in(self._opens.get(interval, ()), lo, hi)


def _refined_spans(demand, cover, stored, present, counts):
    """The cover the planner's refinement settles on, given what will be present."""
    out = []
    pending = deque(cover.spans)
    while pending:
        span = pending.popleft()
        width = span.source.width_ms
        rejected = False
        for fine, fine_width in demand.precedences:
            if fine_width >= width:
                continue
            lo, hi = max(0, span.start_ms - fine_width + 1), span.end_ms
            series = stored.get(fine.interval)
            if series is not None and series.deleted_from is not None and series.deleted_from < hi:
                rejected = True
                break
            if present.any_in(fine.interval, lo, hi):
                rejected = True
                break
        bad = not rejected and _any_in(present.unusable.get(span.source.series.interval, ()),
                                       span.start_ms, span.end_ms)
        if not (rejected or bad):
            out.append(span)
            continue
        finer = tuple(source for source in demand.sources if source.width_ms < width)
        if not finer:
            raise FamilyPlanUnavailable("finest_input_not_composition_qualified")
        replacement = plan_fixed_range(demand.target, span.start_ms, span.end_ms, finer,
                                       required_fields=demand.required_fields)
        counts[0] += 1
        pending.extendleft(reversed(replacement.spans))
    return tuple(out)


def _merge(cells, width):
    windows = []
    for opened in sorted(cells):
        if windows and windows[-1][1] == opened:
            windows[-1][1] = opened + width
        else:
            windows.append([opened, opened + width])
    return tuple((start, end) for start, end in windows)


def plan_family_sources(demands, stored, *, extra=None, max_iterations=MAX_ITERATIONS,
                        max_cells=MAX_CELLS) -> FamilyPlan:
    """Source cells to acquire for every demand of one family (see module docstring).

    ``stored`` maps a canonical interval to its ``StoredSeries``. ``extra``
    maps an interval to opens that will be written anyway (whole archive
    objects): they count as present from the start and are not re-planned.
    Raises ``CoverUnavailable`` (``FamilyPlanUnavailable`` for this module's
    own rules and bounds) when no plan exists; the caller plans as today.
    """
    demands = tuple(demands)
    if not demands:
        return FamilyPlan({}, {}, {}, 0)
    family = {(d.target.exchange, d.target.market_type, d.target.symbol, d.target.identity) for d in demands}
    if len(family) != 1:
        raise ValueError("one family's demands required")
    widths = {}
    for demand in demands:
        spec = parse_interval_spec(demand.target.interval)
        if (spec is None or spec.floor_ms(demand.start_ms) != demand.start_ms
                or spec.floor_ms(demand.stop_ms) != demand.stop_ms or demand.start_ms >= demand.stop_ms):
            raise FamilyPlanUnavailable("whole aligned target ranges required")
        for source in demand.sources:
            widths[source.series.interval] = source.width_ms
    present = _Present(stored)
    planned = {interval: set() for interval in widths}
    provided = {interval: frozenset(opens) for interval, opens in (extra or {}).items()}
    for interval, opens in provided.items():
        present.add(interval, opens)
    covers = {}
    counts = [0]
    for iteration in range(1, max_iterations + 1):
        added = {}
        for position, demand in enumerate(demands):
            spec = parse_interval_spec(demand.target.interval)
            opened = demand.start_ms
            while opened < demand.stop_ms:
                following = spec.next_ms(opened)
                cover = plan_fixed_target(demand.target, opened, following, demand.sources,
                                          required_fields=demand.required_fields)
                spans = _refined_spans(demand, cover, stored, present, counts)
                covers[(position, opened)] = spans
                for span in spans:
                    interval = span.source.series.interval
                    own = stored.get(interval)
                    reusable = own.reusable if own is not None else frozenset()
                    written = provided.get(interval, frozenset())
                    for cell in range(span.start_ms, span.end_ms, span.source.width_ms):
                        if cell not in reusable and cell not in written and cell not in planned[interval]:
                            planned[interval].add(cell)
                            added.setdefault(interval, set()).add(cell)
                if sum(len(cells) for cells in planned.values()) > max_cells:
                    raise FamilyPlanUnavailable("family_cell_budget")
                opened = following
        if not added:
            cells = {interval: frozenset(opens) for interval, opens in planned.items() if opens}
            return FamilyPlan(cells, {interval: _merge(opens, widths[interval]) for interval, opens in cells.items()},
                              covers, iteration, counts[0])
        for interval, opens in added.items():
            present.add(interval, opens)
    raise FamilyPlanUnavailable("family_plan_did_not_settle")
