from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.models import PreparationError
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from tests.test_data_preparation import async_test, bars, request


def test_concurrent_cache_writers_cannot_spend_the_same_remaining_budget(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=100)
    start = threading.Barrier(2)
    def reserve(digest):
        start.wait(timeout=5)
        try:
            repo.reserve_cache_write({"sha256": digest * 64}, 80)
            return "reserved"
        except PreparationError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(reserve, ("a", "b")))
    assert sorted(results) == ["STORAGE_BUDGET", "reserved"]
    assert repo.storage_bytes() == repo.cache_inventory()["pending_write_bytes"] == 80
    assert len(repo.pending_cache_writes()) == 1


def test_compressed_cache_is_reserved_before_writing_and_promoted_atomically(tmp_path):
    requirement = request().requirements[0]
    probe = BarPreparationAdapter(tmp_path / "probe", coordinator=None)
    _, size = probe._write(bars(), requirement)
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=size)
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None)
    adapter.publication_repository = repo
    adapter.reconcile_cache(repo)
    receipt, written = adapter._write(bars(), requirement)
    assert written == size == repo.storage_bytes()
    assert repo.cache_inventory()["pending_write_bytes"] == size
    repo.publish_chunk("chunk", requirement.model_dump(), receipt, size, "run")
    assert repo.storage_bytes() == size
    assert repo.cache_inventory()["pending_write_bytes"] == 0
    # Reusing an already charged object needs no extra allowance.
    assert adapter._write(bars(), requirement) == (receipt, size)
    assert repo.storage_bytes() == size
    repo.publish_chunk("chunk", requirement.model_dump(), receipt, size, "run")
    with pytest.raises(PreparationError, match="next prepared cache object"):
        adapter._write([{**row, "close": row["close"] + 0.5} for row in bars()], requirement)
    assert len(list(adapter.root.glob("*.json.gz"))) == 1
    assert repo.pending_cache_writes() == []
    assert not list(adapter.root.glob(".*.tmp"))


@pytest.mark.parametrize("written", [False, True])
def test_restart_releases_reservation_only_after_interrupted_file_is_gone(tmp_path, written):
    repo = PreparationRepository(tmp_path / "jobs.db")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None)
    adapter.publication_repository = repo
    adapter.reconcile_cache(repo)
    if written:
        adapter._write(bars(), request().requirements[0])
        assert list(adapter.root.glob("*.json.gz"))
    else:
        repo.reserve_cache_write({"sha256": "a" * 64}, 100)
    recovered = PreparationRepository(repo.path)
    assert recovered.storage_bytes() > 0
    adapter.reconcile_cache(recovered)
    assert recovered.pending_cache_writes() == []
    assert recovered.storage_bytes() == 0
    assert not list(adapter.root.glob("*.json.gz"))


def test_failed_cache_replace_removes_temporary_file_and_reservation(tmp_path, monkeypatch):
    repo = PreparationRepository(tmp_path / "jobs.db")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None)
    adapter.publication_repository = repo
    adapter.reconcile_cache(repo)
    def failed(*args):
        raise OSError("fixture replace failure")
    monkeypatch.setattr("app.data_preparation.bar_adapter.os.replace", failed)
    with pytest.raises(OSError, match="fixture replace failure"):
        adapter._write(bars(), request().requirements[0])
    assert repo.pending_cache_writes() == []
    assert repo.storage_bytes() == 0
    assert not list(adapter.root.glob(".*.tmp"))


def test_idle_cleanup_reclaims_abandoned_cache_write_but_waits_for_active_jobs(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None)
    adapter.publication_repository = repo
    adapter.reconcile_cache(repo)
    job = repo.create(request(), 1)
    _, size = adapter._write(bars(), request().requirements[0])
    assert repo.evict_unreferenced(adapter.remove_cached_object)["reclaimed_bytes"] == 0
    assert repo.storage_bytes() == size
    repo.update(job["id"], state="CANCELLED")
    assert repo.evict_unreferenced(adapter.remove_cached_object)["reclaimed_bytes"] == size
    assert repo.storage_bytes() == 0
    assert repo.pending_cache_writes() == []
    assert not list(adapter.root.glob("*.json.gz"))


@async_test
async def test_wrong_cache_owner_cannot_remove_another_databases_pending_write(tmp_path):
    owner = PreparationRepository(tmp_path / "owner.db")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None)
    adapter.publication_repository = owner
    adapter.reconcile_cache(owner)
    receipt, size = adapter._write(bars(), request().requirements[0])
    other = PreparationRepository(tmp_path / "other.db")
    other.reserve_cache_write(receipt, size)
    service = PreparationService(other, adapter)
    with pytest.raises(PreparationError, match="another preparation database"):
        await service.start()
    assert (adapter.root / (receipt["sha256"] + ".json.gz")).exists()
    assert owner.storage_bytes() == size
    assert other.storage_bytes() == size
