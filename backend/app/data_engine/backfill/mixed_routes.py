"""Route-aware mixed planning: step 2 of docs/architecture/MIXED_ROUTE_PLANNING_zh.md.

Off unless ROUTE_AWARE. Today a mixed chunk plans its covers and fetch
windows, and routing later decides which archive objects to import. An
object then writes rows the plan does not account for: into the
neighbouring chunk's targets (whichever writes second replans), or into the
chunk's own coarse spans (``checked_mixed_windows`` rejects them after the
write and the chunk retries). This module makes the import decision while
planning, so the plan says exactly what the chunk writes:

1. plan the chunk's sources over what is stored (``plan_family_sources``,
   the planner's own refinement rules);
2. for each grid, keep only catalog objects lying entirely inside the
   chunk's targets [first, stop), and choose among them with the router's
   own rule (``select_archive_objects``), priced on step 1's cells;
3. plan again with the chosen objects' rows counted as present: finer rows
   an object writes into a coarse span refine it now, and the finer cells
   that then needs outside objects become REST windows, still inside
   [first, stop);
4. emit object tasks (``mixed_route_objects`` names each object), REST
   window tasks (an empty list: REST only), and derive windows that follow
   the settled covers. The router imports exactly the listed objects
   (``HistoricalSourceRouter._prepare_planned``).

Any rule, budget or catalog failure returns None, and the chunk is planned
as today, as does a plan whose writes would not all get their own native
write view (``planned_windows_fit``). The engine captures those views from
the plan before fetching (``planned_route_windows``); the fence rules do not
change.
"""
from __future__ import annotations

from dataclasses import replace

from app.core.executors import run_preparation
from app.data_engine.history.cover_plan import CoverUnavailable

from .family_plan import ChartDemand, FamilyPlanUnavailable, plan_family_sources, read_stored_series
from .models import BackfillTask
from .source_router import PLANNED_OBJECTS_KEY as ROUTE_OBJECTS_KEY, select_archive_objects

ROUTE_AWARE = False


def archive_catalog(engine):
    """The archive catalog and routing thresholds the router would use, or None.

    Returns ``(plan_objects, rest_page_size, minimum_pages, fetch_batch_size)``
    where ``plan_objects(symbol, interval, start_ms, end_ms, now_ms)`` lists
    catalog objects from dates alone. None when the engine routes nothing to
    archives.
    """
    router = getattr(getattr(engine, "_fetcher", None), "_source_router", None)
    cfg = getattr(router, "_cfg", None)
    if router is None or cfg is None or not getattr(cfg, "history_archive_enabled", False):
        return None
    provider = router._provider("binance")
    if provider is None:
        return None
    capabilities = provider.capabilities("futures")

    def plan_objects(symbol, interval, start_ms, end_ms, now_ms):
        if not capabilities.supports(market_type="futures", interval=interval):
            return []
        return provider.plan_objects(market_type="futures", symbol=symbol, interval=interval,
                                     start_ms=start_ms, end_ms=end_ms, now_ms=now_ms)

    return (plan_objects, capabilities.rest_page_size, max(1, cfg.history_archive_min_rest_pages),
            cfg.fetch_batch_size)


def _metadata(target, policy, start, stop):
    return {"custom_interval": target.interval, "history_composition_contract": policy.contract_id,
            "ledger_range": {"start_ms": start, "end_ms": stop}, "mixed_target_range": None}


