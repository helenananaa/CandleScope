from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from app.core import config as core_config
from app.data_engine.data_manager import DataManager
from app.data_engine.manual_history.models import CollectionStatus, JobState
from app.data_engine.manual_history.planner import ManualHistoryPlanner
from app.data_engine.manual_history.repository import ManualHistoryRepository
from app.data_engine.manual_history.service import ManualHistoryService
from app.data_engine.storage import klines_repo
from app.data_engine.storage.klines_repo import KlinesRepoAdapter
from tests.test_manual_history_planner import FakeResolver


START = 1_700_000_040_000
STEP = 60_000
BARS = 5


@pytest.mark.parametrize("blocked", [False, True])
def test_idle_runner_only_probes_storage_when_a_blocked_job_needs_recovery(blocked):
    async def scenario():
        probes = []
        transitions = []
        targets_reset = []
        service = None
        loop = asyncio.get_running_loop()

        def recoverable():
            # Runs on a storage thread. Exercise exactly one scheduler iteration.
            loop.call_soon_threadsafe(service._stop.set)
            return [SimpleNamespace(job_id="blocked", state=JobState.BLOCKED_STORAGE)] if blocked else []

        def pressure():
            probes.append(True)
            return {"level": "normal"}

        repository = SimpleNamespace(
            list_recoverable_jobs=recoverable,
            reset_recoverable_targets=targets_reset.append,
            cas_job_state=lambda job_id, **kwargs: transitions.append((job_id, kwargs)),
        )
        service = ManualHistoryService(
            repository=repository, data_manager=SimpleNamespace(),
            enabled=True, storage_pressure=pressure,
        )
        await service._run_loop()
        assert len(probes) == int(blocked)
        assert targets_reset == (["blocked"] if blocked else [])
        assert len(transitions) == int(blocked)
        if blocked:
            assert transitions[0][1]["to_state"] == JobState.QUEUED
    asyncio.run(scenario())


def _row(open_time: int) -> dict:
    return {
        "open_time": open_time,
        "close_time": open_time + STEP - 1,
        "open": 1.0,
        "high": 2.0,
        "low": 1.0,
        "close": 1.5,
        "volume": 1.0,
        "quote_volume": 1.5,
        "trades": 1,
        "taker_buy_base": 0.5,
        "taker_buy_quote": 0.75,
    }


def _plan(end_open: int = START + (BARS - 1) * STEP) -> dict:
    return {
        "can_start": True,
        "plan_hash": "sha256:phase4-native",
        "selection": {
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
            "requested_start_ms": START,
            "target_count": 1,
        },
        "targets": [{
            "symbol": "BTCUSDT",
            "requested_interval": "1m",
            "canonical_interval": "1m",
            "route_kind": "NATIVE",
            "source_interval": "1m",
            "effective_start_ms": START,
            "initial_end_open_ms": end_open,
            "source_strategy": "REST",
            "estimated_target_rows": BARS,
            "estimated_source_rows": BARS,
            "existing_coverage": "NONE",
            "error": None,
            "boundary_reason": None,
        }],
        "storage": {"estimated_db_growth_bytes": 1000, "estimated_temp_bytes": 100},
    }


def _setup(monkeypatch, tmp_path):
    db_path = tmp_path / "klines.db"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", db_path)
    monkeypatch.setattr(core_config, "KLINES_DB_PATH", db_path)
    klines_repo.init_klines_storage()
    repo = ManualHistoryRepository(db_path)
    dm = DataManager()
    dm.set_storage(KlinesRepoAdapter())
    return db_path, repo, dm


def _service(repo, dm, **kwargs):
    kwargs.setdefault("clock_ms", lambda: START + BARS * STEP)
    kwargs.setdefault("enabled", True)
    kwargs.setdefault("storage", KlinesRepoAdapter())
    return ManualHistoryService(repository=repo, data_manager=dm, **kwargs)


