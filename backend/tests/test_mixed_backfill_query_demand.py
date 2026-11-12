"""Large default-query demand reaches the existing coordinator and ledger."""
import asyncio
from contextlib import contextmanager

import pytest

from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from app.data_engine.history.cover_plan import CoverBudgetExceeded
from app.data_engine.storage import klines_repo
from app.data_engine.storage.gap_ledger import GapLedger
from tests.test_default_mixed_history_query import mixed_query
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_backfill_pipeline import Upstream
from tests.test_mixed_history_reader import MINUTE


def test_large_closed_query_detects_target_demand_even_with_submission_disabled(mixed_query):
    engine = mixed_query
    calls = []
    engine.set_backfill_trigger(lambda *args: calls.append(args))
    options = dict(start_ms=0, end_ms=10007 * MINUTE - 1, limit=1, market_type="futures",
                   min_revision=engine.storage.revision_store.head())
    readonly = engine.query("BTCUSDT", "10007m", auto_backfill=False, **options)
    assert readonly.retryable and not readonly.complete and not calls
    assert readonly.metadata["mixed_target_repair"]
    assert [(m.interval, m.start_ms, m.end_ms) for m in readonly.missing_ranges] == [("10007m", 0, 0)]
    requested = engine.query("BTCUSDT", "10007m", auto_backfill=True, **options)
    assert requested.backfill_triggered and len(calls) == 1 and calls[0][1] == "10007m"


def test_planning_budget_is_not_a_market_gap_or_a_new_download_demand(mixed_query, monkeypatch):
    engine = mixed_query
    calls = []
    engine.set_backfill_trigger(lambda *args: calls.append(args))
    @contextmanager
    def exhausted(*args, **kwargs):
        raise CoverBudgetExceeded("controlled work bound")
        yield  # pragma: no cover
    monkeypatch.setattr(engine, "read_mixed_history_blocks", exhausted)
    result = engine.query("BTCUSDT", "10007m", start_ms=0, end_ms=10007 * MINUTE - 1,
        limit=1, market_type="futures", auto_backfill=True, min_revision=engine.storage.revision_store.head())
    assert result.retryable and not result.complete and not result.missing_ranges and not calls


def test_default_facade_scheduler_ledger_and_canonical_adoption_complete_cold_target(tmp_path, monkeypatch):
    from app.core import config as core_config
    database = tmp_path / "cold-default.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", database)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", database)
    klines_repo.init_klines_storage()
    config = DataManagerConfig()
    dm = DataManager(config)
    storage = klines_repo.KlinesRepoAdapter()
    dm.set_storage(storage)
    engine = engine_for(dm.query_engine)
    upstream = Upstream()
    engine._fetcher = upstream
    ledger = GapLedger(database)
    async def run():
        coordinator = BackfillCoordinator(storage=storage, bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.emit_event, source_available=dm.source_storage_available,
            engine=engine, loop=asyncio.get_running_loop(), gap_ledger=ledger,
            max_concurrency=1, chunk_bars=1000, max_retries=1)
        dm.set_backfill_trigger(coordinator.trigger)
        try:
            initial = dm.query("BTCUSDT", "10007m", start_ms=0, end_ms=10007 * MINUTE - 1,
                limit=1, market_type="futures", backfill_requester="klines_range",
                backfill_metadata={"history_calendar_id": "crypto.24x7.utc"}, min_revision=storage.revision_store.head())
            assert initial.retryable and initial.backfill_triggered
            ids = initial.metadata["backfill_request_ids"]
            assert len(ids) == 1
            outcome = await asyncio.wait_for(coordinator.wait_for_request(ids[0]), timeout=30)
            assert outcome.verified_contiguous is True, outcome.error
            assert outcome.remaining_missing_bars == 0
            assert outcome.request.interval == "10007m"
            ready = dm.query("BTCUSDT", "10007m", start_ms=0, end_ms=10007 * MINUTE - 1,
                limit=1, market_type="futures", auto_backfill=False, min_revision=storage.revision_store.head())
            assert ready.complete and ready.bars[0].volume == 10007
            assert len(upstream.calls) < 11 and "1h" in {task.interval for task in upstream.calls}
            assert storage.count_bars("BTCUSDT", "1m", 0, 10007 * MINUTE - 1, market_type="futures") == 2
            status = await asyncio.to_thread(ledger.get_status, outcome.request)
            assert status["status"] == "filled" and status["missing_count"] == 0
        finally:
            await coordinator.shutdown()
            await dm.shutdown()
    asyncio.run(run())
    assert dm.memory_budget.snapshot()["reserved_bytes"] == 0
