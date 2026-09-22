from concurrent.futures import ThreadPoolExecutor
import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.models import PreparationError
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.data_preparation.storage_inventory import reconcile
from app.local_data.service import LocalDatasetService
from tests.test_data_preparation import async_test, bars, request, terminal


def test_publication_working_space_is_exclusive_and_settles_to_measured_files(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=100)
    barrier = threading.Barrier(2)
    def reserve(_):
        barrier.wait(timeout=5)
        try:
            return repo.reserve_publication(80)
        except PreparationError as error:
            assert error.code == "STORAGE_BUDGET"
            return None
    with ThreadPoolExecutor(max_workers=2) as workers:
        tokens = list(workers.map(reserve, range(2)))
    assert sum(token is not None for token in tokens) == 1
    assert repo.storage_bytes() == 80
    output = tmp_path / "published.bin"
    output.write_bytes(b"x" * 40)
    repo.register_publications([(output, "strategy_input")], reservation=next(t for t in tokens if t))
    assert repo.storage_bytes() == 40
    assert repo.cache_inventory()["publication_reserved_bytes"] == 0


def test_interrupted_publication_is_charged_until_successful_recovery_inventory(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=100)
    root = tmp_path / "datasets"
    root.mkdir()
    repo.register_publication_scopes([(root, "strategy_storage")])
    repo.reserve_publication(80)
    (root / ".interrupted.bin").write_bytes(b"x" * 30)
    recovered = PreparationRepository(repo.path)
    recovered.recover()
    stop = threading.Event()
    stop.set()
    with pytest.raises(PreparationError, match="interrupted"):
        reconcile(recovered, stop)
    assert recovered.storage_bytes() == 80
    reconcile(recovered, threading.Event())
    assert recovered.storage_bytes() == 30
    assert recovered.cache_inventory()["publication_reserved_bytes"] == 0


def test_scan_cannot_release_a_publication_abandoned_after_scan_started(tmp_path, monkeypatch):
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=100)
    root = tmp_path / "datasets"
    root.mkdir()
    repo.register_publication_scopes([(root, "strategy_storage")])
    token = repo.reserve_publication(80)
    original = repo.register_publications
    def racing(objects):
        original(objects)
        (root / "late-file.bin").write_bytes(b"x" * 30)
        repo.abandon_publication(token)
    monkeypatch.setattr(repo, "register_publications", racing)
    reconcile(repo, threading.Event())
    assert repo.cache_inventory()["publication_reserved_bytes"] == 80
    monkeypatch.setattr(repo, "register_publications", original)
    reconcile(repo, threading.Event())
    assert repo.storage_bytes() == 30


@async_test
@pytest.mark.parametrize("consumer", ["REPLAY", "STRATEGY"])
async def test_publication_budget_stops_before_archive_or_snapshot_write_and_retry_resumes(tmp_path, consumer):
    local = LocalDatasetService(tmp_path / "datasets")
    replay = SimpleNamespace(settings=SimpleNamespace(replay_history_origin_uri=None,
        replay_history_archive_dir=tmp_path / "archive"))
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None,
        replay_service=replay, local_data=local, query=lambda *args, **kwargs: bars())
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=100_000)
    service = PreparationService(repo, adapter)
    await service.start()
    try:
        job = service.submit(request().model_copy(update={"consumer": consumer}))
        result = await terminal(service, job["id"])
        assert result["state"] == "BLOCKED_STORAGE", result
        assert result["error"]["code"] == "STORAGE_BUDGET"
        assert not list((tmp_path / "datasets").rglob("bars.sqlite"))
        assert not list((tmp_path / "archive").rglob("*.parquet"))
        assert repo.cache_inventory()["publication_reserved_bytes"] == 0
        repo.configure(cache_budget_bytes=16 * 1024**2, prefetch_enabled=False)
        service.retry(job["id"])
        result = await terminal(service, job["id"])
        assert result["state"] == "READY", result
        assert repo.cache_inventory()["publication_reserved_bytes"] == 0
        assert repo.cache_inventory()["publication_bytes"] > 0
        if consumer == "STRATEGY":
            item = result["result"]["inputs"][0]
            _, rows = local.load_canonical_bars(item["dataset_id"], data_epoch=item["data_epoch"], max_rows=10)
            assert len(rows) == 2
        else:
            assert list((tmp_path / "archive").rglob("*.parquet"))
    finally:
        await service.shutdown()


@async_test
async def test_failure_after_snapshot_rename_is_inventoried_before_reservation_release(tmp_path, monkeypatch):
    local = LocalDatasetService(tmp_path / "datasets")
    publish = local._publish
    def failed(*args, **kwargs):
        publish(*args, **kwargs)
        raise OSError("fixture failure after snapshot rename")
    monkeypatch.setattr(local, "_publish", failed)
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None, local_data=local,
        query=lambda *args, **kwargs: bars())
    repo = PreparationRepository(tmp_path / "jobs.db")
    service = PreparationService(repo, adapter)
    await service.start()
    try:
        job = service.submit(request().model_copy(update={"consumer": "STRATEGY"}))
        result = await terminal(service, job["id"])
        assert result["state"] == "FAILED"
        async def reconciled():
            while repo.settings()["storage_inventory_state"] != "READY":
                await asyncio.sleep(0.01)
        await asyncio.wait_for(reconciled(), 5)
        physical = sum(path.stat().st_size for path in local.root.rglob("*") if path.is_file())
        assert physical > 0
        assert repo.cache_inventory()["publication_bytes"] == physical
        assert repo.cache_inventory()["publication_reserved_bytes"] == 0
    finally:
        await service.shutdown()