async def _write_range(*, start_ms: int, end_ms: int, skip: int | None = None, **_kwargs) -> int:
    rows = []
    open_time = start_ms
    while open_time <= end_ms:
        if skip is None or open_time != skip:
            rows.append(_row(open_time))
        open_time += STEP
    return klines_repo.upsert_klines(
        "BTCUSDT",
        "1m",
        rows,
        source="binance",
        exchange="binance",
        market_type="spot",
    )


@pytest.mark.anyio
async def test_native_job_seals_when_range_is_contiguous(monkeypatch, tmp_path) -> None:
    db_path, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(
        repo, dm,
        planner=ManualHistoryPlanner(resolver=FakeResolver()),
        fetch_native=_write_range,
    )
    created = service.create_from_plan(_plan(), idempotency_key="k1")
    result = await service.run_job(created.job.job_id)
    assert result.state.value == "SUCCEEDED"
    assert repo.get_collection(created.collection.collection_id).status is CollectionStatus.ACTIVE
    target = repo.list_job_targets(created.job.job_id)[0]
    assert target.state.value == "READY"
    verification = KlinesRepoAdapter().verify_contiguous_range(
        "BTCUSDT",
        "1m",
        START,
        START + (BARS - 1) * STEP,
        exchange="binance",
        market_type="spot",
    )
    assert verification["verified_contiguous"] is True
    floors = repo.active_protection_snapshot()
    assert len(floors) == 1
    assert floors[0].durable_owner_count == 1
    assert floors[0].protected_start_ms == START
    dm.reload_durable_protections()
    assert dm.durable_protections.floor_for(floors[0].key) is not None


@pytest.mark.anyio
async def test_gap_prevents_ready(monkeypatch, tmp_path) -> None:
    db_path, repo, dm = _setup(monkeypatch, tmp_path)

    async def write_with_gap(**kwargs) -> int:
        return await _write_range(skip=START + STEP, **kwargs)

    service = _service(repo, dm, fetch_native=write_with_gap)
    created = service.create_from_plan(_plan(), idempotency_key="gap")
    result = await service.run_job(created.job.job_id)
    assert result.state.value == "FAILED"
    assert repo.get_collection(created.collection.collection_id).status is CollectionStatus.PARTIAL
    assert repo.list_job_targets(created.job.job_id)[0].state.value == "FAILED"
    assert repo.active_protection_snapshot()[0].durable_owner_count == 0


