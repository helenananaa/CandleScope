import asyncio
from types import SimpleNamespace

from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from tests.test_data_preparation import Adapter, async_test, request, terminal


def test_adapter_reports_only_current_rate_limit_without_provider_internal_details(tmp_path):
    snapshot = {"status": "rate_limit_deferred", "retry_at_ms": 2000, "rate_limit_bucket": "private-detail"}
    adapter = BarPreparationAdapter(tmp_path, coordinator=SimpleNamespace(progress_for_request=lambda _: snapshot), now_ms=lambda: 1000)
    adapter._repair_requests["key"] = "request"
    assert adapter.acquisition_waiting("key") == {"reason": "RATE_LIMIT", "retry_at_ms": 2000}
    snapshot["retry_at_ms"] = 900
    assert adapter.acquisition_waiting("key") is None
    snapshot.update(status="running", retry_at_ms=2000)
    assert adapter.acquisition_waiting("key") is None
    assert adapter.acquisition_waiting("unrelated") is None


@async_test
async def test_shared_wait_is_persisted_without_retrying_or_losing_cancel_isolation(tmp_path):
    adapter = Adapter()
    waiting = {"reason": "RATE_LIMIT", "retry_at_ms": 9_999_999_999_999}
    adapter.acquisition_waiting = lambda _: waiting
    repo = PreparationRepository(tmp_path / "jobs.db")
    service = PreparationService(repo, adapter)
    await service.start()
    try:
        # Use foreground consumers so both observers can occupy a worker.
        first = await service.submit(request().model_copy(update={"consumer": "STRATEGY"}))
        second = await service.submit(request("second-request").model_copy(update={"consumer": "STRATEGY"}))
        async def both_waiting():
            while any(repo.get(job["id"])["waiting"] != waiting for job in (first, second)):
                await asyncio.sleep(.02)
        await asyncio.wait_for(both_waiting(), 3)
        assert adapter.calls == 1
        assert PreparationRepository(repo.path).get(second["id"])["waiting"] == waiting
        revision = repo.get(second["id"])["revision"]
        repo.set_waiting(second["id"], waiting)
        assert repo.get(second["id"])["revision"] == revision
        await service.cancel(first["id"])
        cancelled = await terminal(service, first["id"])
        assert cancelled["state"] == "CANCELLED" and cancelled["waiting"] is None
        assert repo.get(second["id"])["waiting"] == waiting
        adapter.release.set()
        ready = await terminal(service, second["id"])
        assert ready["state"] == "READY" and ready["waiting"] is None
        assert adapter.calls == 1
    finally:
        adapter.release.set()
        await service.shutdown()


def test_restart_clears_stale_wait_until_coordinator_reconfirms(tmp_path):
    repo = PreparationRepository(tmp_path / "jobs.db")
    job = repo.create(request(), 1)
    repo.update(job["id"], state="RUNNING")
    repo.set_waiting(job["id"], {"reason": "RATE_LIMIT", "retry_at_ms": 5000})
    repo.recover()
    assert repo.get(job["id"])["waiting"] is None
