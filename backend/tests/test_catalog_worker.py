from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import ccxt
import pytest

from app.core import config as app_config
from app.data_engine.ingestion.config import IngestionConfig
from app.exchanges import catalog_worker
from app.exchanges import symbol_catalog
from app.exchanges.catalog_worker import (
    CatalogWorkerUnavailable,
    run_catalog_loader,
)
from app.exchanges.ccxt_ext import generic
from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
from app.exchanges.ccxt_ext.primary import create_binance_ccxt_plugin


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> catalog_worker._CatalogWorker:
    fresh = catalog_worker._CatalogWorker()
    monkeypatch.setattr(catalog_worker, "_worker", fresh)
    monkeypatch.setattr(app_config, "SYMBOL_CATALOG_WORKER_IDLE_SECONDS", 0.0)
    return fresh


def _generation(worker: catalog_worker._CatalogWorker) -> Any:
    assert worker._generation is not None
    return worker._generation


async def _wait_exited(generation: Any) -> None:
    assert generation.retired and generation.reaper is not None
    await asyncio.to_thread(generation.reaper.join, 15)
    try:
        assert not generation.process.is_alive()
    except ValueError:
        pass  # The reaper closes the process object once it has exited.


def test_worker_process_lifecycle(worker: catalog_worker._CatalogWorker, monkeypatch) -> None:
    # Stdlib coroutines stand in for catalog loaders: the child must be able
    # to import a loader by reference, and ``asyncio.sleep(0, result)`` is one.
    rows = [{"symbol": f"S{index}"} for index in range(catalog_worker._ROW_CHUNK * 3 + 7)]

    async def run() -> None:
        assert await run_catalog_loader(asyncio.sleep, 0, rows) == rows
        first = _generation(worker)
        first_pid = first.process.pid
        assert first_pid != os.getpid()

        # Loader exceptions cross the process boundary with their type.
        with pytest.raises(TypeError):
            await run_catalog_loader(asyncio.sleep, "not a delay")

        # A caller timeout cancels only that request; the worker keeps serving.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(run_catalog_loader(asyncio.sleep, 60, []), 0.2)
        assert await run_catalog_loader(asyncio.sleep, 0, [1]) == [1]
        assert _generation(worker) is first

        # An idle worker exits and the next request starts a new one.
        monkeypatch.setattr(app_config, "SYMBOL_CATALOG_WORKER_IDLE_SECONDS", 0.05)
        assert await run_catalog_loader(asyncio.sleep, 0, [2]) == [2]
        await asyncio.sleep(0.2)
        assert worker._generation is None
        await _wait_exited(first)
        monkeypatch.setattr(app_config, "SYMBOL_CATALOG_WORKER_IDLE_SECONDS", 0.0)
        assert await run_catalog_loader(asyncio.sleep, 0, [3]) == [3]
        second = _generation(worker)
        assert second.process.pid != first_pid

        # The catalog lifecycle owns the worker's shutdown.
        await symbol_catalog.cancel_exchange_metadata_refreshes()
        assert worker._generation is None
        await _wait_exited(second)
        symbol_catalog.initialize_exchange_metadata_cache()

    asyncio.run(run())


def test_worker_crash_fails_requests_and_backs_off(worker: catalog_worker._CatalogWorker) -> None:
    async def run() -> None:
        assert await run_catalog_loader(asyncio.sleep, 0, []) == []
        pending = asyncio.ensure_future(run_catalog_loader(asyncio.sleep, 60, []))
        await asyncio.sleep(0.1)
        _generation(worker).process.kill()
        with pytest.raises(CatalogWorkerUnavailable):
            await asyncio.wait_for(pending, 10)
        # A crashed worker is not respawned on every catalog request.
        with pytest.raises(CatalogWorkerUnavailable, match="cooldown"):
            await run_catalog_loader(asyncio.sleep, 0, [])
        await catalog_worker.shutdown_catalog_worker()

    asyncio.run(run())


async def _loader_until_cancelled(started: str, cancelled: str) -> list[Any]:
    Path(started).write_text(str(os.getpid()))
    try:
        await asyncio.Event().wait()
    finally:
        Path(cancelled).write_text(str(os.getpid()))
    return []


def test_cancelled_caller_stops_its_loader_in_the_child(
    worker: catalog_worker._CatalogWorker, tmp_path: Path,
) -> None:
    started = tmp_path / 'started'
    cancelled = tmp_path / 'cancelled'

    async def wait_for_file(path: Path) -> None:
        async with asyncio.timeout(5):
            while not path.exists():
                await asyncio.sleep(0.01)

    async def run() -> None:
        # Start/import the worker before measuring cancellation delivery. Cold
        # CCXT imports have their own 90-second startup bound.
        await worker._ready_generation(__name__)
        pending = asyncio.create_task(
            run_catalog_loader(_loader_until_cancelled, str(started), str(cancelled)),
        )
        try:
            await wait_for_file(started)
            generation = _generation(worker)
            assert int(started.read_text()) == generation.process.pid
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await wait_for_file(cancelled)
            assert int(cancelled.read_text()) == generation.process.pid
            assert await run_catalog_loader(asyncio.sleep, 0, [1]) == [1]
            assert _generation(worker) is generation
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await catalog_worker.shutdown_catalog_worker()

    asyncio.run(run())


