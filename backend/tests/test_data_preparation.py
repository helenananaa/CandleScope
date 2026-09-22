import asyncio
from functools import wraps
from types import SimpleNamespace as NS

import pytest

from app.data_preparation.models import PreparationError, PreparationRequest, Requirement, split_requirement
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.data_preparation.bar_adapter import BarPreparationAdapter

START = 1_710_028_800_000  # UTC day boundary


def async_test(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


def request(key="request-0001", **kwargs):
    return PreparationRequest(idempotency_key=key, consumer="PREFETCH", requirements=[
        Requirement(exchange="binance", market_type="spot", symbol="BTCUSDT",
                    start_ms=START, end_ms=START + 120_000)], **kwargs)


class Adapter:
    def __init__(self):
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def validate(self, request):
        pass

    async def acquire(self, requirement, key):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return {"data": key}, 40

    async def publish(self, request, chunks, job_id):
        return {"chunks": len(chunks)}


async def terminal(service, job_id):
    async def wait():
        while True:
            job = service.repository.get(job_id)
            if job["state"] in {"READY", "FAILED", "CANCELLED", "BLOCKED_STORAGE"}:
                return job
            await asyncio.sleep(0.005)
    return await asyncio.wait_for(wait(), 5)


def test_idempotency_conflict_and_frozen_ranges(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db")
    first = repo.create(request(), 1)
    assert repo.create(request(), 1)["id"] == first["id"]
    with pytest.raises(PreparationError, match="different preparation"):
        repo.create(request(max_bytes=1024), 1)
    parts = split_requirement(Requirement(exchange="binance", market_type="spot", symbol="BTCUSDT",
        start_ms=86_400_000 - 60_000, end_ms=86_400_000 + 60_000))
    assert [(p.start_ms, p.end_ms) for p in parts] == [(86_340_000, 86_400_000), (86_400_000, 86_460_000)]


def test_storage_budget_counts_shared_physical_receipt_once(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=100)
    receipt = {"sha256": "a" * 64}
    repo.publish_chunk("first", {}, receipt, 60, "owner-a")
    repo.publish_chunk("second", {}, receipt, 60, "owner-b")
    assert repo.cache_inventory()["bytes"] == 60
    assert repo.cache_inventory()["referenced_bytes"] == 60
    repo.release("owner-a")
    assert repo.cache_inventory()["referenced_bytes"] == 60
    removed = []
    repo.evict_unreferenced(removed.append)
    assert removed == []
    repo.release("owner-b")
    assert repo.evict_unreferenced(removed.append)["reclaimed_bytes"] == 60
    assert removed == [receipt]
    assert repo.cache_inventory()["bytes"] == 0


def test_publication_files_are_charged_once_and_block_further_work_until_reclaimed(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=100)
    path = tmp_path / "published.parquet"
    path.write_bytes(b"x" * 80)
    repo.register_publications([(path, "replay_bar"), (path, "replay_bar")])
    assert repo.cache_inventory()["publication_bytes"] == 80
    assert repo.cache_inventory()["bytes"] == 80
    repo.publish_chunk("cached", {}, {"sha256": "b" * 64}, 30, "owner")
    with pytest.raises(PreparationError, match="Published history"):
        repo.check_physical_budget()
    with pytest.raises(PreparationError, match="budget"):
        repo.create(request(), 1)
    path.unlink()
    repo.refresh_publications()
    assert repo.cache_inventory()["publication_bytes"] == 0
    assert repo.cache_inventory()["bytes"] == 30
    repo.check_physical_budget()


@async_test
async def test_startup_cache_reconciliation_removes_only_owned_unreferenced_files(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None)
    legacy = adapter.root / ("d" * 64 + ".json.gz")
    legacy.write_bytes(b"unclassified legacy object")
    assert adapter.reconcile_cache(repo) == 0  # establish the directory owner
    retained = adapter.root / ("a" * 64 + ".json.gz")
    retained.write_bytes(b"retained")
    repo.publish_chunk("known", {}, {"sha256": "a" * 64}, 8, "owner")
    orphan = adapter.root / ("b" * 64 + ".json.gz")
    orphan.write_bytes(b"orphan")
    temporary = adapter.root / ("." + "c" * 32 + ".tmp")
    temporary.write_bytes(b"interrupted")
    unknown = adapter.root / "notes.tmp"
    unknown.write_bytes(b"unclassified")
    other = PreparationRepository(tmp_path / "other.db")
    with pytest.raises(PreparationError, match="another preparation database"):
        adapter.reconcile_cache(other)
    assert orphan.exists()
    service = PreparationService(repo, adapter)
    await service.start()
    try:
        assert retained.exists() and unknown.exists() and legacy.exists()
        assert not orphan.exists() and not temporary.exists()
    finally:
        await service.shutdown()


@async_test
async def test_shared_download_cancel_does_not_cancel_other_consumer(tmp_path):
    repo, adapter = PreparationRepository(tmp_path / "jobs.db"), Adapter()
    service = PreparationService(repo, adapter)
    await service.start()
    try:
        a = service.submit(request().model_copy(update={"consumer": "REPLAY"}))
        b = service.submit(request("request-0002").model_copy(update={"consumer": "REPLAY"}))
        await asyncio.wait_for(adapter.entered.wait(), 2)
        service.cancel(a["id"])
        adapter.release.set()
        assert (await terminal(service, a["id"]))["state"] == "CANCELLED"
        assert (await terminal(service, b["id"]))["state"] == "READY"
        assert adapter.calls == 1
        with repo.connect() as db:
            assert {r["owner"] for r in db.execute("SELECT * FROM preparation_refs")} == {b["id"]}
    finally:
        adapter.release.set()
        await service.shutdown()


@async_test
async def test_restart_resumes_publication_without_redownload(tmp_path):
    repo, adapter = PreparationRepository(tmp_path / "jobs.db"), Adapter()
    service = PreparationService(repo, adapter)
    job = service.submit(request())
    from app.data_preparation.models import fingerprint
    fragment = request().requirements[0].model_dump()
    repo.publish_chunk(fingerprint(fragment), fragment, {"data": "saved"}, 40, job["id"])
    repo.update(job["id"], state="RUNNING", stage="PUBLISHING")
    recovered = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await recovered.start()
    try:
        assert (await terminal(recovered, job["id"]))["state"] == "READY"
        assert adapter.calls == 0
    finally:
        await recovered.shutdown()


@async_test
async def test_restart_at_start_barrier_reuses_frozen_consumer_input(tmp_path):
    class LaunchAdapter(Adapter):
        async def publish(self, *args):
            raise AssertionError("Recovery must not choose a newer dataset")

        async def launch(self, req, result, job_id):
            assert result["resolution"]["dataset_id"] == "immutable-old-generation"
            return {**result, "strategy_run": {"run_id": "bt_existing"}}

    adapter = LaunchAdapter()
    repo = PreparationRepository(tmp_path / "jobs.db")
    req = request().model_copy(update={"consumer": "STRATEGY", "intent": {"chart_context": {}}})
    job = repo.create(req, 1)
    repo.update(job["id"], state="RUNNING")
    repo.begin_start(job["id"], {"resolution": {"dataset_id": "immutable-old-generation"}})
    service = PreparationService(repo, adapter)
    await service.start()
    try:
        ready = await terminal(service, job["id"])
        assert ready["state"] == "READY"
        assert ready["result"]["strategy_run"]["run_id"] == "bt_existing"
        assert adapter.calls == 0
    finally:
        await service.shutdown()


@async_test
async def test_failed_publish_retries_without_redownload(tmp_path):
    class Flaky(Adapter):
        attempts = 0

        async def publish(self, request, chunks, job_id):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("interrupted write")
            return await super().publish(request, chunks, job_id)

    adapter = Flaky()
    adapter.release.set()
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    try:
        job = service.submit(request())
        assert (await terminal(service, job["id"]))["state"] == "FAILED"
        service.retry(job["id"])
        assert (await terminal(service, job["id"]))["state"] == "READY"
        assert adapter.calls == 1
    finally:
        await service.shutdown()


def bars():
    return [{"open_time": START + i * 60_000, "close_time": START + (i + 1) * 60_000 - 1,
             "open": 100, "high": 102, "low": 99, "close": 101, "volume": 3,
             "source": "backfill"} for i in range(2)]


@async_test
async def test_real_bar_adapter_download_archive_and_pinned_revision(tmp_path):
    pytest.importorskip("pyarrow")
    from app.replay.history_archive import ReplayHistoryRepository
    values, repairs = [], []

    class Coordinator:
        async def request_and_wait(self, repair):
            repairs.append(repair)
            values.extend(bars())

    replay = NS(settings=NS(replay_history_origin_uri=None, replay_history_archive_dir=tmp_path / "archive"))
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(), replay_service=replay,
                                    query=lambda *a, **kw: list(values))
    req = request().model_copy(update={"consumer": "REPLAY"})
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    try:
        job = service.submit(req)
        result = await terminal(service, job["id"])
        assert result["state"] == "READY", result
        assert len(repairs) == 1
        assert repairs[0].end_ms == START + 60_000
        revision = result["result"]["inputs"][0]["source_revision"]
        reader = ReplayHistoryRepository(tmp_path / "archive")
        rows = reader.query_bars_at_revision(revision, "BTCUSDT", "1m", start_ms=START,
                                            end_ms=START + 60_000, exchange="binance", market_type="spot")
        assert len(rows) == 2
        assert float(rows[0]["close"]) == 101
        values[0]["close"] = 100
        again = service.submit(req.model_copy(update={"idempotency_key": "request-repeat"}))
        repeated = await terminal(service, again["id"])
        assert repeated["state"] == "READY", repeated
        assert repeated["result"]["inputs"][0]["source_revision"] == revision
        assert len(repairs) == 1
    finally:
        await service.shutdown()


@async_test
async def test_corrupt_cached_input_never_becomes_ready(tmp_path):
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None, query=lambda *a, **kw: bars())
    receipt, size = await adapter.acquire(request().requirements[0], "key")
    chunk = {"requirement": request().requirements[0].model_dump(), "receipt": receipt}
    (tmp_path / "chunks" / f"{receipt['sha256']}.json.gz").write_bytes(b"broken")
    with pytest.raises(PreparationError, match="corrupt"):
        adapter.read(chunk)


