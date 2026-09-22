import asyncio
import threading
import sqlite3
from pathlib import Path

import pytest

from app.data_preparation.models import PreparationError
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.storage_inventory import reconcile
from tests.test_data_preparation import Adapter, async_test, bars, request, terminal


def test_adopted_unknown_cache_files_are_preserved_and_charged(tmp_path):
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None)
    unknown = adapter.root / "old-history.bin"
    unknown.write_bytes(b"x" * 150)
    nested = adapter.root / "older-cache"
    nested.mkdir()
    (nested / "history.bin").write_bytes(b"y" * 80)
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=200)
    adapter.reconcile_cache(repo)
    reconcile(repo, threading.Event())
    assert repo.storage_bytes() == 230
    with pytest.raises(PreparationError, match="storage budget"):
        repo.check_physical_budget()
    recovered = PreparationRepository(repo.path)
    adapter.reconcile_cache(recovered)
    reconcile(recovered, threading.Event())
    assert unknown.exists() and recovered.storage_bytes() == 230
    unknown.unlink()  # Operator removes an unowned legacy file, not automatic GC.
    reconcile(recovered, threading.Event())
    assert recovered.storage_bytes() == 80


def test_adopted_bar_object_is_not_double_charged_and_rewrite_reserves_again(tmp_path):
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None)
    requirement = request().requirements[0]
    receipt, size = adapter._write(bars(), requirement)
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=size)
    adapter.publication_repository = repo
    adapter.reconcile_cache(repo)
    reconcile(repo, threading.Event())
    assert repo.storage_bytes() == size
    assert adapter._write(bars(), requirement) == (receipt, size)
    repo.publish_chunk("chunk", requirement.model_dump(), receipt, size, "run")
    assert repo.storage_bytes() == repo.cache_inventory()["referenced_bytes"] == size
    # Receipt adoption survives process restart with the same physical total.
    adapter.reconcile_cache(repo)
    reconcile(repo, threading.Event())
    assert repo.storage_bytes() == size
    with repo.connect() as db:
        db.execute("DELETE FROM preparation_refs")
    assert repo.evict_unreferenced(adapter.remove_cached_object)["reclaimed_bytes"] == size
    assert repo.storage_bytes() == 0
    # Occupy the remaining budget, then try to recreate the previously mapped
    # object. A stale zero-byte mapping must not bypass admission.
    repo.reserve_cache_write({"sha256": "a" * 64}, size)
    with pytest.raises(PreparationError, match="next prepared cache object"):
        adapter._write(bars(), requirement)
    assert not (adapter.root / f"{receipt['sha256']}.json.gz").exists()
    repo.release_cache_write({"sha256": "a" * 64})
    adapter._write(bars(), requirement)
    assert repo.storage_bytes() == size


def test_shared_host_database_tracks_late_wal_and_checkpoint_without_scanning_parent(tmp_path):
    path = tmp_path / "host.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE history (payload BLOB)")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None, host_history_path=path)
    repo = PreparationRepository(tmp_path / "jobs.db")
    repo.register_publication_scopes(adapter.publication_scopes())
    (tmp_path / "unrelated.bin").write_bytes(b"x" * 100_000)
    reconcile(repo, threading.Event())
    assert repo.storage_bytes() == path.stat().st_size
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO history VALUES (zeroblob(40000))")
        connection.commit()
        assert Path(str(path) + "-wal").exists()
        reconcile(repo, threading.Event())
        physical = sum(p.stat().st_size for p in adapter._host_history_files() if p.exists())
        assert repo.storage_bytes() == physical
    finally:
        connection.close()
    assert not Path(str(path) + "-wal").exists()
    recovered = PreparationRepository(repo.path)
    reconcile(recovered, threading.Event())
    assert recovered.storage_bytes() == path.stat().st_size


