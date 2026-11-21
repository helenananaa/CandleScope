"""ADR-BACKTEST-015 P2d: a forward run's committed account through the run facade.

The production continuous controller, its SQLite store and closed-bar events, as in
``test_continuous_strategy_access.py``; no public feed.
"""
import asyncio

import pytest

from app.backtest.continuous_results import FORWARD_RESULT_KINDS
from app.backtest.errors import BacktestError
from app.backtest.run_result import from_host_result
from app.data_engine.data_manager.models import DataEvent, DataEventType
from app.data_engine.data_manager.strategy_runs import STREAM_SCHEMA
from tests.test_continuous_strategy_access import access_setup, create
from tests.test_continuous_strategy_runtime import wait_row
from tests.test_kline_revision_contract import storage as storage  # noqa: F401 - fixture
from tests.test_query_cache_fencing import KEY, START, STEP


def committed_projection(controller, run_id):
    """What the facade must serve: the stored checkpoint's kernel state, projected like a fixed run."""
    engine = controller.store.load(run_id)["checkpoint"]["engine"]
    account = {key: value for key, value in engine["account"].items() if key != "journal"}
    kernel = {**{kind: engine.get(kind, []) for kind in FORWARD_RESULT_KINDS}, "ledger": {"account": account}}
    return from_host_result(kernel, interval="1m", fidelity="BAR_APPROX", clock_policy="FORWARD")


@pytest.mark.parametrize("history", [False, True])
def test_a_forward_run_is_served_and_watched_through_the_facade(storage, tmp_path, monkeypatch, history):
    manager, service, gate, _active, _calls, now = access_setup(storage, tmp_path, monkeypatch)

    async def scenario():
        try:
            await gate.start_continuous()
            access, controller = gate.continuous_access(), gate.continuous
            accepted = await create(access, history=history)
            run_id = accepted["run_id"]
            await controller.wait_initial("request")
            await wait_row(controller.store, run_id, lambda row: row["phase"] == "LIVE")
            runs = gate.runs()

            status = await runs.status(run_id)
            assert (status["family"], status["clock_policy"], status["state"], status["source_state"]) == (
                "continuous", "FORWARD", "RUNNING", "LIVE")
            assert status["result_available"] is True and status["terminal"] is False
            served = await runs.result(run_id)
            assert served == committed_projection(controller, run_id)
            if history:  # the caught-up history already traded
                assert served["fills"] and served["trades"] and served["equity"]
            assert (served["source"], served["authority"], served["clock_policy"], served["interval"]) == (
                "host-kernel", "HOST", "FORWARD", "1m")

            watch = await runs.watch(run_id)
            stream = watch.events()
            first = await anext(stream)
            assert first["schema"] == STREAM_SCHEMA and first["status"]["state"] == "RUNNING"
            revision = first["progress"]["sequence"]
            # A closed bar commits a new revision: the watcher gets a frame, and the result follows it.
            now[0] = START + 25 * STEP
            await manager.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED, KEY))
            async with asyncio.timeout(10):
                frame = await anext(stream)
                while frame["type"] == "heartbeat" or frame["progress"]["sequence"] == revision:
                    frame = await anext(stream)
            assert frame["terminal"] is False and frame["progress"]["sequence"] > revision
            assert await runs.result(run_id) == committed_projection(controller, run_id)
            watch.close()
            await stream.aclose()
            assert gate.diagnostics()["subscriptions"] == 0

            with pytest.raises(BacktestError) as failure:
                await runs.cancel(run_id)
            assert failure.value.code == "RUN_CONTROL_UNSUPPORTED"
        finally:
            await gate.shutdown()
            await manager.event_bus.close()
    try:
        asyncio.run(scenario())
    finally:
        service.shutdown()


def test_a_forward_history_beyond_the_budget_is_refused_not_truncated(storage, tmp_path, monkeypatch):
    manager, service, gate, _active, _calls, _now = access_setup(storage, tmp_path, monkeypatch)

    async def scenario():
        try:
            await gate.start_continuous()
            access, controller = gate.continuous_access(), gate.continuous
            run_id = (await create(access))["run_id"]
            await controller.wait_initial("request")
            await wait_row(controller.store, run_id, lambda row: row["phase"] == "LIVE")
            with pytest.raises(BacktestError) as failure:
                controller.store.results.committed_kernel_result(run_id, max_bytes=1)
            assert failure.value.code == "BUDGET_EXCEEDED"
            with pytest.raises(BacktestError) as missing:
                await gate.runs().result("cs_missing")
            assert missing.value.code == "RUN_NOT_FOUND"
        finally:
            await gate.shutdown()
            await manager.event_bus.close()
    try:
        asyncio.run(scenario())
    finally:
        service.shutdown()
