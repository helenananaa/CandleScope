"""ADR-BACKTEST-015 P4b2: chart FOLLOW runs fed by the DataManager, held by leases, served by the run facade.

The production DataManager over real kline SQLite and its event bus, as in
``test_continuous_strategy_access.py``; bar events are emitted by the test.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.strategy_follows import router as follows_router
from app.api.v1.strategy_runs import router as runs_router
from app.backtest.continuous_provider import ContinuousProviderFactory
from app.backtest.errors import BacktestError
from app.backtest.follow_session import FollowSession
from app.backtest.models import ENGINE_VERSION
from app.backtest.service import BacktestService
from app.backtest.strategy.builtin import BUILTIN_SMA_REVISION
from app.backtest.strategy_versions import material, version_hash
from app.core.config import CORS_ORIGINS
from app.data_engine.data_manager import strategy_follows as module
from app.data_engine.data_manager.models import BarData, DataEvent, DataEventType
from app.data_engine.data_manager.strategy_follows import StrategyFollows
from app.data_engine.data_manager.strategy_runs import STREAM_SCHEMA
from app.data_engine.storage import klines_repo
from app.market_dataset.snapshot import MarketEvent
from tests.test_backtest_control_plane import _settings
from tests.test_continuous_controller import market
from tests.test_continuous_provider import spec
from tests.test_kline_revision_contract import storage as storage  # noqa: F401 - fixture
from tests.test_follow_session import assert_follow_equals_fixed
from tests.test_query_cache_fencing import KEY, SOURCE, START, STEP, _row
from tests.test_strategy_run_oracles import BAR, python_provider, python_revision


def series(interval="1m"):
    return {"exchange": KEY.exchange, "market_type": KEY.market_type, "symbol": KEY.symbol, "interval": interval,
            "identity": asdict(KEY.identity)}


def body(holder="cell-a", *, python=False, from_ms=START, interval="1m", **extra):
    return {"holder": holder, "series": series(interval), "provider": spec(python=python),
            "execution": {"account_model": "SPOT_CASH_V1"}, "from_ms": from_ms, **extra}


def follow_setup(storage, tmp_path, monkeypatch, *, count=25, **options):
    manager, active, _calls = market(storage, monkeypatch, count=count)
    service = BacktestService.start(_settings(tmp_path), now_ms=1)
    gate = manager.bind_strategy(service)
    now = [START + 20 * STEP]
    follows = StrategyFollows(gate, clock_ms=lambda: now[0], sweep_s=0.05,
                              provider_factory=ContinuousProviderFactory(scratch_root=tmp_path), **options)
    gate._follows = follows
    return manager, service, gate, follows, active, now


def stored_events(count):
    rows = []
    for index, close in enumerate(stored_closes(count)):
        opened = START + index * STEP
        rows.append(MarketEvent(index + 1, opened + STEP - 1, "BARS", {
            "open": "100", "high": "250", "low": "50", "close": close, "volume": "10",
            "open_time_ms": opened, "close_time_ms": opened + STEP - 1, "is_closed": True}))
    return rows


def fixed_python_run(service, count=20, key="chart-fixed-python"):
    """A completed fixed Python host run on the DataManager's first ``count`` bars, as the chart tester creates."""
    revision = python_revision(service)
    payload = {**BAR, "strategy_revision_id": revision, "python_runtime_mode": "TRUSTED_LOCAL",
               "python_trusted_confirmed": True, "exchange": KEY.exchange, "market_type": KEY.market_type,
               "symbol": KEY.symbol, "account_model": "SPOT_CASH_V1",
               "start_time_ms": START, "end_time_ms": START + count * STEP - 1}
    service.smoke_strategy_revision(revision, payload, now_ms=4)
    row = service.create_run(payload, idempotency_key=key, now_ms=4)
    completed = service.execute_bar_run(str(row["run_id"]), events=stored_events(count), provider=python_provider(),
                                        now_ms=5)
    assert completed["state"] == "COMPLETED", completed
    return str(row["run_id"]), completed


def run(scenario, manager, gate, service):
    async def owned():
        try:
            await scenario()
        finally:
            await gate.shutdown()
            await manager.event_bus.close()
    try:
        asyncio.run(owned())
    finally:
        service.shutdown()