@pytest.mark.anyio
async def test_duplicate_create_reuses_job(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(repo, dm, fetch_native=_write_range)
    first = service.create_from_plan(_plan(), idempotency_key="dup")
    second = service.create_from_plan(_plan(), idempotency_key="dup")
    assert second.reused_existing is True
    assert second.job.job_id == first.job.job_id


@pytest.mark.anyio
async def test_replay_does_not_corrupt_existing_contiguous_range(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(repo, dm, fetch_native=_write_range)
    created = service.create_from_plan(_plan(), idempotency_key="replay")
    await service.run_job(created.job.job_id)
    again = service.create_from_plan(_plan(), idempotency_key="replay-2")
    await service.run_job(again.job.job_id)
    verification = KlinesRepoAdapter().verify_contiguous_range(
        "BTCUSDT",
        "1m",
        START,
        START + (BARS - 1) * STEP,
        exchange="binance",
        market_type="spot",
    )
    assert verification["verified_contiguous"] is True
    rows = klines_repo.query_klines(
        "BTCUSDT", "1m", exchange="binance", market_type="spot"
    )
    assert len(rows) == BARS


@pytest.mark.anyio
async def test_native_fetch_marks_explicit_archive_demand(monkeypatch, tmp_path) -> None:
    captured: list[object] = []

    class _Coordinator:
        async def request_and_wait(self, request):
            captured.append(request)

    _, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(
        repo, dm,
        coordinator=_Coordinator(),
        fetch_native=None,
        verify_range=lambda *args, **kwargs: {
            "verified_contiguous": True,
            "expected_count": BARS,
            "actual_count": BARS,
        },
        enabled=True,
    )
    created = service.create_from_plan(_plan(), idempotency_key="explicit")
    await service.run_job(created.job.job_id)
    assert captured
    request = captured[0]
    assert request.reason == "manual_history_download"
    assert request.metadata["archive_explicit_demand"] is True
    assert request.metadata["requires_trusted_finality"] is True


@pytest.mark.anyio
async def test_shared_source_is_fetched_once_for_native_and_derived(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, str]] = []
    aligned = 318_353 * 89 * 60_000
    source_end = aligned + 88 * 60_000

    async def write_counted(*, symbol: str, interval: str, start_ms: int, end_ms: int, **kwargs) -> int:
        calls.append((symbol, interval))
        rows = []
        open_time = start_ms
        while open_time <= end_ms:
            rows.append(_row(open_time))
            open_time += STEP
        return klines_repo.upsert_klines(
            symbol,
            interval,
            rows,
            source="binance",
            exchange="binance",
            market_type="spot",
        )

    _, repo, dm = _setup(monkeypatch, tmp_path)
    plan = {
        "can_start": True,
        "plan_hash": "sha256:phase6-shared",
        "selection": {
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT"],
            "intervals": ["1m", "89m"],
            "requested_start_ms": aligned,
            "target_count": 2,
        },
        "targets": [
            {
                "symbol": "BTCUSDT",
                "requested_interval": "1m",
                "canonical_interval": "1m",
                "route_kind": "NATIVE",
                "source_interval": "1m",
                "effective_start_ms": aligned,
                "initial_end_open_ms": source_end,
                "source_strategy": "REST",
                "estimated_target_rows": 89,
                "estimated_source_rows": 89,
                "existing_coverage": "NONE",
                "error": None,
                "boundary_reason": None,
            },
            {
                "symbol": "BTCUSDT",
                "requested_interval": "89m",
                "canonical_interval": "89m",
                "route_kind": "DERIVED",
                "source_interval": "1m",
                "effective_start_ms": aligned,
                "initial_end_open_ms": aligned,
                "source_strategy": "REST",
                "estimated_target_rows": 1,
                "estimated_source_rows": 89,
                "existing_coverage": "NONE",
                "error": None,
                "boundary_reason": None,
            },
        ],
        "storage": {},
    }
    service = _service(repo, dm, fetch_native=write_counted)
    created = service.create_from_plan(plan, idempotency_key="shared-1m")
    result = await service.run_job(created.job.job_id)
    assert result.state.value in {"SUCCEEDED", "PARTIAL"}
    assert calls == [("BTCUSDT", "1m")]
    states = {item.canonical_interval: item.state.value for item in repo.list_job_targets(created.job.job_id)}
    assert states["1m"] == "READY"


@pytest.mark.anyio
async def test_cancel_queued_job_is_cancelled(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(repo, dm, fetch_native=_write_range)
    created = service.create_from_plan(_plan(), idempotency_key="cancel-q")
    cancelled = await service.cancel_job(created.job.job_id)
    assert cancelled.state.value == "CANCELLED"
    assert repo.list_job_targets(created.job.job_id)[0].state.value == "CANCELLED"
    assert repo.active_protection_snapshot() == ()


@pytest.mark.anyio
async def test_cancel_active_job_waits_for_physical_fetch_to_be_inert(monkeypatch, tmp_path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def held_fetch(**_kwargs) -> int:
        started.set()
        await release.wait()
        return 0

    _, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(repo, dm, fetch_native=held_fetch)
    created = service.create_from_plan(_plan(), idempotency_key="cancel-active")
    running = asyncio.create_task(service.run_job(created.job.job_id))
    await started.wait()
    cancelling = await service.cancel_job(created.job.job_id)
    assert cancelling.state.value == "CANCELLING"
    assert repo.list_job_targets(created.job.job_id)[0].state.value == "FETCHING"
    release.set()
    cancelled = await running
    assert cancelled.state.value == "CANCELLED"
    assert repo.active_protection_snapshot() == ()


@pytest.mark.anyio
async def test_recover_running_job_requeues(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(repo, dm, fetch_native=_write_range)
    created = service.create_from_plan(_plan(), idempotency_key="recover-1")
    repo.cas_job_state(
        created.job.job_id,
        from_state=created.job.state,
        to_state=JobState.RUNNING,
        stage="fetching",
    )
    recovered = service.recover_jobs()
    assert recovered[0].state.value == "QUEUED"
    assert recovered[0].recovery_count == 1


@pytest.mark.anyio
async def test_blocked_storage_when_disk_is_critical(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(repo, dm, fetch_native=_write_range)
    service._disk_free_bytes = lambda: 0
    created = service.create_from_plan(_plan(), idempotency_key="disk-0")
    result = await service.run_job(created.job.job_id)
    assert result.state.value == "BLOCKED_STORAGE"


@pytest.mark.anyio
async def test_blocked_storage_requeues_after_pressure_recovers(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    pressure = {"level": "critical", "disk_free_critical": False}
    service = _service(
        repo,
        dm,
        fetch_native=_write_range,
        storage_pressure=lambda: pressure,
    )
    created = service.create_from_plan(_plan(), idempotency_key="disk-recover")
    blocked = await service.run_job(created.job.job_id)
    assert blocked.state.value == "BLOCKED_STORAGE"
    pressure["level"] = "normal"
    recovered = service.recover_jobs()
    assert recovered[0].state.value == "QUEUED"
    assert repo.list_job_targets(created.job.job_id)[0].state.value == "QUEUED"
    completed = await service.run_job(created.job.job_id)
    assert completed.state.value == "SUCCEEDED"


@pytest.mark.anyio
async def test_derived_materialization_reads_source_in_bounded_pages(monkeypatch, tmp_path) -> None:
    aligned = (START // (2 * STEP)) * (2 * STEP)
    source_rows = 6_000
    final_source_open = aligned + (source_rows - 1) * STEP
    final_target_open = aligned + (source_rows - 2) * STEP

    async def write_source(*, symbol: str, interval: str, start_ms: int, end_ms: int, **_kwargs) -> int:
        return klines_repo.upsert_klines(
            symbol,
            interval,
            [_row(open_time) for open_time in range(start_ms, end_ms + 1, STEP)],
            source="binance",
            exchange="binance",
            market_type="spot",
        )

    _, repo, dm = _setup(monkeypatch, tmp_path)
    original_query = klines_repo.query_klines
    limits: list[int | None] = []

    def recording_query(*args, **kwargs):
        limits.append(kwargs.get("limit"))
        return original_query(*args, **kwargs)

    monkeypatch.setattr(klines_repo, "query_klines", recording_query)
    plan = {
        "can_start": True,
        "plan_hash": "sha256:paged-derived",
        "selection": {
            "exchange": "binance",
            "market_type": "spot",
            "symbols": ["BTCUSDT"],
            "intervals": ["2m"],
            "requested_start_ms": aligned,
            "target_count": 1,
        },
        "targets": [{
            "symbol": "BTCUSDT",
            "requested_interval": "2m",
            "canonical_interval": "2m",
            "route_kind": "DERIVED",
            "source_interval": "1m",
            "effective_start_ms": aligned,
            "initial_end_open_ms": final_target_open,
            "source_strategy": "REST",
            "estimated_target_rows": source_rows // 2,
            "estimated_source_rows": source_rows,
            "existing_coverage": "NONE",
            "error": None,
            "boundary_reason": None,
        }],
        "storage": {},
    }
    service = _service(
        repo,
        dm,
        fetch_native=write_source,
        clock_ms=lambda: final_source_open + STEP,
    )
    created = service.create_from_plan(plan, idempotency_key="paged-derived")
    completed = await service.run_job(created.job.job_id)
    assert completed.state.value == "SUCCEEDED"
    assert limits.count(5_000) >= 2
    derived_rows = original_query(
        "BTCUSDT",
        "2m",
        exchange="binance",
        market_type="spot",
    )
    assert len(derived_rows) == source_rows // 2


@pytest.mark.anyio
async def test_feature_flag_off_keeps_durable_floor(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(repo, dm, fetch_native=_write_range)
    created = service.create_from_plan(_plan(), idempotency_key="flag-off-floor")
    await service.run_job(created.job.job_id)
    service.enabled = False
    dm.reload_durable_protections()
    floors = dm.durable_protections.clone()
    assert floors
    collections = repo.list_collections()
    assert collections[0].collection_id == created.collection.collection_id


@pytest.mark.anyio
async def test_seal_recomputes_last_closed_and_fills_tail(monkeypatch, tmp_path) -> None:
    calls: list[tuple[int, int]] = []

    async def write_counted(*, start_ms: int, end_ms: int, **kwargs) -> int:
        calls.append((start_ms, end_ms))
        return await _write_range(start_ms=start_ms, end_ms=end_ms, **kwargs)

    _, repo, dm = _setup(monkeypatch, tmp_path)
    ticks = {"n": 0}

    def clock_ms() -> int:
        ticks["n"] += 1
        if ticks["n"] <= 1:
            return START + BARS * STEP
        return START + (BARS + 1) * STEP

    extra_end = START + BARS * STEP
    service = _service(repo, dm, fetch_native=write_counted, clock_ms=clock_ms)
    created = service.create_from_plan(_plan(), idempotency_key="tail")
    result = await service.run_job(created.job.job_id)
    assert result.state.value == "SUCCEEDED"
    assert calls[0] == (START, START + (BARS - 1) * STEP)
    assert calls[-1] == (extra_end, extra_end)
    target = repo.list_job_targets(created.job.job_id)[0]
    assert target.sealed_end_open_ms == extra_end
    verification = KlinesRepoAdapter().verify_contiguous_range(
        "BTCUSDT",
        "1m",
        START,
        extra_end,
        exchange="binance",
        market_type="spot",
    )
    assert verification["verified_contiguous"] is True


_SETTLED = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.PARTIAL}


async def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.01)


class _LoopThreadProbe:
    """Repository proxy that records the methods called on the event loop thread."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.loop_thread: int | None = None
        self.loop_calls: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            if threading.get_ident() == self.loop_thread:
                self.loop_calls.append(name)
            return attr(*args, **kwargs)

        return call


def _derived_plan(aligned: int, final_target_open: int) -> dict:
    plan = _plan()
    plan["plan_hash"] = "sha256:off-loop-derived"
    plan["selection"] = {**plan["selection"], "intervals": ["2m"], "requested_start_ms": aligned}
    plan["targets"] = [{
        **plan["targets"][0],
        "requested_interval": "2m",
        "canonical_interval": "2m",
        "route_kind": "DERIVED",
        "effective_start_ms": aligned,
        "initial_end_open_ms": final_target_open,
    }]
    return plan


@pytest.mark.anyio
async def test_runner_settles_cancelling_then_blocked_then_queued(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    service = _service(
        repo, dm,
        fetch_native=_write_range,
        storage_pressure=lambda: {"level": "normal"},
        idle_poll_seconds=60,
    )
    await service.start()
    # Nothing awaits until all three exist, so the runner's first scan sees
    # them together. The queued job is the oldest and must still go last.
    queued = service.create_from_plan(_plan(), idempotency_key="order-queued").job.job_id
    blocked = service.create_from_plan(_plan(), idempotency_key="order-blocked").job.job_id
    cancelling = service.create_from_plan(_plan(), idempotency_key="order-cancelling").job.job_id
    repo.cas_job_state(
        blocked, from_state=JobState.QUEUED, to_state=JobState.BLOCKED_STORAGE, stage="blocked_storage"
    )
    repo.cas_job_state(
        cancelling, from_state=JobState.QUEUED, to_state=JobState.CANCELLING, stage="cancelling"
    )
    events: list[tuple[str, str]] = []
    cas, finalize = repo.cas_job_state, repo.finalize_job_cancellation

    def recording_cas(job_id, **kwargs):
        events.append((job_id, kwargs["to_state"].value))
        return cas(job_id, **kwargs)

    def recording_finalize(job_id):
        events.append((job_id, "finalized"))
        return finalize(job_id)

    monkeypatch.setattr(repo, "cas_job_state", recording_cas)
    monkeypatch.setattr(repo, "finalize_job_cancellation", recording_finalize)
    try:
        await _wait_until(
            lambda: all(repo.get_job(job).state in _SETTLED for job in (queued, blocked, cancelling))
        )
    finally:
        await service.stop()
    assert events[:3] == [(cancelling, "finalized"), (blocked, "QUEUED"), (queued, "RUNNING")]
    assert repo.get_job(cancelling).state is JobState.CANCELLED
    assert repo.get_job(queued).state is JobState.SUCCEEDED
    assert repo.get_job(blocked).state is JobState.SUCCEEDED


@pytest.mark.anyio
async def test_stop_drains_an_in_flight_scan_and_runs_nothing_after_it(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    fetches: list[dict] = []

    async def fetch(**kwargs) -> int:
        fetches.append(kwargs)
        return 0

    service = _service(repo, dm, fetch_native=fetch, idle_poll_seconds=60)
    await service.start()
    entered, release = threading.Event(), threading.Event()
    list_jobs = repo.list_recoverable_jobs

    def gated_list():
        entered.set()
        assert release.wait(5)
        return list_jobs()

    monkeypatch.setattr(repo, "list_recoverable_jobs", gated_list)
    created = service.create_from_plan(_plan(), idempotency_key="stop-drain")
    assert await asyncio.to_thread(entered.wait, 5)
    stopping = asyncio.create_task(service.stop())
    await asyncio.sleep(0.1)
    # The storage thread is mid-read: stop waits for it rather than abandoning it.
    assert not stopping.done()
    release.set()
    await asyncio.wait_for(stopping, 5)
    # The scan saw the queued job, but cancellation won: nothing ran.
    assert fetches == []
    assert repo.get_job(created.job.job_id).state is JobState.QUEUED


@pytest.mark.anyio
async def test_enqueue_wakes_an_idle_runner_instead_of_a_fast_poll(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    scans: list[float] = []
    list_jobs = repo.list_recoverable_jobs

    def counting_list():
        scans.append(time.monotonic())
        return list_jobs()

    monkeypatch.setattr(repo, "list_recoverable_jobs", counting_list)
    service = _service(repo, dm, fetch_native=_write_range, idle_poll_seconds=60)
    await service.start()
    await _wait_until(lambda: len(scans) >= 2)  # startup recovery, then the first scan
    await asyncio.sleep(0.3)
    assert len(scans) == 2
    created = service.create_from_plan(_plan(), idempotency_key="wake")
    await _wait_until(lambda: repo.get_job(created.job.job_id).state is JobState.SUCCEEDED, timeout=5)
    started = time.monotonic()
    await service.stop()
    assert time.monotonic() - started < 1.0


@pytest.mark.anyio
async def test_fallback_poll_requeues_a_blocked_job_once_pressure_clears(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    pressure = {"level": "critical"}
    service = _service(
        repo, dm,
        fetch_native=_write_range,
        storage_pressure=lambda: dict(pressure),
        idle_poll_seconds=0.05,
    )
    job_id = service.create_from_plan(_plan(), idempotency_key="fallback").job.job_id
    await service.start()
    try:
        await _wait_until(lambda: repo.get_job(job_id).state is JobState.BLOCKED_STORAGE)
        await asyncio.sleep(0.25)  # several fallback scans while pressure holds
        assert repo.get_job(job_id).state is JobState.BLOCKED_STORAGE
        pressure["level"] = "normal"  # no event announces this; the fallback poll must
        await _wait_until(lambda: repo.get_job(job_id).state is JobState.SUCCEEDED)
    finally:
        await service.stop()


@pytest.mark.anyio
async def test_storage_block_yields_to_a_cancel_that_landed_first(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    job_id = ""

    def pressure():
        # A cancel commits after the job's cancel check, then pressure goes
        # critical: CANCELLING cannot move to BLOCKED_STORAGE, so cancel wins.
        if repo.get_job(job_id).state is JobState.RUNNING:
            repo.cas_job_state(
                job_id, from_state=JobState.RUNNING, to_state=JobState.CANCELLING, stage="cancelling"
            )
            return {"level": "critical"}
        return {"level": "normal"}

    service = _service(repo, dm, fetch_native=_write_range, storage_pressure=pressure)
    job_id = service.create_from_plan(_plan(), idempotency_key="block-vs-cancel").job.job_id
    result = await service.run_job(job_id)
    assert result.state is JobState.CANCELLED
    assert repo.list_job_targets(job_id)[0].state.value == "CANCELLED"


@pytest.mark.anyio
@pytest.mark.parametrize("route", ["native", "derived"])
async def test_job_keeps_sqlite_off_the_event_loop(monkeypatch, tmp_path, route) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    loop_thread = threading.get_ident()
    probe = _LoopThreadProbe(repo)
    storage_calls: list[tuple[str, bool]] = []
    adapter = KlinesRepoAdapter()
    original_query = klines_repo.query_klines

    def verify(*args, **kwargs):
        storage_calls.append(("verify_range", threading.get_ident() == loop_thread))
        return adapter.verify_contiguous_range(*args, **kwargs)

    def query(*args, **kwargs):
        storage_calls.append(("query_klines", threading.get_ident() == loop_thread))
        return original_query(*args, **kwargs)

    monkeypatch.setattr(klines_repo, "query_klines", query)
    if route == "native":
        plan, clock = _plan(), START + BARS * STEP
    else:
        aligned = (START // (2 * STEP)) * (2 * STEP)
        plan, clock = _derived_plan(aligned, aligned + 8 * STEP), aligned + 10 * STEP
    service = _service(
        probe, dm, fetch_native=_write_range, verify_range=verify, clock_ms=lambda: clock
    )
    created = service.create_from_plan(plan, idempotency_key=f"off-loop-{route}")
    probe.loop_thread = loop_thread
    result = await service.run_job(created.job.job_id)
    assert result.state is JobState.SUCCEEDED
    assert probe.loop_calls == []
    assert storage_calls and not any(on_loop for _, on_loop in storage_calls)
    if route == "derived":
        assert ("query_klines", False) in storage_calls


@pytest.mark.anyio
async def test_runner_lifecycle_and_cancel_keep_sqlite_off_the_event_loop(monkeypatch, tmp_path) -> None:
    _, repo, dm = _setup(monkeypatch, tmp_path)
    probe = _LoopThreadProbe(repo)
    service = _service(probe, dm, fetch_native=_write_range, idle_poll_seconds=60)
    cancelled = service.create_from_plan(_plan(), idempotency_key="lifecycle-cancel").job.job_id
    blocked = service.create_from_plan(_plan(), idempotency_key="lifecycle-blocked").job.job_id
    repo.cas_job_state(
        blocked, from_state=JobState.QUEUED, to_state=JobState.BLOCKED_STORAGE, stage="blocked_storage"
    )
    probe.loop_thread = threading.get_ident()
    assert (await service.cancel_job(cancelled)).state is JobState.CANCELLED
    await service.start()  # recovery requeues the blocked job; the runner then completes it
    try:
        await _wait_until(lambda: repo.get_job(blocked).state is JobState.SUCCEEDED)
    finally:
        await service.stop()
    assert probe.loop_calls == []
