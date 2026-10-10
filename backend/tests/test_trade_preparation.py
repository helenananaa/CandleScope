import asyncio
import hashlib
import io
import threading
from functools import partial
from types import SimpleNamespace

import pytest

from app.data_engine.storage.raw_trade_archive import ParquetRawAggTradeArchive
from app.data_preparation.bar_adapter import BarPreparationAdapter, storage_call
from app.data_preparation.models import PreparationError, PreparationRequest, Requirement
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.data_preparation.storage_inventory import reconcile
from app.replay.trade_import import import_official_date_range, ReplayTradeImportError
from tests.test_data_preparation import async_test, terminal
from tests.test_replay_trade_import import _rows, _zip_bytes, START_MS


def adapter_and_network(tmp_path, *, corrupt=False, max_rows_per_file=100_000, rows=None):
    archive = ParquetRawAggTradeArchive(tmp_path / "trades")
    adapter = BarPreparationAdapter(tmp_path / "cache", coordinator=None,
                                   replay_service=SimpleNamespace(raw_trade_archive=archive))
    body, filename = _zip_bytes(_rows() if rows is None else rows)
    digest = "0" * 64 if corrupt else hashlib.sha256(body).hexdigest()
    calls = []

    def opener(url, **kwargs):
        assert len(list((archive.root / "_preparation_downloads").iterdir())) == 1
        calls.append(url)
        return io.BytesIO(f"{digest}  {filename}\n".encode() if url.endswith(".CHECKSUM") else body)

    adapter.trades.importer = partial(import_official_date_range, opener=opener, max_rows_per_file=max_rows_per_file)
    return adapter, archive, calls


def requirement(start=START_MS, end=START_MS + 60_000):
    return Requirement(exchange="binance", market_type="futures", symbol="BTCUSDT",
                       role="TRADES", start_ms=start, end_ms=end)


@async_test
async def test_trade_day_download_shared_by_disjoint_ranges_and_survives_cache_gc(tmp_path):
    adapter, archive, calls = adapter_and_network(tmp_path)
    left = requirement(end=START_MS + 1001)
    right = requirement(start=START_MS + 1001)
    receipts = await asyncio.gather(adapter.acquire(left, "left"), adapter.acquire(right, "right"))
    assert len(calls) == 2  # One checksum and one official ZIP for both selections.
    for selected, (receipt, size) in zip((left, right), receipts):
        assert size > 0
        chunk = {"receipt": receipt, "requirement": selected.model_dump()}
        reference = await storage_call(adapter.trades.validate_receipt, chunk)
        assert reference.row_count == 2
        adapter.remove_cached_object(receipt)
        archive.validate_dataset(reference)
    await adapter.acquire(requirement(), "restart")
    assert len(calls) == 2  # Existing verified archive is reused without network.


@async_test
async def test_trade_storage_counts_shared_objects_once_and_survives_receipt_gc(tmp_path):
    adapter, archive, _ = adapter_and_network(tmp_path)
    repo = PreparationRepository(tmp_path / "jobs.db")
    repo.register_publication_scopes(adapter.publication_scopes())
    selected = (requirement(end=START_MS + 1001), requirement(start=START_MS + 1001))
    receipts = await asyncio.gather(*(adapter.acquire(req, str(i)) for i, req in enumerate(selected)))
    for i, (req, (receipt, size)) in enumerate(zip(selected, receipts)):
        repo.publish_chunk(str(i), req.model_dump(), receipt, size, "run")
    # Legacy receipt charges exist before an inventory has mapped their files.
    assert repo.storage_bytes() == sum(size for _, size in receipts)
    reconcile(repo, threading.Event())
    physical = sum(path.stat().st_size for path in archive.root.rglob("*") if path.is_file())
    selected_files = {archive.root / item["object_id"] for receipt, _ in receipts
                      for item in receipt["dataset"]["objects"]}
    assert repo.cache_inventory()["bytes"] == physical
    assert repo.cache_inventory()["engine_owned_bytes"] == physical
    assert repo.cache_inventory()["referenced_bytes"] == sum(path.stat().st_size for path in selected_files)
    recovered = PreparationRepository(repo.path)
    reconcile(recovered, threading.Event())
    assert recovered.storage_bytes() == physical
    recovered.release("run")
    gc = recovered.evict_unreferenced(adapter.remove_cached_object)
    assert gc == {"removed_chunks": 2, "reclaimed_bytes": 0}
    assert recovered.cache_inventory()["referenced_bytes"] == 0
    assert recovered.storage_bytes() == physical
    # Interrupted imports are inventory even if no successful receipt exists.
    staging = archive.root / ".interrupted-download.tmp"
    staging.write_bytes(b"x" * 31)
    reconcile(recovered, threading.Event())
    assert recovered.storage_bytes() == physical + 31
    staging.unlink()
    reconcile(recovered, threading.Event())
    assert recovered.storage_bytes() == physical


