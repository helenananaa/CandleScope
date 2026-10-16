"""Catalog reads must support initialized runs that never had an empty setup."""

import json

import pytest

from app.replay.training.errors import TrainingRunError
from app.replay.training.models import TrainingRunSetupRequest
from tests.test_replay_v2_training_phase4 import _request, _service

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("disclosure", ["NONE", "HIDE_ALL"])
async def test_direct_and_nested_fork_catalog_survives_restart_without_mutation(tmp_path, disclosure):
    database = tmp_path / "fork-catalog.db"
    service = await _service(database)
    snapshots = {}
    catalogs = {}
    try:
        created = await service.training.create_run(await _request(
            service, integrity_mode="SANDBOX", disclosure=disclosure))
        run_id = created["run"]["run_id"]
        for generation in range(3):
            if generation:
                review = await service.training.start_review(run_id, event_id=None)
                child = await service.training.fork_run(run_id, event_id=review["selected_event_id"])
                run_id = child["run"]["run_id"]
            before = await service.training.get_market_tracks(run_id)
            catalog = await service.training.market_catalog(run_id)
            assert catalog["entries"]
            assert any(entry["start_compatibility"]["state"] == "READY" for entry in catalog["entries"])
            # A legacy run/fork has a source selection, not an empty-run time
            # commitment. A read must not fabricate or persist that contract.
            assert "time_commitment" not in catalog
            if disclosure == "HIDE_ALL":
                assert all(not entry.get("eligible_ranges") for entry in catalog["entries"])
            assert await service.training.get_market_tracks(run_id) == before
            snapshots[run_id] = before
            catalogs[run_id] = catalog
    finally:
        await service.shutdown(step_timeout=1.0)
    restarted = await _service(database)
    try:
        for run_id, before in snapshots.items():
            assert await restarted.training.market_catalog(run_id) == catalogs[run_id]
            assert await restarted.training.get_market_tracks(run_id) == before
    finally:
        await restarted.shutdown(step_timeout=1.0)


async def test_missing_run_and_corrupt_setup_do_not_become_legacy_catalogs(tmp_path):
    service = await _service(tmp_path / "invalid-catalog.db")
    try:
        with pytest.raises(TrainingRunError, match="does not exist") as missing:
            await service.training.market_catalog("missing-run")
        assert missing.value.code == "TRAINING_RUN_NOT_FOUND"
        created = await service.training.create_run(await _request(service, integrity_mode="SANDBOX"))
        run_id = created["run"]["run_id"]
        await service.training.store.base_store.run_extension_write(lambda db: db.execute(
            "INSERT INTO replay_training_run_setup(run_id, setup_json, setup_hash, created_at_ms) VALUES (?, ?, ?, ?)",
            (run_id, json.dumps({"invalid": True}), "sha256:" + "0" * 64, 0),
        ))
        with pytest.raises(TrainingRunError) as corrupt:
            await service.training.market_catalog(run_id)
        assert corrupt.value.code == "TRAINING_RUN_STORAGE_DEGRADED"
    finally:
        await service.shutdown(step_timeout=1.0)


async def test_catalog_cache_keeps_empty_setup_commitment_out_of_initialized_run(tmp_path):
    service = await _service(tmp_path / "catalog-cache.db")
    try:
        request = await _request(service, integrity_mode="SANDBOX")
        empty = await service.training.create_empty_run(TrainingRunSetupRequest.from_market_request(request))
        initialized = await service.training.create_run(request)
        cache = {}
        before = await service.training.market_catalog(empty["run"]["run_id"], _catalog_cache=cache)
        assert before["time_commitment"]["committed"] is True
        legacy = await service.training.market_catalog(initialized["run"]["run_id"], _catalog_cache=cache)
        assert "time_commitment" not in legacy
        assert all("time_commitment" not in value for value in cache.values())
        assert all("start_compatibility" not in entry for value in cache.values() for entry in value["entries"])
        assert await service.training.market_catalog(empty["run"]["run_id"], _catalog_cache=cache) == before
    finally:
        await service.shutdown(step_timeout=1.0)
