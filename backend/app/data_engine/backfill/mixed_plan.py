"""Qualified bounded proposals for the existing historical backfill pipeline.

This module plans/reads only. Fetching, native commits, reconciliation, target
ownership, quota and publication remain with their existing owners.
"""
from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass, replace
import math
import sys
import time

from app.core.executors import run_preparation, run_storage
from app.data_engine.aggregation.adapters import chart_field_summary
from app.data_engine.series_key import SeriesKey
from app.data_engine.history.cover_plan import (
    CoverUnavailable, FixedHistorySource, HistoryReadSpan,
    plan_fixed_batch, plan_fixed_range,
)
from app.data_engine.history.source_precedence import collect_presence_windows, finer_requirements
from app.data_engine.history import AlwaysOpenCalendar
from app.data_engine.interval_policy import parse_interval_spec, row_is_closed
from app.data_engine.interval_resolution import IntervalPurpose, IntervalRouteKind, IntervalResolver
from app.data_engine.kline_quality import source_is_trusted_final
from app.data_engine.memory_budget import retained_size
from app.data_engine.series_identity import identity_from_metadata
from app.data_engine.storage.revisions import acquisition_revision, StaleAcquisition
from app.data_engine.market_data.models import MarketChannel
from app.exchanges import get_exchange_registry
from .models import BackfillPlan, IntervalComponent, IntervalDecomposition
from .cold_cover import choose_cold_sources

MAX_SOURCE_ROWS = 16_384
MAX_TARGETS = 512
MAX_TASKS = 4096
MAX_POSITION_WORK = 131_072
WORK_BYTES = 4 * 1024 * 1024
PLAN_BYTES = 32_768 * 512 + 64 * 1024


class _DeclineMixed(Exception):
    pass


def reusable_component(row, width, now_ms, fields):
    """Use K130 field validation; this helper owns no reducer or field sums."""
    try:
        opened = row["open_time"]
        if (type(opened) is not int or opened % width or row.get("close_time") != opened + width - 1
                or opened + width > now_ms or not source_is_trusted_final(row.get("source"))):
            return False
        if not row_is_closed(row):
            return False
        values = chart_field_summary((row,), validate_ohlcv=True).project(enhanced_complete=True)
        return all(values.get(field) is not None for field in fields)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


@dataclass(frozen=True)
class _MixedBinding:
    engine: object
    config: object
    storage: object
    planner: object
    resolver: object
    detector: object
    calendar_resolver: object
    calendar: object
    target: SeriesKey
    declaration: tuple

    def validate_owner(self):
        """Cheap cancellation/rebind checks between tentative source pages.

        Qualification/calendar proof is still fully re-evaluated before reads
        begin and immediately before materialization; no page publishes data.
        """
        cfg, planner, target = self.config, self.planner, self.target
        if (self.engine._cfg is not cfg or self.engine._storage is not self.storage
                or self.engine.planner is not planner or self.engine.detector is not self.detector
                or planner._interval_resolver is not self.resolver
                or self.detector._calendar_resolver is not self.calendar_resolver
                or not cfg.mixed_custom_history or not cfg.reconcile_generate_custom
                or cfg.custom_alignment_mode != "epoch" or cfg.alignment_epoch_ms
                or getattr(planner, "_custom_alignment_fn", None) is not None
                or getattr(planner, "_custom_decomposition_fn", None) is not None
                or target.interval in getattr(planner, "_interval_mappings", {})
                or getattr(self.engine.reconciler, "_custom_aggregator", None) is not None):
            raise StaleAcquisition("mixed backfill owner or qualification binding changed")

    def validate(self):
        self.validate_owner()
        target = self.target
        if (self.detector._resolve_calendar(target.exchange, target.market_type, target.symbol) != self.calendar
                or self.resolver.history_composition_routes(exchange=target.exchange,
                    market_type=target.market_type, interval=target.interval) != self.declaration):
            raise StaleAcquisition("mixed backfill owner or qualification binding changed")


