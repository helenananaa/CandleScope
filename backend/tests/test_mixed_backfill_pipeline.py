"""Actual default backfill/reconcile/writer pipeline with deterministic upstream records."""
import asyncio

import pytest

from app.data_engine.backfill.models import FetchResult, FetchedBar, BackfillStatus
from app.data_engine.storage.klines_repo import AsyncKlinesRepoAdapter
from app.data_engine.interval_policy import parse_interval_ms
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_history_reader import row, MINUTE
from tests.test_backfill_coordinator import _quota_deferral

ENHANCED = frozenset({"quote_volume", "trades", "taker_buy_base", "taker_buy_quote"})
META = dict(requires_trusted_finality=True, requester="klines_range", history_calendar_id="crypto.24x7.utc")


class Upstream:
    def __init__(self, *, unknown_hour=False, import_extra_fine=False):
        self.unknown_hour = unknown_hour
        self.import_extra_fine = import_extra_fine
        self.calls = []

    async def fetch(self, tasks, **_):
        self.calls.extend(tasks)
        if self.import_extra_fine:
            self.import_extra_fine = False
            # Model an existing archive owner committing additional fine rows
            # under the same acquisition; this is not an external generation.
            await AsyncKlinesRepoAdapter().upsert_bars("BTCUSDT", "1m", [{
                **row(0, MINUTE), "volume": 77, "quote_volume": 154, "trades": 77,
                "taker_buy_base": 77, "taker_buy_quote": 154}],
                source="backfill_archive_verified", market_type="futures")
        results = []
        for task in tasks:
            width = parse_interval_ms(task.interval)
            values = []
            for opened in range(task.start_ms, task.end_ms + 1, width):
                data = row(opened, width)
                values.append(FetchedBar(symbol=task.symbol, interval=task.interval,
                    exchange=task.exchange, market_type=task.market_type,
                    **data, enhanced_fields=frozenset() if self.unknown_hour and task.interval == "1h" else ENHANCED))
            results.append(FetchResult(task, values))
        return results


def repair(engine):
    return engine.run("BTCUSDT", intervals=["10007m"], range_start_ms=0, range_end_ms=0,
                      exchange="binance", market_type="futures", metadata=META)


def test_default_cold_pipeline_fetches_native_mixed_inputs_and_materializes_only_target(mixed_query):
    engine = engine_for(mixed_query)
    upstream = Upstream()
    engine._fetcher = upstream
    report = asyncio.run(repair(engine))
    assert report.status == BackfillStatus.COMPLETED, report.errors
    assert report.metadata["mixed_history"] and report.plan.estimated_requests < 11
    assert report.plan.mixed_binding is None
    assert report.reconcile_result.custom_bars_written == 1
    assert {task.interval for task in upstream.calls} == {"1h", "15m", "1m"}
    result = mixed_query.query("BTCUSDT", "10007m", start_ms=0, end_ms=10007 * MINUTE - 1,
        limit=1, market_type="futures", min_revision=mixed_query.storage.revision_store.head())
    assert result.complete and result.bars[0].trusted_final
    assert result.bars[0].volume == result.bars[0].trades == 10007
    assert result.metadata["target_materialized"]
    assert mixed_query.storage.count_bars("BTCUSDT", "1m", 0, 10007 * MINUTE - 1,
                                           market_type="futures") == 2
    assert any(w.interval == "10007m" and w.bars_written == 1 for w in report.written_ranges)
    assert not any(w.interval == "1m" and w.bars_written == 10007 for w in report.written_ranges)


def test_unknown_coarse_fields_remain_pending_then_retry_refines_from_canonical(mixed_query):
    engine = engine_for(mixed_query)
    upstream = Upstream(unknown_hour=True)
    engine._fetcher = upstream
    async def run():
        first = await repair(engine)
        assert first.status == BackfillStatus.PARTIAL
        assert first.reconcile_result.custom_bars_written == first.reconcile_result.write_errors == 0
        assert any("coverage incomplete" in error.lower() for error in first.errors)
        assert mixed_query.storage.count_bars("BTCUSDT", "10007m", 0, 10007 * MINUTE - 1,
                                               market_type="futures") == 0
        previous = len(upstream.calls)
        second = await repair(engine)
        assert second.status == BackfillStatus.COMPLETED, second.errors
        assert second.reconcile_result.custom_bars_written == 1
        assert "1h" not in {task.interval for task in upstream.calls[previous:]}
    asyncio.run(run())


def test_additional_owned_fine_import_invalidates_coarse_proposal_before_target_write(mixed_query):
    engine = engine_for(mixed_query)
    engine._fetcher = Upstream(import_extra_fine=True)
    async def run():
        first = await repair(engine)
        assert first.status == BackfillStatus.PARTIAL, first.errors
        assert first.reconcile_result.custom_bars_written == 0
        assert mixed_query.storage.count_bars("BTCUSDT", "10007m", 0, 10007 * MINUTE - 1,
                                               market_type="futures") == 0
        second = await repair(engine)
        assert second.status == BackfillStatus.COMPLETED, second.errors
        result = mixed_query.query("BTCUSDT", "10007m", start_ms=0, end_ms=10007 * MINUTE - 1,
            limit=1, market_type="futures", min_revision=mixed_query.storage.revision_store.head())
        assert result.complete and result.bars[0].volume == 10007 + 76
    asyncio.run(run())


