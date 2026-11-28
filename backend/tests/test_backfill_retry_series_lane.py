"""RC 32: a chart's retry backoff keeps its series lane from background imports.

Go to date before a listing (Binance spot BTCUSDT 1m, 2017-08-17 02:00) proves
the pre-listing minutes absent by seeing the same empty page twice
(``promote_after=2``), with a retry backoff between the attempts. The scheduler
runs one chunk per series, and a backoff hands the lane back. In the RC a
background gap audit for the same series started a monthly archive import in
that gap (61 s, every batch rejected by the family check), so the confirmation
queued behind it and the jump gave up after its 60 s budget.

These tests drive the real coordinator and scheduler with a fake engine. The
archive import runs on its own thread, as a storage writer would, and holds
the lane until the test releases it.
"""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from app.data_engine.data_manager.backfill_coordinator import (
    BackfillCoordinator,
    RepairRequest,
)
from app.data_engine.history import (
    AlwaysOpenCalendar,
    BoundaryState,
    HistoryAvailability,
    HistoryAvailabilityService,
    HistoryBoundaryRepository,
    HistorySeriesKey,
)
from app.exchanges import HistoryAvailabilityPolicy, HistoryEmptyPageSemantics

MINUTE = 60_000
LISTED_AT = 120 * MINUTE
# The jump window ends before the listing so its whole range is the gap to prove.
PRE_LISTING = (LISTED_AT - 10 * MINUTE, LISTED_AT - MINUTE)
# Later history the gap audit fills from an archive object.
ARCHIVE = (LISTED_AT + 1_000 * MINUTE, LISTED_AT + 1_001 * MINUTE)
BACKOFF_SECONDS = 0.2
# Generous: the assertions are about order, and a loaded machine can stall threads.
TIMEOUT_SECONDS = 10.0


async def _ignore(*args, **kwargs) -> None:
    return None


def _report(*, source_complete: bool) -> SimpleNamespace:
    return SimpleNamespace(
        status="completed",
        errors=[],
        reconcile_result=SimpleNamespace(bars_written=0, custom_bars_written=0),
        fetch_results=[SimpleNamespace(
            source_complete=source_complete,
            retryable=False,
            exhausted_before_ms=None,
        )],
    )


class _Storage:
    """Stored bars start at the listing; the archive range is already written."""

    def __init__(self) -> None:
        self.rows = [
            {"open_time": open_time, "source": "backfill_archive_verified"}
            for open_time in (LISTED_AT, *range(ARCHIVE[0], ARCHIVE[1] + 1, MINUTE))
        ]

    def get_bounds(self, *args, **kwargs) -> dict:
        return {"earliest_open_time": LISTED_AT, "latest_open_time": ARCHIVE[1], "total_count": len(self.rows)}

    def query_bars(self, **kwargs) -> list[dict]:
        start_ms, end_ms = int(kwargs["start_ms"]), int(kwargs["end_ms"])
        return [row for row in self.rows if start_ms <= row["open_time"] <= end_ms]


