import asyncio
from pathlib import Path

import pytest

from app.backtest.errors import BacktestError
from app.backtest.service import BacktestService
from app.backtest.strategy.protocol import CrashProvider, DeterministicFakeProvider
from app.core.config import load_backtest_settings
from app.data_engine.data_manager.strategy import StrategyDataManager
from app.market_dataset.snapshot import MarketEvent


@pytest.fixture
def service(tmp_path: Path):
    settings = load_backtest_settings({"BACKTEST_ENABLED": "1", "BACKTEST_BAR_ENABLED": "1"},
        data_dir=tmp_path, klines_db_path=tmp_path / "market.db", replay_db_path=tmp_path / "replay.db")
    value = BacktestService.start(settings, now_ms=1)
    yield value
    value.shutdown()


def create_run(service, key="run"):
    return service.create_run({"strategy_revision_id": "rev-1",
        "dataset_id": "local-0123456789abcdef0123456789abcdef", "data_epoch": "sha256:" + "ab" * 32,
        "snapshot_hash": "sha256:" + "cd" * 32, "fidelity_mode": "BAR_APPROX",
        "start_time_ms": 1, "end_time_ms": 2001, "parameters": {}}, idempotency_key=key, now_ms=2)


def events():
    return tuple(MarketEvent(sequence=i, event_time_ms=i * 1000, role="BARS",
        payload={"open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}) for i in (1, 2))


@pytest.mark.parametrize("crash", [False, True])
def test_actual_engine_completion_and_failure_arrive_without_polling(service, crash):
    async def check():
        run = create_run(service)
        manager = StrategyDataManager(service)
        subscription = await manager.subscribe_run(run["run_id"])
        stream = subscription.events()
        assert (await anext(stream))["run"]["state"] == "QUEUED"
        if crash:
            with pytest.raises(Exception, match="PROVIDER_CRASH"):
                await asyncio.to_thread(service.execute_bar_run, run["run_id"], events=events(), provider=CrashProvider(), now_ms=3)
        else:
            await asyncio.to_thread(service.execute_bar_run, run["run_id"], events=events(), provider=DeterministicFakeProvider(), now_ms=3)
        received = [event async for event in stream]
        final = received[-1]
        assert final["terminal"] is True
        assert final["run"]["snapshot_hash"] == run["snapshot_hash"]
        assert final["run"]["config_hash"] == run["config_hash"]
        if crash:
            assert final["type"] == "failed"
            assert final["error"]["code"] == "PROVIDER_CRASH_UNRECOVERABLE"
            assert "crash" in final["error"]["message"].lower()
        else:
            assert final["type"] == "completed"
            assert final["result"]["report_hash"] == service.get_report(run["run_id"])["hashes"]["report"]
            assert final["result"]["summary"]["runId"] == run["run_id"]
        assert manager.diagnostics()["subscriptions"] == 0
        assert service.repository.run_updates.diagnostics()["subscriptions"] == 0
        manager.close()
    asyncio.run(check())


def test_heartbeats_do_not_poll_and_checkpoint_wakeup_is_compact(service, monkeypatch):
    async def check():
        run = create_run(service)
        reads = 0
        original = service.repository.read_run_progress
        def read(run_id):
            nonlocal reads
            reads += 1
            return original(run_id)
        monkeypatch.setattr(service.repository, "read_run_progress", read)
        manager = StrategyDataManager(service, heartbeat_seconds=0.01)
        subscription = await manager.subscribe_run(run["run_id"])
        stream = subscription.events()
        assert (await anext(stream))["type"] == "status"
        for _ in range(3):
            assert (await anext(stream))["type"] == "heartbeat"
        assert reads == 1
        service.repository.update_run_state(run["run_id"], state="RUNNING", updated_at_ms=3)
        assert service.repository.save_checkpoint(dict(run_id=run["run_id"], sequence=15, generation=1,
            payload_json="not expanded by status", state_hash="checkpoint", created_at_ms=4))
        event = await anext(stream)
        assert event["type"] == "progress" and event["progress"]["sequence"] == 15
        assert "payload_json" not in event["progress"] and "config_json" not in event["run"]
        assert reads == 2
        await stream.aclose()
        assert manager.diagnostics()["subscriptions"] == 0
    asyncio.run(check())


def test_releasing_view_does_not_cancel_run_or_sibling_and_close_wakes_waiters(service):
    async def check():
        run = create_run(service)
        manager = StrategyDataManager(service, max_subscriptions=2)
        first, second = await manager.subscribe_run(run["run_id"]), await manager.subscribe_run(run["run_id"])
        with pytest.raises(BacktestError, match="RUN_CAPACITY_EXCEEDED"):
            await manager.subscribe_run(run["run_id"])
        a, b = first.events(), second.events()
        await anext(a); await anext(b)
        pending = asyncio.create_task(anext(a))
        await asyncio.sleep(0)
        first.close()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, 1)
        assert service.get_run(run["run_id"])["state"] == "QUEUED"
        assert manager.diagnostics()["subscriptions"] == 1
        service.cancel_run(run["run_id"], now_ms=3)
        assert (await anext(b))["type"] == "cancelled"
        await b.aclose()
        other = create_run(service, "other")
        last = (await manager.subscribe_run(other["run_id"])).events()
        await anext(last)
        pending = asyncio.create_task(anext(last))
        await asyncio.sleep(0)
        manager.close()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, 1)
        assert service.get_run(other["run_id"])["state"] == "QUEUED"
        assert manager.diagnostics()["subscriptions"] == 0
    asyncio.run(check())


def test_invalid_request_releases_subscription_and_new_generation_ends_old_stream(service):
    async def check():
        manager = StrategyDataManager(service)
        with pytest.raises(BacktestError, match="unknown run"):
            await manager.subscribe_run("missing")
        assert manager.diagnostics()["subscriptions"] == 0
        run = create_run(service)
        stream = (await manager.subscribe_run(run["run_id"])).events()
        await anext(stream)
        service.repository.update_run_state(run["run_id"], state="QUEUED", generation=2, updated_at_ms=4)
        received = [event async for event in stream]
        assert received[-1]["type"] == "error" and received[-1]["terminal"] is True
        assert received[-1]["error"]["code"] == "RUN_IDENTITY_CHANGED"
        assert manager.diagnostics()["subscriptions"] == 0
        manager.close()
    asyncio.run(check())


def test_http_stream_returns_terminal_summary_and_request_errors(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.backtests import router
    from app.data_engine.data_manager.core import DataManagerCore
    api = FastAPI()
    api.include_router(router, prefix="/api/v1")
    core = DataManagerCore()
    core.bind_strategy(service)
    api.state.data_manager_core = core
    api.state.backtest_service = service
    run = create_run(service)
    service.execute_bar_run(run["run_id"], events=events(), provider=DeterministicFakeProvider(), now_ms=3)
    with TestClient(api) as client:
        unknown = client.get("/api/v1/backtests/runs/missing/events")
        assert unknown.status_code == 400
        assert unknown.json()["error"]["code"] == "SCHEMA_UNKNOWN_FIELD"
        response = client.get(f"/api/v1/backtests/runs/{run['run_id']}/events")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        assert response.headers["cache-control"] == "no-store"
        import json
        rows = [json.loads(line) for line in response.text.splitlines()]
        assert len(rows) == 1 and rows[0]["type"] == "completed"
        assert rows[0]["result"]["summary"]["runId"] == run["run_id"]
    assert core.strategy.diagnostics()["subscriptions"] == 0
    core.close_strategy()


def test_http_disconnect_releases_only_the_view_subscription(service):
    async def check():
        from fastapi import FastAPI
        from starlette.middleware.gzip import GZipMiddleware
        from app.api.v1.backtests import router
        from app.data_engine.data_manager.core import DataManagerCore
        api = FastAPI()
        api.add_middleware(GZipMiddleware, minimum_size=1)
        api.include_router(router, prefix="/api/v1")
        core = DataManagerCore()
        core.bind_strategy(service)
        api.state.data_manager_core = core
        run = create_run(service)
        body_sent = asyncio.Event()
        bodies = []
        async def receive():
            await body_sent.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                bodies.append(message["body"])
                body_sent.set()
        path = f"/api/v1/backtests/runs/{run['run_id']}/events"
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
                 "http_version": "1.1", "method": "GET", "scheme": "http", "path": path,
                 "raw_path": path.encode(), "query_string": b"", "headers": [(b"accept-encoding", b"gzip")],
                 "client": ("127.0.0.1", 12345), "server": ("test", 80)}
        await asyncio.wait_for(api(scope, receive, send), 3)
        import json
        assert json.loads(bodies[0])["type"] == "status", "gzip must not buffer the first progress frame"
        assert core.strategy.diagnostics()["subscriptions"] == 0
        assert service.get_run(run["run_id"])["state"] == "QUEUED"
        core.close_strategy()
    asyncio.run(check())