async def build_mixed_backfill_plan(engine, gaps, metadata, diagnostics):
    cfg, storage = engine._cfg, engine._storage
    if (not getattr(cfg, "mixed_custom_history", False) or not cfg.reconcile_generate_custom or len(gaps) != 1
            or cfg.custom_alignment_mode != "epoch" or cfg.alignment_epoch_ms
            or metadata.get("history_calendar_id") not in (None, "crypto.24x7.utc")
            or not all(callable(getattr(storage, name, None)) for name in
                       ("query_bars_range_presence", "query_canonical_page"))):
        return None
    gap = gaps[0]
    detector = engine.detector
    resolve_calendar = getattr(detector, "_resolve_calendar", None)
    if not callable(resolve_calendar):
        return None
    calendar = resolve_calendar(gap.exchange, gap.market_type, gap.symbol)
    calendar_resolver = getattr(detector, "_calendar_resolver", None)
    if not isinstance(calendar, AlwaysOpenCalendar):
        return None
    identity = identity_from_metadata(gap.exchange, metadata)
    if identity is not None and not identity.is_legacy_default_for(gap.exchange):
        return None
    planner = engine.planner
    if not all(callable(getattr(planner, name, None)) for name in ("_plan_standard_gap", "_deduplicate_tasks")):
        return None
    if (getattr(planner, "_custom_alignment_fn", None) is not None
            or getattr(planner, "_custom_decomposition_fn", None) is not None
            or gap.interval in getattr(planner, "_interval_mappings", {})
            or getattr(getattr(engine, "_reconciler", None), "_custom_aggregator", None) is not None):
        return None
    resolver = getattr(planner, "_interval_resolver", None)
    composition_for = getattr(resolver, "history_composition_routes", None)
    if not callable(composition_for):
        return None
    declaration = composition_for(exchange=gap.exchange, market_type=gap.market_type, interval=gap.interval)
    if declaration is None:
        return None
    policy, routes, precedence_routes = declaration
    target_route = resolver.resolve(exchange=gap.exchange, market_type=gap.market_type,
                                    interval=gap.interval, purpose=IntervalPurpose.HISTORY)
    spec = target_route.spec
    if target_route.kind is not IntervalRouteKind.DERIVED or spec.phase_ms:
        return None
    base = parse_interval_spec(target_route.base_interval)
    if base is None or base.nominal_ms >= max(route.spec.nominal_ms for route in routes):
        return None
    first, stop = spec.floor_ms(gap.start_ms), spec.next_ms(spec.floor_ms(gap.end_ms))
    now_ms = int(time.time() * 1000)
    if first < 0 or stop > now_ms or (stop - first) // spec.nominal_ms > MAX_TARGETS:
        return None
    store = getattr(storage, "revision_store", None)
    floor = acquisition_revision()
    if store is None or floor is None:
        return None
    target = SeriesKey(gap.symbol, spec.canonical, exchange=gap.exchange, market_type=gap.market_type)
    binding = _MixedBinding(engine, cfg, storage, planner, resolver, detector,
                            calendar_resolver, calendar, target, declaration)
    sources = tuple(FixedHistorySource(replace(target, interval=r.canonical_interval), r.spec.nominal_ms,
        0, ((0, stop),), frozenset(policy.fields), policy.contract_id) for r in routes)
    precedences = tuple((replace(target, interval=r.canonical_interval), r.spec.nominal_ms)
                        for r in precedence_routes)
    keys = tuple((key.exchange, key.market_type, key.symbol, key.interval, *key.identity.storage_values)
                 for key, _ in precedences)
    channel = get_exchange_registry().get_capabilities(target.exchange).channel_capability(
        MarketChannel.KLINE, target.market_type)
    if channel.history_composition != policy:
        return None
    declared_limit = channel.limits.get("rest.max_limit", cfg.fetch_batch_size)
    if type(declared_limit) is not int or declared_limit <= 0:
        return None
    page_size = min(max(1, cfg.fetch_batch_size), declared_limit)
    diagnostics.update(mixed_plan_attempted=True, mixed_plan_contract=policy.contract_id,
        mixed_plan_probe_reads=0, mixed_plan_probe_rows=0, mixed_plan_input_pages=0,
        mixed_plan_input_rows=0, mixed_plan_refinements=0, mixed_plan_positions=0)
    planner.metrics.inc("mixed_proposals")
    count = await storage.count_bars(target.symbol, base.canonical, first, stop - 1,
        exchange=target.exchange, market_type=target.market_type)
    if count >= (stop - first) // base.nominal_ms:
        diagnostics["mixed_plan_fallback"] = "local_single_base_preferred"
        return None
    _, changes = await run_storage(store.read_series_changes, keys)
    if any(change and change["revision"] > floor for change in changes):
        raise StaleAcquisition("mixed planning sources changed after acquisition")
    mutations = {key: change for (key, _), change in zip(precedences, changes)}
    versions = tuple(change["revision"] if change else 0 for change in changes)
    budget = getattr(engine, "memory_budget", None)
    work = budget.reserve("history-backfill", WORK_BYTES) if budget is not None else nullcontext()
    builder = _MixedBackfillBuilder(engine, gap, target, policy, sources, precedences,
                                    mutations, now_ms, diagnostics, budget)
    try:
        with work:
            if all(change is None for change in changes):
                planning = budget.reserve("history-backfill", PLAN_BYTES) if budget else nullcontext()
                with planning:
                    choice = await run_preparation(choose_cold_sources, target, first, stop, sources,
                        required_fields=frozenset(policy.fields), target_width=spec.nominal_ms,
                        base_width=base.nominal_ms, page_size=page_size,
                        task_page_size=max(1, cfg.fetch_batch_size), max_rows=MAX_SOURCE_ROWS,
                        max_tasks=MAX_TASKS, max_positions=MAX_POSITION_WORK // 2)
                builder.positions(choice.positions)
                diagnostics.update(mixed_cold_candidates=choice.candidates,
                    mixed_cold_estimated_requests=choice.requests, mixed_cold_source_rows=choice.rows)
                binding.validate()
                if choice.sources is None:
                    raise _DeclineMixed(choice.reason)
                sources = choice.sources
            covers, cursor = [], first
            while cursor < stop:
                planning = budget.reserve("history-backfill", PLAN_BYTES) if budget else nullcontext()
                with planning:
                    batch = await run_preparation(plan_fixed_batch, target, cursor, stop, sources,
                        required_fields=frozenset(policy.fields), max_source_rows=MAX_SOURCE_ROWS,
                        max_positions=builder.remaining_positions())
                covers.extend(batch.covers)
                builder.positions(batch.explored_positions)
                if sum(c.planned_rows for c in covers) > MAX_SOURCE_ROWS:
                    raise _DeclineMixed("source_row_budget")
                cursor = batch.planned_range[1]
            baseline_requests = math.ceil(((stop - first) // base.nominal_ms) / page_size)
            initial_requests = sum(math.ceil(span.rows / page_size) for cover in covers for span in cover.spans)
            if all(change is None for change in changes) and initial_requests > baseline_requests:
                raise _DeclineMixed("cold_rest_request_cost")
            for offset in range(0, len(covers), 32):
                batch = covers[offset:offset + 32]
                await builder.prefetch(batch)
                for cover in batch:
                    await builder.refine(cover)
            tasks = planner._deduplicate_tasks(builder.tasks)
            windows = planner._deduplicate_tasks(builder.windows)
            requests = sum(math.ceil(task.estimated_bars / page_size) for task in tasks)
            if requests > baseline_requests:
                raise _DeclineMixed("rest_request_cost")
            _, current = await run_storage(store.read_versions, keys)
            if tuple(current) != versions or engine._storage is not storage or engine._cfg is not cfg:
                raise StaleAcquisition("mixed planning sources or bindings changed")
            if (detector._calendar_resolver is not calendar_resolver
                    or detector._resolve_calendar(target.exchange, target.market_type, target.symbol) != calendar):
                raise StaleAcquisition("mixed planning calendar changed")
            if (not cfg.mixed_custom_history or composition_for(exchange=target.exchange,
                    market_type=target.market_type, interval=target.interval) != declaration):
                raise StaleAcquisition("mixed planning qualification changed")
            binding.validate()
            components = [IntervalComponent(interval, sum(t.estimated_bars for t in windows if t.interval == interval),
                                             parse_interval_spec(interval).nominal_ms)
                          for interval in dict.fromkeys(task.interval for task in windows)]
            decomp = IntervalDecomposition(target.interval, spec.nominal_ms, components,
                composition_policy=policy, composition_target_range=(first, stop))
            diagnostics.update(mixed_history=True, mixed_source_rows=builder.rows,
                mixed_estimated_rest_requests=requests, single_base_estimated_rest_requests=baseline_requests)
            planner.metrics.inc("mixed_adopted_plans")
            planner.metrics.set("last_mixed_source_rows", builder.rows)
            planner.metrics.set("last_mixed_estimated_requests", requests)
            return BackfillPlan(gaps=gaps, decompositions=[decomp], tasks=tasks,
                estimated_requests=requests, estimated_bars=sum(t.estimated_bars for t in tasks),
                custom_intervals=[target.interval], metadata=dict(diagnostics), derived_source_windows=windows, mixed_binding=binding)
    except (_DeclineMixed, CoverUnavailable) as exc:
        diagnostics["mixed_plan_positions"] += getattr(exc, "explored_positions", 0)
        diagnostics["mixed_plan_fallback"] = str(exc)
        return None


class _MixedBackfillBuilder:
    def __init__(self, engine, gap, target, policy, sources, precedences, mutations, now_ms, report, budget):
        self.engine, self.gap, self.target, self.policy = engine, gap, target, policy
        self.sources, self.precedences, self.mutations = sources, precedences, mutations
        self.now_ms, self.report, self.budget = now_ms, report, budget
        self.storage = engine._storage
        self.presence, self.tasks, self.windows = {}, [], []
        self.rows = 0
        # Task records/metadata are finalized before admission and remain
        # reachable until this builder exits. Count each once; never retain an
        # ID for a temporary root container or the transient presence map.
        self._task_seen = {id(gap)}
        self._task_bytes = 0

    def _check_work(self, windows=(), tasks=()):
        self._task_bytes += retained_size(windows, self._task_seen)[0]
        self._task_bytes += retained_size(tasks, self._task_seen)[0]
        # The shared parent gap and current batch can contain mutable metadata;
        # remeasure them independently rather than accepting a stale ID hit.
        transient = retained_size((self.gap, self.presence))[0]
        accounting = sys.getsizeof(self._task_seen) + len(self._task_seen) * sys.getsizeof(sys.maxsize * 2 + 1)
        total = self._task_bytes + transient + accounting + sys.getsizeof(self.tasks) + sys.getsizeof(self.windows)
        self.report['mixed_plan_work_bytes'] = total
        self.report['mixed_plan_work_high_water_bytes'] = max(total,
            self.report.get('mixed_plan_work_high_water_bytes', 0))
        if len(self.tasks) + len(self.windows) > MAX_TASKS or total > WORK_BYTES:
            raise _DeclineMixed('task_work_budget')

    def positions(self, count):
        self.report["mixed_plan_positions"] += count
        if self.report["mixed_plan_positions"] > MAX_POSITION_WORK:
            raise _DeclineMixed("planning_work_budget")

    def remaining_positions(self):
        remaining = MAX_POSITION_WORK - self.report["mixed_plan_positions"]
        if remaining <= 0:
            raise _DeclineMixed("planning_work_budget")
        return min(32_768, remaining)

    async def prefetch(self, covers):
        self.presence.clear()
        requests = collect_presence_windows((span for cover in covers for span in cover.spans),
                                            self.precedences, self.mutations)
        for source, ranges in requests.items():
            for offset in range(0, len(ranges), 256):
                chunk = ranges[offset:offset + 256]
                self.report["mixed_plan_probe_reads"] += 1
                flags = await self.storage.query_bars_range_presence(source.symbol, source.interval, chunk,
                    exchange=source.exchange, market_type=source.market_type, series_identity=source.identity)
                self.report["mixed_plan_probe_rows"] += len(flags)
                if len(flags) != len(chunk) or any(type(flag) is not bool for flag in flags):
                    raise StaleAcquisition("mixed planning presence receipt is invalid")
                self.presence.update(((source, lo, hi), flag) for (lo, hi), flag in zip(chunk, flags))

    async def finer_present(self, span):
        for source, lo, hi, deleted in finer_requirements(span, self.precedences, self.mutations):
            if deleted:
                return True
            key = source, lo, hi
            if key not in self.presence:
                self.report["mixed_plan_probe_reads"] += 1
                flags = await self.storage.query_bars_range_presence(source.symbol, source.interval, ((lo, hi),),
                    exchange=source.exchange, market_type=source.market_type, series_identity=source.identity)
                self.report["mixed_plan_probe_rows"] += len(flags)
                if len(flags) != 1 or type(flags[0]) is not bool:
                    raise StaleAcquisition("mixed refinement presence receipt is invalid")
                self.presence[key] = flags[0]
            if self.presence[key]:
                return True
        return False

    async def known_inputs(self, span):
        trusted, cursor, last = set(), span.start_ms, -1
        while cursor < span.end_ms:
            self.report["mixed_plan_input_pages"] += 1
            rows = await self.storage.query_canonical_page(self.target.symbol, span.source.series.interval,
                cursor, span.end_ms - 1, exchange=self.target.exchange, market_type=self.target.market_type,
                series_identity=self.target.identity)
            self.report["mixed_plan_input_rows"] += len(rows)
            if len(rows) > 256:
                raise StaleAcquisition("mixed planning canonical page exceeds its bound")
            if not rows:
                break
            for row in rows:
                opened = row.get("open_time")
                if type(opened) is not int or not cursor <= opened < span.end_ms or opened <= last:
                    raise StaleAcquisition("mixed planning canonical page has invalid ordering")
                if not reusable_component(row, span.source.width_ms, self.now_ms, self.policy.fields):
                    return True, set()
                trusted.add(opened)
                last = opened
            if len(trusted) > MAX_SOURCE_ROWS:
                raise _DeclineMixed("canonical_input_budget")
            if len(rows) < 256:
                break
            cursor = last + 1
        return False, trusted

    async def refine(self, cover):
        pending = deque(cover.spans)
        while pending:
            span = pending.popleft()
            finer = tuple(source for source in self.sources if source.width_ms < span.source.width_ms)
            rejected = await self.finer_present(span)
            bad, trusted = (False, set()) if rejected else await self.known_inputs(span)
            if rejected or bad:
                if not finer:
                    raise _DeclineMixed("finest_input_not_composition_qualified")
                planning = self.budget.reserve("history-backfill", PLAN_BYTES) if self.budget else nullcontext()
                with planning:
                    replacement = await run_preparation(plan_fixed_range, self.target, span.start_ms, span.end_ms,
                        finer, required_fields=frozenset(self.policy.fields),
                        max_positions=self.remaining_positions())
                self.positions(replacement.explored_positions)
                self.report["mixed_plan_refinements"] += 1
                pending.extendleft(reversed(replacement.spans))
                continue
            self.rows += span.rows
            if self.rows > MAX_SOURCE_ROWS:
                raise _DeclineMixed("refined_source_row_budget")
            native_gap = replace(self.gap, interval=span.source.series.interval,
                start_ms=span.start_ms, end_ms=span.end_ms - span.source.width_ms, missing_bars=span.rows)
            windows = self.engine.planner._plan_standard_gap(native_gap, span.source.width_ms)
            for task in windows:
                task.parent_gap = self.gap
                task.metadata.update(custom_interval=self.target.interval,
                    history_composition_contract=self.policy.contract_id,
                    ledger_range={"start_ms": span.start_ms, "end_ms": span.end_ms - span.source.width_ms})
            self.windows.extend(windows)
            self._check_work(windows=windows)
            # Existing paging owner splits each missing contiguous source run.
            at = span.start_ms
            while at < span.end_ms:
                if at in trusted:
                    at += span.source.width_ms
                    continue
                first = at
                while at < span.end_ms and at not in trusted:
                    at += span.source.width_ms
                missing = replace(native_gap, start_ms=first, end_ms=at - span.source.width_ms,
                                  missing_bars=(at - first) // span.source.width_ms)
                for task in self.engine.planner._plan_standard_gap(missing, span.source.width_ms):
                    task.parent_gap = self.gap
                    task.metadata = dict(windows[0].metadata)
                    self.tasks.append(task)
                    self._check_work(tasks=(task,))


async def checked_mixed_windows(storage, target, policy, windows):
    """Recheck finer presence after native commits, including archive overread.

    An import can legitimately store extra native rows. If those rows are finer
    than a chosen coarse span, do not materialize that old proposal. The next
    ordinary retry can replan from canonical inputs. D126 remains write owner.
    """
    declaration = IntervalResolver().history_composition_routes(exchange=target.exchange,
        market_type=target.market_type, interval=target.interval)
    if declaration is None or declaration[0] != policy:
        raise StaleAcquisition("mixed materialization qualification changed")
    _, selected, routes = declaration
    selected_widths = {r.canonical_interval: r.spec.nominal_ms for r in selected}
    precedences = tuple((replace(target, interval=r.canonical_interval), r.spec.nominal_ms) for r in routes)
    keys = tuple((key.exchange, key.market_type, key.symbol, key.interval, *key.identity.storage_values)
                 for key, _ in precedences)
    store = storage.revision_store
    _, changes = await run_storage(store.read_series_changes, keys)
    mutations = {key: change for (key, _), change in zip(precedences, changes)}
    versions = tuple(change["revision"] if change else 0 for change in changes)
    result = []
    if len(windows) > MAX_TASKS:
        raise StaleAcquisition("mixed materialization windows exceed their bound")
    for offset in range(0, len(windows), 64):
        batch, presence = [], {}
        for window in windows[offset:offset + 64]:
            interval, first, last, identity = window
            if interval not in selected_widths or (identity and not identity.is_legacy_default_for(target.exchange)):
                raise StaleAcquisition("mixed materialization source identity changed")
            width = selected_widths[interval]
            source = FixedHistorySource(replace(target, interval=interval), width, 0,
                ((first, last + width),), frozenset(policy.fields), policy.contract_id)
            batch.append((window, HistoryReadSpan(source, first, last + width)))
        requests = collect_presence_windows((span for _, span in batch), precedences, mutations)
        for source, ranges in requests.items():
            for start in range(0, len(ranges), 256):
                chunk = ranges[start:start + 256]
                flags = await storage.query_bars_range_presence(source.symbol, source.interval, chunk,
                    exchange=source.exchange, market_type=source.market_type, series_identity=source.identity)
                if len(flags) != len(chunk) or any(type(flag) is not bool for flag in flags):
                    raise StaleAcquisition("mixed post-commit presence receipt is invalid")
                presence.update(((source, lo, hi), flag) for (lo, hi), flag in zip(chunk, flags))
        for window, span in batch:
            if not any(deleted or presence[(source, lo, hi)] for source, lo, hi, deleted
                       in finer_requirements(span, precedences, mutations)):
                result.append(window)
    _, current = await run_storage(store.read_versions, keys)
    if tuple(current) != versions:
        raise StaleAcquisition("mixed post-commit canonical inputs changed")
    return result
