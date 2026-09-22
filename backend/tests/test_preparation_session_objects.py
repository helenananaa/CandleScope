import asyncio
import threading
import zlib

import pytest

from app.data_preparation.models import PreparationError
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.storage_inventory import reconcile
from app.replay.storage.sqlite_store import _DatasetObjectStore, dataset_object_write_budget
from tests.test_data_preparation import async_test


def test_session_object_reserves_exact_compressed_size_and_reuses_without_extra_space(tmp_path):
    payload = b'{"bars":[]}' * 100
    size = len(zlib.compress(payload, level=6))
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=size)
    store = _DatasetObjectStore(tmp_path / "objects")
    with dataset_object_write_budget(repo):
        object_id = store.put(payload)
        assert store.put(payload) == object_id
        with pytest.raises(PreparationError) as failure:
            store.put(payload + b"different")
    assert failure.value.code == "STORAGE_BUDGET"
    assert store.get(object_id) == payload
    assert repo.storage_bytes() == size
    assert repo.cache_inventory()["publication_reserved_bytes"] == 0
    assert len(list(store.root.rglob("*.json.zlib"))) == 1
    assert not list(store.root.rglob("*.tmp"))


@async_test
async def test_session_budget_context_crosses_worker_boundary_without_affecting_other_launches(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=1)
    automatic = _DatasetObjectStore(tmp_path / "automatic")
    ordinary = _DatasetObjectStore(tmp_path / "ordinary")
    async def prepared():
        with dataset_object_write_budget(repo):
            with pytest.raises(PreparationError):
                await asyncio.to_thread(automatic.put, b"prepared")
    async def manual():
        return await asyncio.to_thread(ordinary.put, b"ordinary")
    _, object_id = await asyncio.gather(prepared(), manual())
    assert ordinary.get(object_id) == b"ordinary"
    assert not list(automatic.root.rglob("*.json.zlib"))
    assert repo.storage_bytes() == 0


def test_session_copy_rename_failure_keeps_budget_until_files_are_inventoried(tmp_path, monkeypatch):
    repo = PreparationRepository(tmp_path / "jobs.db")
    store = _DatasetObjectStore(tmp_path / "objects")
    repo.register_publication_scopes([(store.root, "replay_session_inputs")])
    register = repo.register_publications
    def failed(*args, **kwargs):
        raise OSError("fixture after object rename")
    monkeypatch.setattr(repo, "register_publications", failed)
    with dataset_object_write_budget(repo), pytest.raises(OSError):
        store.put(b"prepared snapshot")
    assert repo.cache_inventory()["publication_reserved_bytes"] > 0
    assert len(list(store.root.rglob("*.json.zlib"))) == 1
    monkeypatch.setattr(repo, "register_publications", register)
    reconcile(repo, threading.Event())
    assert repo.storage_bytes() == sum(path.stat().st_size for path in store.root.rglob("*.json.zlib"))
    assert repo.cache_inventory()["publication_reserved_bytes"] == 0
