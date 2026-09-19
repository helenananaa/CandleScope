from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading

import pytest

from app.backtest.trade_snapshot_cache import TradeSnapshotCache
from app.market_dataset.snapshot import MarketDatasetError, MarketEvent


@dataclass(frozen=True)
class Dataset:
    epoch: str = "a"
    row_count: int = 1


class Archive:
    def __init__(self):
        self.pins = 0
        self.releases = 0
        self.invalid = False
        self.second_pin = threading.Event()

    def pin_dataset(self, dataset):
        if self.invalid:
            raise ValueError("checksum changed")
        self.pins += 1
        if self.pins >= 2:
            self.second_pin.set()
        return self.pins

    def release_dataset(self, token):
        self.releases += 1


def tape():
    return (MarketEvent(1, 1, "TRADES", {"price": "1.2300", "qty": "1"}),)


def test_each_borrow_is_detached_and_source_is_revalidated():
    cache, archive, dataset = TradeSnapshotCache(10000), Archive(), Dataset()
    original = tape()
    calls = []

    def load():
        calls.append(True)
        return original

    first = cache.read(archive, dataset, max_events=1, loader=load)
    first[0].payload["price"] = "99"
    second = cache.read(archive, dataset, max_events=1, loader=load)
    assert second[0].payload["price"] == "1.2300"
    second[0].payload["price"] = "88"
    assert cache.read(archive, dataset, max_events=1, loader=load)[0].payload["price"] == "1.2300"
    assert len(calls) == 1 and archive.pins == archive.releases == 3
    assert cache.stats["hits"] == 2
    archive.invalid = True
    with pytest.raises(ValueError, match="checksum"):
        cache.read(archive, dataset, max_events=1, loader=load)
    with pytest.raises(MarketDatasetError, match="BUDGET_EXCEEDED"):
        cache.read(archive, dataset, max_events=0, loader=load)


def test_byte_limit_eviction_identity_and_shutdown():
    archive = Archive()
    tiny = TradeSnapshotCache(1)
    for _ in range(2):
        assert tiny.read(archive, Dataset(), max_events=1, loader=tape) == tape()
    assert tiny.stats["entries"] == 0
    cache = TradeSnapshotCache(10000, max_entries=1)
    for epoch in ("a", "b", "a"):
        cache.read(archive, Dataset(epoch), max_events=1, loader=tape)
    assert cache.stats["misses"] == 3 and cache.stats["entries"] == 1
    cache.read(Archive(), Dataset("a"), max_events=1, loader=tape)
    assert cache.stats["misses"] == 4
    cache.close()
    assert cache.stats["bytes"] == 0
    cache.read(archive, Dataset(), max_events=1, loader=tape)
    assert cache.stats["entries"] == 0


def test_concurrent_identical_requests_load_once():
    cache, archive = TradeSnapshotCache(10000), Archive()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def load():
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return tape()

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(cache.read, archive, Dataset(), max_events=1, loader=load)
        assert entered.wait(5)
        second = pool.submit(cache.read, archive, Dataset(), max_events=1, loader=load)
        assert archive.second_pin.wait(5)
        release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert len(calls) == 1 and a == b and a[0] is not b[0]
    assert a[0].payload is not b[0].payload
    assert archive.pins == archive.releases == 2


def test_failed_load_not_cached_and_pin_released():
    cache, archive = TradeSnapshotCache(10000), Archive()

    def fail():
        raise RuntimeError("read failure")

    with pytest.raises(RuntimeError):
        cache.read(archive, Dataset(), max_events=1, loader=fail)
    assert cache.stats["entries"] == 0 and archive.pins == archive.releases == 1
    assert cache.read(archive, Dataset(), max_events=1, loader=tape) == tape()


def test_worker_cache_real_parquet_and_corruption(tmp_path, monkeypatch):
    from scripts.benchmark_strategy_research import archive_fixture
    from scripts.benchmark_trade_strategy import settings
    from app.backtest.runtime import BacktestWorker
    from app.local_data.service import LocalDatasetService

    monkeypatch.setenv("BACKTEST_TRADE_SNAPSHOT_CACHE_ENABLED", "1")
    start, end = archive_fixture(tmp_path / "archive", 1000)
    worker = BacktestWorker(settings=settings(tmp_path), local_data=LocalDatasetService(tmp_path / "local"),
                            trade_archive_dir=tmp_path / "archive")
    dataset = worker.trade_archive.freeze_dataset(exchange="binance", market_type="usdm", symbol="BTCUSDT",
                                                  start_time_ms=start, end_time_ms=end)
    first = worker._load_trade_events(dataset)
    assert worker._load_trade_events(dataset) == first
    assert worker._trade_snapshots.stats["hits"] == 1
    path = next((tmp_path / "archive").rglob("*.parquet"))
    raw = path.read_bytes()
    path.write_bytes(b"X" + raw[1:])
    with pytest.raises(RuntimeError, match="checksum"):
        worker._load_trade_events(dataset)
    worker.shutdown()
    assert worker._trade_snapshots.stats["bytes"] == 0
