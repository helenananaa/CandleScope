"""Controlled SQLite interleavings for query refill and deletion ownership."""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import BarData, SeriesKey
from app.data_engine.interval_resolution import IntervalPurpose
from app.data_engine.storage import klines_repo


START = 1_700_000_040_000
STEP = 60_000
SOURCE = "backfill_rest_verified"
KEY = SeriesKey("BTCUSDT", "1m")


def _row(timestamp: int, close: float = 100) -> dict:
    return dict(
        open_time=timestamp, close_time=timestamp + STEP - 1,
        open=100, high=250, low=50, close=close, volume=10,
        quote_volume=1000, trades=10, taker_buy_base=5, taker_buy_quote=500,
    )


class _PausedRead(klines_repo.KlinesRepoAdapter):
    def __init__(self):
        super().__init__()
        self.read = threading.Event()
        self.release = threading.Event()
        self.once = True

    def _pause(self, rows):
        if self.once:
            self.once = False
            self.read.set()
            assert self.release.wait(10), "storage read was not released"
        return rows

    def query_bar_components(self, *args, **kwargs):
        return self._pause(super().query_bar_components(*args, **kwargs))

    def fetch_before_bar_components(self, *args, **kwargs):
        return self._pause(super().fetch_before_bar_components(*args, **kwargs))


def _manager(tmp_path, monkeypatch, adapter_type=_PausedRead):
    path = tmp_path / "bars.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    klines_repo.upsert_klines(
        "BTCUSDT", "1m", [_row(START), _row(START + STEP)], source=SOURCE,
    )
    adapter = adapter_type()
    manager = DataManager()
    manager.set_storage(adapter)
    # Lazy provider initialization is not part of the controlled race. Finish
    # it before starting the worker/barrier deadline on a cold interpreter.
    manager.interval_resolver.resolve(
        exchange="binance", market_type="spot", interval="1m",
        purpose=IntervalPurpose.HISTORY,
    )
    return manager, adapter


def _query(manager, mode, *, auto_backfill=False):
    if mode == "before":
        return manager.query_before(
            "BTCUSDT", "1m", before_ms=START + 2 * STEP, limit=2,
            auto_backfill=auto_backfill,
        )
    return manager.query(
        "BTCUSDT", "1m", start_ms=START, end_ms=START + STEP, limit=2,
        auto_backfill=auto_backfill,
    )


@pytest.mark.parametrize("mode", ["range", "before"])
@pytest.mark.parametrize("partial_cache", [False, True])
@pytest.mark.parametrize("change", ["amend", "delete"])
def test_old_read_cannot_undo_adoption_or_delete(
    tmp_path, monkeypatch, mode, partial_cache, change,
):
    manager, adapter = _manager(tmp_path, monkeypatch)
    if partial_cache:
        manager.cache.bulk_load(KEY, [BarData.from_storage_row({**_row(START), "source": SOURCE})])
    with ThreadPoolExecutor(max_workers=1) as worker:
        result_future = worker.submit(_query, manager, mode)
        try:
            assert adapter.read.wait(10), "query did not reach storage"
            if change == "amend":
                klines_repo.upsert_klines("BTCUSDT", "1m", [_row(START + STEP, 200)], source=SOURCE)
                rows = klines_repo.query_klines("BTCUSDT", "1m")
                asyncio.run(manager.on_bars_backfilled(
                    "BTCUSDT", "1m", [BarData.from_storage_row(row) for row in rows],
                ))
                expected = [100, 200]
            else:
                assert asyncio.run(manager.delete_storage_data(symbol="BTCUSDT", interval="1m")) == 2
                assert manager.cache.get_latest(KEY, 2) == []
                expected = []
        finally:
            adapter.release.set()
        result = result_future.result(10)

    assert [bar.close for bar in result.bars] == expected
    assert [bar.close for bar in manager.cache.get_latest(KEY, 2)] == expected
    assert [bar.close for bar in _query(manager, mode).bars] == expected
    assert result.metadata["cache_read_retries"] == 1
    assert manager.cache.snapshot()["active_read_tokens"] == 0


class _PausedDelete(klines_repo.KlinesRepoAdapter):
    def __init__(self):
        super().__init__()
        self.committed = threading.Event()
        self.release = threading.Event()

    def delete_bars(self, **kwargs):
        deleted = super().delete_bars(**kwargs)
        self.committed.set()
        assert self.release.wait(10), "physical delete was not released"
        return deleted


def test_cancelled_delete_finishes_cache_invalidation(tmp_path, monkeypatch):
    manager, adapter = _manager(tmp_path, monkeypatch, _PausedDelete)
    assert len(_query(manager, "range").bars) == 2

    async def scenario():
        task = asyncio.create_task(manager.delete_storage_data(symbol="BTCUSDT", interval="1m"))
        try:
            assert await asyncio.to_thread(adapter.committed.wait, 10)
            task.cancel()
        finally:
            adapter.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert klines_repo.query_klines("BTCUSDT", "1m") == []
    assert manager.cache.get_latest(KEY, 2) == []
    assert _query(manager, "range").bars == []