def test_future_unsupported_and_budget_rejected_before_download(tmp_path):
    adapter = BarPreparationAdapter(tmp_path, coordinator=None)
    for changes, code in [({"role": "TRADES"}, "TRADE_ARCHIVE_UNAVAILABLE"),
                          ({"start_ms": START + 1}, "INVALID_TIME_GRID"),
                          ({"start_ms": adapter.now_ms(), "end_ms": adapter.now_ms() + 60_000}, "INVALID_TIME_GRID")]:
        req = request().model_copy(update={"requirements": [request().requirements[0].model_copy(update=changes)]})
        with pytest.raises(PreparationError) as error:
            adapter.validate(req)
        assert error.value.code == code
    with pytest.raises(PreparationError) as error:
        adapter.validate(request(max_bytes=1024))
    assert error.value.code == "STORAGE_BUDGET"


@async_test
async def test_prepared_strategy_dataset_is_readable(tmp_path):
    from app.local_data.service import LocalDatasetService
    local = LocalDatasetService(tmp_path / "datasets")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None, local_data=local,
                                    query=lambda *a, **kw: bars())
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    try:
        job = service.submit(request().model_copy(update={"consumer": "STRATEGY"}))
        result = await terminal(service, job["id"])
        assert result["state"] == "READY", result
        item = result["result"]["inputs"][0]
        manifest, rows = local.load_canonical_bars(item["dataset_id"], data_epoch=item["data_epoch"], max_rows=10)
        assert len(rows) == 2
        assert manifest["symbol"] == "BTCUSDT"
    finally:
        await service.shutdown()