class _FakeCatalogExchange:
    precisionMode = ccxt.TICK_SIZE

    def __init__(self) -> None:
        self.load_calls = 0
        self.closed = False
        self.markets = {
            "ETH/USDT": {
                "id": "ETHUSDT", "symbol": "ETH/USDT", "base": "ETH", "quote": "USDT",
                "spot": True, "active": True, "precision": {"price": 0.01},
            },
            "BTC/USDT": {
                "id": "BTCUSDT", "symbol": "BTC/USDT", "base": "BTC", "quote": "USDT",
                "spot": True, "active": True, "precision": {"price": 0.1},
                "created": 1_500_000_000_000,
            },
            "OLD/USDT": {
                "id": "OLDUSDT", "symbol": "OLD/USDT", "base": "OLD", "quote": "USDT",
                "spot": True, "active": False,
            },
            "BTC/USDT:USDT": {
                "id": "BTCUSDT", "symbol": "BTC/USDT:USDT", "base": "BTC", "quote": "USDT",
                "swap": True, "linear": True, "active": True,
            },
        }

    async def load_markets(self) -> dict[str, Any]:
        self.load_calls += 1
        return self.markets

    async def close(self, clean_instance_data: bool = False) -> None:
        self.closed = True


def test_list_symbol_rows_match_inline_symbols_and_carry_proxy(monkeypatch) -> None:
    configs: list[IngestionConfig] = []
    exchanges: list[_FakeCatalogExchange] = []

    def create(_entry: Any, config: IngestionConfig, **_kwargs: Any) -> _FakeCatalogExchange:
        configs.append(config)
        exchanges.append(_FakeCatalogExchange())
        return exchanges[-1]

    class _ProxyConfig(IngestionConfig):
        # Stands in for persisted proxy settings in the backend process.
        def __init__(self, **kwargs: Any) -> None:
            kwargs.setdefault("proxy_mode", "custom")
            kwargs.setdefault("http_proxy", "http://127.0.0.1:7890")
            super().__init__(**kwargs)

    loader_calls: list[tuple[Any, ...]] = []

    async def run_inline(function, *args):
        # The worker process cannot see monkeypatches; run the same loader here.
        loader_calls.append(args)
        return await function(*args)

    monkeypatch.setattr(generic, "_create_exchange", create)
    monkeypatch.setattr(generic, "IngestionConfig", _ProxyConfig)
    monkeypatch.setattr(generic, "run_catalog_loader", run_inline)
    monkeypatch.setattr(app_config, "SYMBOL_CATALOG_WORKER_ENABLED", True)
    adapter = create_binance_ccxt_plugin().adapter()

    rows = asyncio.run(adapter.list_symbol_rows("spot"))
    inline = [item.to_dict() for item in asyncio.run(adapter.list_symbols("spot"))]

    assert rows == inline
    assert [row["symbol"] for row in rows] == ["BTCUSDT", "ETHUSDT"]
    assert rows[0]["priceTickSize"] == "0.1"
    assert rows[0]["listedAtMs"] == 1_500_000_000_000
    assert loader_calls[0][0] == get_ccxt_catalog_entry("binance")
    assert loader_calls[0][2:5] == ("custom", "http://127.0.0.1:7890", True)
    assert loader_calls[0][5].http_proxy == "http://127.0.0.1:7890"
    assert {(config.proxy_mode, config.http_proxy) for config in configs} == {
        ("custom", "http://127.0.0.1:7890"),
    }
    assert all(exchange.closed for exchange in exchanges)

    async def unavailable(function, *args):
        raise CatalogWorkerUnavailable("no worker")

    monkeypatch.setattr(generic, "run_catalog_loader", unavailable)
    assert asyncio.run(adapter.list_symbol_rows("spot")) == inline

    monkeypatch.setattr(generic, "run_catalog_loader", None)
    monkeypatch.setattr(app_config, "SYMBOL_CATALOG_WORKER_ENABLED", False)
    assert asyncio.run(adapter.list_symbol_rows("spot")) == inline


def test_generic_catalog_rows_keep_ccxt_symbols(monkeypatch) -> None:
    monkeypatch.setattr(generic, "_create_exchange", lambda *_a, **_k: _FakeCatalogExchange())
    entry = get_ccxt_catalog_entry("bybit")

    rows = asyncio.run(
        generic.load_ccxt_symbol_rows(entry, "spot", "none", None, False),
    )

    assert [row["symbol"] for row in rows] == ["BTC/USDT", "ETH/USDT"]
    assert {row["exchange"] for row in rows} == {"bybit"}


def test_catalog_request_pickles_for_the_worker() -> None:
    import pickle

    entry = get_ccxt_catalog_entry("binance")
    message = ("load", 1, generic.load_ccxt_symbol_rows, (entry, "spot", "system", None, True))

    payload = pickle.dumps(message)

    assert pickle.loads(payload) == message
    # Requests are written from the event loop; keep them far below the
    # 8 KB pipe buffer so the write never waits for the child.
    assert len(payload) < 4096
