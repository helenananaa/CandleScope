"""ADR-BACKTEST-015 P2: real native and CandleScope-matched Pine runs through the run facade.

Needs the qualified Pine runtime (runs in the "Pine host contracts" workflow).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.backtest.run_result import from_native_record
from app.data_engine.data_manager.strategy import StrategyDataManager
from tests.test_run_result_pine import EXTERNAL
from tests.test_strategy_run_oracles_pine import native_runtime, pytestmark  # noqa: F401 - fixture, marker


def test_pine_runs_read_the_same_through_the_facade(native_runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.backtests import router as family_router
    from app.api.v1.strategy_runs import router
    from tests.test_native_backtests import terminal

    runtime, request = native_runtime
    native_id = terminal(runtime.native, runtime.native.create(request, "facade-native")["run_id"], timeout=90)["run_id"]
    external_id = terminal(runtime.native, runtime.native.create({**request, **EXTERNAL}, "facade-external")["run_id"],
                           timeout=90)["run_id"]
    app = FastAPI()
    app.state.data_manager_core = SimpleNamespace(strategy=StrategyDataManager(runtime.service, runtime=runtime))
    app.include_router(router)
    app.include_router(family_router)
    with TestClient(app) as client:
        native = client.get(f"/strategy-runs/{native_id}").json()
        external = client.get(f"/strategy-runs/{external_id}").json()
        native_result = client.get(f"/strategy-runs/{native_id}/result")
        external_result = client.get(f"/strategy-runs/{external_id}/result")
        adapters = (client.get(f"/backtests/native/runs/{native_id}/run-result").json(),
                    client.get(f"/backtests/external/runs/{external_id}/run-result").json())
        matrix = client.get("/strategy-runs/capabilities").json()
    assert (native["family"], native["authority"], native["fidelity"], native["language"], native["state"]) == (
        "native", "SCRIPT", None, "pine", "COMPLETED")
    assert (external["family"], external["authority"], external["fidelity"], external["language"], external["state"]) == (
        "external", "HOST", "BAR_APPROX", "pine", "COMPLETED")
    assert native["result_available"] and external["result_available"]
    assert native_result.status_code == external_result.status_code == 200
    assert native_result.json() == from_native_record(runtime.native.get(native_id)) == adapters[0]
    assert external_result.json() == from_native_record(runtime.native.get(external_id)) == adapters[1]
    rows = {(row["family"], row["language"]): row for row in matrix["profiles"]}
    assert rows["native", "pine"]["available"] and rows["external", "pine"]["available"]
    assert matrix["families"]["native"]["available"] and matrix["families"]["external"]["available"]


def test_a_real_pine_run_is_watched_to_completion_without_polling(native_runtime):
    import asyncio

    runtime, request = native_runtime

    async def check():
        manager = StrategyDataManager(runtime.service, runtime=runtime)
        run_id = runtime.native.create(request, "facade-watch")["run_id"]
        frames = [frame async for frame in (await manager.runs().watch(run_id)).events() if frame["type"] != "heartbeat"]
        states = [frame["status"]["state"] for frame in frames]
        assert states[-1] == "COMPLETED" and frames[-1]["terminal"] and frames[-1]["status"]["result_available"]
        assert set(states) <= {"QUEUED", "RUNNING", "COMPLETED"} and len(states) == len(set(states))
        assert runtime.native.run_updates.diagnostics()["subscriptions"] == 0
        manager.close()
    asyncio.run(check())