@async_test
@pytest.mark.parametrize("account_history,block_session_copy", [("proxy", False), ("exact", False), ("missing", False), ("proxy", True)])
async def test_replay_api_empty_archive_downloads_and_creates_one_recoverable_run(tmp_path, account_history, block_session_copy, monkeypatch):
    from dataclasses import replace
    import httpx
    from fastapi import FastAPI
    from app.api.v1.data_preparation import router
    from app.replay.service import ReplayService
    from app.replay.storage import ReplaySQLiteStore
    from app.replay.history_archive import ReplayHistoryRepository
    from tests.fixtures.replay.service_fakes import replay_settings
    from tests.test_replay_v2_run_centric import _setup_payload
    archive = tmp_path / "archive"
    settings = replace(replay_settings(tmp_path / "replay.db"), replay_history_archive_dir=archive,
                       replay_account_history_enabled=True)
    replay = ReplayService(settings=settings, store=ReplaySQLiteStore(tmp_path / "replay.db"),
                           repository=ReplayHistoryRepository(archive),
                           native_intervals=lambda _: ("1m",))
    await replay.start()
    if account_history == "exact":
        from tests.fixtures.replay.account_history import build_account_history_archive
        capture = tmp_path / "verified-account.sqlite3"
        build_account_history_archive(capture, range_start_ms=START, range_end_ms=START + 12 * 60_000)
        await replay.training.account_history.import_archive(capture)
    inventory = []

    class Coordinator:
        async def request_and_wait(self, repair):
            for timestamp in range(repair.start_ms, repair.end_ms + 1, 60_000):
                inventory.append({**bars()[0], "open_time": timestamp, "close_time": timestamp + 59_999})

    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(), replay_service=replay,
        query=lambda *a, **kw: [r for r in inventory if kw["start_ms"] <= r["open_time"] <= kw["end_ms"]])
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    object_store = replay.store._dataset_objects
    put = object_store.put
    if block_session_copy:
        def no_copy_space(payload):
            occupied = service.repository.storage_bytes()
            with service.repository.connect() as db:
                db.execute("UPDATE preparation_settings SET value=? WHERE name='cache_budget_bytes'", (str(occupied),))
            return put(payload)
        monkeypatch.setattr(object_store, "put", no_copy_space)
    app = FastAPI()
    app.state.data_preparation_service = service
    app.include_router(router)
    try:
        setup = {**_setup_payload(), "requested_start_ms": START + 5 * 60_000, "forward_cache_ms": 5 * 60_000}
        if account_history != "proxy":
            setup.update(account_data_mode="HISTORICAL_EXACT", funding_mode="HISTORICAL_EXACT")
        body = {"idempotency_key": "api-launch-1", "setup": setup,
                "exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/replay", json=body)
            assert response.status_code == 202, response.text
            job = await terminal(service, response.json()["id"])
            if block_session_copy:
                assert job["state"] == "BLOCKED_STORAGE", job
                assert job["error"]["code"] == "STORAGE_BUDGET"
                assert not list(object_store.root.rglob("*.json.zlib"))
                monkeypatch.setattr(object_store, "put", put)
                service.repository.configure(cache_budget_bytes=16 * 1024**2, prefetch_enabled=False)
                service.retry(job["id"])
                job = await terminal(service, job["id"])
            if account_history == "missing":
                assert job["state"] == "FAILED", job
                assert job["error"]["code"] == "AUXILIARY_HISTORY_UNAVAILABLE"
                assert job["request"]["intent"]["replay_setup"]["account_data_mode"] == "HISTORICAL_EXACT"
                assert inventory == []  # Reject missing account inputs before downloading BAR history.
                return
            assert job["state"] == "READY", job
            if account_history == "exact":
                assert job["result"]["replay_dependencies"]["account_history_ref"]["archive_id"]
            run_id = job["result"]["run"]["run_id"]
            assert run_id == f"prepared-{job['id']}"
            assert job["result"]["run"]["adapter_session_id"]
            repeated = await client.post("/data-preparations/replay", json=body)
            assert repeated.json()["id"] == job["id"]
            # Crash after consumer commit and before job READY is retry-safe.
            replayed = await adapter.launch(PreparationRequest.model_validate(job["request"]), {"inputs": []}, job["id"])
            assert replayed["run"]["run_id"] == run_id
            runs = await replay.training.list_runs(limit=50, cursor=None, state=None, source_kind=None, compatibility=None)
            assert len(runs["items"]) == 1
    finally:
        await service.shutdown()
        await replay.shutdown()


