"""Exercise first preparation with an empty history and cold instrument catalog."""
import asyncio
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.data_preparation import router
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.replay.training.models import TrainingRunSetupRequest
from tests.fixtures.replay.service_fakes import replay_settings
from tests.test_data_preparation import START, async_test, bars, terminal
from tests.test_replay_v2_run_centric import _setup_payload


@pytest.mark.parametrize("progressive", [True, False])
@pytest.mark.parametrize("catalog", ["warm", "refresh", "recover"])
@async_test
async def test_first_history_preparation_and_metadata_recovery(tmp_path, progressive, catalog):
    available = catalog == "warm"
    refreshes = []

    async def refresh(exchange, market):
        nonlocal available
        refreshes.append((exchange, market))
        if catalog == "refresh":
            available = True

    replay = ReplayService(
        settings=replace(replay_settings(tmp_path / "replay.db"),
                         replay_history_archive_dir=tmp_path / "history",
                         max_warmup_bars=5000, max_bar_dataset_rows=100000,
                         trade_page_rows=50000),
        store=ReplaySQLiteStore(tmp_path / "replay.db"),
        instrument_metadata_resolver=lambda exchange, market, symbol: (
            {"exchange": exchange, "marketType": market, "symbol": symbol,
             "baseAsset": "LTC", "quoteAsset": "USDT"} if available else None),
        instrument_metadata_refresher=refresh,
    )
    await replay.start()
    inventory, acquisitions = {}, []

    class Coordinator:
        async def request_and_wait(self, repair):
            acquisitions.append((repair.start_ms, repair.end_ms))
            for timestamp in range(repair.start_ms, repair.end_ms + 1, 60000):
                inventory[timestamp] = {**bars()[0], "open_time": timestamp,
                                        "close_time": timestamp + 59999}

    adapter = BarPreparationAdapter(
        tmp_path / "chunks", coordinator=Coordinator(), replay_service=replay,
        query=lambda *a, **kw: [inventory[t] for t in sorted(inventory)
                               if kw["start_ms"] <= t <= kw["end_ms"]],
    )
    repository = PreparationRepository(tmp_path / "jobs.db")
    service = PreparationService(repository, adapter)
    await service.start()
    app = FastAPI()
    app.state.data_preparation_service = service
    app.include_router(router)
    try:
        assert (await replay.catalog(warmup_bars=200, horizon_ms=86400000,
                                     quality_mode="exact", blind_mode=False))["entries"] == []
        setup = {**_setup_payload(), "requested_start_ms": START + 479 * 60000,
                 "indicator_warmup_bars": 200, "forward_cache_ms": 86400000,
                 "visible_history_lookback": {"mode": "ALL_AVAILABLE", "duration_ms": None},
                 "time_disclosure_policy": "NONE"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/replay", json={
                "idempotency_key": "first-launch-empty-catalog", "setup": setup,
                "exchange": "binance", "market_type": "spot", "symbol": "LTCUSDT",
                "display_interval": "1h", "progressive": progressive})
            assert response.status_code == 202, response.text
            job_id = response.json()["id"]
            if catalog == "recover":
                async def waiting():
                    while True:
                        job = repository.get(job_id)
                        if job["error"] is not None:
                            return job
                        await asyncio.sleep(.005)
                failed = await asyncio.wait_for(waiting(), 5)
                assert failed["state"] == "QUEUED", failed
                assert failed["error"]["code"] == "INSTRUMENT_METADATA_UNAVAILABLE"
                assert failed["error"]["retryable"] is True
                assert failed["result"]["inputs"]
                assert "run" not in failed["result"]
                first_downloads = list(acquisitions)
                await service.shutdown()
                # Restart after the persisted retry deadline with the original
                # journal, published input and newly available catalog.
                available = True
                repository = PreparationRepository(repository.path)
                repository.now = lambda: failed["next_attempt_ms"] + 1
                service = PreparationService(repository, adapter)
                app.state.data_preparation_service = service
                await service.start()
            ready = await terminal(service, job_id)
            assert ready["state"] == "READY", ready
            assert ready["result"]["run"]["adapter_session_id"]
            assert acquisitions and len(acquisitions) == len(set(acquisitions))
            if catalog == "recover":
                assert all(acquisitions.count(item) == 1 for item in first_downloads)
            assert refreshes == ([] if catalog == "warm" else [("binance", "spot")])
            # A launch receipt lost after consumer commit can be replayed while
            # offline; the committed account identity must not need refresh.
            available = False
            old_refreshes = list(refreshes)
            same = await replay.training.create_empty_run(
                TrainingRunSetupRequest.from_dict(setup), preparation_id=job_id,
                _preparation_market_identity=("binance", "spot", "LTCUSDT"))
            assert same["created"] is False
            assert same["run"]["run_id"] == ready["result"]["run"]["run_id"]
            assert refreshes == old_refreshes
    finally:
        await service.shutdown()
        await replay.shutdown(step_timeout=5)
