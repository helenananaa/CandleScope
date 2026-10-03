from __future__ import annotations

import asyncio
from enum import Enum
from pathlib import Path
import subprocess
import sys

from app.data_engine.data_manager.backfill_contracts import RepairOutcome, RepairRequest
from app.data_engine.data_manager.backfill_history import BackfillHistoryPlanner
from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
from app.data_engine.history.models import BoundaryReason


def test_backfill_contracts_and_components_import_without_coordinator() -> None:
    # A clean interpreter also checks eager parent package imports. Inspecting
    # this test process would miss imports already performed by other tests.
    result = subprocess.run(
        [sys.executable, "-B", "-c", """
import sys
from app.data_engine.data_manager.backfill_contracts import RepairRequest
assert 'app.data_engine.data_manager.backfill_coordinator' not in sys.modules
assert 'app.data_engine.data_manager.backfill_scheduler' not in sys.modules
assert 'app.data_engine.data_manager.backfill_history' not in sys.modules
from app.data_engine.data_manager.backfill_history import BackfillHistoryPlanner
from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
assert 'app.data_engine.data_manager.backfill_coordinator' not in sys.modules
"""],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_coordinator_imports_reexport_the_same_contracts() -> None:
    from app.data_engine.data_manager import backfill_contracts, backfill_coordinator

    for name in (
        "BACKFILL_REASON_PRIORITIES", "HistoryPolicyResolver",
        "LedgerReconciliationReport", "RepairOutcome", "RepairRequest",
        "RepairReconcileSummary", "RepairReportSummary",
        "RepairWrittenRangeSummary", "ScanReport", "priority_for_reason",
    ):
        assert getattr(backfill_coordinator, name) is getattr(backfill_contracts, name)


def test_standalone_scheduler_keeps_deduped_waiters_until_finalization() -> None:
    class Status(Enum):
        COMPLETED = "completed"

    async def run() -> None:
        futures = {}
        events = []
        finalizing = asyncio.Event()
        finish_finalizing = asyncio.Event()

        def future_for(request):
            if request.request_id not in futures:
                futures[request.request_id] = asyncio.get_running_loop().create_future()
            return futures[request.request_id]

        async def execute(request):
            events.append("execute")
            return RepairOutcome(request=request, status=Status.COMPLETED, bars_loaded=1)

        async def finalize(request, outcome):
            events.append("finalize_started")
            finalizing.set()
            await finish_finalizing.wait()
            events.append("finalized")

        def complete(request, outcome):
            events.append("complete")
            future_for(request).set_result(outcome)

        scheduler = BackfillScheduler(
            execute=execute,
            future_for=future_for,
            finalize=finalize,
            complete=complete,
            on_queued=lambda request: events.append("queued"),
        )
        try:
            canonical_id, future = scheduler.submit(RepairRequest(
                symbol="BTCUSDT", interval="1m", start_ms=0, end_ms=0,
                request_id="original",
            ))
            await asyncio.wait_for(finalizing.wait(), timeout=1)
            assert not future.done()
            deduped_id, deduped_future = scheduler.submit(RepairRequest(
                symbol="BTCUSDT", interval="1m", start_ms=0, end_ms=0,
                request_id="duplicate",
            ))
            assert deduped_id == canonical_id
            assert deduped_future is future
            finish_finalizing.set()
            outcome = await asyncio.wait_for(future, timeout=1)
            assert outcome.bars_loaded == 1
            assert events == ["queued", "execute", "finalize_started", "finalized", "complete"]
            assert scheduler.snapshot()["recent_outcomes"][canonical_id]["status"] == "completed"
        finally:
            finish_finalizing.set()
            await scheduler.shutdown()

    asyncio.run(run())


def test_standalone_history_planner_preserves_closed_bar_admission(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.data_engine.data_manager.backfill_history.time.time", lambda: 150,
    )
    planner = BackfillHistoryPlanner()
    request = RepairRequest(
        symbol="BTCUSDT", interval="1m", start_ms=60_000, end_ms=120_000,
        request_id="closed-and-forming",
    )
    prepared = planner.prepare(request)
    assert prepared.request is not None
    assert prepared.request.request_id == request.request_id
    assert (prepared.request.start_ms, prepared.request.end_ms) == (60_000, 60_000)
    assert request.end_ms == 120_000

    forming = RepairRequest(symbol="BTCUSDT", interval="1m", start_ms=120_000, end_ms=120_000)
    no_fetch = planner.prepare(forming)
    assert no_fetch.request is None
    outcome = planner.no_fetch_outcome(forming, no_fetch.plan)
    assert outcome.terminal_reason == BoundaryReason.FORMING_BAR.value
    assert outcome.retryable is False