@async_test
@pytest.mark.parametrize("launch_strategy", [False, True])
async def test_strategy_api_prepares_frozen_multi_minute_context(tmp_path, launch_strategy):
    import json
    import httpx
    from fastapi import FastAPI
    from app.api.v1.data_preparation import router
    from tests.test_backtest_chart_context import _runtime
    runtime = _runtime(tmp_path)
    from tests.test_backtest_strategy_workspace_m9 import _revision
    launch_intent = ({"strategy": {"strategy_revision_id": _revision(runtime.service)["revision_id"],
                                  "parameters": {"length": 3}}} if launch_strategy else {})
    rows = []
    start = START // 300_000 * 300_000

    class Coordinator:
        async def request_and_wait(self, repair):
            for timestamp in range(repair.start_ms, repair.end_ms + 1, 60_000):
                rows.append({**bars()[0], "open_time": timestamp, "close_time": timestamp + 59_999})

    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(),
        local_data=runtime.local_data, backtest_runtime=runtime,
        query=lambda *a, **kw: [r for r in rows if kw["start_ms"] <= r["open_time"] <= kw["end_ms"]])
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    app = FastAPI()
    app.state.data_preparation_service = service
    app.state.backtest_runtime = runtime
    app.include_router(router)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/data-preparations/strategy", json={
                **launch_intent,
                "idempotency_key": "strategy-auto-1", "context": {
                    "exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT",
                    "interval": "5m", "range_mode": "CUSTOM", "fidelity_preference": "FAST",
                    "start_time_ms": start, "end_time_ms": start + 600_000 - 1,
                }})
            assert response.status_code == 202, response.text
            job = await terminal(service, response.json()["id"])
            assert job["state"] == "READY", job
            resolution = job["result"]["resolution"]
            assert resolution["status"] == "READY"
            assert resolution["coverage"]["row_count"] == (6 if launch_strategy else 2)
            assert resolution["request"]["end_time_ms"] == start + 600_000 - 1
            if launch_strategy:
                run = job["result"]["strategy_run"]
                assert run["run_id"].startswith("bt_")
                assert resolution["preparation"] == {"warmup_bars": 4, "requested_start_ms": start,
                                                       "prepared_start_ms": start - 4 * 300_000}
                repeated = await adapter.launch(PreparationRequest.model_validate(job["request"]), job["result"], job["id"])
                assert repeated["strategy_run"]["run_id"] == run["run_id"]
                assert len(runtime.service.list_runs()) == 1
            submitted = json.loads(response.request.content)
            retried = await client.post("/data-preparations/strategy", json=submitted)
            assert retried.status_code == 202
            assert retried.json()["id"] == job["id"]
            def forbidden(*args, **kwargs):
                raise AssertionError("Immutable strategy input must not redownload live bars")
            adapter.query = forbidden
            adapter.coordinator = None
            submitted["idempotency_key"] = "strategy-local-reuse"
            cached = await client.post("/data-preparations/strategy", json=submitted)
            assert cached.status_code == 202, cached.text
            reused = await terminal(service, cached.json()["id"])
            assert reused["state"] == "READY", reused["error"]
            assert reused["result"]["resolution"]["snapshot_hash"] == resolution["snapshot_hash"]
    finally:
        await service.shutdown()
        runtime.shutdown()


