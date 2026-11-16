"""Bounded cold-only cost comparison using the existing H127 cover planner.

Proposals grant no availability or write permission. Existing canonical reads,
finer precedence, acquisition fences and materialization still decide adoption.
"""
from dataclasses import dataclass
import math

from app.data_engine.history.cover_plan import CoverUnavailable, CoverBudgetExceeded, plan_fixed_batch


@dataclass(frozen=True, slots=True)
class ColdCoverChoice:
    sources: tuple | None
    positions: int
    candidates: int
    requests: int | None
    rows: int | None
    reason: str | None


def _candidates(sources, base_width):
    widths = sorted({source.width_ms for source in sources}, reverse=True)
    seen = set()
    # Prefixes retain the ordinary exact-cover choices. Coarsest/intermediate/
    # finest alternatives can avoid paying for every boundary granularity.
    groups = [tuple(source for source in sources if source.width_ms <= width)
              for width in widths if width > base_width]
    groups.extend(tuple(source for source in sources
                        if source.width_ms in {widths[0], middle, widths[-1]})
                  for middle in widths[1:-1])
    for group in groups:
        if group not in seen:
            seen.add(group)
            yield group
            if len(seen) >= 32:
                return


def _minimum_rows(width, sources):
    widths = sorted({source.width_ms for source in sources}, reverse=True)
    if any(coarse % fine for coarse, fine in zip(widths, widths[1:])):
        return math.ceil(width / widths[0])
    # For nested integer grids, aligned greedy coin count is a lower bound;
    # arbitrary real phases may require more edge rows, never fewer.
    rows = 0
    for step in widths:
        count, width = divmod(width, step)
        rows += count
    return rows if width == 0 else math.inf


def choose_cold_sources(target, first, stop, sources, *, required_fields,
                        target_width, base_width, page_size, task_page_size,
                        max_rows, max_tasks, max_positions):
    """Compare at most 32 qualified grid subsets, without retaining plans.

    Only declared grids wider than the original single base are alternatives.
    Each candidate consumes the same finite search budget, including abandoned
    attempts. A lower bound discards impossible row budgets before searching.
    Candidate batches are released before advancing; the chosen sources are
    planned once more by the ordinary executor. This is a bounded heuristic,
    not a global optimizer for arbitrary source subsets or live network costs.
    """
    best, best_score = None, None
    spent = tried = 0
    reason = 'source_row_budget'
    targets = (stop - first) // target_width
    for candidate in _candidates(sources, base_width):
        if targets * _minimum_rows(target_width, candidate) > max_rows:
            continue
        width = max(source.width_ms for source in candidate)
        cursor, rows, requests, tasks = first, 0, 0, 0
        tried += 1
        valid = True
        while cursor < stop:
            remaining = max_positions - spent
            if remaining <= 0:
                reason, valid = 'planning_work_budget', False
                break
            try:
                batch = plan_fixed_batch(target, cursor, stop, candidate,
                    required_fields=required_fields, max_source_rows=max_rows,
                    max_positions=min(32_768, remaining))
            except CoverUnavailable as error:
                spent += error.explored_positions
                reason = 'planning_work_budget' if isinstance(error, CoverBudgetExceeded) else 'source_unavailable'
                valid = False
                break
            spent += batch.explored_positions
            rows += batch.planned_rows
            requests += sum(math.ceil(span.rows / page_size)
                            for cover in batch.covers for span in cover.spans)
            # In an empty view each missing source run creates both the
            # original reconciliation window and fetch tasks, before dedup.
            tasks += 2 * sum(math.ceil(span.rows / task_page_size)
                             for cover in batch.covers for span in cover.spans)
            cursor = batch.planned_range[1]
            del batch
            if rows > max_rows or tasks > max_tasks:
                reason = 'source_row_budget' if rows > max_rows else 'task_work_budget'
                valid = False
                break
        if valid:
            score = requests, rows, -width
            if best_score is None or score < best_score:
                best, best_score = candidate, score
        if spent >= max_positions:
            break
    return ColdCoverChoice(best, spent, tried,
        best_score[0] if best_score else None, best_score[1] if best_score else None,
        None if best is not None else reason)