async def until(read, predicate, *, timeout=10):
    async with asyncio.timeout(timeout):
        while True:
            value = await read()
            if predicate(value):
                return value
            await asyncio.sleep(0.01)


def expected_result(definition, closes, *, python=False):
    """The same bars applied to a fresh FOLLOW session: what the fed run must show."""
    rows = []
    for index, close in enumerate(closes):
        opened = START + index * STEP
        rows.append({"open": "100", "high": "250", "low": "50", "close": close, "volume": "10",
                     "open_time_ms": opened, "close_time_ms": opened + STEP - 1, "is_closed": True})
    session = FollowSession("fl_expected", definition, ContinuousProviderFactory(), interval="1m")
    try:
        session.extend([MarketEvent(index, row["close_time_ms"], "BARS", row) for index, row in enumerate(rows, 1)])
        return session.result()
    finally:
        session.close()


def stored_closes(count):
    return [str(100 + index % 7) for index in range(count)]


async def emit(manager, event_type, **values):
    await manager.event_bus.emit(DataEvent(event_type, KEY, **values))


def bar_at(index, close=100):
    return BarData(time=(START + index * STEP) // 1000, open=100, high=250, low=50, close=close, volume=10,
                   is_closed=True)


@pytest.mark.parametrize("python", [False, True])
def test_a_follow_run_applies_closed_bars_as_they_close_and_never_a_forming_one(storage, tmp_path, monkeypatch, python):
    manager, service, gate, follows, active, now = follow_setup(storage, tmp_path, monkeypatch)

    async def scenario():
        runs = gate.runs()
        held = await follows.open(body(python=python), trusted=True)
        follow_id = held["follow_id"]
        assert held["created"] and follow_id.startswith("fl_")
        assert active == {f"strategy-follow:{follow_id}"}, "the run holds its own live stream"
        status = await until(lambda: runs.status(follow_id), lambda value: value["source_state"] == "LIVE")
        assert (status["family"], status["authority"], status["clock_policy"], status["fidelity"], status["state"]) == (
            "follow", "HOST", "FOLLOW", "BAR_APPROX", "RUNNING")
        assert status["language"] == ("python" if python else "builtin")
        assert status["result_available"] and not status["terminal"] and status["generation"] == 1
        session = follows.sessions.get(follow_id)
        # 25 bars are stored, but at this clock only the first 20 have closed.
        assert (session.sequence, session.through_ms) == (20, START + 20 * STEP - 1)
        served = await runs.result(follow_id)
        assert served == expected_result(session.definition, stored_closes(20), python=python)
        assert served["clock_policy"] == "FOLLOW" and served["fills"], "the oracle strategy trades"
        if not python:
            assert status["version_hash"] == version_hash(
                material("builtin", BUILTIN_SMA_REVISION, {}, {"engine_version": ENGINE_VERSION}))

        watch = await runs.watch(follow_id)
        stream = watch.events()
        first = await anext(stream)
        assert first["schema"] == STREAM_SCHEMA and first["progress"]["created_at_ms"] == START + 20 * STEP - 1
        now[0] = START + 25 * STEP + 1
        await emit(manager, DataEventType.BAR_CLOSED, bar=bar_at(24))
        async with asyncio.timeout(10):
            frame = await anext(stream)
            while frame["type"] == "heartbeat" or frame["progress"]["created_at_ms"] < START + 25 * STEP - 1:
                frame = await anext(stream)
        assert frame["status"]["source_state"] == "LIVE" and session.sequence == 25
        assert await runs.result(follow_id) == expected_result(session.definition, stored_closes(25), python=python)
        watch.close()
        await stream.aclose()

        with pytest.raises(BacktestError) as refused:
            await runs.cancel(follow_id)
        assert refused.value.code == "RUN_CONTROL_UNSUPPORTED"
    run(scenario, manager, gate, service)
    assert not active, "shutdown releases the run's stream"


