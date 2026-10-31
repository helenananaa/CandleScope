"""Real archive publication and host fills; only transport and engine decisions are fixtures."""
import asyncio
import os
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.data_preparation import router
from app.backtest.runtime import BacktestRuntime
from app.core.config import load_backtest_settings
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.local_data.service import LocalImportOptions
from tests.test_data_preparation import async_test, terminal
from tests.test_replay_trade_import import START_MS, _rows
from tests.test_trade_preparation import adapter_and_network


def environment(tmp_path, *, mismatch=False):
    rows = []
    bars = []
    for minute in range(4):
        for i, original in enumerate(_rows()):
            row = original.copy()
            row[0] = str(100 + minute * 4 + i)
            row[1] = str(Decimal(row[1]) + minute * 10)
            row[3], row[4] = str(1000 + minute * 10 + i), str(1000 + minute * 10 + i)
            row[5] = str(int(row[5]) + minute * 60_000)
            rows.append(row)
        prices = [float(row[1]) for row in rows[-4:]]
        bars.append(dict(open_time=START_MS + minute * 60_000,
            close_time=START_MS + (minute + 1) * 60_000 - 1,
            open=prices[0], high=max(prices), low=min(prices), close=prices[-1], volume=2.5,
            source="backfill_rest_verified"))
    adapter, archive, calls = adapter_and_network(tmp_path, rows=rows)
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1",
        "BACKTEST_CHART_CONTEXT_ENABLED": "1", "BACKTEST_TRADE_TAPE_ENABLED": "1"},
        data_dir=tmp_path, klines_db_path=tmp_path / "bars.db", replay_db_path=tmp_path / "replay.db")
    runtime = BacktestRuntime.start(settings, local_data_dir=tmp_path / "local", trade_archive_dir=archive.root)
    adapter.local_data, adapter.backtest_runtime = runtime.local_data, runtime
    adapter.query = lambda symbol, *args, **kw: bars
    identity = {"protocol": "candlescope.native-strategy/1", "engine": {"package": "test-pine", "version": "test"}}
    observed = []
    def runner(plugin, wire, **kwargs):
        if wire.get("operation") == "describe":
            return {"identity": identity}
        observed.append(wire)
        intents = [{"bar_index": 0, "action": "entry", "id": "L", "direction": "long", "qty": .25}]
        if len(wire["bars"]) > 1:
            intents.append({"bar_index": 1, "action": "close", "id": "L"})
        return {"identity": identity, "execution_mode": "CANDLESCOPE", "account_authority": "candlescope",
            "contract": "external-broker/1", "intents": intents}
    runtime.native.resolver = lambda language: {"plugin_id": "candlescope.pine-compat", "command": ["fixture"]}
    runtime.native.runner = runner
    runtime.native.analyze_source = lambda source, libraries=None: {"requirements": {"requests": []}}
    csv = tmp_path / "signals.csv"
    csv.write_text("time,open,high,low,close,volume\n" + "\n".join(
        f"{bar['open_time']},{bar['open']},{bar['high']},{bar['low']},{bar['close']},{bar['volume'] + int(mismatch)}"
        for bar in bars))
    manifest = runtime.local_data.import_csv(csv, LocalImportOptions(name="Frozen signals", symbol="BTCUSDT",
        interval="1m", timestamp_unit="ms"))
    data = dict(dataset_id=manifest["dataset_id"], data_epoch=manifest["data_epoch"], interval="1m",
        exchange="binance", market_type="futures", start_time_ms=START_MS, end_time_ms=START_MS + 240_000 - 1)
    snapshot = runtime.preview_snapshot(**data)
    run = {**data, "snapshot_hash": snapshot["snapshot_hash"], "language": "pine", "source": 'strategy("fixture")',
        "execution_fidelity": "TRADE_TAPE", "host_settings": {"slippage_bps": 0, "taker_fee_bps": 0},
        "context": {"symbol": "BTCUSDT", "timeframe": "1"}}
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    app = FastAPI()
    app.include_router(router)
    app.state.data_preparation_service, app.state.backtest_runtime = service, runtime
    return runtime, service, app, run, calls, observed


