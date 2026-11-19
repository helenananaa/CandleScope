"""Two cold charts of one symbol through the real coordinator, engine and storage.

With the family fill on, their sources are acquired once by the fill's
native pieces and the charts' chunks then only derive. Without it, or when
the fill declines or stalls, the charts still complete on their own.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from contextvars import ContextVar

import pytest

from app.core import config as core_config
from app.data_engine.data_manager import DataManager, family_fill as ff
from app.data_engine.data_manager.backfill_contracts import RepairRequest
from app.data_engine.data_manager.backfill_coordinator import BackfillCoordinator
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.interval_policy import parse_interval_ms
from app.data_engine.storage import klines_repo
from app.data_engine.storage.gap_ledger import GapLedger
from app.data_engine.backfill.fetcher import HistoricalFetcher
from app.data_engine.ingestion.config import IngestionConfig
from tests.history_stream_transport import IntervalTransport
from tests.test_mixed_backfill_plan import engine_for
from tests.test_mixed_history_reader import MINUTE

CONTRACT = "binance.usdm.trade-klines/base-utc/1"
WIDE = 10007 * MINUTE
# A wide composed chart and a prime chart on its single 1m base, as a cold
# workspace opens them (the coordinator gives the prime page the bounded batch).
CHARTS = (("10007m", 0, WIDE - 1, "required_history_composition"),
          ("89m", 0, 112 * 89 * MINUTE - 1, "bounded_history_batch_contract"))


# The requester of the engine run a page is fetched for.
REQUESTER = ContextVar("requester", default=None)


class Transport(IntervalTransport):
    """Native pages with receipts, and who asked for each one."""

    def __init__(self, slow_requester=None, delay=3.0):
        super().__init__()
        self.owners = []
        self.slow_requester, self.delay = slow_requester, delay

    async def http_fetch(self, request):
        owner = REQUESTER.get()
        if owner is not None and owner == self.slow_requester:
            # Far past the fill's stall limit, but it does answer (a real
            # request times out at the HTTP layer instead of hanging).
            await asyncio.sleep(self.delay)
        self.owners.append(owner)
        return await super().http_fetch(request)


def fetched_rows(transport, requester=None):
    rows = Counter()
    for call, owner in zip(transport.calls, transport.owners):
        if requester is not None and owner != requester:
            continue
        width = parse_interval_ms(call.descriptor.interval)
        first = (call.start_ms + width - 1) // width * width
        rows.update((call.descriptor.interval, opened)
                    for opened in list(range(first, call.end_ms + 1, width))[:call.limit])
    return rows


def run_charts(tmp_path, monkeypatch, *, enabled, transport=None, patch=None):
    database = tmp_path / "family.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", database)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", database)
    monkeypatch.setattr(ff, "ENABLED", enabled)
    monkeypatch.setattr(ff, "DEBOUNCE_SECONDS", 0.01)
    klines_repo.init_klines_storage()
    config = DataManagerConfig()
    config.query.auto_backfill = False
    dm = DataManager(config)
    storage = klines_repo.KlinesRepoAdapter()
    dm.set_storage(storage)
    engine = engine_for(dm.query_engine)
    transport = transport or Transport()
    engine.config.fetch_batch_size = 1500
    engine.config.fetch_binance_futures_rate_limit_delay = 0
    engine._fetcher = HistoricalFetcher(engine.config, transport, IngestionConfig())
    original = engine.run_receipt
    async def run_receipt(*args, **kwargs):
        token = REQUESTER.set((kwargs.get("metadata") or {}).get("requester"))
        try:
            return await original(*args, **kwargs)
        finally:
            REQUESTER.reset(token)
    engine.run_receipt = run_receipt
    ledger = GapLedger(database)

    async def run():
        coordinator = BackfillCoordinator(storage=storage, bars_backfilled=dm.on_bars_backfilled,
            emit_event=dm.emit_event, source_available=dm.source_storage_available,
            engine=engine, loop=asyncio.get_running_loop(), gap_ledger=ledger,
            max_concurrency=0, chunk_bars=1000)
        if patch is not None:
            patch(coordinator, engine)
        try:
            ids = [coordinator.request(RepairRequest("BTCUSDT", interval, start, end, market_type="futures",
                       reason="initial_history", requester="klines_history",
                       metadata={contract: CONTRACT, "history_calendar_id": "crypto.24x7.utc"}))
                   for interval, start, end, contract in CHARTS]
            outcomes = [await asyncio.wait_for(coordinator.wait_for_request(i), timeout=60) for i in ids]
            gate = coordinator._scheduler.family_gate
            metrics = dict(gate.metrics) if gate is not None else None
            complete = []
            for interval, start, end, _ in CHARTS:
                width = parse_interval_ms(interval)
                result = dm.query("BTCUSDT", interval, start_ms=start, end_ms=end, limit=(end - start + 1) // width,
                                  market_type="futures", auto_backfill=False,
                                  min_revision=storage.revision_store.head())
                complete.append(result.complete and len(result.bars) == (end - start + 1) // width)
            return outcomes, metrics, complete
        finally:
            await coordinator.shutdown()
            await dm.shutdown()
    outcomes, metrics, complete = asyncio.run(run())
    assert dm.memory_budget.snapshot()["reserved_bytes"] == 0
    return outcomes, metrics, complete, transport


def test_the_fill_acquires_each_source_row_once_and_the_charts_only_derive(tmp_path, monkeypatch):
    outcomes, metrics, complete, transport = run_charts(tmp_path, monkeypatch, enabled=True)
    assert all(outcome.verified_contiguous for outcome in outcomes), [o.error for o in outcomes]
    assert complete == [True, True]
    assert metrics["fills"] == 1 and metrics["pieces"] > 0
    assert metrics["declined"] == metrics["piece_failures"] == metrics["stalls"] == 0
    rows = fetched_rows(transport)
    assert rows and max(rows.values()) == 1
    # Every source row came from the fill's pieces; no chart chunk fetched.
    assert fetched_rows(transport, "family_fill") == rows


def test_without_the_fill_the_same_charts_complete_as_before(tmp_path, monkeypatch):
    outcomes, metrics, complete, transport = run_charts(tmp_path, monkeypatch, enabled=False)
    assert metrics is None
    assert all(outcome.verified_contiguous for outcome in outcomes)
    assert complete == [True, True]
    assert not fetched_rows(transport, "family_fill")


def test_a_declined_plan_releases_the_charts_to_acquire_for_themselves(tmp_path, monkeypatch):
    def patch(coordinator, engine):
        async def fail(**_):
            raise RuntimeError("controlled planning failure")
        engine.plan_mixed_sources = fail
    outcomes, metrics, complete, transport = run_charts(tmp_path, monkeypatch, enabled=True, patch=patch)
    assert metrics["declined"] == 1 and metrics["pieces"] == 0
    assert all(outcome.verified_contiguous for outcome in outcomes)
    assert complete == [True, True]
    assert not fetched_rows(transport, "family_fill")


def test_a_stalled_piece_releases_the_charts(tmp_path, monkeypatch):
    monkeypatch.setattr(ff, "STALL_SECONDS", 0.5)
    outcomes, metrics, complete, transport = run_charts(tmp_path, monkeypatch, enabled=True,
                                                        transport=Transport(slow_requester="family_fill"))
    assert metrics["stalls"] == 1
    assert all(outcome.verified_contiguous for outcome in outcomes)
    assert complete == [True, True]