def test_missing_bars_wait_for_data_but_a_late_newest_bar_stays_live(storage, tmp_path, monkeypatch):
    manager, service, gate, follows, _active, now = follow_setup(storage, tmp_path, monkeypatch)
    requested = []
    original = manager.bars.query

    def query(*args, **kwargs):
        if kwargs.get("auto_backfill"):
            requested.append((kwargs["start_ms"], kwargs["end_ms"]))
        return original(*args, **{**kwargs, "auto_backfill": False})
    monkeypatch.setattr(manager.bars, "query", query)

    async def scenario():
        runs = gate.runs()
        now[0] = START + 30 * STEP
        follow_id = (await follows.open(body()))["follow_id"]
        status = await until(lambda: runs.status(follow_id), lambda value: value["source_state"] == "WAITING_DATA")
        assert status["state"] == "BLOCKED" and not status["result_available"]
        session = follows.sessions.get(follow_id)
        assert session.sequence == 25, "the bars that are there are applied"
        assert requested and requested[0][0] == START + 25 * STEP, "the overdue bars are backfilled"
        with pytest.raises(BacktestError) as early:
            await runs.result(follow_id)
        assert early.value.code == "RUN_RESULT_NOT_READY"

        klines_repo.upsert_klines(KEY.symbol, KEY.interval, [_row(START + i * STEP, 100 + i % 7) for i in range(25, 30)],
                                  source=SOURCE)
        await emit(manager, DataEventType.BACKFILL_COMPLETED)
        status = await until(lambda: runs.status(follow_id), lambda value: value["source_state"] == "LIVE")
        assert session.sequence == 30 and status["generation"] == 1, "an unchanged processed range is not recomputed"

        # Bar 30 closed 10 s ago and has not arrived: the run is live up to what the source has.
        requested.clear()
        now[0] = START + 31 * STEP + 10_000
        await emit(manager, DataEventType.BAR_CLOSED)
        await asyncio.sleep(0.2)
        assert (await runs.status(follow_id))["source_state"] == "LIVE" and session.sequence == 30
        assert not requested, "a bar within its grace is not backfilled"
        now[0] += module.TAIL_GRACE_MS
        await until(lambda: runs.status(follow_id), lambda value: value["source_state"] == "WAITING_DATA")
    run(scenario, manager, gate, service)


def test_a_revised_processed_bar_recomputes_the_run_as_its_next_generation(storage, tmp_path, monkeypatch):
    manager, service, gate, follows, _active, now = follow_setup(storage, tmp_path, monkeypatch)

    async def scenario():
        runs = gate.runs()
        follow_id = (await follows.open(body()))["follow_id"]
        await until(lambda: runs.status(follow_id), lambda value: value["source_state"] == "LIVE")
        watch = await runs.watch(follow_id)
        stream = watch.events()
        assert (await anext(stream))["status"]["generation"] == 1

        # A bar after what the run has read is only new input.
        klines_repo.upsert_klines(KEY.symbol, KEY.interval, [_row(START + 22 * STEP, 140)], source=SOURCE)
        await emit(manager, DataEventType.BAR_AMENDED, bar=bar_at(22))
        await asyncio.sleep(0.2)
        assert (await runs.status(follow_id))["generation"] == 1

        closes = stored_closes(20)
        closes[5] = "131"
        klines_repo.upsert_klines(KEY.symbol, KEY.interval, [_row(START + 5 * STEP, 131)], source=SOURCE)
        await emit(manager, DataEventType.BAR_AMENDED, bar=bar_at(5))
        status = await until(lambda: runs.status(follow_id),
                             lambda value: value["generation"] == 2 and value["source_state"] == "LIVE")
        assert status["state"] == "RUNNING", "no approval: the run recomputed on its own"
        session = follows.sessions.get(follow_id)
        assert await runs.result(follow_id) == expected_result(session.definition, closes)
        async with asyncio.timeout(10):
            frame = await anext(stream)
            while frame["type"] != "error":
                frame = await anext(stream)
        assert frame["error"]["code"] == "RUN_IDENTITY_CHANGED" and frame["terminal"]
        await stream.aclose()

        # A backfill that changed processed bars without an amendment event is found by re-reading them.
        closes[3] = "77"
        klines_repo.upsert_klines(KEY.symbol, KEY.interval, [_row(START + 3 * STEP, 77)], source=SOURCE)
        manager.cache.invalidate(KEY)  # as the DataManager's own backfill write does
        await emit(manager, DataEventType.BACKFILL_COMPLETED)
        await until(lambda: runs.status(follow_id), lambda value: value["generation"] == 3 and value["result_available"])
        session = follows.sessions.get(follow_id)
        assert await runs.result(follow_id) == expected_result(session.definition, closes)
    run(scenario, manager, gate, service)