@pytest.mark.parametrize("mode", ["range", "before"])
def test_conflicting_retry_does_not_start_new_download_after_delete(tmp_path, monkeypatch, mode):
    manager, adapter = _manager(tmp_path, monkeypatch)
    downloads = []
    manager.query_engine.set_backfill_trigger(lambda *args: downloads.append(args))
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(_query, manager, mode, auto_backfill=True)
        try:
            assert adapter.read.wait(10)
            asyncio.run(manager.delete_storage_data(symbol="BTCUSDT", interval="1m"))
        finally:
            adapter.release.set()
        assert future.result(10).bars == []
    assert downloads == []
    _query(manager, mode, auto_backfill=True)
    assert downloads  # A new request can explicitly ask for history again.


@pytest.mark.parametrize("mode", ["range", "before"])
def test_repeated_conflict_is_bounded_retryable_and_does_not_download(tmp_path, monkeypatch, mode):
    class ChangingStorage(klines_repo.KlinesRepoAdapter):
        manager = None
        def query_bar_components(self, *args, **kwargs):
            rows = super().query_bar_components(*args, **kwargs)
            self.manager.cache.invalidate(KEY)
            return rows
        def fetch_before_bar_components(self, *args, **kwargs):
            rows = super().fetch_before_bar_components(*args, **kwargs)
            self.manager.cache.invalidate(KEY)
            return rows
    manager, adapter = _manager(tmp_path, monkeypatch, ChangingStorage)
    adapter.manager = manager
    downloads = []
    manager.query_engine.set_backfill_trigger(lambda *args: downloads.append(args))
    result = _query(manager, mode, auto_backfill=True)
    assert result.bars == []
    assert result.retryable and not result.complete and result.has_more
    assert result.history_state == "pending"
    assert result.metadata["cache_read_conflict"] is True
    assert result.metadata["storage_reads"] == 2
    assert result.metadata["cache_read_retries"] == 1
    assert downloads == []
    assert manager.cache.snapshot()["active_read_tokens"] == 0


def test_delete_failure_after_commit_still_invalidates(tmp_path, monkeypatch):
    class FailedAfterCommit(klines_repo.KlinesRepoAdapter):
        def delete_bars(self, **kwargs):
            super().delete_bars(**kwargs)
            raise OSError("lost completion after commit")
    manager, _ = _manager(tmp_path, monkeypatch, FailedAfterCommit)
    _query(manager, "range")
    with pytest.raises(OSError, match="lost completion"):
        asyncio.run(manager.delete_storage_data(symbol="BTCUSDT", interval="1m"))
    assert klines_repo.query_klines("BTCUSDT", "1m") == []
    assert manager.cache.get_latest(KEY, 2) == []


@pytest.mark.parametrize("gap_kind", ["interior", "before_right"])
@pytest.mark.parametrize("change", ["amend", "delete"])
def test_gap_fill_uses_the_same_fence_as_the_initial_page(tmp_path, monkeypatch, gap_kind, change):
    missing_time = START + (STEP if gap_kind == "interior" else 2 * STEP)
    class GapStorage(_PausedRead):
        initial = True
        def query_bar_components(self, *args, **kwargs):
            rows = klines_repo.KlinesRepoAdapter.query_bar_components(self, *args, **kwargs)
            if kwargs["start_ms"] == missing_time:
                return self._pause(rows)
            if self.initial:
                self.initial = False
                klines_repo.upsert_klines("BTCUSDT", "1m", [_row(missing_time)], source=SOURCE)
            return rows
        def fetch_before_bar_components(self, *args, **kwargs):
            rows = klines_repo.KlinesRepoAdapter.fetch_before_bar_components(self, *args, **kwargs)
            if self.initial:
                self.initial = False
                klines_repo.upsert_klines("BTCUSDT", "1m", [_row(missing_time)], source=SOURCE)
            return rows

    manager, adapter = _manager(tmp_path, monkeypatch, GapStorage)
    # Exercise the local gap fence alone. Durable revision fencing now detects
    # the synthetic initial-page mutation before this gap branch is reached.
    manager.cache.revision_consumer = None
    if gap_kind == "interior":
        klines_repo.delete_klines("BTCUSDT", "1m", start_ms=START + STEP)
        klines_repo.upsert_klines("BTCUSDT", "1m", [_row(START + 2 * STEP)], source=SOURCE)
    def read():
        if gap_kind == "interior":
            return manager.query("BTCUSDT", "1m", start_ms=START, end_ms=START + 2 * STEP,
                                 limit=3, auto_backfill=False)
        return manager.query_before("BTCUSDT", "1m", before_ms=START + 3 * STEP,
                                    limit=3, auto_backfill=False)
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(read)
        try:
            assert adapter.read.wait(10), "query did not reach gap read"
            if change == "delete":
                assert asyncio.run(manager.delete_storage_data(symbol="BTCUSDT", interval="1m")) == 3
                expected = []
            else:
                klines_repo.upsert_klines("BTCUSDT", "1m", [_row(START + i * STEP, 200) for i in range(3)], source=SOURCE)
                rows = klines_repo.query_klines("BTCUSDT", "1m")
                asyncio.run(manager.on_bars_backfilled("BTCUSDT", "1m", [BarData.from_storage_row(row) for row in rows]))
                expected = [200, 200, 200]
        finally:
            adapter.release.set()
        result = future.result(10)
    assert [bar.close for bar in result.bars] == expected
    assert [bar.close for bar in manager.cache.get_latest(KEY, 3)] == expected
    assert result.metadata["cache_read_retries"] == 1
    assert manager.cache.snapshot()["active_read_tokens"] == 0