@async_test
@pytest.mark.parametrize("frozen,language", [(False, "fixture"), (True, "fixture"), (True, "pine")])
async def test_host_preparation_freezes_signals_and_matches_verified_prints(tmp_path, frozen, language):
    if language != "fixture" and not os.environ.get("NATIVE_TEST_PYTHON"):
        pytest.skip("requires installed native strategy plugins")
    runtime, service, app, run, calls, observed = environment(tmp_path)
    if language != "fixture":
        from app.backtest.native import invoke
        from tests.test_native_strategy_plugins import plugin
        runtime.native.runner, runtime.native.resolver = invoke, plugin
        run["language"] = language
        run["source"] = '''//@version=6
strategy("Prepared Renko")
r = ticker.renko(syminfo.tickerid, "Traditional", 0.05)
brick = request.security(r, timeframe.period, close)
previous = request.security(r, timeframe.period, close[1])
plot(brick)
if bar_index == 1 and brick > previous
    strategy.entry("L", strategy.long, qty=0.25)
if bar_index == 2 and brick > previous
    strategy.close("L")
'''
    await service.start()
    try:
        if frozen:
            route = "/external-strategy"
            body = {"idempotency_key": "frozen-host-trades", "run": run}
        else:
            route = "/native-strategy"
            body = {"idempotency_key": "live-host-trades", "language": "pine", "source": run["source"],
                "execution": {"execution_fidelity": "TRADE_TAPE", "host_settings": run["host_settings"]},
                "context": {key: run[key] for key in ("exchange", "market_type", "interval", "start_time_ms", "end_time_ms")}}
            body["context"].update(symbol="BTCUSDT", range_mode="CUSTOM", fidelity_preference="FAST")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations" + route, json=body)
            assert response.status_code == 202, response.text
            job = await terminal(service, response.json()["id"])
            assert job["state"] == "READY", job["error"]
            again = await client.post("/data-preparations" + route, json=body)
            assert again.json()["id"] == job["id"]
            changed = {**body, "run": {**run, "source": 'strategy("changed")'}} if frozen else {**body, "source": 'strategy("changed")'}
            assert (await client.post("/data-preparations" + route, json=changed)).status_code == 409
        for _ in range(2000):
            record = runtime.native.get(job["result"]["native_run"]["run_id"])
            if record["state"] in {"COMPLETED", "FAILED"}: break
            await asyncio.sleep(.01)
        assert record["state"] == "COMPLETED", record.get("error")
        result = record["result"]
        assert result["account_authority"] == "candlescope"
        expected_prices = ["110.1", "120.1"] if language == "fixture" else ["120.1", "130.1"]
        assert [Decimal(row["price"]) for row in result["trades"]] == list(map(Decimal, expected_prices))
        fill_minutes = [1, 2] if language == "fixture" else [2, 3]
        assert [row["event_time_ms"] for row in result["trades"]] == [START_MS + minute * 60_000 + 1000 for minute in fill_minutes]
        assert Decimal(result["closed_trades"][0]["profit"]) == Decimal("2.5")
        assert len(calls) == 2  # One verified checksum and one ZIP; no bar replacement.
        assert [item["role"] for item in job["request"]["requirements"]].count("TRADES") == 1
        if frozen:
            assert record["config"]["dataset_id"] == run["dataset_id"]
            assert record["config"]["snapshot_hash"] == run["snapshot_hash"]
            assert len(job["request"]["requirements"]) == 1
        assert len(runtime.native.list()) == 1
        if language == "fixture":
            # Baseline plus independently rerun baseline/fee/slippage scenarios.
            assert len(observed) == 16
            assert [len(wire["bars"]) for wire in observed] == [1, 2, 3, 4] * 4
            assert result["cost_sensitivity"]["baseline_reexecution_verified"]
        else:
            graphic = result["graphics"][0]
            first_brick = graphic["values"][1] if "values" in graphic else next(point["value"] for point in graphic["data"] if point["time"] == START_MS // 1000 + 60)
            assert first_brick == 110.3
            assert first_brick != float(result["trades"][0]["price"])
    finally:
        await service.shutdown()
        runtime.shutdown()


@async_test
async def test_frozen_mismatch_does_not_replace_csv_or_launch_engine(tmp_path):
    runtime, service, app, run, calls, observed = environment(tmp_path, mismatch=True)
    await service.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/external-strategy", json={"idempotency_key": "mismatch-host", "run": run})
            assert response.status_code == 202, response.text
            job = await terminal(service, response.json()["id"])
        assert job["state"] == "FAILED", job
        assert "DATA_SNAPSHOT_MISMATCH" in str(job["error"])
        assert runtime.native.list() == []
        assert not observed
        assert runtime.preview_snapshot(**{key: run[key] for key in ("dataset_id", "data_epoch", "interval", "exchange", "market_type", "start_time_ms", "end_time_ms")})["snapshot_hash"] == run["snapshot_hash"]
    finally:
        await service.shutdown()
        runtime.shutdown()


@async_test
@pytest.mark.parametrize("change,code", [
    ({"snapshot_hash": "sha256:" + "ab" * 32}, "DATA_SNAPSHOT_MISMATCH"),
    ({"context": {"symbol": "ETHUSDT", "timeframe": "1"}}, "DATA_SNAPSHOT_MISMATCH"),
    ({"execution_fidelity": "BAR_APPROX"}, "INPUT_UNSUPPORTED"),
    ({"market_type": "spot"}, "TRADE_PROVIDER_UNSUPPORTED"),
])
async def test_frozen_invalid_inputs_reject_before_downloading(tmp_path, change, code):
    runtime, service, app, run, calls, observed = environment(tmp_path)
    await service.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/external-strategy", json={"idempotency_key": "invalid-host", "run": {**run, **change}})
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == code
        assert calls == observed == []
    finally:
        await service.shutdown()
        runtime.shutdown()
