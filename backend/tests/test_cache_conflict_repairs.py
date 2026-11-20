"""A read that lost its cache adoption is a retry, never a reason to download.

``QueryEngine._run_cache_read`` answers a twice-conflicted read as pending with
``cache_read_conflict`` and schedules nothing. A custom interval built from
streamed base pages must keep that marker when the conflicted page is not the
newest, and the API's verification must not turn the short answer into a repair.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.klines as klines_api
from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.custom_query import CustomIntervalQueryService
from app.data_engine.data_manager.models import BarData, QueryResult, QuerySource, SeriesKey
from app.data_engine.interval_resolution import IntervalPurpose
from app.data_engine.storage import klines_repo

MINUTE = 60_000
WIDTH = 89 * MINUTE
TARGETS = 130


def _page(conflict):
    return QueryResult(bars=[], symbol="BTCUSDT", interval="1m", source=QuerySource.STORAGE, total=0,
                       has_more=True, retryable=conflict, complete=not conflict,
                       history_state="pending" if conflict else "ready",
                       metadata={"all_rows_final": True, **({"cache_read_conflict": True} if conflict else {})})


@pytest.mark.parametrize("pages", [(False, True), (False, False, True), (True, False), (False, False)])
def test_merged_base_pages_keep_any_page_cache_conflict(pages):
    bar = BarData(time=60, open=1, high=1, low=1, close=1, volume=1, source="backfill")
    merged = CustomIntervalQueryService._merge_base_page_results([_page(c) for c in pages], [bar])
    assert bool(merged.metadata.get("cache_read_conflict")) is any(pages)
    assert klines_api._snapshot_is_stable(merged) is not any(pages)


class _ConflictingPages(klines_repo.KlinesRepoAdapter):
    """Competing adoptions of the 1m series while the older base pages are read."""

    manager = None
    conflicts = 0

    def fetch_before_bar_components(self, *args, **kwargs):
        rows = super().fetch_before_bar_components(*args, **kwargs)
        if self.conflicts:
            self.conflicts -= 1
            self.manager.cache.invalidate(SeriesKey("BTCUSDT", "1m"))
        return rows


def _manager(tmp_path, monkeypatch, conflicts):
    path = tmp_path / "bars.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    rows = [dict(open_time=at, close_time=at + MINUTE - 1, open=100.0, high=101.0, low=99.0, close=100.5,
                 volume=1.0, quote_volume=100.0, trades=3, taker_buy_base=0.5, taker_buy_quote=50.0)
            for at in range(0, TARGETS * WIDTH, MINUTE)]
    for i in range(0, len(rows), 2000):
        klines_repo.upsert_klines("BTCUSDT", "1m", rows[i:i + 2000], source="backfill")
    adapter = _ConflictingPages()
    manager = DataManager()
    manager.set_storage(adapter)
    adapter.manager, adapter.conflicts = manager, conflicts
    manager.interval_resolver.resolve(exchange="binance", market_type="spot", interval="1m",
                                      purpose=IntervalPurpose.HISTORY)
    downloads = []
    manager.query_engine.set_backfill_trigger(lambda *args, **kwargs: downloads.append(args))
    return manager, downloads


@pytest.mark.parametrize("conflicts", [0, 2])
def test_custom_read_with_a_conflicted_older_page_is_a_retry(tmp_path, monkeypatch, conflicts):
    manager, downloads = _manager(tmp_path, monkeypatch, conflicts)
    result = manager.query("BTCUSDT", "89m", start_ms=0, end_ms=(TARGETS - 1) * WIDTH, limit=TARGETS,
                           auto_backfill=True)
    assert result.metadata.get("base_streaming") is True
    if conflicts:
        # The newest page was adopted; the next one lost both attempts.
        assert result.metadata.get("base_page_count", 0) >= 2
        assert result.metadata.get("cache_read_conflict") is True
        assert result.retryable and not result.complete and result.history_state == "pending"
        assert len(result.bars) < TARGETS
        assert not klines_api._snapshot_is_stable(result)
    else:
        assert result.complete and len(result.bars) == TARGETS
        assert not result.metadata.get("cache_read_conflict")
        assert klines_api._snapshot_is_stable(result)
    assert downloads == []


class _ShortAnswer:
    """A data manager whose answer lacks one bar; ``conflict`` marks it a lost adoption."""

    def __init__(self, conflict):
        self.conflict = conflict
        self.repair_calls = []

    def query(self, symbol, interval, *, start_ms, end_ms, limit, exchange, market_type,
              auto_backfill=None, **kwargs):
        bars = [BarData(time=value // 1000, open=1, high=2, low=1, close=2, volume=10, source="backfill")
                for value in (start_ms, end_ms)]
        return QueryResult(bars=bars, symbol=symbol, interval=interval, exchange=exchange,
                           market_type=market_type, source=QuerySource.STORAGE, total=len(bars),
                           has_more=self.conflict, retryable=self.conflict, complete=not self.conflict,
                           history_state="pending" if self.conflict else "ready",
                           metadata={"all_rows_final": True,
                                     **({"cache_read_conflict": True} if self.conflict else {})})

    def request_backfill(self, *args, **kwargs):
        self.repair_calls.append((args, kwargs))
        return "verification-repair"


def _client(dm):
    app = FastAPI()
    app.include_router(klines_api.router, prefix="/api/v1")
    app.state.data_manager = dm
    return TestClient(app)


@pytest.mark.parametrize("conflict", [False, True])
def test_range_verification_does_not_repair_a_conflicted_read(conflict):
    dm = _ShortAnswer(conflict)
    response = _client(dm).get("/api/v1/klines/range", params={
        "symbol": "BTCUSDT", "interval": "1m", "start_ms": 60_000, "end_ms": 180_000, "repair": "async"})
    assert response.status_code == 200
    assert len(dm.repair_calls) == (0 if conflict else 1)
    assert response.json()["history_state"] == "pending"


@pytest.mark.parametrize("conflict", [False, True])
def test_history_verification_does_not_repair_a_conflicted_read(monkeypatch, conflict):
    monkeypatch.setattr(klines_api, "_schedule_related_interval_warmup", lambda *args, **kwargs: None)

    class Coordinator:
        waited = []

        async def wait_for_request(self, request_id):
            self.waited.append(request_id)
            return object()

    class Runtime:
        def get_backfill_coordinator(self):
            return coordinator

    coordinator = Coordinator()
    dm = _ShortAnswer(conflict)
    app = FastAPI()
    app.include_router(klines_api.router, prefix="/api/v1")
    app.state.data_manager = dm
    app.state.data_engine_runtime = Runtime()
    response = TestClient(app).get("/api/v1/klines/history", params={
        "symbol": "BTCUSDT", "interval": "1m", "count_back": 3, "max_wait_ms": 1000})
    assert response.status_code == 200
    assert len(dm.repair_calls) == (0 if conflict else 1)
    if not conflict:
        assert dm.repair_calls[0][1]["reason"] == "initial_history"
    assert response.json()["complete"] is False
