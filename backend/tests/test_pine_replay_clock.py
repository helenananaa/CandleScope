"""Replay HTTP -> durable cursor -> isolated installed Pine -> local providers."""

import os
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import indicators
from app.indicator.replay_context import IndicatorReplayContext, replay_execution_options
from app.indicator.runtime_routes import IndicatorRuntimeRoute, IndicatorRuntimeRoutes
from app.indicator.runtime_service import IndicatorRuntimeService
from app.plugin_runtime.registry import runtime_registry_from_wire
from app.plugin_runtime.service import RuntimeHostService
from app.replay.training.errors import TrainingRunError
from candlescope_plugin_sdk import Bar
from tests.test_replay_v2_training_phase5 import _request, _service

pytestmark = pytest.mark.anyio


@pytest.fixture
async def replay(tmp_path):
    path = tmp_path / "clock.db"
    service = await _service(path)
    created = await service.training.create_run(await _request(service))
    session = created["run"]["adapter_session_id"]
    tracks = await service.training.get_market_tracks(created["run"]["run_id"])
    track = tracks["tracks"][0]["track_id"]
    binding = await service.training.store.history_binding(session_id=session, track_id=track)
    context = IndicatorReplayContext(sessionId=session, trackId=track,
        dataEpoch=binding["session_data_epoch"], revealedBoundaryMs=binding["virtual_time_ms"],
        sourceSequence=binding["source_sequence"])
    try:
        yield service, context, path
    finally:
        await service.shutdown(step_timeout=1.0)


@pytest.mark.parametrize(("changed", "code"), [
    ({"revealedBoundaryMs": "future"}, "HISTORY_BOUNDARY_AHEAD"),
    ({"sourceSequence": "future"}, "HISTORY_SOURCE_SEQUENCE_AHEAD"),
    ({"dataEpoch": "sha256:" + "0" * 64}, "HISTORY_DATA_EPOCH_MISMATCH"),
])
async def test_durable_clock_rejects_stale_or_ahead_observations(replay, changed, code):
    service, context, _ = replay
    changed = {key: getattr(context, key) + 1 if value == "future" else value for key, value in changed.items()}
    with pytest.raises(TrainingRunError) as caught:
        await replay_execution_options(context.model_copy(update=changed), service.training,
            exchange="binance", market_type="spot", symbol="BTCUSDT")
    assert caught.value.code == code
    with pytest.raises(TrainingRunError, match="market does not match"):
        await replay_execution_options(context, service.training,
            exchange="okx", market_type="spot", symbol="BTCUSDT")


