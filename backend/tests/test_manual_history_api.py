from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.manual_history import router as manual_history_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(manual_history_router, prefix="/api/v1")
    return TestClient(app)


NOW_MS = 1_780_000_000_000
START_MS = 1_700_000_000_000


def test_plan_endpoint_is_read_only_and_expands_targets(monkeypatch) -> None:
    from tests.test_manual_history_planner import FakeResolver, NOW_MS

    monkeypatch.setattr(
        "app.api.v1.manual_history.MANUAL_HISTORY_DOWNLOAD_ENABLED",
        True,
    )

    def fake_build_planner(*, feature_enabled: bool, request=None):
        del request
        from app.data_engine.manual_history.planner import ManualHistoryPlanner

        return ManualHistoryPlanner(
            resolver=FakeResolver(),
            clock_ms=lambda: NOW_MS,
            feature_enabled=feature_enabled,
            normalize_symbol_fn=lambda symbol, **kw: str(symbol).strip().upper(),
            disk_snapshot=lambda: {
                "physical_size_bytes": 1_000,
                "free_bytes": 50_000_000_000,
            },
            sqlite_budget_bytes=10_000_000_000,
        )

    monkeypatch.setattr(
        "app.api.v1.manual_history._build_planner",
        fake_build_planner,
    )
    client = _client()
    response = client.post(
        "/api/v1/settings/storage/manual-downloads/plan",
        json={
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "intervals": ["1m", "1h", "89m"],
            "start_ms": START_MS,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["selection"]["target_count"] == 6
    assert "plan_hash" in payload
    assert payload["storage"]["estimate_confidence"] in {"LOW", "MEDIUM", "HIGH"}
    assert "estimated_db_growth_bytes" in payload["storage"]


def test_plan_rejects_user_end_ms() -> None:
    response = _client().post(
        "/api/v1/settings/storage/manual-downloads/plan",
        json={
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
            "start_ms": START_MS,
            "end_ms": NOW_MS,
        },
    )
    assert response.status_code == 422


def test_list_jobs_without_runtime_is_empty() -> None:
    response = _client().get("/api/v1/settings/storage/manual-downloads")
    assert response.status_code == 200
    assert response.json()["jobs"] == []


def test_create_is_closed_when_feature_flag_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.v1.manual_history.MANUAL_HISTORY_DOWNLOAD_ENABLED",
        False,
    )
    response = _client().post(
        "/api/v1/settings/storage/manual-downloads",
        json={
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
            "start_ms": START_MS,
            "plan_hash": "sha256:" + ("0" * 64),
            "idempotency_key": "disabled-create",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "feature_flag_disabled"


def test_disabled_create_rejects_before_request_schema_validation(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.v1.manual_history.MANUAL_HISTORY_DOWNLOAD_ENABLED",
        False,
    )
    response = _client().post(
        "/api/v1/settings/storage/manual-downloads",
        json={
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
            "start_ms": START_MS,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "feature_flag_disabled"


def test_create_uses_factory_runtime_service_not_hand_built(monkeypatch, tmp_path) -> None:
    import inspect

    from app.core import config as core_config
    from app.data_engine.data_manager import DataManager
    from app.data_engine.runtime import attach_manual_history_service, start_data_engine
    from app.data_engine.storage import klines_repo
    from app.data_engine.storage.klines_repo import KlinesRepoAdapter
    from tests.test_manual_history_planner import FakeResolver, NOW_MS as PLAN_NOW

    source = inspect.getsource(start_data_engine)
    assert "attach_manual_history_service" in source
    assert "manual_history_service=manual_history_service" in source

    db_path = tmp_path / "klines.db"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", db_path)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", db_path)
    monkeypatch.setattr(
        "app.data_engine.runtime.KLINES_DB_PATH",
        db_path,
    )
    monkeypatch.setattr(
        "app.api.v1.manual_history.MANUAL_HISTORY_DOWNLOAD_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "app.data_engine.runtime.MANUAL_HISTORY_DOWNLOAD_ENABLED",
        True,
    )
    klines_repo.init_klines_storage()
    dm = DataManager()
    dm.set_storage(KlinesRepoAdapter())

    class _Coordinator:
        async def request_and_wait(self, request):
            del request

    service = attach_manual_history_service(
        data_manager=dm,
        coordinator=_Coordinator(),  # type: ignore[arg-type]
        enabled=True,
    )
    assert service.coordinator is not None

    def fake_build_planner(*, feature_enabled: bool, request=None):
        del request
        from app.data_engine.manual_history.planner import ManualHistoryPlanner

        return ManualHistoryPlanner(
            resolver=FakeResolver(),
            clock_ms=lambda: PLAN_NOW,
            feature_enabled=feature_enabled,
            normalize_symbol_fn=lambda symbol, **kw: str(symbol).strip().upper(),
            disk_snapshot=lambda: {
                "physical_size_bytes": 1_000,
                "free_bytes": 50_000_000_000,
            },
            sqlite_budget_bytes=10_000_000_000,
        )

    monkeypatch.setattr("app.api.v1.manual_history._build_planner", fake_build_planner)
    app = FastAPI()
    app.include_router(manual_history_router, prefix="/api/v1")
    runtime = type("Runtime", (), {})()
    runtime.manual_history_service = service
    runtime.data_manager = dm
    app.state.data_engine_runtime = runtime
    app.state.data_manager = dm
    client = TestClient(app)
    plan = client.post(
        "/api/v1/settings/storage/manual-downloads/plan",
        json={
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
            "start_ms": START_MS,
        },
    )
    assert plan.status_code == 200
    created = client.post(
        "/api/v1/settings/storage/manual-downloads",
        json={
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
            "start_ms": START_MS,
            "plan_hash": plan.json()["plan_hash"],
            "idempotency_key": "factory-runtime-create-1",
        },
    )
    assert created.status_code == 202, created.text
    assert created.json()["status"] == "accepted"
    assert created.json()["job"]["state"] in {"QUEUED", "RUNNING", "SUCCEEDED"}
    repeated = client.post(
        "/api/v1/settings/storage/manual-downloads",
        json={
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
            "start_ms": START_MS,
            "plan_hash": plan.json()["plan_hash"],
            "idempotency_key": "factory-runtime-create-1",
        },
    )
    assert repeated.status_code == 202
    assert repeated.json()["reused_existing"] is True
    assert repeated.json()["job"]["job_id"] == created.json()["job"]["job_id"]


class _ThreadProbe:
    """Proxy that records each call and whether it ran on the event loop thread."""

    def __init__(self, inner=None) -> None:
        self._inner = inner
        self.loop_thread: int | None = None
        self.calls: list[tuple[str, bool]] = []

    def wrap(self, name, func):
        def call(*args, **kwargs):
            self.calls.append((name, threading.get_ident() == self.loop_thread))
            return func(*args, **kwargs)

        return call

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        return self.wrap(name, attr) if callable(attr) else attr


def _runtime_app(monkeypatch, tmp_path):
    """App over a real repository, DataManager and the real planner wiring."""

    from app.data_engine.manual_history.planner import ManualHistoryPlanner
    from app.data_engine.storage.klines_repo import get_bounds
    from tests.test_manual_history_planner import NOW_MS as PLAN_NOW
    from tests.test_manual_history_planner import FakeResolver
    from tests.test_manual_history_service import _service, _setup

    db_path, repo, dm = _setup(monkeypatch, tmp_path)
    probe = _ThreadProbe(repo)
    service = _service(probe, dm, idle_poll_seconds=60)
    monkeypatch.setattr("app.api.v1.manual_history.MANUAL_HISTORY_DOWNLOAD_ENABLED", True)
    monkeypatch.setattr("app.api.v1.manual_history.KLINES_DB_PATH", db_path)
    monkeypatch.setattr(
        "app.api.v1.manual_history.ManualHistoryPlanner",
        lambda **kwargs: ManualHistoryPlanner(
            resolver=FakeResolver(),
            clock_ms=lambda: PLAN_NOW,
            normalize_symbol_fn=lambda symbol, **kw: str(symbol).strip().upper(),
            **kwargs,
        ),
    )
    # Coverage bounds and disk probes are storage reads too.
    monkeypatch.setattr("app.api.v1.manual_history.get_bounds", probe.wrap("get_bounds", get_bounds))
    monkeypatch.setattr(
        "app.api.v1.manual_history.storage_file_snapshot",
        probe.wrap("storage_file_snapshot", lambda path: {"physical_size_bytes": 1_000}),
    )
    monkeypatch.setattr(
        "app.api.v1.manual_history.disk_pressure_snapshot",
        probe.wrap("disk_pressure_snapshot", lambda path: {"free_bytes": 50_000_000_000}),
    )
    app = FastAPI()
    app.include_router(manual_history_router, prefix="/api/v1")
    app.state.data_engine_runtime = SimpleNamespace(manual_history_service=service, data_manager=dm)
    app.state.data_manager = dm
    return app, probe, service, dm


_SELECTION = {
    "exchange": "binance",
    "market_type": "spot",
    "symbols": ["BTCUSDT"],
    "intervals": ["1m"],
    "start_ms": START_MS,
}
_BASE = "/api/v1/settings/storage/manual-downloads"


def test_handlers_keep_repository_and_storage_reads_off_the_event_loop(monkeypatch, tmp_path) -> None:
    app, probe, service, _ = _runtime_app(monkeypatch, tmp_path)

    @app.middleware("http")
    async def record_loop_thread(request, call_next):
        probe.loop_thread = threading.get_ident()
        return await call_next(request)

    wakes: list[bool] = []
    wake = service._wake_runner

    def recording_wake() -> None:
        wakes.append(threading.get_ident() == probe.loop_thread)
        wake()

    monkeypatch.setattr(service, "_wake_runner", recording_wake)
    client = TestClient(app)

    plan = client.post(f"{_BASE}/plan", json=_SELECTION)
    assert plan.status_code == 200, plan.text
    create_body = {**_SELECTION, "plan_hash": plan.json()["plan_hash"], "idempotency_key": "off-loop-create"}
    created = client.post(_BASE, json=create_body)
    assert created.status_code == 202, created.text
    assert created.json()["reused_existing"] is False
    job = created.json()["job"]
    assert [target["symbol"] for target in job["targets"]] == ["BTCUSDT"]
    repeated = client.post(_BASE, json=create_body)
    assert repeated.status_code == 202
    assert repeated.json()["reused_existing"] is True
    assert repeated.json()["job"]["job_id"] == job["job_id"]

    jobs = client.get(_BASE)
    assert jobs.status_code == 200
    assert [item["job_id"] for item in jobs.json()["jobs"]] == [job["job_id"]]
    detail = client.get(f"{_BASE}/{job['job_id']}")
    assert detail.status_code == 200
    assert detail.json()["job"]["targets"][0]["canonical_interval"] == "1m"
    assert client.get(f"{_BASE}/job:missing").status_code == 404
    collections = client.get(f"{_BASE}/collections")
    assert collections.status_code == 200
    (collection,) = collections.json()["collections"]
    assert collection["collection_id"] == job["collection_id"]
    assert [target["symbol"] for target in collection["targets"]] == ["BTCUSDT"]
    released = client.post(f"{_BASE}/collections/{job['collection_id']}/release")
    assert released.status_code == 200
    assert released.json()["state"] == "RELEASED"

    called = {name for name, _ in probe.calls}
    assert {
        "list_recoverable_jobs",
        "get_bounds",
        "storage_file_snapshot",
        "disk_pressure_snapshot",
        "get_job_by_idempotency_key",
        "create_collection_and_job",
        "list_job_targets",
        "list_jobs",
        "get_job",
        "list_collections",
        "list_collection_targets",
        "release_collection",
    } <= called
    assert [name for name, on_loop in probe.calls if on_loop] == []
    # The runner's wake event is set from the loop, never from a storage thread.
    assert wakes == [True, True]


@pytest.mark.anyio
async def test_create_waits_for_the_gc_guard_without_blocking_the_event_loop(monkeypatch, tmp_path) -> None:
    app, _, _, dm = _runtime_app(monkeypatch, tmp_path)
    entered = threading.Event()
    held = threading.Event()
    release = threading.Event()
    guarded_create = dm.create_manual_history_collection

    def signalling_create(repository, spec):
        entered.set()
        return guarded_create(repository, spec)

    monkeypatch.setattr(dm, "create_manual_history_collection", signalling_create)

    def hold_guard() -> None:
        # Stands in for a GC or seal pass holding the guard.
        with dm._storage_gc_guard:
            held.set()
            release.wait(5)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        plan = await client.post(f"{_BASE}/plan", json=_SELECTION)
        assert plan.status_code == 200, plan.text
        holder = threading.Thread(target=hold_guard)
        holder.start()
        try:
            assert await asyncio.to_thread(held.wait, 5)
            create = asyncio.create_task(client.post(_BASE, json={
                **_SELECTION, "plan_hash": plan.json()["plan_hash"], "idempotency_key": "guard-held",
            }))
            assert await asyncio.to_thread(entered.wait, 5)
            # Other requests keep being served while the create waits for the guard.
            started = time.monotonic()
            listed = await client.get(_BASE)
            assert listed.status_code == 200
            assert time.monotonic() - started < 1.0
            await asyncio.sleep(0.1)
            assert not create.done()
        finally:
            release.set()
            await asyncio.to_thread(holder.join, 5)
        created = await asyncio.wait_for(create, 5)
    assert created.status_code == 202, created.text


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/plan", _SELECTION),
        ("post", "", {**_SELECTION, "plan_hash": "sha256:" + "0" * 64, "idempotency_key": "busy-create"}),
        ("get", "", None),
        ("get", "/collections", None),
        ("get", "/job:busy", None),
        ("post", "/collections/col:busy/release", None),
    ],
)
def test_full_storage_executor_is_a_retryable_503(monkeypatch, tmp_path, method, path, body) -> None:
    from app.core.bounded_executor import ExecutorBusyError
    from app.data_engine.manual_history.repository import ManualHistoryRepository
    from app.data_engine.manual_history.service import ManualHistoryService
    from app.main import executor_busy_handler

    async def busy(func, *args, **kwargs):
        raise ExecutorBusyError("storage")

    monkeypatch.setattr("app.api.v1.manual_history.run_storage", busy)
    monkeypatch.setattr("app.data_engine.manual_history.service.run_storage", busy)
    monkeypatch.setattr("app.api.v1.manual_history.MANUAL_HISTORY_DOWNLOAD_ENABLED", True)
    app = FastAPI()
    app.include_router(manual_history_router, prefix="/api/v1")
    app.add_exception_handler(ExecutorBusyError, executor_busy_handler)
    # Never opened: every handler hits the full executor first.
    repository = ManualHistoryRepository(tmp_path / "unused.db")
    service = ManualHistoryService(repository=repository, data_manager=None)
    app.state.data_engine_runtime = SimpleNamespace(manual_history_service=service)
    client = TestClient(app)
    response = getattr(client, method)(f"{_BASE}{path}", **({"json": body} if body else {}))
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["detail"]["retryable"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("cancel_first", [False, True])
async def test_concurrent_creates_recheck_reserved_budget_after_inflight_commit(
    monkeypatch, tmp_path, cancel_first,
) -> None:
    app, _, service, _ = _runtime_app(monkeypatch, tmp_path)
    entered, release = threading.Event(), threading.Event()
    create = service.create_from_plan

    def held_create(plan, **kwargs):
        entered.set()
        assert release.wait(5)
        return create(plan, **kwargs)

    monkeypatch.setattr(service, "create_from_plan", held_create)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        planned = await client.post(f"{_BASE}/plan", json=_SELECTION)
        assert planned.status_code == 200
        plan = planned.json()
        growth = plan["storage"]["estimated_db_growth_bytes"]
        assert growth > 0
        # Enough for either request alone, but not both durable reservations.
        monkeypatch.setattr(
            "app.api.v1.manual_history.disk_pressure_snapshot",
            lambda path: {"free_bytes": int(growth * 1.5)},
        )
        body = {**_SELECTION, "plan_hash": plan["plan_hash"]}
        first = asyncio.create_task(client.post(_BASE, json={**body, "idempotency_key": "admission-first"}))
        second = None
        try:
            assert await asyncio.to_thread(entered.wait, 5), first.result().text if first.done() else "create did not start"
            if cancel_first:
                first.cancel()
                await asyncio.sleep(0)
                first.cancel()
            second = asyncio.create_task(client.post(_BASE, json={**body, "idempotency_key": "admission-second"}))
            await asyncio.sleep(0.05)
            assert not first.done() and not second.done()
        finally:
            release.set()
        if cancel_first:
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            assert (await first).status_code == 202
        assert second is not None
        rejected = await asyncio.wait_for(second, 5)
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["reason"] == "storage_conflict"
        jobs = (await client.get(_BASE)).json()["jobs"]
        assert len(jobs) == 1
        # A cancelled caller can recover its durable job without duplicating it.
        retry = await client.post(_BASE, json={**body, "idempotency_key": "admission-first"})
        assert retry.status_code == 202 and retry.json()["reused_existing"] is True
        assert retry.json()["job"]["job_id"] == jobs[0]["job_id"]


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["emit", "claim", "cancel_claim", "release", "close"])
async def test_market_event_dispatch_continues_while_manual_create_waits_for_sqlite(
    monkeypatch, tmp_path, operation,
) -> None:
    from unittest.mock import AsyncMock

    from app.api.v1.stream_kline_batch import (
        KlineBatchConnection,
        KlineBatchLimits,
        _BatchSubscription,
    )
    from app.data_engine.data_manager.models import (
        DataEvent,
        DataEventType,
        SeriesKey,
        StreamInfo,
        StreamStatus,
    )

    app, _, service, dm = _runtime_app(monkeypatch, tmp_path)
    held, release, released, writing = (threading.Event() for _ in range(4))
    delivered = asyncio.Event()
    key = SeriesKey("BTCUSDT", "price", exchange="binance", market_type="spot")
    seen = []

    async def receive(event):
        seen.append(event.detail["price"])
        delivered.set()

    dm.event_bus.subscribe(callback=receive, key=key, event_types={DataEventType.PRICE_UPDATED})

    async def active_stream(symbol, interval, **kwargs):
        return StreamInfo(
            key=SeriesKey(symbol, interval, exchange=kwargs["exchange"], market_type=kwargs["market_type"]),
            status=StreamStatus.ACTIVE,
        )

    monkeypatch.setattr(dm.coordinator, "ensure_stream", active_stream)
    monkeypatch.setattr(dm.coordinator, "stop_stream", AsyncMock())
    monkeypatch.setattr(dm.warm_start, "seed_if_needed", AsyncMock())
    # Match the already-running native host: resolve lazy adapter metadata
    # before the controlled SQL contention, which tests GC ownership only.
    dm.stream_policy.plan("BTCUSDT", "5m", exchange="binance", market_type="spot")
    owner = "sqlite-contention-consumer"
    connection = KlineBatchConnection(SimpleNamespace(), dm, limits=KlineBatchLimits.from_config())
    if operation in {"release", "close"}:
        await dm.ensure_stream("BTCUSDT", "5m", consumer_id=owner)
    if operation == "close":
        handle = await dm.subscribe_async(callback=receive, symbol="BTCUSDT", interval="5m")
        connection.subscriptions["test"] = _BatchSubscription(
            client_id="test", exchange="binance", market_type="spot", symbol="BTCUSDT",
            consumer_id=owner, handles={"5m": handle},
        )

    @app.get("/loop-health")
    async def health():
        return {"consumers": dm.event_bus.get_subscriber_count(key)}

    create = service.repository._inner.create_collection_and_job

    def record_write(spec):
        # DataManager already holds the GC guard when it reaches this write.
        writing.set()
        return create(spec)

    monkeypatch.setattr(service.repository._inner, "create_collection_and_job", record_write)

    def hold_sqlite():
        connection = sqlite3.connect(tmp_path / "klines.db")
        try:
            connection.execute("BEGIN IMMEDIATE")
            held.set()
            # Release even if old event dispatch blocks the test's event loop.
            release.wait(1)
        finally:
            connection.rollback()
            connection.close()
            released.set()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        planned = await client.post(f"{_BASE}/plan", json=_SELECTION)
        assert planned.status_code == 200
        holder = threading.Thread(target=hold_sqlite)
        holder.start()
        pending = None
        lifecycle = None
        try:
            assert await asyncio.to_thread(held.wait, 5)
            pending = asyncio.create_task(client.post(_BASE, json={
                **_SELECTION, "plan_hash": planned.json()["plan_hash"],
                "idempotency_key": "price-dispatch-during-write",
            }))
            assert await asyncio.to_thread(writing.wait, 5)
            if operation in {"claim", "cancel_claim"}:
                lifecycle = asyncio.create_task(dm.ensure_stream("BTCUSDT", "5m", consumer_id=owner))
            elif operation == "release":
                lifecycle = asyncio.create_task(dm.release_stream("BTCUSDT", "5m", consumer_id=owner))
            elif operation == "close":
                lifecycle = asyncio.create_task(connection.close())
            if lifecycle is not None:
                await asyncio.sleep(0.03)
                assert not lifecycle.done()
                if operation in {"cancel_claim", "release", "close"}:
                    lifecycle.cancel()
                    await asyncio.sleep(0)
                    lifecycle.cancel()
                    if operation == "cancel_claim":
                        with pytest.raises(asyncio.CancelledError):
                            await lifecycle
                        lifecycle = None
                    else:
                        assert not lifecycle.done(), "cleanup abandoned a protected stream"
            await dm.event_bus.emit(DataEvent(
                event_type=DataEventType.PRICE_UPDATED, key=key, detail={"price": 123.0},
            ))
            await asyncio.wait_for(delivered.wait(), 0.5)
            health_response = await client.get("/loop-health")
            assert health_response.status_code == 200 and health_response.json()["consumers"] == 1
            assert seen == [123.0]
            assert not released.is_set(), "market delivery waited for the SQLite/GC guard"
            assert not pending.done()
        finally:
            release.set()
            await asyncio.to_thread(holder.join, 5)
            if pending is not None:
                result = await asyncio.wait_for(pending, 5)
                assert result.status_code == 202, result.text
            if lifecycle is not None:
                if operation in {"release", "close"}:
                    with pytest.raises(asyncio.CancelledError):
                        await lifecycle
                else:
                    assert (await lifecycle).status is StreamStatus.ACTIVE
                    await dm.release_stream("BTCUSDT", "5m", consumer_id=owner)
            assert dm.stream_lease_snapshot()["series_count"] == 0
            await dm.event_bus.close()
