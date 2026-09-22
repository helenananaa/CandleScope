import asyncio

from app.data_preparation.prefetch import next_prefetch
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from tests.test_data_preparation import Adapter, START, async_test, request, terminal


def test_prefetch_requires_repeated_user_interest_and_never_crosses_now():
    jobs = [{"idempotency_key": f"job-{i}", "state": "READY", "created_ms": START,
             "request": request().model_copy(update={"consumer": "REPLAY"}).model_dump()} for i in range(2)]
    assert next_prefetch(jobs[:1], now_ms=START + 300_000) is None
    planned = next_prefetch(jobs, now_ms=START + 330_001)
    assert planned.consumer == "PREFETCH"
    assert planned.requirements[0].start_ms == START + 120_000
    assert planned.requirements[0].end_ms == START + 300_000
    jobs.append({"idempotency_key": planned.idempotency_key, "state": "READY", "created_ms": START,
                 "request": planned.model_dump()})
    assert next_prefetch(jobs, now_ms=START + 330_001) is None
    assert next_prefetch(jobs, now_ms=START + 8 * 86_400_000) is None


def test_cache_settings_survive_restart(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db")
    assert not repo.settings()["prefetch_enabled"]
    repo.configure(cache_budget_bytes=64 * 1024**2, prefetch_enabled=True)
    assert PreparationRepository(repo.path).settings() == {
        "cache_budget_bytes": 64 * 1024**2, "prefetch_enabled": True}


@async_test
async def test_prefetch_leaves_a_foreground_worker_available(tmp_path):
    adapter = Adapter()
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter, workers=2)
    await service.start()
    try:
        first = service.submit(request("prefetch-one"))
        second = service.submit(request("prefetch-two"))
        await asyncio.wait_for(adapter.entered.wait(), 2)
        foreground_req = request("foreground-one").model_copy(update={"consumer": "REPLAY",
            "requirements": [request().requirements[0].model_copy(update={"symbol": "ETHUSDT"})]})
        foreground = service.submit(foreground_req)
        for _ in range(100):
            if adapter.calls == 2:
                break
            await asyncio.sleep(0.01)
        assert adapter.calls == 2
        assert service.repository.get(second["id"])["state"] == "QUEUED"
        assert service.repository.get(foreground["id"])["state"] == "RUNNING"
        adapter.release.set()
        assert (await terminal(service, first["id"]))["state"] == "READY"
        assert (await terminal(service, foreground["id"]))["state"] == "READY"
        assert (await terminal(service, second["id"]))["state"] == "READY"
    finally:
        adapter.release.set()
        await service.shutdown()
