"""What the backend does differently in a browser tab, where every page load
is a cold start (``sys.platform == "emscripten"``)."""
from __future__ import annotations

import asyncio
import sys
import time
from enum import Enum

import pytest

from app.data_engine.data_manager.backfill_contracts import RepairOutcome, RepairRequest
from app.data_engine.data_manager.backfill_scheduler import BackfillScheduler
from app.exchanges.public_ws import connection_rules
from app.exchanges.rate_limits import RateLimitAdmission, RateLimitDeferred


def test_browser_tab_opens_binance_sockets_without_spacing(monkeypatch) -> None:
    native = [rule.name for rule in connection_rules("binance", None)]
    assert native == ["binance_ws_connect_window", "binance_ws_connect_pacing"]

    monkeypatch.setattr(sys, "platform", "emscripten")
    (window,) = connection_rules("binance", None)
    # Binance's documented limit stays: 300 attempts per five minutes.
    assert (window.name, window.capacity, window.refill_interval_seconds, window.algorithm) == (
        "binance_ws_connect_window", 300, 300.0, "sliding_window")
    assert [rule.name for rule in connection_rules("okx", None)] == [
        "okx_ws_connect_window", "okx_ws_connect_pacing"]


class _Status(Enum):
    COMPLETED = "completed"


async def _deferred_behind_probe(lease_seconds: float) -> tuple[int, float | None]:
    """Run one chunk that first meets another request's cold-start probe.

    Returns how often it ran within 1.5 s and when it completed.
    """
    futures: dict[str, asyncio.Future] = {}
    runs = 0
    started = time.monotonic()
    completed_after: float | None = None

    def future_for(request):
        if request.request_id not in futures:
            futures[request.request_id] = asyncio.get_running_loop().create_future()
        return futures[request.request_id]

    async def execute(request):
        nonlocal runs
        runs += 1
        if runs == 1:
            # What RateLimitManager answers while a probe is in flight: the
            # wait is the probe's fail-safe lease, not when its response comes.
            raise RateLimitDeferred(RateLimitAdmission(
                False, "binance:spot:request_weight:ip", 2, "probe_in_flight", lease_seconds,
                time.monotonic() + lease_seconds, int((time.time() + lease_seconds) * 1000),
                "binance_spot_klines",
            ))
        return RepairOutcome(request=request, status=_Status.COMPLETED, bars_loaded=1)

    async def finalize(request, outcome):
        return None

    def complete(request, outcome):
        nonlocal completed_after
        completed_after = time.monotonic() - started
        future_for(request).set_result(outcome)

    scheduler = BackfillScheduler(
        execute=execute, future_for=future_for, finalize=finalize, complete=complete,
        on_queued=lambda request: None,
    )
    try:
        _, future = scheduler.submit(RepairRequest(
            symbol="BTCUSDT", interval="1h", start_ms=0, end_ms=0, request_id="chart",
        ))
        await asyncio.wait({future}, timeout=1.5)
    finally:
        await scheduler.shutdown()
    return runs, completed_after


def test_native_chunk_behind_a_probe_waits_for_the_lease() -> None:
    runs, completed_after = asyncio.run(_deferred_behind_probe(30.0))
    assert (runs, completed_after) == (1, None)


def test_browser_tab_chunk_behind_a_probe_looks_again_shortly(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "emscripten")
    runs, completed_after = asyncio.run(_deferred_behind_probe(30.0))
    assert runs == 2
    assert completed_after is not None and completed_after < 1.0


@pytest.mark.parametrize("platform", ["emscripten", sys.platform])
def test_budget_deferral_keeps_its_retry_time(monkeypatch, platform) -> None:
    # Only the probe's lease is an upper bound. A bucket's refill time is exact.
    monkeypatch.setattr(sys, "platform", platform)

    async def run() -> int:
        runs = 0

        async def execute(request):
            nonlocal runs
            runs += 1
            raise RateLimitDeferred(RateLimitAdmission(
                False, "binance:spot:request_weight:ip", 2, "budget", 30.0,
                time.monotonic() + 30.0, int((time.time() + 30.0) * 1000), "binance_spot_klines",
            ))

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        async def finalize(request, outcome):
            return None

        scheduler = BackfillScheduler(
            execute=execute, future_for=lambda request: future, finalize=finalize,
            complete=lambda request, outcome: None, on_queued=lambda request: None,
        )
        try:
            scheduler.submit(RepairRequest(
                symbol="BTCUSDT", interval="1h", start_ms=0, end_ms=0, request_id="chart",
            ))
            await asyncio.sleep(1.0)
        finally:
            await scheduler.shutdown()
        return runs

    assert asyncio.run(run()) == 1
