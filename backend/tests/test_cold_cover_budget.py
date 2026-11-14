"""Cold comparison costs, hard work limits and actual owner cancellation."""
import asyncio
import threading

import pytest

from app.data_engine.backfill.cold_cover import choose_cold_sources
from app.data_engine.backfill import mixed_plan
from app.data_engine.history.cover_plan import FixedHistorySource, plan_fixed_batch
from app.data_engine.storage.revisions import ensure_acquisition, StaleAcquisition
from app.data_engine.series_key import SeriesKey
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_plan import engine_for, gap, propose
from tests.test_mixed_history_reader import FIELDS, MINUTE

TARGET = SeriesKey('BTCUSDT', '10007m', market_type='futures')
WIDTH = 10007 * MINUTE


def choose(**overrides):
    sources = tuple(FixedHistorySource(SeriesKey('BTCUSDT', interval, market_type='futures'),
        minutes * MINUTE, 0, ((0, WIDTH),), FIELDS, 'fixture/qualified')
        for interval, minutes in [('1m', 1), ('5m', 5), ('15m', 15), ('1h', 60), ('4h', 240), ('1d', 1440)])
    options = dict(required_fields=FIELDS, target_width=WIDTH, base_width=MINUTE,
        page_size=1000, task_page_size=1000, max_rows=16_384, max_tasks=4096,
        max_positions=65_536)
    options.update(overrides)
    return choose_cold_sources(TARGET, 0, WIDTH, sources, **options)


@pytest.mark.parametrize('page,requests', [(1000, 2), (32, 4)])
def test_cold_choice_uses_request_page_cost_and_replays_an_exact_cover(page, requests):
    choice = choose(page_size=page, task_page_size=page)
    assert choice.requests == requests and choice.sources is not None
    batch = plan_fixed_batch(TARGET, 0, WIDTH, choice.sources, required_fields=FIELDS)
    assert batch.planned_range == (0, WIDTH) and batch.next_start_ms is None
    assert batch.planned_rows == choice.rows <= 16_384
    assert sum(span.end_ms - span.start_ms for cover in batch.covers for span in cover.spans) == WIDTH
    assert 0 < choice.positions <= 65_536 and 0 < choice.candidates <= 32


def test_later_search_budget_does_not_discard_an_already_feasible_choice():
    choice = choose(max_positions=100)
    assert choice.sources is not None and choice.reason is None
    assert choice.positions == 100 and choice.requests <= 5
    assert plan_fixed_batch(TARGET, 0, WIDTH, choice.sources).planned_range == (0, WIDTH)


def test_planning_does_not_rewalk_all_earlier_tasks_for_every_new_span(mixed_query, monkeypatch):
    original = mixed_plan.retained_size
    visited = 0
    def observed(*args, **kwargs):
        nonlocal visited
        result = original(*args, **kwargs)
        visited += result[1]
        return result
    monkeypatch.setattr(mixed_plan, 'retained_size', observed)
    plan, _ = propose(engine_for(mixed_query), mixed_query, gap(count=16))
    assert plan is not None
    assert visited < 64 * (len(plan.tasks) + len(plan.derived_source_windows))


def test_incremental_accounting_covers_the_actual_retained_task_graph(mixed_query, monkeypatch):
    original = mixed_plan._MixedBackfillBuilder._check_work
    checks = []
    def observed(builder, *args, **kwargs):
        original(builder, *args, **kwargs)
        actual, _ = mixed_plan.retained_size((builder.tasks, builder.windows, builder.presence,
                                             builder._task_seen, builder.gap))
        checks.append(actual)
        assert actual <= builder.report['mixed_plan_work_bytes'] <= mixed_plan.WORK_BYTES
    monkeypatch.setattr(mixed_plan._MixedBackfillBuilder, '_check_work', observed)
    plan, _ = propose(engine_for(mixed_query), mixed_query, gap(count=2))
    assert plan is not None and len(checks) > 2


def test_shared_gap_metadata_growth_is_still_charged_after_its_first_task(mixed_query, monkeypatch):
    engine = engine_for(mixed_query)
    requested = gap()
    original = engine._storage.query_canonical_page
    calls = 0
    async def changed(*args, **kwargs):
        nonlocal calls
        rows = await original(*args, **kwargs)
        calls += 1
        if calls == 2:
            requested.metadata['work-budget-witness'] = bytearray(mixed_plan.WORK_BYTES)
        return rows
    monkeypatch.setattr(engine._storage, 'query_canonical_page', changed)
    plan, report = propose(engine, mixed_query, requested)
    assert calls == 2 and plan is None and report['mixed_plan_fallback'] == 'task_work_budget'


@pytest.mark.parametrize('limits,reason', [
    ({'max_rows': 1}, 'source_row_budget'),
    ({'max_tasks': 1}, 'task_work_budget'),
    ({'max_positions': 1}, 'planning_work_budget'),
])
def test_unavailable_work_budget_never_returns_a_partial_cover(limits, reason):
    choice = choose(**limits)
    assert choice.sources is None and choice.reason == reason
    assert choice.positions <= limits.get('max_positions', 65_536)


def test_rollout_change_during_cold_comparison_cannot_issue_the_old_plan(mixed_query, monkeypatch):
    engine = engine_for(mixed_query)
    original = mixed_plan.choose_cold_sources
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        engine.config.mixed_custom_history = False
        return result
    monkeypatch.setattr(mixed_plan, 'choose_cold_sources', changed)
    async def forbidden(*args, **kwargs):
        raise AssertionError('old cold proposal reached canonical inputs')
    monkeypatch.setattr(engine._storage, 'query_canonical_page', forbidden)
    async def run():
        with ensure_acquisition(mixed_query.storage.revision_store.head()):
            with pytest.raises(StaleAcquisition):
                await mixed_plan.build_mixed_backfill_plan(engine, [gap()], {}, {})
        await engine.close()
    asyncio.run(run())


def test_cancel_keeps_the_existing_work_reservation_until_physical_comparison_exits(mixed_query, monkeypatch):
    engine = engine_for(mixed_query)
    entered, release = threading.Event(), threading.Event()
    original = mixed_plan.choose_cold_sources
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(mixed_plan, 'choose_cold_sources', blocked)
    async def forbidden(*args, **kwargs):
        raise AssertionError('cancelled proposal reached canonical inputs')
    monkeypatch.setattr(engine._storage, 'query_canonical_page', forbidden)
    async def proposal():
        with ensure_acquisition(mixed_query.storage.revision_store.head()):
            return await mixed_plan.build_mixed_backfill_plan(engine, [gap()], {}, {})
    async def run():
        task = asyncio.create_task(proposal())
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not task.done()
            assert mixed_query.memory_budget.snapshot()['reserved_bytes'] >= mixed_plan.WORK_BYTES + mixed_plan.PLAN_BYTES
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert mixed_query.memory_budget.snapshot()['reserved_bytes'] == 0
        finally:
            release.set()
            if not task.done():
                await asyncio.gather(task, return_exceptions=True)
            await engine.close()
    asyncio.run(run())