@async_test
async def test_shutdown_drains_acquisition_and_new_owner_recovers(tmp_path):
    adapter = Adapter()
    repo = PreparationRepository(tmp_path / "jobs.db")
    service = PreparationService(repo, adapter)
    await service.start()
    job = service.submit(request())
    await asyncio.wait_for(adapter.entered.wait(), 2)
    with pytest.raises(PreparationError, match="Another backend"):
        await PreparationService(repo, adapter).start()
    await asyncio.wait_for(service.shutdown(), 2)
    assert repo.get(job["id"])["state"] == "RUNNING"
    adapter.release.set()
    recovered = PreparationService(repo, adapter)
    await recovered.start()
    try:
        assert (await terminal(recovered, job["id"]))["state"] == "READY"
    finally:
        await recovered.shutdown()


def test_cache_cleanup_preserves_pinned_input_and_requires_finished_owner(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db")
    job = repo.create(request(), 1)
    repo.publish_chunk("a", {}, {"sha256": "a" * 64}, 20, job["id"])
    removed = []
    assert repo.evict_unreferenced(removed.append)["removed_chunks"] == 0
    with pytest.raises(PreparationError, match="Active"):
        repo.release_finished(job["id"])
    repo.update(job["id"], state="READY", result={"dataset": "immutable"})
    repo.release_finished(job["id"])
    assert repo.evict_unreferenced(removed.append) == {"removed_chunks": 1, "reclaimed_bytes": 20}
    assert len(removed) == 1
    assert repo.get(job["id"])["result"] == {"dataset": "immutable"}


@pytest.mark.parametrize("unlink_before_crash", [False, True])
def test_cache_gc_crash_never_leaves_deleted_coverage_readable(tmp_path, unlink_before_crash):
    repo = PreparationRepository(tmp_path / "jobs.db")
    path = tmp_path / "object"
    path.write_bytes(b"verified cached payload")
    repo.publish_chunk("gc-object", {}, {"sha256": "b" * 64}, 24, "fixture")
    repo.release("fixture")

    def crash(receipt):
        if unlink_before_crash:
            path.unlink()
        raise RuntimeError("simulated process interruption")

    with pytest.raises(RuntimeError, match="interruption"):
        repo.evict_unreferenced(crash)
    recovered = PreparationRepository(tmp_path / "jobs.db")
    assert recovered.chunk("gc-object") is None
    assert recovered.cache_inventory()["pending_delete_bytes"] == 24
    assert recovered.cache_inventory()["bytes"] == 24
    assert recovered.cleanup_pending(lambda receipt: path.unlink(missing_ok=True), before_workers=True) == 24
    assert not path.exists()
    assert recovered.cache_inventory()["bytes"] == 0


def test_pending_gc_preserves_object_adopted_by_new_acquisition(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db")
    receipt = {"sha256": "c" * 64}
    repo.publish_chunk("old", {}, receipt, 32, "old-owner")
    repo.release("old-owner")
    with pytest.raises(OSError):
        repo.evict_unreferenced(lambda receipt: (_ for _ in ()).throw(OSError("busy")))
    repo.publish_chunk("new", {}, receipt, 32, "new-owner")

    def forbidden(receipt):
        raise AssertionError("Re-adopted bytes are still pinned")

    assert repo.cleanup_pending(forbidden) == 0
    assert repo.chunk("new") is not None
    assert repo.cache_inventory()["bytes"] == 32


@async_test
async def test_existing_archive_is_reused_without_live_query_or_download(tmp_path):
    from app.replay.history_archive import ReplayHistoryArchiveWriter, ReplayHistoryImportBatch, ReplayHistoryRepository
    from app.replay.catalog import ReplaySeriesIdentity
    root = tmp_path / "archive"
    writer = ReplayHistoryArchiveWriter(root)
    writer.import_batches(ReplaySeriesIdentity("binance", "spot", "BTCUSDT"), "1m", [
        ReplayHistoryImportBatch(rows=bars(), source_provider="test", source_object_key="known", source_period="test")])
    def forbidden(*a, **kw):
        raise AssertionError("complete archive must avoid live history reads")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=None,
        replay_service=NS(_repository=ReplayHistoryRepository(root)), query=forbidden)
    receipt, size = await adapter.acquire(request().requirements[0], "known")
    assert receipt["origin"] == "replay_archive"
    assert size > 0


@async_test
async def test_partial_overlap_only_downloads_gap_and_containment_is_sliced(tmp_path):
    from app.local_data.service import LocalDatasetService
    inventory, fetched = [], []
    class Coordinator:
        async def request_and_wait(self, repair):
            fetched.append((repair.start_ms, repair.end_ms))
            for timestamp in range(repair.start_ms, repair.end_ms + 1, 60_000):
                inventory.append({**bars()[0], "open_time": timestamp, "close_time": timestamp + 59_999})
    local = LocalDatasetService(tmp_path / "datasets")
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(), local_data=local,
        query=lambda *a, **kw: [r for r in inventory if kw["start_ms"] <= r["open_time"] <= kw["end_ms"]])
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    await service.start()
    try:
        first = service.submit(request())
        assert (await terminal(service, first["id"]))["state"] == "READY"
        fragment = request().requirements[0].model_copy(update={"start_ms": START + 60_000, "end_ms": START + 180_000})
        second = service.submit(request("partial-0002").model_copy(update={"consumer": "STRATEGY", "requirements": [fragment]}))
        result = await terminal(service, second["id"])
        assert result["state"] == "READY", result
        item = result["result"]["inputs"][0]
        _, rows = local.load_canonical_bars(item["dataset_id"], data_epoch=item["data_epoch"], max_rows=10)
        assert [r["open_time_ms"] for r in rows] == [START + 60_000, START + 120_000]
        assert fetched == [(START, START + 60_000), (START + 120_000, START + 120_000)]
    finally:
        await service.shutdown()


def test_storage_reservation_is_atomic_and_cannot_be_bypassed_by_retry(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db", cache_budget_bytes=3000)
    first = repo.create(request(), 1)
    with pytest.raises(PreparationError, match="budget"):
        repo.create(request("reserve-0002"), 1)
    repo.update(first["id"], state="FAILED")
    repo.create(request("reserve-0002"), 1)
    with pytest.raises(PreparationError, match="budget"):
        repo.retry(first["id"])