def test_quota_deferral_keeps_committed_native_inputs_and_retry_does_not_refetch_them(mixed_query):
    engine = engine_for(mixed_query)
    engine.config.fetch_batch_size = 2
    class Deferred(Upstream):
        once = True
        async def fetch(self, tasks, **options):
            if self.once:
                self.once = False
                completed = await super().fetch(tasks[:2])
                await options["on_deferred"](completed)
                raise _quota_deferral(1)
            return await super().fetch(tasks, **options)
    upstream = Deferred()
    engine._fetcher = upstream
    async def run():
        from app.exchanges.rate_limits import RateLimitDeferred
        with pytest.raises(RateLimitDeferred):
            await repair(engine)
        assert mixed_query.storage.count_bars("BTCUSDT", "10007m", 0, 10007 * MINUTE - 1,
                                               market_type="futures") == 0
        first_keys = {task.task_key for task in upstream.calls}
        assert len(first_keys) == 2
        previous = len(upstream.calls)
        report = await repair(engine)
        assert report.status == BackfillStatus.COMPLETED, report.errors
        assert not first_keys & {task.task_key for task in upstream.calls[previous:]}
        assert report.reconcile_result.custom_bars_written == 1
    asyncio.run(run())


def test_rollback_before_materialization_rejects_old_plan_and_original_route_can_rebuild(mixed_query):
    engine = engine_for(mixed_query)
    class Switch(Upstream):
        async def fetch(self, tasks, **options):
            results = await super().fetch(tasks, **options)
            engine.config.mixed_custom_history = False
            return results
    engine._fetcher = Switch()
    async def run():
        first = await repair(engine)
        assert first.status != BackfillStatus.COMPLETED
        assert mixed_query.storage.count_bars("BTCUSDT", "10007m", 0, 10007 * MINUTE - 1,
                                               market_type="futures") == 0
        engine._fetcher = Upstream()
        second = await repair(engine)
        assert second.status == BackfillStatus.COMPLETED, second.errors
        assert not second.plan.metadata.get("mixed_history")
        assert {task.interval for task in second.plan.tasks} == {"1m"}
        assert second.reconcile_result.custom_bars_written == 1
    asyncio.run(run())


def test_complete_fine_history_with_unknown_enhancements_keeps_original_unknown_contract(mixed_query):
    mixed_query.storage.upsert_bars("BTCUSDT", "1m", [dict(
        open_time=t * MINUTE, close_time=(t + 1) * MINUTE - 1,
        open=100, high=102, low=99, close=101, volume=1, quote_volume=None,
        trades=None, taker_buy_base=None, taker_buy_quote=None) for t in range(10007)],
        source="backfill", market_type="futures")
    engine = engine_for(mixed_query)
    upstream = Upstream()
    engine._fetcher = upstream
    report = asyncio.run(repair(engine))
    assert report.status == BackfillStatus.COMPLETED, report.errors
    assert report.metadata["mixed_plan_fallback"] == "local_single_base_preferred"
    assert not upstream.calls
    result = mixed_query.query("BTCUSDT", "10007m", start_ms=0, end_ms=10007 * MINUTE - 1,
        limit=1, market_type="futures", min_revision=mixed_query.storage.revision_store.head())
    assert result.complete and result.bars[0].volume == 10007
    assert result.bars[0].quote_volume is result.bars[0].trades is None


def test_confirmed_empty_upstream_keeps_empty_evidence_without_fabricating_target(mixed_query):
    engine = engine_for(mixed_query)
    class Empty:
        async def fetch(self, tasks, **options):
            return [FetchResult(task, source_complete=True, exhausted_before_ms=task.end_ms,
                                empty_reason="source_empty") for task in tasks]
    engine._fetcher = Empty()
    report = asyncio.run(repair(engine))
    assert report.status == BackfillStatus.COMPLETED and not report.errors
    assert all(result.source_complete and result.empty_reason for result in report.fetch_results)
    assert report.reconcile_result.custom_bars_written == report.reconcile_result.bars_written == 0
    assert mixed_query.storage.count_bars("BTCUSDT", "10007m", 0, 10007 * MINUTE - 1,
                                          market_type="futures") == 0


@pytest.mark.parametrize("mutation", ["calendar", "resolver", "alignment"])
def test_download_completion_cannot_materialize_after_owner_binding_changes(mixed_query, mutation):
    engine = engine_for(mixed_query)
    class Changed(Upstream):
        async def fetch(self, tasks, **options):
            result = await super().fetch(tasks, **options)
            if mutation == "calendar":
                engine.detector.set_calendar_resolver(lambda *args: "unknown.session")
            elif mutation == "resolver":
                from app.data_engine.interval_resolution import IntervalResolver
                engine.planner._interval_resolver = IntervalResolver()
            else:
                engine.config.alignment_epoch_ms = 60000
            return result
    engine._fetcher = Changed()
    report = asyncio.run(repair(engine))
    assert report.status != BackfillStatus.COMPLETED
    assert report.reconcile_result.custom_bars_written == 0
    assert mixed_query.storage.count_bars("BTCUSDT", "10007m", 0, 10007 * MINUTE - 1,
                                           market_type="futures") == 0