class _Engine:
    """Empty pages before the listing; a blocking archive import for the audit."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.listing_attempts = 0
        self.import_started = asyncio.Event()
        self.release_import = threading.Event()
        self.order: list[str] = []
        # Optional hold on the first pre-listing page, so the test can queue
        # other work while that attempt still owns the series lane.
        self.first_listing_page = asyncio.Event()
        self.continue_first_listing: asyncio.Event | None = None

    async def run(self, **kwargs):
        if kwargs["metadata"]["reason"] == "background_gap_audit":
            self.order.append("archive")
            done = self.loop.create_future()

            def import_archive() -> None:
                # Not on the coordinator's task: a real import takes the
                # storage writer on its own thread for the whole object.
                try:
                    self.loop.call_soon_threadsafe(self.import_started.set)
                    self.release_import.wait(timeout=TIMEOUT_SECONDS * 3)
                finally:
                    self.loop.call_soon_threadsafe(lambda: done.done() or done.set_result(None))

            threading.Thread(target=import_archive, name="archive-import", daemon=True).start()
            await done
            return _report(source_complete=False)
        self.listing_attempts += 1
        self.order.append(f"listing-{self.listing_attempts}")
        if self.listing_attempts == 1:
            self.first_listing_page.set()
            if self.continue_first_listing is not None:
                await self.continue_first_listing.wait()
        return _report(source_complete=True)


def _coordinator(tmp_path, engine: _Engine) -> tuple[BackfillCoordinator, HistoryAvailabilityService]:
    calendar = AlwaysOpenCalendar()
    service = HistoryAvailabilityService(
        boundaries=HistoryBoundaryRepository(tmp_path / "history.sqlite3"),
    )
    policy = HistoryAvailabilityPolicy(
        empty_page_semantics=HistoryEmptyPageSemantics.AUTHORITATIVE_RANGE_EMPTY,
        calendar_id=calendar.calendar_id,
    )
    context = SimpleNamespace(
        availability=HistoryAvailability(calendar_id=calendar.calendar_id, revision="cap-v1"),
        calendar=calendar,
        policy=policy,
        empty_page_semantics=HistoryEmptyPageSemantics.AUTHORITATIVE_RANGE_EMPTY,
    )
    coordinator = BackfillCoordinator(
        storage=_Storage(),
        bars_backfilled=_ignore,
        emit_event=_ignore,
        engine=engine,
        loop=asyncio.get_running_loop(),
        base_delay_seconds=BACKOFF_SECONDS,
        history_service=service,
        history_policy_resolver=lambda request: context,
    )
    return coordinator, service


def _request(
    range_ms: tuple[int, int], *, request_id: str, reason: str, priority: int, symbol: str = "BTCUSDT",
) -> RepairRequest:
    return RepairRequest(
        symbol=symbol,
        interval="1m",
        start_ms=range_ms[0],
        end_ms=range_ms[1],
        exchange="binance",
        market_type="spot",
        reason=reason,
        priority=priority,
        request_id=request_id,
        requester="klines_range" if reason == "visible_range_gap" else "background_audit",
    )


async def _until(predicate, *, timeout: float = TIMEOUT_SECONDS) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def test_pre_listing_confirmation_does_not_queue_behind_a_background_archive_import(tmp_path) -> None:
    async def _run() -> None:
        engine = _Engine(asyncio.get_running_loop())
        engine.continue_first_listing = asyncio.Event()
        coordinator, service = _coordinator(tmp_path, engine)
        listing = asyncio.create_task(coordinator.request_and_wait(_request(
            PRE_LISTING, request_id="go-to-date", reason="visible_range_gap", priority=20,
        )))
        await asyncio.wait_for(engine.first_listing_page.wait(), timeout=TIMEOUT_SECONDS)
        # While the chart's first attempt runs, the gap audit asks for later
        # history on the same series. It queues: the lane is taken.
        audit = asyncio.create_task(coordinator.request_and_wait(_request(
            ARCHIVE, request_id="gap-audit", reason="background_gap_audit", priority=160,
        )))
        await _until(lambda: coordinator.progress_for_request("gap-audit") is not None)
        assert engine.order == ["listing-1"]
        # The first empty page is only a candidate boundary, so the chart's
        # request backs off and hands the lane back.
        engine.continue_first_listing.set()
        try:
            # The confirmation finishes while the archive import has not been released.
            outcome = await asyncio.wait_for(asyncio.shield(listing), timeout=TIMEOUT_SECONDS)
            assert outcome.terminal_reason == "provider_exhausted"
            assert outcome.retryable is False
            assert engine.listing_attempts == 2
            assert not engine.release_import.is_set()
            boundary = service.get_boundary(
                HistorySeriesKey("binance", "spot", "BTCUSDT", "kline", "1m"), "left", include_stale=True,
            )
            assert boundary is not None and boundary.bound.state is BoundaryState.CONFIRMED
            assert boundary.bound.value_ms == LISTED_AT
            # The audit is only delayed: it takes the lane once the chart's request is done.
            await asyncio.wait_for(engine.import_started.wait(), timeout=TIMEOUT_SECONDS)
            assert engine.order == ["listing-1", "listing-2", "archive"]
            assert coordinator.snapshot()["retry_lane_skips"] >= 1
        finally:
            engine.release_import.set()
        audit_outcome = await asyncio.wait_for(audit, timeout=TIMEOUT_SECONDS)
        assert audit_outcome.status == "completed"
        await coordinator.shutdown()

    asyncio.run(_run())


def test_a_running_background_import_still_finishes_before_the_chart_retry(tmp_path) -> None:
    """The lane is not preempted: work that already holds it keeps it."""

    async def _run() -> None:
        engine = _Engine(asyncio.get_running_loop())
        coordinator, _service = _coordinator(tmp_path, engine)
        audit = asyncio.create_task(coordinator.request_and_wait(_request(
            ARCHIVE, request_id="gap-audit", reason="background_gap_audit", priority=160,
        )))
        await asyncio.wait_for(engine.import_started.wait(), timeout=TIMEOUT_SECONDS)
        listing = asyncio.create_task(coordinator.request_and_wait(_request(
            PRE_LISTING, request_id="go-to-date", reason="visible_range_gap", priority=20,
        )))
        await asyncio.sleep(BACKOFF_SECONDS)
        assert engine.listing_attempts == 0
        engine.release_import.set()
        outcome = await asyncio.wait_for(listing, timeout=TIMEOUT_SECONDS)
        assert outcome.terminal_reason == "provider_exhausted"
        assert engine.order == ["archive", "listing-1", "listing-2"]
        await asyncio.wait_for(audit, timeout=TIMEOUT_SECONDS)
        await coordinator.shutdown()

    asyncio.run(_run())


def test_background_work_on_another_series_runs_during_the_backoff(tmp_path) -> None:
    """Only the retrying request's own series waits; the scheduler stays busy."""

    async def _run() -> None:
        engine = _Engine(asyncio.get_running_loop())
        engine.continue_first_listing = asyncio.Event()
        coordinator, _service = _coordinator(tmp_path, engine)
        listing = asyncio.create_task(coordinator.request_and_wait(_request(
            PRE_LISTING, request_id="go-to-date", reason="visible_range_gap", priority=20,
        )))
        await asyncio.wait_for(engine.first_listing_page.wait(), timeout=TIMEOUT_SECONDS)
        audit = asyncio.create_task(coordinator.request_and_wait(_request(
            ARCHIVE, request_id="gap-audit", reason="background_gap_audit", priority=160, symbol="ETHUSDT",
        )))
        engine.continue_first_listing.set()
        try:
            await asyncio.wait_for(engine.import_started.wait(), timeout=TIMEOUT_SECONDS)
            assert not listing.done()
            outcome = await asyncio.wait_for(asyncio.shield(listing), timeout=TIMEOUT_SECONDS)
            assert outcome.terminal_reason == "provider_exhausted"
            assert engine.order == ["listing-1", "archive", "listing-2"]
            assert coordinator.snapshot()["retry_lane_skips"] == 0
        finally:
            engine.release_import.set()
        await asyncio.wait_for(audit, timeout=TIMEOUT_SECONDS)
        await coordinator.shutdown()

    asyncio.run(_run())