def test_follow_runs_are_shared_held_by_leases_and_stop_with_the_last_one(storage, tmp_path, monkeypatch):
    manager, service, gate, follows, active, now = follow_setup(storage, tmp_path, monkeypatch, capacity=2)
    clock = [1000.0]
    follows.sessions.clock = lambda: clock[0]

    async def scenario():
        runs = gate.runs()
        first = await follows.open(body("cell-a"))
        shared = await follows.open(body("cell-b"))
        assert first["created"] and not shared["created"] and shared["follow_id"] == first["follow_id"]
        follow_id = first["follow_id"]
        other = await follows.open(body("cell-c", from_ms=START + STEP))
        assert other["follow_id"] != follow_id, "another start is another run"
        with pytest.raises(BacktestError) as full:
            await follows.open(body("cell-d", from_ms=START + 2 * STEP))
        assert full.value.code == "FOLLOW_CAPACITY_EXCEEDED"
        await until(lambda: runs.status(follow_id), lambda value: value["source_state"] == "LIVE")

        await follows.release(follow_id, "cell-a")
        assert (await runs.status(follow_id))["state"] == "RUNNING", "cell-b still holds it"
        clock[0] += 20
        await follows.renew(follow_id, {"holder": "cell-b"})
        clock[0] += 20  # cell-c's lease has expired; cell-b renewed
        stopped = await until(lambda: runs.status(other["follow_id"]), lambda value: value["terminal"])
        assert (stopped["state"], stopped["source_state"], stopped["result_available"]) == ("CANCELLED", "STOPPED", False)
        with pytest.raises(BacktestError) as gone:
            await runs.result(other["follow_id"])
        assert gone.value.code == "RUN_NOT_FOUND"
        async def streams():
            return set(active)
        await until(streams, lambda value: value == {f"strategy-follow:{follow_id}"})  # a stopped run lets its stream go
        assert other["follow_id"] not in follows.feeds

        await follows.release(follow_id, "cell-b")
        assert (await runs.status(follow_id))["state"] == "CANCELLED" and not follows.feeds and not active
        with pytest.raises(BacktestError) as renew:
            await follows.renew(follow_id, {"holder": "cell-b"})
        assert renew.value.code == "RUN_NOT_FOUND"
    run(scenario, manager, gate, service)


def test_follow_requests_are_validated_and_bounded(storage, tmp_path, monkeypatch):
    manager, service, gate, follows, _active, now = follow_setup(storage, tmp_path, monkeypatch)

    async def scenario():
        cases = [
            (body(python=True), {}, "TRUSTED_ORIGIN_REQUIRED"),
            (body(from_ms=START + 1), {"trusted": True}, "FOLLOW_INPUT_INVALID"),
            (body(from_ms=START - 20_001 * STEP), {}, "BUDGET_EXCEEDED"),
            (body(interval="1M"), {}, "FIDELITY_UNSUPPORTED"),
            ({**body(), "unknown": 1}, {}, "FOLLOW_INPUT_INVALID"),
            (body(holder=""), {}, "FOLLOW_INPUT_INVALID"),
        ]
        for request, options, code in cases:
            with pytest.raises(BacktestError) as refused:
                await follows.open(request, **options)
            assert refused.value.code == code, request
        assert not follows.feeds and follows.sessions.diagnostics() == {"runs": 0, "leases": 0}

        capabilities = await gate.runs().capabilities()
        assert capabilities["families"]["follow"] == {"available": True, "reason": None}
        rows = [row for row in capabilities["profiles"] if row["family"] == "follow"]
        assert {row["language"] for row in rows} == {"builtin", "python"}
        assert all(row["clock_policy"] == "FOLLOW" and row["fidelities"] == ["BAR_APPROX"]
                   and row["fixed_intervals_only"] and row["controls"] == {"cancel": False} for row in rows)
    run(scenario, manager, gate, service)


