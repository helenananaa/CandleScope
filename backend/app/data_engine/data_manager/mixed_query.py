"""Default closed-history consumer of H127, with conservative local precedence.

Provider capability owns composability. Existing finer canonical data (even
partial/untrusted) takes precedence over independent native coarse candles.
Missing finer data alone is not proof after a deletion. All probes and target
pages share a final D126/B130 view; no output is adopted inside that view.
"""
from __future__ import annotations

from dataclasses import replace
import time

from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.history.cover_plan import CoverBudgetExceeded, CoverUnavailable, FixedHistorySource
from app.data_engine.history import AlwaysOpenCalendar
from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
from app.data_engine.interval_resolution import IntervalPurpose
from app.data_engine.memory_budget import reserve_work
from app.data_engine.storage.revisions import acquisition_revision, StaleAcquisition
from .models import BarData, QueryResult, QuerySource
from .mixed_precedence import MixedPrecedence, BATCH_TARGETS, WORK_BYTES


def query_closed_mixed(engine, key, *, start_ms=None, end_ms=None, before_ms=None,
                       limit, report, auto_backfill=None):
    """Try a bounded closed page; unavailable inputs keep the original route.

    A stale view never falls back into a new generation. ``report`` contains
    only work counters/reasons, including abandoned reads, not staged market
    data. Current/forming and unsupported calendar/identity pages stay on the
    existing single-base executor.
    """
    config = engine._cfg
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
    if base_spec is not None and base_spec.nominal_ms >= max(route.spec.nominal_ms for route in routes):
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
            and stop % base_spec.nominal_ms == 0 and 0 < expected_base_rows <= engine._cfg.max_limit
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
        if count >= expected_base_rows:
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

    bars = []
    try:
        # Keep staged output charged through the caller's materialization/cache
        # adoption, rather than releasing it when this helper returns.
        reserve_work(engine.memory_budget, "history-query", limit * 1024)
        with engine.memory_budget.reserve("history-query", 64 * 1024 + WORK_BYTES):
            with manager.view(keys, acquired_at=floor) as view:
                binding()
                values = [(source.exchange, source.market_type, source.symbol, source.interval,
                           *source.identity.storage_values) for source in keys]
                try:
                    _, changes = store.read_series_changes(values)
                except Exception as exc:
                    raise StaleAcquisition("mixed precedence evidence unavailable") from exc
                versions = {revision.series: revision.version for revision in view.revisions}
                if any((change["revision"] if change else 0) != versions[source]
                       for source, change in zip(keys, changes)):
                    raise BlockRevisionChanged("mixed precedence evidence changed")
                mutations = dict(zip(keys, changes))

                probes = MixedPrecedence(engine, storage, key, sources, precedences, mutations, report)
                for batch_start in range(first, stop, spec.nominal_ms * BATCH_TARGETS):
                    opens = range(batch_start, min(stop, batch_start + spec.nominal_ms * BATCH_TARGETS),
                                  spec.nominal_ms)
                    probes.prepare(opens, spec.nominal_ms)
                    for opened in opens:
                        with engine.read_mixed_history_blocks(key, opened, opened + spec.nominal_ms,
                                sources, required_fields=frozenset(policy.fields),
                                admit_span=probes.admits, on_page=page) as read:
                            pass
                        if any(revision.version != versions[revision.series] for revision in read.receipt.revisions):
                            raise BlockRevisionChanged("mixed target generations differ")
                        receipt = read.receipt
                        report["mixed_planned_rows"] += receipt.planned_rows
                        report["mixed_accepted_rows"] += receipt.accepted_rows
                        report["mixed_fallbacks"] += receipt.fallbacks
                        bars.append(BarData(time=opened // 1000, is_closed=True, source="backfill_aggregated",
                            **read.summary.values.project(enhanced_complete=True)))
                binding()
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
                and base_spec is not None and (stop - first) // base_spec.nominal_ms > config.max_limit):
            # A large legacy base-window reservation can defer before it ever
            # reports a gap. Surface the actual closed target demand to the
            # existing DataManager scheduler instead of silently starving it.
            allow = config.auto_backfill if auto_backfill is None else bool(auto_backfill)
            missing = engine._trigger_backfill(key, first, last, reason="query_empty",
                missing_bars=(stop - first) // spec.nominal_ms, submit=allow)
            if missing is not None:
                return QueryResult(bars=[], symbol=key.symbol, interval=key.interval,
                    exchange=key.exchange, market_type=key.market_type, source=QuerySource.EMPTY,
                    complete=False, retryable=True, history_state="pending", has_more=True,
                    missing_ranges=[missing], backfill_triggered=bool(allow and engine._backfill_trigger),
                    metadata={**report, "derived_from": "mixed", "mixed_target_repair": True,
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
                  "derived_from": "mixed", "mixed_acquisition_revision": floor})
