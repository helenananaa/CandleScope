"""A fresh replay can acquire a second market without replacing its account."""
import asyncio
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.data_preparation import router
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.models import PreparationError
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.replay.training.errors import TrainingRunError
from app.replay.training.models import ReplayV2CommandType as Command
from tests.fixtures.replay.service_fakes import replay_settings
from tests.test_data_preparation import START, async_test, bars, terminal
from tests.test_replay_v2_run_centric import _setup_payload
from tests.test_replay_v2_training_phase5 import _acquire, _command


@pytest.mark.parametrize("progressive", [True, False])
@pytest.mark.parametrize("recover", [False, True])
@async_test
async def test_second_market_preparation_preserves_frozen_run(tmp_path, progressive, recover):
    def metadata(exchange, market, symbol):
        base, quote = {"LTCUSDT": ("LTC", "USDT"), "DOGEUSDT": ("DOGE", "USDT"),
                       "DOGEBTC": ("DOGE", "BTC")}.get(symbol, (None, None))
        return ({"exchange": exchange, "marketType": market, "symbol": symbol,
                 "baseAsset": base, "quoteAsset": quote} if base else None)

    replay = ReplayService(
        settings=replace(replay_settings(tmp_path / "replay.db"),
                         replay_history_archive_dir=tmp_path / "history",
                         max_warmup_bars=5000, max_bar_dataset_rows=100000),
        store=ReplaySQLiteStore(tmp_path / "replay.db"), instrument_metadata_resolver=metadata,
    )
    await replay.start()
    inventory, acquisitions = {}, []
    fail = recover

    class Coordinator:
        async def request_and_wait(self, repair):
            if repair.symbol == "DOGEUSDT" and fail:
                raise PreparationError("UPSTREAM_UNAVAILABLE", "temporary history outage", retryable=True)
            acquisitions.append((repair.symbol, repair.start_ms, repair.end_ms))
            for timestamp in range(repair.start_ms, repair.end_ms + 1, 60_000):
                inventory[repair.symbol, timestamp] = {
                    **bars()[0], "open_time": timestamp, "close_time": timestamp + 59_999,
                }

    adapter = BarPreparationAdapter(
        tmp_path / "chunks", coordinator=Coordinator(), replay_service=replay,
        query=lambda symbol, interval, **kw: [inventory[s, t] for s, t in sorted(inventory)
            if s == symbol and kw["start_ms"] <= t <= kw["end_ms"]],
    )
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    app = FastAPI()
    app.state.data_preparation_service = service
    app.include_router(router)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            setup = {**_setup_payload(), "requested_start_ms": START + 479 * 60_000,
                     "indicator_warmup_bars": 200, "forward_cache_ms": 86_400_000,
                     "visible_history_lookback": {"mode": "ALL_AVAILABLE", "duration_ms": None},
                     "time_disclosure_policy": "NONE"}
            first = await client.post("/data-preparations/replay", json={
                "idempotency_key": "first-market-history", "setup": setup, "exchange": "binance",
                "market_type": "spot", "symbol": "LTCUSDT", "progressive": progressive})
            assert first.status_code == 202, first.text
            ready = await terminal(service, first.json()["id"])
            assert ready["state"] == "READY", ready
            run = ready["result"]["run"]
            run_id, session_id = run["run_id"], run["adapter_session_id"]
            await _acquire(replay, run_id=run_id, selected_session_id=session_id, command_id="acquire-first")
            order = {"client_order_id": "first-order", "side": "BUY", "order_type": "MARKET",
                     "quantity": "1", "reduce_only": False, "limit_price": None, "stop_price": None}
            await replay.training.command(run_id, _command(run_id, "buy-first", Command.PLACE_ORDER,
                await replay.get_session(session_id), order))
            frozen = await replay.training.store.run_binding(run_id)
            before = await replay.training.get_market_tracks(run_id)
            assert before["portfolio"]["positions"][0]["position"]["quantity"] == "1"
            with pytest.raises(TrainingRunError) as missing:
                await replay.training.market_track_plan(run_id, exchange="binance", market_type="spot",
                                                        symbol="DOGEUSDT", subscription_tier="NONE")
            assert missing.value.code == "MARKET_TRACK_UNAVAILABLE"
            payload = {"run_id": run_id, "exchange": "binance", "market_type": "spot", "symbol": "DOGEUSDT"}
            for mismatch in [{"exchange": "other"}, {"market_type": "futures"}, {"symbol": "DOGEBTC"}]:
                denied = await client.post("/data-preparations/replay-market", json={**payload, **mismatch})
                assert denied.status_code == 409, denied.text
                assert denied.json()["detail"]["code"] == "MARKET_SCOPE_MISMATCH"
            assert all(symbol == "LTCUSDT" for symbol, *_ in acquisitions)
            submitted = await client.post("/data-preparations/replay-market", json=payload)
            assert submitted.status_code == 202, submitted.text
            job_id = submitted.json()["id"]
            if recover:
                async def waiting():
                    while True:
                        job = service.repository.get(job_id)
                        if job["error"]:
                            return job
                        await asyncio.sleep(.005)
                failed = await asyncio.wait_for(waiting(), 5)
                assert failed["state"] == "QUEUED" and failed["error"]["retryable"]
                await service.shutdown()
                fail = False
                repository = PreparationRepository(tmp_path / "jobs.db")
                repository.now = lambda: failed["next_attempt_ms"] + 1
                service = PreparationService(repository, adapter)
                app.state.data_preparation_service = service
                await service.start()
            prepared = await terminal(service, job_id)
            assert prepared["state"] == "READY", prepared
            same = await client.post("/data-preparations/replay-market", json=payload)
            assert same.json()["id"] == job_id
            assert "run" not in prepared["result"]
            assert await replay.training.store.run_binding(run_id) == frozen
            after = await replay.training.get_market_tracks(run_id)
            assert after["tracks"] == before["tracks"] and after["portfolio"] == before["portfolio"]
            requirement = prepared["request"]["requirements"][0]
            assert requirement["start_ms"] == setup["requested_start_ms"] - 200 * 60_000
            assert requirement["end_ms"] == setup["requested_start_ms"] + 86_400_000
            assert len(acquisitions) == len(set(acquisitions))
            plan = await replay.training.market_track_plan(run_id, exchange="binance", market_type="spot",
                                                          symbol="DOGEUSDT", subscription_tier="NONE")
            added = await replay.training.command(run_id, _command(run_id, "add-second", Command.ADD_TRACK,
                await replay.get_session(session_id), {"plan_id": plan["plan_id"]}))
            selected = await replay.training.command(run_id, _command(run_id, "select-second", Command.SELECT_TRACK,
                await replay.get_session(session_id), {"track_id": added["data"]["track"]["track_id"],
                    "expected_viewer_revision": added["viewer_state"]["semantic_view_revision"]}))
            tracks = await replay.training.get_market_tracks(run_id)
            assert len(tracks["tracks"]) == 2
            assert selected["viewer_state"]["selected_track_id"] == added["data"]["track"]["track_id"]
            assert {track["symbol"] for track in tracks["tracks"]} == {"LTCUSDT", "DOGEUSDT"}
            second_session = selected["session_id"]
            await replay.training.command(run_id, _command(run_id, "buy-second", Command.PLACE_ORDER,
                await replay.get_session(second_session), {**order, "client_order_id": "second-order"}))
            await replay.training.command(run_id, _command(run_id, "step-both", Command.STEP_BASE,
                await replay.get_session(second_session), {"count": 1}))
            advanced = await replay.training.get_market_tracks(run_id)
            assert len(advanced["portfolio"]["positions"]) == 2
            assert len({track["cursor"]["virtual_time_ms"] for track in advanced["tracks"]}) == 1
    finally:
        await service.shutdown()
        await replay.shutdown(step_timeout=5)
