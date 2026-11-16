"""Qualified cold proposals against the actual bounded canonical repository."""
import asyncio

import pytest

from app.data_engine.backfill import BackfillEngine
from app.data_engine.backfill.config import BackfillConfig
from app.data_engine.backfill.mixed_plan import build_mixed_backfill_plan
from app.data_engine.backfill.models import GapInfo, GapType
from app.data_engine.interval_policy import parse_interval_ms
from app.data_engine.storage.klines_repo import AsyncKlinesRepoAdapter
from app.data_engine.storage.revisions import ensure_acquisition, StaleAcquisition
from tests.test_default_mixed_history_query import mixed_query, seed
from tests.test_mixed_history_reader import row, MINUTE


def gap(period=10007, count=1):
    return GapInfo("BTCUSDT", f"{period}m", GapType.HEAD, 0, (count - 1) * period * MINUTE,
                   count, market_type="futures")


def engine_for(query):
    cfg = BackfillConfig()
    cfg.history_archive_enabled = False
    engine = BackfillEngine(cfg, storage=AsyncKlinesRepoAdapter())
    engine.memory_budget = query.memory_budget
    return engine


def propose(engine, query, requested, report=None):
    report = report if report is not None else {}
    async def run():
        with ensure_acquisition(query.storage.revision_store.head()):
            return await build_mixed_backfill_plan(engine, [requested], {}, report)
    return asyncio.run(run()), report


def test_cold_large_prime_proposes_exact_mixed_inputs_and_component_scoped_routing(mixed_query):
    query = mixed_query
    engine = engine_for(query)
    plan, report = propose(engine, query, gap())
    assert plan is not None and report["mixed_history"]
    assert plan.metadata["mixed_source_rows"] == 669
    assert plan.estimated_requests < plan.metadata["single_base_estimated_rest_requests"]
    intervals = {task.interval for task in plan.tasks}
    assert intervals == {"15m", "1m"}
    assert plan.estimated_requests == 2
    at = 0
    for task in sorted(plan.derived_source_windows, key=lambda task: task.start_ms):
        width = parse_interval_ms(task.interval)
        assert task.start_ms == at
        assert task.metadata["ledger_range"]["start_ms"] <= task.start_ms
        assert task.metadata["ledger_range"]["end_ms"] >= task.end_ms
        assert task.metadata["custom_interval"] == "10007m"
        assert task.parent_gap.interval == "10007m"
        at = task.end_ms + width
    assert at == 10007 * MINUTE
    assert plan.decompositions[0].composition_policy is not None
    assert plan.decompositions[0].composition_target_range == (0, 10007 * MINUTE)
    assert plan.decompositions[0].to_dict()["history_composition"]["fields"]
    assert plan.decompositions[0].to_dict()["component_count_scope"] == "requested_target_range"
    assert sum(c.count * c.duration_ms for c in plan.decompositions[0].components) == 10007 * MINUTE
    assert sum(w["rows"] for w in plan.to_dict()["mixed_source_windows"]) == report["mixed_source_rows"]


def test_cold_prime_viewport_fits_existing_budget_with_proven_coarse_grids(mixed_query):
    query = mixed_query
    requested = gap(count=128)
    plan, report = propose(engine_for(query), query, requested)
    assert plan is not None, report
    assert {'4h', '1d'} & {task.interval for task in plan.tasks}
    assert report['mixed_source_rows'] <= 16_384
    assert plan.estimated_requests <= report['single_base_estimated_rest_requests']
    assert plan.estimated_requests < 973  # Earlier six-grid greedy proposal.
    assert plan.decompositions[0].composition_target_range == (0, 128 * 10007 * MINUTE)
    assert sum(component.count * component.duration_ms
               for component in plan.decompositions[0].components) == 128 * 10007 * MINUTE
    assert query.storage.count_bars('BTCUSDT', '1m', 0, 128 * 10007 * MINUTE - 1,
                                   market_type='futures') == 0


def test_cold_small_query_keeps_single_rest_page_instead_of_fanning_out(mixed_query):
    plan, report = propose(engine_for(mixed_query), mixed_query, gap(89))
    assert plan is None and report["mixed_plan_fallback"] == "cold_rest_request_cost"
    assert report["mixed_plan_input_pages"] == report["mixed_plan_probe_reads"] == 0


def test_local_native_components_need_no_refetch_but_keep_full_materialization_inputs(mixed_query):
    query = mixed_query
    seed(query, period=10007, count=1)
    plan, report = propose(engine_for(query), query, gap())
    assert plan is not None and not plan.tasks and plan.derived_source_windows
    assert plan.estimated_requests == plan.estimated_bars == 0
    assert report["mixed_source_rows"] < 200
    assert query.storage.count_bars("BTCUSDT", "10007m", 0, 10007 * MINUTE - 1,
                                     market_type="futures") == 0


def test_partial_finer_amendment_prevents_reusing_independent_coarse_plan(mixed_query):
    query = mixed_query
    seed(query, period=10007, count=1)
    query.storage.upsert_bars("BTCUSDT", "3m", [{**row(99 * MINUTE, 3 * MINUTE), "volume": 20}],
                             source="data_manager_amended", market_type="futures")
    plan, report = propose(engine_for(query), query, gap())
    assert report["mixed_plan_refinements"] > 0
    if plan is not None:
        for task in plan.derived_source_windows:
            assert not (parse_interval_ms(task.interval) > 3 * MINUTE
                        and task.start_ms <= 99 * MINUTE <= task.end_ms)


@pytest.mark.parametrize("mutation", ["source", "rollout", "calendar"])
def test_planning_source_and_rollout_changes_cannot_issue_old_native_plan(mixed_query, monkeypatch, mutation):
    query = mixed_query
    seed(query, period=10007, count=1)
    engine = engine_for(query)
    original = engine._storage.query_canonical_page
    fired = False
    async def changed(*args, **kwargs):
        nonlocal fired
        rows = await original(*args, **kwargs)
        if not fired:
            fired = True
            if mutation == "source":
                query.storage.upsert_bars("BTCUSDT", "3m", [row(99 * MINUTE, 3 * MINUTE)],
                                         source="data_manager_amended", market_type="futures")
            elif mutation == "rollout":
                engine.config.mixed_custom_history = False
            else:
                engine.detector.set_calendar_resolver(lambda *args: "unknown.session")
        return rows
    monkeypatch.setattr(engine._storage, "query_canonical_page", changed)
    with pytest.raises(StaleAcquisition):
        propose(engine, query, gap())
    assert fired


def test_rollback_keeps_the_existing_planner_and_canonical_inputs(mixed_query):
    engine = engine_for(mixed_query)
    engine.config.mixed_custom_history = False
    plan, report = propose(engine, mixed_query, gap())
    assert plan is None and report == {}
    legacy = engine.planner.plan([gap()])
    assert {task.interval for task in legacy.tasks} == {"1m"}


def test_unknown_calendar_cannot_gain_mixed_native_source_qualification(mixed_query):
    engine = engine_for(mixed_query)
    engine.detector.set_calendar_resolver(lambda *args: "unknown.session")
    plan, report = propose(engine, mixed_query, gap())
    assert plan is None and not report