@async_test
async def test_incomplete_trade_file_inventory_keeps_legacy_receipt_charge(tmp_path):
    adapter, archive, _ = adapter_and_network(tmp_path, max_rows_per_file=2)
    receipt, size = await adapter.acquire(requirement(), "legacy")
    repo = PreparationRepository(tmp_path / "jobs.db")
    repo.publish_chunk("legacy", requirement().model_dump(), receipt, size, "run")
    repo.register_publication_scopes(adapter.publication_scopes())
    # Only one file is registered; partial discovery must not discount the whole receipt.
    object_path = archive.root / receipt["dataset"]["objects"][0]["object_id"]
    assert len(receipt["dataset"]["objects"]) == 2
    repo.reconcile_trade_receipts(stop=threading.Event())
    assert repo.storage_bytes() == size
    repo.register_publications([(object_path, "trade_archive")])
    repo.reconcile_trade_receipts(stop=threading.Event())
    assert repo.storage_bytes() == size + object_path.stat().st_size
    reconcile(repo, threading.Event())
    assert repo.storage_bytes() == sum(path.stat().st_size for path in archive.root.rglob("*") if path.is_file())


@async_test
async def test_trade_preparation_publishes_real_immutable_reference(tmp_path):
    adapter, archive, calls = adapter_and_network(tmp_path)
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    try:
        job = await service.submit(PreparationRequest(idempotency_key="trade-prefetch", consumer="PREFETCH",
                                                requirements=[requirement()]))
        ready = await terminal(service, job["id"])
        assert ready["state"] == "READY", ready["error"]
        assert ready["result"]["inputs"][0]["dataset"]["row_count"] == 4
        assert len(calls) == 2
    finally:
        await service.shutdown()


@async_test
async def test_bad_official_checksum_never_publishes_trade_input(tmp_path):
    adapter, archive, calls = adapter_and_network(tmp_path, corrupt=True)
    with pytest.raises(PreparationError, match="checksum"):
        await adapter.acquire(requirement(), "bad")
    assert archive.list_verified_windows(exchange="binance", market_type="futures", symbol="BTCUSDT") == ()


def test_trade_provider_and_open_day_are_explicitly_rejected(tmp_path):
    adapter, _, calls = adapter_and_network(tmp_path)
    for req, code in [(requirement().model_copy(update={"market_type": "spot"}), "TRADE_PROVIDER_UNSUPPORTED"),
                      (requirement(start=adapter.now_ms() - 1000, end=adapter.now_ms()), "TRADE_DAY_UNPUBLISHED")]:
        with pytest.raises(PreparationError) as error:
            adapter.trades.validate(req, adapter.now_ms())
        assert error.value.code == code
    assert calls == []


@async_test
async def test_trade_download_budget_rejects_before_network(tmp_path):
    adapter, archive, calls = adapter_and_network(tmp_path)
    adapter.publication_repository = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=100_000)
    with pytest.raises(PreparationError) as failure:
        await adapter.acquire(requirement(), "budget")
    assert failure.value.code == "STORAGE_BUDGET"
    assert calls == []
    assert not list(archive.root.rglob("*.parquet"))
    assert adapter.publication_repository.cache_inventory()["publication_reserved_bytes"] == 0


@async_test
async def test_budget_limited_transfer_reports_storage_block_instead_of_provider_failure(tmp_path):
    adapter, _, _ = adapter_and_network(tmp_path)
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=2 * 1024**2 + 128 * 1024)
    adapter.publication_repository = repo
    def limited(**kwargs):
        assert kwargs["max_download_bytes"] == 64 * 1024
        raise ReplayTradeImportError("official aggregate-trade object exceeds its byte limit")
    adapter.trades.importer = limited
    with pytest.raises(PreparationError) as failure:
        await adapter.acquire(requirement(), "limited")
    assert failure.value.code == "STORAGE_BUDGET"
    assert repo.abandoned_publications()


@async_test
async def test_trade_expansion_budget_rejects_before_parquet_and_retains_quarantine_charge(tmp_path):
    rows = [[str(100 + i), "100.10", "0.5", str(1000 + i), str(1000 + i),
             str(START_MS + 1000 + i), "true"] for i in range(600)]
    adapter, archive, calls = adapter_and_network(tmp_path, rows=rows)
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=2 * 1024**2 + 128 * 1024)
    adapter.publication_repository = repo
    repo.register_publication_scopes(adapter.publication_scopes())
    with pytest.raises(PreparationError) as failure:
        await adapter.acquire(requirement(), "expansion")
    assert failure.value.code == "STORAGE_BUDGET"
    assert len(calls) == 2
    assert not list(archive.root.rglob("*.parquet"))
    assert repo.cache_inventory()["publication_reserved_bytes"] > 0
    reconcile(repo, threading.Event())
    quarantine_bytes = sum(path.stat().st_size for path in archive.root.rglob("*") if path.is_file())
    assert quarantine_bytes > 0
    assert repo.storage_bytes() == quarantine_bytes
    assert repo.cache_inventory()["publication_reserved_bytes"] == 0
    repo.configure(cache_budget_bytes=16 * 1024**2, prefetch_enabled=False)
    receipt, size = await adapter.acquire(requirement(), "retry")
    before = repo.storage_bytes()
    repo.publish_chunk("retry", requirement().model_dump(), receipt, size, "run")
    assert repo.storage_bytes() == before  # Physical files are already charged.
    assert receipt["dataset"]["row_count"] == 600
    assert repo.cache_inventory()["publication_reserved_bytes"] == 0
    assert len(calls) == 4


