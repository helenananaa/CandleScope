from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.exchanges.public_admission import PublicAdmission, PublicDemand, TrafficClass
from app.exchanges.rate_limits import HistoricalRequest, RateLimitDeferred, RateLimitManager, RateLimitRule


def request() -> HistoricalRequest:
    return HistoricalRequest("binance", "spot", "/api/v3/klines", "BTCUSDT")


def rule(key: str, capacity: int = 10, **kwargs) -> RateLimitRule:
    return RateLimitRule(key, key, capacity, 3600, **kwargs)


def test_atomic_constraints_and_concurrent_reservation() -> None:
    async def run():
        manager = RateLimitManager()
        first, second = rule("binance:ip", 2), rule("binance:key", 1)
        await manager.acquire_nowait(second, request())
        with pytest.raises(RateLimitDeferred):
            await manager.acquire_many_nowait([first, second], request())
        assert manager.available_capacity(first) == 2
        results = await asyncio.gather(*[
            manager.acquire_many_nowait([first], request()) for _ in range(10)
        ], return_exceptions=True)
        assert sum(isinstance(result, list) for result in results) == 2
        assert sum(isinstance(result, RateLimitDeferred) for result in results) == 8
    asyncio.run(run())


def test_critical_intent_only_protects_its_resource_and_cancellation_releases_it() -> None:
    async def run():
        scheduler = PublicAdmission(RateLimitManager())
        shared, independent = rule("binance:spot:ip:egress=a"), rule("okx:ip:egress=b")
        alive = True
        foreground = PublicDemand(TrafficClass.INTERACTIVE, alive=lambda: alive)
        scheduler.protect(foreground, shared.bucket_key)
        background = PublicDemand(TrafficClass.BACKGROUND, defer=True)
        with pytest.raises(RateLimitDeferred, match="critical_demand"):
            await scheduler.acquire([shared], request(), demand=background)
        permit = await scheduler.acquire([independent], request(), demand=background)
        permit.finish(status_code=200)
        alive = False
        permit = await scheduler.acquire([shared], request(), demand=background)
        permit.finish(status_code=200)
        assert scheduler.snapshot()["protected"] == 0
    asyncio.run(run())


def test_execution_capacity_cancellation_and_idempotent_unknown_settlement() -> None:
    async def run():
        scheduler = PublicAdmission(RateLimitManager(), max_in_flight=1)
        quota = rule("binance:ip")
        permit = await scheduler.acquire([quota], request())
        queued = asyncio.create_task(scheduler.acquire([quota], request()))
        async with asyncio.timeout(1):
            while scheduler.snapshot()["pending"] != 1:
                await asyncio.sleep(0.001)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        permit.finish(response_unknown=True)
        permit.finish(status_code=200)
        snapshot = scheduler.snapshot()
        assert snapshot["pending"] == snapshot["in_flight"] == 0
        assert snapshot["counts"]["attempts"] == snapshot["counts"]["unknown"] == 1
        assert scheduler.manager.available_capacity(quota) < 9.01
    asyncio.run(run())


def test_deferred_waiter_wakes_on_release_and_no_concurrency_oversell() -> None:
    async def run():
        scheduler = PublicAdmission(RateLimitManager(), max_in_flight=2)
        quota = rule("binance:ip", max_concurrency=1)
        active = 0
        maximum = 0
        async def attempt():
            nonlocal active, maximum
            permit = await scheduler.acquire([quota], request())
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.001)
            active -= 1
            permit.finish(status_code=200)
        await asyncio.wait_for(asyncio.gather(*[attempt() for _ in range(8)]), 1)
        assert maximum == 1
    asyncio.run(run())


def test_probe_settles_from_ipc_callback_owner_without_refund() -> None:
    async def run():
        manager = RateLimitManager(conservative_cold_start=True)
        quota = rule("binance:ip")
        permit = await asyncio.create_task(PublicAdmission(manager).acquire([quota], request()))
        permit.finish(status_code=200)
        assert manager.snapshot()[quota.bucket_key]["probe_in_flight"] is False
        assert manager.available_capacity(quota) < 0.01
    asyncio.run(run())


