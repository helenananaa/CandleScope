from __future__ import annotations

import asyncio
from contextlib import contextmanager
import sqlite3
import threading

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.data_preparation import router
from app.core.bounded_executor import BoundedExecutor
from app.data_preparation.lease import PreparationLease
from app.data_preparation.models import PreparationError
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.data_preparation.storage import storage_call
from tests.test_data_preparation import Adapter, async_test, request


@async_test
async def test_journal_lifecycle_and_http_routes_never_open_sqlite_on_the_event_loop(tmp_path):
    loop_thread = threading.get_ident()
    class CheckedRepository(PreparationRepository):
        @contextmanager
        def connect(self):
            assert threading.get_ident() != loop_thread, "SQLite on the event loop"
            with super().connect() as db:
                yield db
    repo = await storage_call(CheckedRepository, tmp_path / "jobs.db")
    adapter = Adapter()
    adapter.release.set()
    adapter.publication_scopes = lambda: []
    service = PreparationService(repo, adapter)
    app = FastAPI()
    app.state.data_preparation_service = service
    app.include_router(router)
    await service.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations", json=request().model_dump())
            assert response.status_code == 202, response.text
            job_id = response.json()["id"]
            async def ready():
                while True:
                    item = await client.get(f"/data-preparations/{job_id}")
                    assert item.status_code == 200, item.text
                    if item.json()["state"] == "READY":
                        return
                    assert item.json()["state"] not in {"FAILED", "CANCELLED"}, item.text
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(ready(), 5)
            for path in ("", "/cache", f"/{job_id}"):
                assert (await client.get("/data-preparations" + path)).status_code == 200
            assert (await client.post(f"/data-preparations/{job_id}/cancel")).status_code == 200
            assert (await client.post(f"/data-preparations/{job_id}/retry")).status_code == 409
            assert (await client.post(f"/data-preparations/{job_id}/release-cache")).status_code == 200
            assert (await client.put("/data-preparations/cache/settings", json={
                "cache_budget_bytes": 32 * 1024**2, "prefetch_enabled": False})).status_code == 200
    finally:
        await service.shutdown()


@async_test
async def test_locked_write_keeps_loop_responsive_and_shutdown_retains_lease(tmp_path, monkeypatch):
    repo = PreparationRepository(tmp_path / "jobs.db")
    service = PreparationService(repo, Adapter(), workers=0)
    await service.start()
    job = await service.submit(request())
    locked, release, unlocked = threading.Event(), threading.Event(), threading.Event()
    def hold_write_lock():
        with sqlite3.connect(repo.path) as writer:
            writer.execute("BEGIN IMMEDIATE")
            locked.set()
            # If the loop blocks again, release from another thread so the
            # test fails its assertion rather than hanging until DB timeout.
            release.wait(2)
            writer.rollback()
            unlocked.set()
    holder = threading.Thread(target=hold_write_lock)
    holder.start()
    assert await asyncio.to_thread(locked.wait, 1)
    entered = threading.Event()
    original = repo.cancel
    def cancel(job_id):
        entered.set()
        return original(job_id)
    monkeypatch.setattr(repo, "cancel", cancel)
    operation = asyncio.create_task(service.cancel(job["id"]))
    shutdown = None
    try:
        async def entered_worker():
            while not entered.is_set():
                await asyncio.sleep(0.001)
        await asyncio.wait_for(entered_worker(), 2)
        await asyncio.sleep(0.02)
        assert not unlocked.is_set(), "Event loop stalled until the watchdog released SQLite"
        assert not operation.done(), "Write should still be waiting for SQLite"
        operation.cancel()
        await asyncio.sleep(0)
        operation.cancel()
        shutdown = asyncio.create_task(service.shutdown())
        await asyncio.sleep(0.02)
        shutdown.cancel()
        await asyncio.sleep(0)
        shutdown.cancel()
        await asyncio.sleep(0.02)
        assert not operation.done() and not shutdown.done()
        contender = PreparationLease(repo.path.with_suffix(".lock"))
        with pytest.raises(PreparationError, match="Another backend"):
            contender.acquire()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        with pytest.raises(asyncio.CancelledError):
            await shutdown
        assert repo.get(job["id"])["cancel_requested"]
        contender.acquire()
        contender.release()
    finally:
        release.set()
        await asyncio.to_thread(holder.join)
        await asyncio.gather(operation, *([shutdown] if shutdown else []), return_exceptions=True)
        await service.shutdown()


@async_test
async def test_http_admission_returns_retryable_503_instead_of_waiting(tmp_path, monkeypatch):
    pool = BoundedExecutor("preparation", max_workers=1, max_pending=0)
    gate = threading.Event()
    physical = pool.submit(lambda: gate.wait(5))
    monkeypatch.setattr("app.core.executors._preparation_executor", pool)
    app = FastAPI()
    app.state.data_preparation_service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), Adapter())
    app.include_router(router)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations", json=request().model_dump())
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "EXECUTOR_BUSY"
        assert response.headers["Retry-After"] == "1"
    finally:
        gate.set()
        await asyncio.wrap_future(physical)
        pool.shutdown()


def test_older_inventory_scan_cannot_certify_a_newer_publication(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db")
    job = repo.create(request(), 1)
    generation = repo.begin_inventory()
    repo.update(job["id"], state="FAILED", inventory_dirty=True)
    repo.finish_inventory(generation, "READY")
    assert repo.settings()["storage_inventory_state"] == "SCANNING"
    repo.finish_inventory(repo.begin_inventory(), "READY")
    assert repo.settings()["storage_inventory_state"] == "READY"
