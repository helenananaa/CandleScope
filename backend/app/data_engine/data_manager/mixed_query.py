"""Default closed-history consumer of H127, with conservative local precedence.

Provider capability owns composability. Existing finer canonical data (even
partial/untrusted) takes precedence over independent native coarse candles.
Missing finer data alone is not proof after a deletion. Probes and target pages
read inside D126/B130 views; no output is adopted inside a view. Each batch of
targets has its own view and proves its read extent unchanged since the query's
floor, so the page is exactly what one view at the floor would compose. Its
write and adoption are then checked by range (``capture_read_computation``),
like a backfill reduction, not by every family series staying unchanged.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
import time

from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.history.cover_plan import CoverBudgetExceeded, CoverUnavailable, FixedHistorySource
from app.data_engine.history import AlwaysOpenCalendar
from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
from app.data_engine.interval_resolution import IntervalPurpose
from app.data_engine.memory_budget import reserve_work
from app.data_engine.storage.mixed_history_fence import ClosedMixedRead, capture_read_computation
from app.data_engine.storage.range_changes import check_store_range
from app.data_engine.storage.revisions import acquisition_revision, current_acquisition, StaleAcquisition
from .models import BarData, QueryResult, QuerySource
from .mixed_precedence import MixedPrecedence, BATCH_TARGETS, WORK_BYTES
from .mixed_history import MixedHistorySession
from .config import CUSTOM_HISTORY_MAX_BASE_PAGES, CUSTOM_HISTORY_SOURCE_PAGE_ROWS

# Target reads share their view's qualification and page allowance
# (MixedHistorySession). False restores one view per target and per page.
SESSION_READS = True
# One B130 view per batch of targets instead of one for the whole page. A view
# ends at any change to one of its series, including the live minute far past
# this page: one view over a 128-target page was discarded on most busy loads.
# A disturbed batch is composed again, up to BATCH_ATTEMPTS times in all.
BATCH_VIEWS = True
BATCH_ATTEMPTS = 3
# Per-target work rows, reported as each target is read.
TARGET_COUNTERS = ("mixed_planned_rows", "mixed_accepted_rows", "mixed_fallbacks")
# Persist and adopt a composed page by its range proof (see module docstring).
READ_PROOF = True


def query_closed_mixed(engine, key, *, start_ms=None, end_ms=None, before_ms=None,
                       limit, report, auto_backfill=None, materialized_result=None,
                       composition_contract=None):
    """Try a bounded closed page; unavailable inputs keep the original route.

    A stale view never falls back into a new generation. ``report`` contains
    only work counters/reasons, including abandoned reads, not staged market
    data. Current/forming and unsupported calendar/identity pages stay on the
    existing single-base executor.
    """
    config = engine._cfg
    if composition_contract is not None:
        engine._interval_resolver.require_history_composition(exchange=key.exchange,
            market_type=key.market_type, interval=key.interval, contract_id=composition_contract,
            identity=key.identity, enabled=config.mixed_custom_history
                and (engine.history_policy is None
                     or isinstance(engine._calendar_for(key), AlwaysOpenCalendar)))
    if not config.mixed_custom_history:
        return None
    spec = parse_interval_spec(key.interval)
    if (spec is None or spec.alignment is not IntervalAlignment.FIXED_EPOCH
            or not key.identity.is_legacy_default_for(key.exchange) or limit <= 0):
        return None
    calendar = engine._calendar_for(key)
    if calendar is not None and not isinstance(calendar, AlwaysOpenCalendar):
        return None
    upper = before_ms - 1 if before_ms is not None else end_ms
    if upper is None:
        return None
    last = spec.floor_ms(int(upper))
    stop = spec.next_ms(last)
    if stop > int(time.time() * 1000) or last < 0:
        return None
    first = max(spec.phase_ms, last - (limit - 1) * spec.nominal_ms)
    if start_ms is not None:
        lower = spec.floor_ms(int(start_ms))
        if lower < start_ms:
            lower = spec.next_ms(lower)
        first = max(first, lower)
    if first > last:
        return None
    resolver = engine._interval_resolver
    declaration = resolver.history_composition_routes(exchange=key.exchange,
        market_type=key.market_type, interval=key.interval)
    storage = engine.storage
    manager = getattr(engine, "shared_blocks", None)
    store = getattr(storage, "revision_store", None)
    if declaration is None or manager is None or store is None:
        return None
    policy, routes, precedence_routes = declaration
    single = resolver.resolve(exchange=key.exchange, market_type=key.market_type,
                              interval=key.interval, purpose=IntervalPurpose.HISTORY)
    base_spec = parse_interval_spec(single.base_interval)
    if (composition_contract is None and base_spec is not None
            and base_spec.nominal_ms >= max(route.spec.nominal_ms for route in routes)):
        # Preserve the cheaper existing coarse-source route when the qualified
        # mixed grids cannot reduce its input count (e.g. 45m from 15m).
        return None
    sources = tuple(FixedHistorySource(replace(key, interval=route.canonical_interval),
        route.spec.nominal_ms, route.spec.phase_ms, ((0, stop),), frozenset(policy.fields),
        policy.contract_id) for route in routes)
    # Unqualified native grids cannot be selected, but their known canonical
    # contents/deletions must still prevent bypassing a finer correction.
    precedences = tuple((replace(key, interval=route.canonical_interval), route.spec.nominal_ms)
                        for route in precedence_routes)
    keys = tuple(source for source, _ in precedences)
    history_policy = engine.history_policy
    floor = acquisition_revision()
    if floor is None:
        floor = store.head()
    report.update(mixed_history_attempted=True, mixed_page_reads=0, mixed_page_rows=0,
                  mixed_cache_hits=0, mixed_probe_reads=0, mixed_probe_rows=0,
                  mixed_count_reads=0, mixed_count_rows=0, mixed_count_failures=0,
                  mixed_presence_reads=0, mixed_presence_rows=0, mixed_presence_failures=0,
                  mixed_preflight_positions=0,
                  mixed_fallbacks=0, mixed_accepted_rows=0, mixed_planned_rows=0,
                  mixed_contract=policy.contract_id)
    expected_base_rows = (stop - first) // base_spec.nominal_ms if base_spec is not None else 0
    if (base_spec is not None and first % base_spec.nominal_ms == 0
            and stop % base_spec.nominal_ms == 0 and 0 < expected_base_rows
            <= CUSTOM_HISTORY_MAX_BASE_PAGES * min(config.max_limit, CUSTOM_HISTORY_SOURCE_PAGE_ROWS)
            and (expected_base_rows <= config.max_limit or (stop-first)//spec.nominal_ms > 1)
            and callable(getattr(storage, "count_bars", None))):
        report["mixed_count_reads"] += 1
        try:
            count = engine._count_canonical_history_rows(storage,
                replace(key, interval=single.base_interval), first, stop)
        except StaleAcquisition:
            raise
        except Exception:
            report.update(mixed_count_failures=1, mixed_fallback_reason="local_cost_probe_failed")
            return None
        report["mixed_count_rows"] = 1
        near_complete_stream = (expected_base_rows > config.max_limit and count > 0
            and 0 < expected_base_rows-count <= min(config.max_limit, CUSTOM_HISTORY_SOURCE_PAGE_ROWS))
        if (count >= expected_base_rows or near_complete_stream) and composition_contract is None:
            # Only a cost preference: the original executor still validates
            # every actual row, gap, field, grid, finality and acquisition.
            report["mixed_fallback_reason"] = "local_single_base_preferred"
            return None

    def binding():
        if (engine.storage is not storage or engine.shared_blocks is not manager
                or engine._cfg is not config or not config.mixed_custom_history
                or engine.history_policy is not history_policy or engine._interval_resolver is not resolver
                or resolver.history_composition_routes(exchange=key.exchange,
                    market_type=key.market_type, interval=key.interval) != declaration):
            raise BlockRevisionChanged("mixed query binding or qualification changed")

    def page(receipt):
        report["mixed_page_reads"] += receipt.storage_reads
        report["mixed_page_rows"] += receipt.storage_rows
        report["mixed_cache_hits"] += receipt.cache_hits

    values = [(source.exchange, source.market_type, source.symbol, source.interval,
               *source.identity.storage_values) for source in keys]
    # A finer precedence bar opening before a target can still overlap it.
    lead = max((width for _, width in precedences), default=0)

    def compose(batch_start, batch_stop, probe_cover, out, counts):
        """Targets in [batch_start, batch_stop) inside one view; publish nothing.

        ``counts`` keeps this attempt's TARGET_COUNTERS, which are also
        reported as each target is read (as one whole-page view did).
        """
        with manager.view(keys, acquired_at=None if BATCH_VIEWS else floor) as view:
            binding()
            try:
                _, changes = store.read_series_changes(values)
            except Exception as exc:
                raise StaleAcquisition("mixed precedence evidence unavailable") from exc
            versions = {revision.series: revision.version for revision in view.revisions}
            if any((change["revision"] if change else 0) != versions[source]
                   for source, change in zip(keys, changes)):
                raise BlockRevisionChanged("mixed precedence evidence changed")
            if BATCH_VIEWS:
                # This view may be newer than the floor: what it reads must not
                # differ from the floor, so every batch is as of the floor.
                check_store_range(store, values, max(0, batch_start - lead), batch_stop, floor)
            mutations = dict(zip(keys, changes))

            resident = getattr(manager, 'has_resident_inputs', None)
            if (probe_cover and callable(getattr(storage, 'count_bars', None)) and callable(resident)
                    and not resident(view, first, stop)):
                # Even counting every row (including untrusted, overlapping
                # or cross-boundary inputs) cannot cover more than this
                # duration. A shortage can skip an expensive exact-cover
                # attempt, but a sufficient count grants no authority.
                upper = 0
                for source in sources:
                    report['mixed_count_reads'] += 1
                    try:
                        count = engine._count_canonical_history_rows(storage, source.series, first, stop)
                    except StaleAcquisition:
                        raise
                    except Exception as exc:
                        report['mixed_count_failures'] += 1
                        raise BlockUnavailable('mixed local coverage count unavailable') from exc
                    report['mixed_count_rows'] += 1
                    if type(count) is not int or count < 0:
                        raise BlockUnavailable('mixed local coverage count unavailable') from ValueError('invalid count')
                    upper += count * source.width_ms
                    if upper >= stop - first:
                        break
                report['mixed_local_coverage_upper_ms'] = upper
                if upper < stop - first:
                    binding()
                    report['mixed_impossible_local_cover'] = True
                    raise BlockUnavailable('mixed history source has unavailable coverage or fields')

            probes = MixedPrecedence(engine, storage, key, sources, precedences, mutations, report)
            session = MixedHistorySession(engine, view, floor) if SESSION_READS else None
            pages = (engine.memory_budget.reserve("history-query", MixedHistorySession.PAGE_BYTES)
                     if session is not None else nullcontext())
            with pages:
                for group in range(batch_start, batch_stop, spec.nominal_ms * BATCH_TARGETS):
                    opens = range(group, min(batch_stop, group + spec.nominal_ms * BATCH_TARGETS),
                                  spec.nominal_ms)
                    probes.prepare(opens, spec.nominal_ms)
                    for opened in opens:
                        with engine.read_mixed_history_blocks(key, opened, opened + spec.nominal_ms,
                                sources, required_fields=frozenset(policy.fields),
                                admit_span=probes.admits, on_page=page,
                                **({"session": session} if session is not None else {})) as read:
                            pass
                        if any(revision.version != versions[revision.series] for revision in read.receipt.revisions):
                            raise BlockRevisionChanged("mixed target generations differ")
                        receipt = read.receipt
                        for slot, value in enumerate((receipt.planned_rows, receipt.accepted_rows, receipt.fallbacks)):
                            counts[slot] += value
                            report[TARGET_COUNTERS[slot]] += value
                        out.append(BarData(time=opened // 1000, is_closed=True, source="backfill_aggregated",
                            **read.summary.values.project(enhanced_complete=True)))
            binding()

    bars = []
    computation = None
    try:
        # Keep staged output charged through the caller's materialization/cache
        # adoption, rather than releasing it when this helper returns.
        reserve_work(engine.memory_budget, "history-query", limit * 1024)
        with engine.memory_budget.reserve("history-query", 64 * 1024 + WORK_BYTES):
            if READ_PROOF:
                computation = capture_read_computation(store, current_acquisition(),
                    (key.exchange, key.market_type, key.symbol, key.interval, *key.identity.storage_values),
                    tuple(values), first, last, spec.nominal_ms, floor)
            step = spec.nominal_ms * BATCH_TARGETS if BATCH_VIEWS else stop - first
            for index, batch_start in enumerate(range(first, stop, step)):
                for attempt in range(BATCH_ATTEMPTS if BATCH_VIEWS else 1):
                    out, counts = [], [0, 0, 0]
                    try:
                        compose(batch_start, min(stop, batch_start + step), index == 0, out, counts)
                        break
                    except BlockRevisionChanged:
                        if not BATCH_VIEWS or attempt + 1 == BATCH_ATTEMPTS:
                            raise
                        # Its targets are composed again: count them once.
                        for name, value in zip(TARGET_COUNTERS, counts):
                            report[name] -= value
                        report["mixed_view_retries"] = report.get("mixed_view_retries", 0) + 1
                bars.extend(out)
            binding()
    except BlockRevisionChanged as exc:
        raise StaleAcquisition("mixed history precedence/publication view changed") from exc
    except CoverBudgetExceeded:
        report["mixed_fallback_reason"] = "planning_budget"
        return None
    except (BlockUnavailable, CoverUnavailable) as exc:
        report["mixed_fallback_reason"] = str(exc)
        if (isinstance(exc, BlockUnavailable) and exc.__cause__ is None
                and str(exc) in {"mixed history source has unavailable coverage or fields",
                                 "mixed history cannot prove complete authoritative coverage"}
                and base_spec is not None and (composition_contract is not None
                    or (stop - first) // base_spec.nominal_ms > config.max_limit)):
            # A large legacy base-window reservation can defer before it ever
            # reports a gap. Surface the actual closed target demand to the
            # existing DataManager scheduler instead of silently starving it.
            allow = config.auto_backfill if auto_backfill is None else bool(auto_backfill)
            # The target probe precedes this optional mixed read under the
            # original query acquisition fence. Missing source coverage must
            # not discard already committed, individually final target rows.
            target_lower = first if start_ms is not None else spec.phase_ms
            partial = ([bar for bar in materialized_result.bars
                        if bar.trusted_final and target_lower <= bar.time_ms < stop
                        and spec.floor_ms(bar.time_ms) == bar.time_ms]
                       if materialized_result is not None else [])
            spans, cursor = [], first
            for opened in sorted({bar.time_ms for bar in partial if bar.time_ms >= first}):
                if cursor < opened:
                    spans.append((cursor, opened - spec.nominal_ms))
                cursor = opened + spec.nominal_ms
            if cursor < stop:
                spans.append((cursor, last))
            missing = [gap for lo, hi in spans if (gap := engine._trigger_backfill(
                key, lo, hi, reason="query_empty", missing_bars=(hi - lo) // spec.nominal_ms + 1,
                submit=allow)) is not None]
            if missing:
                return QueryResult(bars=partial, symbol=key.symbol, interval=key.interval,
                    exchange=key.exchange, market_type=key.market_type,
                    source=materialized_result.source if partial else QuerySource.EMPTY,
                    total=len(partial),
                    complete=False, retryable=True, history_state="pending", has_more=True,
                    missing_ranges=missing, backfill_triggered=bool(allow and engine._backfill_trigger),
                    metadata={**report, "derived_from": "mixed", "mixed_target_repair": True,
                        "mixed_partial_materialized": bool(partial),
                        "target_partial_materialized_rows": len(partial),
                        "storage_reads": report["mixed_page_reads"] + report["mixed_probe_reads"]
                            + report["mixed_count_reads"] + report["mixed_presence_reads"],
                        "storage_rows": report["mixed_page_rows"] + report["mixed_probe_rows"]
                            + report["mixed_count_rows"] + report["mixed_presence_rows"]})
        return None
    return QueryResult(bars=bars, symbol=key.symbol, interval=key.interval, exchange=key.exchange,
        market_type=key.market_type, source=QuerySource.STORAGE, total=len(bars),
        has_more=first > 0, cache_hit=False, complete=True,
        next_before_ms=first if first > 0 else None,
        metadata={**report, "mixed_history": True, "all_rows_final": True,
                  "storage_reads": report["mixed_page_reads"] + report["mixed_probe_reads"] + report["mixed_count_reads"] + report["mixed_presence_reads"],
                  "storage_rows": report["mixed_page_rows"] + report["mixed_probe_rows"] + report["mixed_count_rows"] + report["mixed_presence_rows"],
                  "derived_from": "mixed", "mixed_acquisition_revision": floor},
        _closed_target_read=(ClosedMixedRead(storage, store, computation, tuple(bars))
                             if computation is not None else None))