def test_sliding_window_does_not_refill_early(monkeypatch) -> None:
    async def run():
        now = [100.0]
        monkeypatch.setattr("app.exchanges.rate_limits.time.monotonic", lambda: now[0])
        manager = RateLimitManager()
        quota = rule("okx:ws_connect:ip", 3, algorithm="sliding_window")
        quota.refill_interval_seconds = 1
        for _ in range(3):
            await manager.acquire_nowait(quota, request())
        now[0] += 0.9
        admission = await manager.inspect(quota, request())
        assert not admission.allowed
        assert admission.retry_after_seconds == pytest.approx(0.1)
        now[0] += 0.1
        assert (await manager.inspect(quota, request())).allowed
    asyncio.run(run())


def test_priority_rollback_keeps_consumption_and_cooldown() -> None:
    async def run():
        scheduler = PublicAdmission(RateLimitManager())
        quota = rule("binance:ip")
        permit = await scheduler.acquire([quota], request())
        permit.finish(status_code=429, retry_after=10)
        before = scheduler.manager.snapshot()[quota.bucket_key]
        scheduler.set_priority_enabled(False)
        with pytest.raises(RateLimitDeferred, match="cooldown"):
            await scheduler.acquire([quota], request(), demand=PublicDemand(defer=True))
        after = scheduler.manager.snapshot()[quota.bucket_key]
        assert after["cooldown_until"] == before["cooldown_until"]
        assert after["tokens"] < 9.01
    asyncio.run(run())


def test_dependency_inherits_live_foreground_and_loses_cancelled_importance() -> None:
    alive = True
    foreground = PublicDemand(TrafficClass.INTERACTIVE, alive=lambda: alive)
    metadata = PublicDemand(TrafficClass.BACKGROUND)
    metadata.inherit(foreground)
    assert metadata.priority() == TrafficClass.INTERACTIVE
    alive = False
    assert metadata.priority() == TrafficClass.BACKGROUND


def test_closing_socket_cancels_unsent_control_and_removes_its_windows() -> None:
    from app.exchanges.public_ws import AdmittedWebSocket
    from app.exchanges.public_admission import get_public_admission
    async def run():
        class Socket:
            sent = 0
            async def send_str(self, payload):
                self.sent += 1
            async def close(self):
                pass
        socket = Socket()
        wrapper = AdmittedWebSocket(socket, "binance", "spot", "test")
        for _ in range(5):
            await wrapper.send_str("subscribe")
        blocked = asyncio.create_task(wrapper.send_str("subscribe"))
        async with asyncio.timeout(1):
            while get_public_admission().snapshot()["pending"] != 1:
                await asyncio.sleep(0.001)
        await wrapper.close()
        with pytest.raises(asyncio.CancelledError):
            await blocked
        assert socket.sent == 5
        assert get_public_admission().snapshot()["in_flight"] == 0
        assert not any(":ws_control:connection:" in key for key in get_public_admission().manager.snapshot())
    asyncio.run(run())


@pytest.mark.parametrize("foreground_has_quota", [True, False])
def test_execution_pressure_prioritizes_only_runnable_foreground(foreground_has_quota) -> None:
    async def run():
        scheduler = PublicAdmission(RateLimitManager(), max_in_flight=1)
        held = await scheduler.acquire([rule("held:ip")], request())
        foreground_rule = rule("foreground:ip")
        if not foreground_has_quota:
            scheduler.manager.record_cooldown(foreground_rule, 60)
        order = []
        async def attempt(label, quota, traffic_class):
            permit = await scheduler.acquire([quota], request(), demand=PublicDemand(traffic_class))
            order.append(label)
            permit.finish(status_code=200)
        background = asyncio.create_task(attempt("background", rule("background:ip"), TrafficClass.BACKGROUND))
        foreground = asyncio.create_task(attempt("foreground", foreground_rule, TrafficClass.INTERACTIVE))
        async with asyncio.timeout(1):
            while scheduler.snapshot()["pending"] != 2:
                await asyncio.sleep(0.001)
        held.finish(status_code=200)
        await asyncio.wait_for(background, 1)
        if foreground_has_quota:
            await foreground
            assert order == ["foreground", "background"]
        else:
            assert order == ["background"]
            foreground.cancel()
            with pytest.raises(asyncio.CancelledError):
                await foreground
    asyncio.run(run())