def _gap_tasks(planner, gap, interval, width, start, stop, metadata):
    native_gap = replace(gap, interval=interval, start_ms=start, end_ms=stop - width,
                         missing_bars=(stop - start) // width)
    tasks = planner._plan_standard_gap(native_gap, width)
    for task in tasks:
        task.parent_gap = gap
        task.metadata.update(metadata)
    return tasks


async def route_aware_plan(engine, storage, gap, target, first, stop, sources, precedences, policy,
                           now_ms, page_size, *, catalog=None, max_rows, coalesce):
    """``(fetch tasks, derive windows, diagnostics)`` for this chunk, or None to plan as today."""
    catalog = archive_catalog(engine) if catalog is None else catalog
    demand = ChartDemand(target, first, stop, tuple(sources), tuple(precedences), frozenset(policy.fields))
    try:
        stored = await read_stored_series(storage, [demand], now_ms=now_ms)
        alone = await run_preparation(plan_family_sources, [demand], stored)
    except (FamilyPlanUnavailable, CoverUnavailable):
        return None
    widths = {source.series.interval: source.width_ms for source in sources}
    imports = {}
    if catalog is not None:
        plan_objects, rest_page_size, minimum_pages, fetch_batch_size = catalog
        for interval, windows in alone.windows.items():
            width = widths[interval]
            owned = [ref for ref in plan_objects(target.symbol, interval, first, stop - 1, now_ms)
                     if ref.start_ms >= first and ref.end_ms + 1 <= stop]
            if not owned:
                continue
            # Priced as the router prices a run: on the windows this chunk
            # would otherwise fetch.
            run = [BackfillTask(symbol=target.symbol, interval=interval, start_ms=lo, end_ms=hi - width,
                                estimated_bars=(hi - lo) // width, exchange=target.exchange,
                                market_type=target.market_type,
                                metadata={**_metadata(target, policy, first, stop - 1),
                                          "mixed_fetch_windows": [(lo, hi - width)]})
                   for lo, hi in windows]
            selection = select_archive_objects(owned, run, exchange=target.exchange,
                market_type=target.market_type, interval=interval, route_start_ms=first,
                route_end_ms=stop - 1, rest_page_size=rest_page_size, minimum_pages=minimum_pages,
                fetch_batch_size=fetch_batch_size)
            if selection.objects:
                imports[interval] = list(selection.objects)
    extra = {interval: [opened for ref in refs for opened in range(ref.start_ms, ref.end_ms + 1, widths[interval])]
             for interval, refs in imports.items()}
    try:
        plan = await run_preparation(plan_family_sources, [demand], stored, extra=extra)
    except (FamilyPlanUnavailable, CoverUnavailable):
        return None
    if sum(span.rows for spans in plan.covers.values() for span in spans) > max_rows:
        return None
    planner = engine.planner
    windows = []
    for spans in plan.covers.values():
        for span in spans:
            width = span.source.width_ms
            windows.extend(_gap_tasks(planner, gap, span.source.series.interval, width, span.start_ms,
                                      span.end_ms, _metadata(target, policy, span.start_ms, span.end_ms - width)))
    fetches = []
    for interval, runs in plan.windows.items():
        width = widths[interval]
        for lo, hi in runs:
            fetches.extend(_gap_tasks(planner, gap, interval, width, lo, hi,
                                      _metadata(target, policy, lo, hi - width)))
    tasks = coalesce(fetches)
    for interval, refs in imports.items():
        width = widths[interval]
        for ref in refs:
            tasks.extend(_gap_tasks(planner, gap, interval, width, ref.start_ms, ref.end_ms + 1,
                {**_metadata(target, policy, ref.start_ms, ref.end_ms + 1 - width),
                 ROUTE_OBJECTS_KEY: [ref.object_key]}))
    for task in (*tasks, *windows):
        task.metadata["mixed_target_range"] = [first, stop]
    for task in tasks:
        # The router imports exactly the listed objects; none on REST tasks.
        task.metadata.setdefault(ROUTE_OBJECTS_KEY, [])
    from app.data_engine.storage.native_history_fence import planned_windows_fit
    from .fetcher import planned_route_windows
    if not planned_windows_fit(planned_route_windows(tasks)):
        # Writes outside the captured views would take the family-wide check.
        return None
    diagnostics = {"mixed_route_aware": True,
                   "mixed_route_imports": {interval: len(refs) for interval, refs in imports.items()},
                   "mixed_route_rest_cells": {interval: len(cells) for interval, cells in plan.cells.items()}}
    return tasks, windows, diagnostics