@async_test
async def test_trade_replay_preparation_launches_engine_with_bar_and_tape_inputs(tmp_path):
    import httpx
    from fastapi import FastAPI
    from dataclasses import replace
    from app.api.v1.data_preparation import router
    from tests.test_replay_v2_run_centric import _trade_service, _setup_payload
    from tests.fixtures.replay.trade_service_fakes import TRADE_REPLAY_START_MS

    replay = await _trade_service(tmp_path / "replay.db", tmp_path / "trades")
    # Preparation reuses immutable archive inputs and verifies their manifest.
    # A fake query repository without a matching manifest is not an archive.
    from app.replay.catalog import ReplaySeriesIdentity
    from app.replay.history_archive import ReplayHistoryArchiveWriter, ReplayHistoryImportBatch, ReplayHistoryRepository
    root = tmp_path / "bars"
    rows = replay._repository.query_bars("BTCUSDT", "1m", exchange="binance", market_type="futures")
    ReplayHistoryArchiveWriter(root).import_batches(ReplaySeriesIdentity("binance", "futures", "BTCUSDT"), "1m", [
        ReplayHistoryImportBatch(rows=rows, source_provider="test", source_object_key="trade-bars", source_period="test")])
    replay.settings = replace(replay.settings, replay_history_archive_dir=root)
    replay._repository = ReplayHistoryRepository(root)
    adapter = BarPreparationAdapter(tmp_path / "cache", coordinator=None, replay_service=replay)
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    app = FastAPI()
    app.state.data_preparation_service = service
    app.include_router(router)
    try:
        body = {"idempotency_key": "trade-launch-real", "exchange": "binance", "market_type": "futures",
                "symbol": "BTCUSDT", "setup": {**_setup_payload(), "source_kind": "AGG_TRADE",
                "requested_start_ms": TRADE_REPLAY_START_MS, "forward_cache_ms": 4 * 60_000,
                "time_disclosure_policy": "NONE"}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/replay", json=body)
            assert response.status_code == 202, response.text
            ready = await terminal(service, response.json()["id"])
            assert ready["state"] == "READY", ready["error"]
            assert ready["result"]["run"]["adapter_session_id"]
            assert len(ready["result"]["inputs"]) == 2
    finally:
        await service.shutdown()
        await replay.shutdown()


@async_test
async def test_precise_strategy_prepares_bars_and_official_trades(tmp_path):
    import httpx
    from fastapi import FastAPI
    from app.api.v1.data_preparation import router
    from app.backtest.runtime import BacktestRuntime
    from app.core.config import load_backtest_settings
    from tests.test_data_preparation import bars

    adapter, archive, calls = adapter_and_network(tmp_path)
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1",
        "BACKTEST_CHART_CONTEXT_ENABLED": "1", "BACKTEST_TRADE_TAPE_ENABLED": "1"},
        data_dir=tmp_path, klines_db_path=tmp_path / "klines.db", replay_db_path=tmp_path / "replay.db")
    runtime = BacktestRuntime.start(settings, local_data_dir=tmp_path / "local", trade_archive_dir=archive.root)
    adapter.local_data = runtime.local_data
    adapter.backtest_runtime = runtime
    adapter.query = lambda *args, **kwargs: [{**bars()[0], "open_time": START_MS, "close_time": START_MS + 59_999}]
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    app = FastAPI()
    app.state.data_preparation_service = service
    app.state.backtest_runtime = runtime
    app.include_router(router)
    context = {"exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT", "interval": "1m",
               "range_mode": "CUSTOM", "start_time_ms": START_MS, "end_time_ms": START_MS + 59_999,
               "fidelity_preference": "PRECISE"}
    try:
        assert runtime.chart_context.resolve(context, automatic_preparation=True)["status"] == "NEEDS_DATA"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/strategy", json={"idempotency_key": "precise-strategy", "context": context})
            assert response.status_code == 202, response.text
            ready = await terminal(service, response.json()["id"])
            assert ready["state"] == "READY", ready["error"]
            assert ready["result"]["resolution"]["fidelity"]["mode"] == "AGG_TRADE_EXECUTION"
            assert len(calls) == 2
    finally:
        await service.shutdown()
        runtime.shutdown()