def test_the_lease_routes_hold_renew_and_release_a_follow_run(storage, tmp_path, monkeypatch):
    manager, service, gate, follows, active, now = follow_setup(storage, tmp_path, monkeypatch)
    app = FastAPI()
    app.state.data_manager_core = SimpleNamespace(strategy=gate)
    app.include_router(follows_router, prefix="/api/v1")
    app.include_router(runs_router, prefix="/api/v1")
    trusted = {"origin": next(iter(CORS_ORIGINS))}

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            refused = await client.post("/api/v1/strategy-follows", json=body(python=True))
            assert refused.status_code == 403 and refused.json()["error"]["code"] == "TRUSTED_ORIGIN_REQUIRED"
            held = await client.post("/api/v1/strategy-follows", json=body(python=True), headers=trusted)
            assert held.status_code == 200, held.text
            follow_id = held.json()["follow_id"]
            assert held.json()["lease_ms"] == 30_000

            async def status():
                return (await client.get(f"/api/v1/strategy-runs/{follow_id}")).json()
            await until(status, lambda value: value["source_state"] == "LIVE")
            result = await client.get(f"/api/v1/strategy-runs/{follow_id}/result")
            assert result.status_code == 200 and result.json()["clock_policy"] == "FOLLOW"
            renewed = await client.put(f"/api/v1/strategy-follows/{follow_id}/lease", json={"holder": "cell-a"})
            assert renewed.status_code == 200 and renewed.json()["held"] is True
            unknown = await client.put("/api/v1/strategy-follows/fl_missing/lease", json={"holder": "cell-a"})
            assert unknown.status_code == 404
            cancel = await client.post(f"/api/v1/strategy-runs/{follow_id}/cancel")
            assert cancel.status_code == 409
            released = await client.delete(f"/api/v1/strategy-follows/{follow_id}/lease", params={"holder": "cell-a"})
            assert released.status_code == 200 and released.json()["held"] is False
            assert (await status())["state"] == "CANCELLED" and not active
            gone = await client.get(f"/api/v1/strategy-runs/{follow_id}/result")
            assert gone.status_code == 404
    run(scenario, manager, gate, service)


def test_a_completed_python_chart_run_is_followed_from_its_own_revision_and_start(storage, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED", "1")
    manager, service, gate, follows, _active, now = follow_setup(storage, tmp_path, monkeypatch)
    run_id, completed = fixed_python_run(service)

    async def scenario():
        runs = gate.runs()
        request = {"holder": "cell-a", "run_id": run_id, "series": series()}
        with pytest.raises(BacktestError) as untrusted:
            await follows.open(request)
        assert untrusted.value.code == "TRUSTED_ORIGIN_REQUIRED"
        held = await follows.open(request, trusted=True)
        assert held["from_ms"] == START, "FOLLOW starts where the fixed run starts"
        follow_id = held["follow_id"]
        await until(lambda: runs.status(follow_id), lambda value: value["source_state"] == "LIVE")
        # On the same 20 closed bars, FOLLOW is the fixed run (§3.4), but for the orders FIXED cancels at its end.
        assert_follow_equals_fixed(await runs.result(follow_id), completed["result"], interval="1m")
        assert (await follows.open({**request, "holder": "cell-b"}, trusted=True))["follow_id"] == follow_id
        now[0] = START + 25 * STEP
        await emit(manager, DataEventType.BAR_CLOSED)
        await until(lambda: runs.status(follow_id),
                    lambda value: follows.sessions.get(follow_id).through_ms == START + 25 * STEP - 1)
        _, longer = fixed_python_run(service, 25, "chart-fixed-python-25")
        assert_follow_equals_fixed(await runs.result(follow_id), longer["result"], interval="1m")

        for wrong, code in (({**request, "run_id": "bt_missing"}, "RUN_NOT_FOUND"),
                            ({**request, "series": series("5m")}, "FOLLOW_INPUT_INVALID")):
            with pytest.raises(BacktestError) as refused:
                await follows.open(wrong, trusted=True)
            assert refused.value.code == code
    run(scenario, manager, gate, service)
