import asyncio
import os

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.data_preparation import router
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.models import PreparationRequest
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from tests.test_backtest_chart_context import _runtime
from tests.test_backtest_account_v2_m4 import rules
from tests.test_data_preparation import START, async_test, terminal
from tests.test_native_strategy_plugins import plugin


@async_test
@pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PYTHON"), reason="requires installed Pine worker")
async def test_automatic_pine_bar_v2_preparation_preserves_account_inputs_and_launch_identity(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.native.resolver = plugin
    inventory, acquired = [], []
    class Coordinator:
        async def request_and_wait(self, repair):
            acquired.append(repair.symbol)
            inventory.extend({"open_time": stamp, "close_time": stamp + 59999,
                "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "source": "backfill_rest_verified"}
                for stamp in range(repair.start_ms, repair.end_ms + 1, 60000))
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(), local_data=runtime.local_data,
        backtest_runtime=runtime, query=lambda symbol, *args, **kw: [row for row in inventory
            if kw["start_ms"] <= row["open_time"] <= kw["end_ms"]])
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    app = FastAPI()
    app.include_router(router)
    app.state.data_preparation_service, app.state.backtest_runtime = service, runtime
    body = {"idempotency_key": "automatic-pine-v2-bar", "language": "pine", "source": '''//@version=6
strategy("Automatic V2",calc_on_order_fills=true)
varip bool sent=false
if bar_index==0 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=7)
if strategy.position_size>0
    strategy.exit("X","L",stop=9.5,limit=10.5)
''', "context": {"exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT", "interval": "1m",
        "range_mode": "CUSTOM", "fidelity_preference": "FAST", "start_time_ms": START, "end_time_ms": START + 300000 - 1},
        "chart_metadata": {"priceTickSize": "1/10"}, "execution": {"execution_fidelity": "BAR_APPROX", "fill_recalculation": True,
            "host_settings": {"initial_balance": 10000, "slippage_bps": 0, "taker_fee_bps": 0},
            "account_model": "LINEAR_PERP_ONE_WAY_V2", "leverage": 10, "funding_mode": "HISTORICAL_REQUIRED",
            "execution_model_revision": "EXECUTION_REALISM_V2", "participation_rate": .05,
            "account_data": {"symbol": "BTCUSDT", "events": [
                {"time_ms": START - 2, "role": "INSTRUMENT_RULES", "payload": dict(rules().payload)},
                {"time_ms": START - 1, "role": "MARK_INDEX", "payload": {"mark_price": "10", "index_price": "10"}},
                {"time_ms": START + 70000, "role": "FUNDING", "payload": {"funding_rate": ".01", "period_id": "prepared"}}],
                "provenance": {"fixture": "account-data"}}}}
    await service.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            invalid = {**body, "execution": {**body["execution"], "account_data": None}}
            assert (await client.post("/data-preparations/native-strategy", json=invalid)).status_code == 422
            assert acquired == []
            response = await client.post("/data-preparations/native-strategy", json=body)
            assert response.status_code == 202, response.text
            job = await terminal(service, response.json()["id"])
            assert job["state"] == "READY", job.get("error")
            assert (await client.post("/data-preparations/native-strategy", json=body)).json()["id"] == job["id"]
            changed = {**body, "execution": {**body["execution"], "participation_rate": .1}}
            assert (await client.post("/data-preparations/native-strategy", json=changed)).status_code == 409
        key = job["result"]["native_run"]["run_id"]
        for _ in range(1000):
            record = runtime.native.get(key)
            if record["state"] in {"COMPLETED", "FAILED"}:
                break
            await asyncio.sleep(.02)
        assert record["state"] == "COMPLETED", record.get("error")
        assert record["config"]["account_data"] == body["execution"]["account_data"]
        assert [float(row["qty"]) for row in record["result"]["trades"]] == [5, 2, 3, 4]
        assert float(record["result"]["position"]["cumulative_funding"]) == -.5
        assert record["result"]["fill_model"] == "PINE_OHLC_PATH_V2"
        resumed = await adapter.launch(PreparationRequest.model_validate(job["request"]), job["result"], job["id"])
        assert resumed["native_run"]["run_id"] == key and len(runtime.native.list()) == 1
    finally:
        await service.shutdown()
        runtime.shutdown()