@async_test
async def test_host_growth_blocks_snapshot_publication_after_download(tmp_path):
    path = tmp_path / "host.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE history (payload BLOB)")
    rows = []
    class Coordinator:
        async def request_and_wait(self, request):
            with sqlite3.connect(path) as db:
                db.execute("INSERT INTO history VALUES (zeroblob(100000))")
            rows.extend(bars())
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(),
        host_history_path=path, query=lambda *args, **kwargs: rows)
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=path.stat().st_size + 10_000)
    service = PreparationService(repo, adapter)
    await service.start()
    try:
        job = service.submit(request())
        result = await terminal(service, job["id"])
        assert result["state"] == "BLOCKED_STORAGE", result
        assert result["error"]["code"] == "STORAGE_BUDGET"
        assert not list(adapter.root.glob("*.json.gz"))
        assert repo.storage_bytes() >= path.stat().st_size > repo.cache_budget_bytes
    finally:
        await service.shutdown()


def test_registered_directory_recovers_unjournaled_publication_and_staging_bytes(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=100)
    root = tmp_path / "archive"
    root.mkdir()
    repo.register_publication_scopes([(root, "replay_archive"), (root / "objects", "replay_objects")])
    (root / "objects").mkdir()
    (root / "objects" / "committed.parquet").write_bytes(b"x" * 80)
    (root / ".interrupted.tmp").write_bytes(b"y" * 30)
    recovered = PreparationRepository(repo.path)
    reconcile(recovered, threading.Event())
    assert recovered.cache_inventory()["publication_bytes"] == 110
    assert recovered.settings()["storage_inventory_state"] == "READY"
    with pytest.raises(PreparationError, match="storage budget"):
        recovered.check_physical_budget()
    (root / ".interrupted.tmp").unlink()
    reconcile(recovered, threading.Event())
    assert recovered.cache_inventory()["publication_bytes"] == 80


def test_cancelled_inventory_is_not_reported_as_complete(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db")
    repo.register_publication_scopes([(tmp_path / "archive", "replay_archive")])
    stop = threading.Event()
    stop.set()
    with pytest.raises(PreparationError, match="interrupted"):
        reconcile(repo, stop)
    assert repo.settings()["storage_inventory_state"] == "INCOMPLETE"


@async_test
@pytest.mark.parametrize("cancel", [False, True])
async def test_inventory_runs_in_background_and_gates_only_preparation(tmp_path, monkeypatch, cancel):
    entered, release = threading.Event(), threading.Event()
    def controlled(repository, stop):
        entered.set()
        assert release.wait(4)
        reconcile(repository, stop)
    monkeypatch.setattr("app.data_preparation.storage_inventory.reconcile", controlled)
    adapter = Adapter()
    adapter.publication_scopes = lambda: []
    adapter.release.set()
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await asyncio.wait_for(service.start(), 1)
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        job = service.submit(request())
        await asyncio.sleep(0.05)
        assert adapter.calls == 0
        if cancel:
            service.cancel(job["id"])
            assert (await terminal(service, job["id"]))["state"] == "CANCELLED"
            assert adapter.calls == 0
        else:
            release.set()
            assert (await terminal(service, job["id"]))["state"] == "READY"
            assert adapter.calls == 1
    finally:
        release.set()
        await service.shutdown()


@async_test
async def test_retry_repeats_failed_inventory_before_acquisition(tmp_path, monkeypatch):
    attempts = 0
    def flaky(repository, stop):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            repository.set_inventory_state("INCOMPLETE")
            raise PreparationError("STORAGE_INVENTORY_UNAVAILABLE", "Fixture read failure")
        reconcile(repository, stop)
    monkeypatch.setattr("app.data_preparation.storage_inventory.reconcile", flaky)
    adapter = Adapter()
    adapter.publication_scopes = lambda: []
    adapter.release.set()
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    try:
        job = service.submit(request())
        assert (await terminal(service, job["id"]))["state"] == "FAILED"
        assert adapter.calls == 0
        service.retry(job["id"])
        assert (await terminal(service, job["id"]))["state"] == "READY"
        assert attempts == 2 and adapter.calls == 1
    finally:
        await service.shutdown()