async def test_http_batch_checks_shared_replay_context_once_before_scheduling(replay, monkeypatch):
    service, context, _ = replay
    app = FastAPI()
    app.include_router(indicators.router)
    app.state.replay_service = service
    calls = []
    original = service.training.store.history_binding

    async def observed(**kwargs):
        calls.append(kwargs)
        return await original(**kwargs)

    monkeypatch.setattr(service.training.store, "history_binding", observed)
    body = {"context": {"exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT", "interval": "1m",
        "replayContext": context.model_dump()}, "ohlcv": [{"time": context.revealedBoundaryMs // 1000,
        "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
        "requests": [{"clientId": str(i), "jobKey": str(i), "mode": "builtin", "name": "MA"} for i in range(3)]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
        assert (await client.post("/indicators/compute/batch", json=body)).json()["ok"] is True
        assert len(calls) == 1
        body["context"]["replayContext"]["revealedBoundaryMs"] += 1
        result = await client.post("/indicators/compute/batch", json=body)
        assert result.status_code == 409
        assert result.json()["detail"]["code"] == "HISTORY_BOUNDARY_AHEAD"
        body["context"]["replayContext"]["revealedBoundaryMs"] = True
        assert (await client.post("/indicators/compute/batch", json=body)).status_code == 422
        assert len(calls) == 2


@pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"), reason="requires installed Pine candidate")
@pytest.mark.parametrize("window", [1, 128, 628])
async def test_forming_chart_replay_uses_captured_clock_across_retry_and_process_restart(replay, tmp_path, window):
    service, context, path = replay
    # Stop before a small candle closes inside a still-forming 5m chart bar.
    start = ((context.revealedBoundaryMs - 120_000) // 300_000) * 300_000
    boundary = start + 119_999
    context = context.model_copy(update={"revealedBoundaryMs": boundary})
    python = os.environ["NATIVE_TEST_PINE_PYTHON"]
    version = subprocess.check_output([python, "-I", "-c",
        "from importlib.metadata import version; print(version('candlescope-plugin-pine-compat'))"],
        executable=python, text=True).strip()
    registry = runtime_registry_from_wire({"schemaVersion": 1, "plugins": [{
        "id": "candlescope.pine-compat", "package": "candlescope-plugin-pine-compat", "version": version,
        "enabled": True, "autoStart": False, "required": False,
        "launch": {"executable": os.environ["NATIVE_TEST_PINE_PYTHON"],
            "args": ["-I", "-u", "-m", "candlescope_plugin_pine_compat"], "workingDirectory": str(tmp_path)},
    }]})
    host = RuntimeHostService(registry, host_name="CandleScope", host_version="0.3.0")
    runtime = IndicatorRuntimeService(IndicatorRuntimeRoutes((
        IndicatorRuntimeRoute(language="pyne", mode="legacy"),
        IndicatorRuntimeRoute(language="pine", mode="sidecar", runtime_id="candlescope.pine-compat"),
    )), host=host)
    calls = []
    remote = [Bar(time=(start // 1000) + i * 60, open=i + 10, high=i + 11, low=i + 9,
        close=i + 10, volume=1) for i in range(-2, 8)]

    def query(symbol, interval, **kwargs):
        calls.append((symbol, interval, kwargs))
        # Over-return deliberately, like a stale local cache: the host must
        # still enforce the captured boundary before the engine receives rows.
        return SimpleNamespace(bars=remote, missing_ranges=[])

    runtime.pine_data_manager = lambda: SimpleNamespace(query=query)
    app = FastAPI()
    app.include_router(indicators.router)
    app.state.replay_service = service
    app.state.indicator_runtime_service = runtime
    source = '''//@version=6
indicator("Replay clock")
plot(timenow, title="clock")
values = request.security_lower_tf("OKX:ETH-USDT", "1", close)
plot(array.size(values), title="count")
plot(request.security("OKX:ETH-USDT", "1", close), title="remote")
plot(request.currency_rate("USD", "EUR"), title="fx")
'''
    rates = {"schemaVersion": 1, "pairs": [{"from": "USD", "to": "EUR", "rates": [
        {"effectiveTime": start - 1, "rate": .8}, {"effectiveTime": start + 120_000, "rate": .9}]}]}
    body = {"context": {"exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT", "interval": "5m",
        "replayContext": context.model_dump()}, "ohlcv": [{"time": start // 1000 - index * 300,
        "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1, "is_closed": index != 0}
            for index in reversed(range(window))],
        "requests": [{"clientId": "pine", "jobKey": "clock", "mode": "script", "language": "pine", "script": source,
            "params": {"__pineContexts": [{"symbol": "OKX:ETH-USDT", "timeframe": "1", "marketType": "usdm"}],
                "__pineCurrencyRates": rates}}]}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
            async def compute():
                response = await client.post("/indicators/compute/batch", json=body)
                assert response.status_code == 200, response.text
                result = response.json()["results"][0]["payload"]
                assert result["ok"] is True, result
                return result

            first = await compute()
            values = [line["data"][-1]["value"] for line in first["lines"]]
            assert values == [boundary, 2, 11, .8]
            assert calls[-1][0:2] == ("ETH-USDT", "1m")
            assert calls[-1][2] == {"end_ms": boundary, "limit": 100001, "exchange": "okx", "market_type": "usdm", "auto_backfill": False}
            remote.append(replace(remote[-1], time=remote[-1].time + 60, close=999))
            rates["pairs"][0]["rates"].append({"effectiveTime": start + 300_000, "rate": 1.5})
            assert await compute() == first
            await runtime.stop()
            await host.stop()
            # A freshly loaded SQLite replay and newly launched plugin must
            # use the same captured observation after interrupted work.
            await service.shutdown(step_timeout=1.0)
            recovered = await _service(path)
            app.state.replay_service = recovered
            try:
                assert await compute() == first
            finally:
                await recovered.shutdown(step_timeout=1.0)
            # Realtime requests deliberately retain the wall clock path.
            del body["context"]["replayContext"]
            live = await compute()
            assert live["lines"][0]["data"][-1]["value"] > boundary
            assert live["lines"][1]["data"][-1]["value"] == 5
    finally:
        await runtime.stop()
        await host.stop()
