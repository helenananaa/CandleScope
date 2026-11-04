from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from app.exchanges.public_admission import PublicAdmission, PublicDemand, TrafficClass
from app.exchanges.rate_limits import HistoricalRequest, RateLimitDeferred, RateLimitManager, RateLimitRule


def request() -> HistoricalRequest:
    return HistoricalRequest("binance", "spot", "/api/v3/klines", "BTCUSDT")


def rule(key: str, capacity: int = 10, **kwargs) -> RateLimitRule:
    return RateLimitRule(key, key, capacity, 3600, **kwargs)


def test_quota_failure_keeps_request_path_and_numeric_feedback_without_secrets() -> None:
    async def run():
        scheduler = PublicAdmission(RateLimitManager())
        quota = rule("binance:futures:legacy")
        target = HistoricalRequest("binance", "futures",
            "https://username:password@fapi.binance.com/fapi/v1/fundingInfo?apiKey=hidden#secret", "")
        permit = await scheduler.acquire([quota], target, demand=PublicDemand(TrafficClass.BACKGROUND))
        permit.finish(status_code=429, body_code="-1003", headers={
            "Retry-After": "2", "X-MBX-USED-WEIGHT-1M": "2400",
            "Authorization": "Bearer hidden", "X-MBX-USED-WEIGHT": "not-a-number",
        })
        snapshot = scheduler.snapshot()
        entry = snapshot["recent"][-1]
        assert entry["endpoint"] == "/fapi/v1/fundingInfo"
        assert entry["exchange"] == "binance" and entry["market_type"] == "futures"
        assert entry["rules"] == [quota.name]
        assert entry["traffic_class"] == "background"
        assert entry["status_code"] == 429 and entry["body_code"] == "-1003"
        assert entry["quota_headers"] == {"retry-after": "2", "x-mbx-used-weight-1m": "2400"}
        assert entry["observed_at_ms"] > 0
        encoded = json.dumps(snapshot)
        for secret in ["username", "password", "apiKey", "hidden", "Authorization", "secret"]:
            assert secret not in encoded
        assert snapshot["in_flight"] == 0 and snapshot["counts"]["completed"] == 1
        assert scheduler.manager.snapshot()[quota.bucket_key]["cooldown_remaining_seconds"] > 0
    asyncio.run(run())


def test_diagnostic_history_remains_bounded_and_duplicate_completion_is_ignored() -> None:
    async def run():
        scheduler = PublicAdmission(RateLimitManager())
        quota = rule("independent:ip", capacity=200)
        for index in range(140):
            permit = await scheduler.acquire([quota], request())
            permit.finish(status_code=200)
            permit.finish(status_code=418, headers={"Retry-After": "999"})
        snapshot = scheduler.snapshot()
        assert len(snapshot["recent"]) == 128
        assert snapshot["counts"]["completed"] == 140
        assert all(row["status_code"] == 200 for row in snapshot["recent"])
        assert snapshot["recent"][0]["attempt_id"] < snapshot["recent"][-1]["attempt_id"]
        assert snapshot["in_flight"] == 0
        assert scheduler.manager.snapshot()[quota.bucket_key]["cooldown_remaining_seconds"] == 0
    asyncio.run(run())


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


def test_sustained_foreground_cannot_starve_executable_background():
    async def run():
        scheduler = PublicAdmission(RateLimitManager(), max_in_flight=1, max_priority_bypass=3)
        quota = rule("shared", 100)
        held = await scheduler.acquire([quota], request())
        order = []

        async def work(label, traffic):
            permit = await scheduler.acquire([quota], request(), demand=PublicDemand(traffic))
            order.append(label)
            permit.finish(status_code=200)

        background = asyncio.create_task(work("background", TrafficClass.BACKGROUND))
        critical = [asyncio.create_task(work(str(i), TrafficClass.INTERACTIVE)) for i in range(12)]
        while scheduler.snapshot()["pending"] != 13:
            await asyncio.sleep(0)
        held.finish(status_code=200)
        await asyncio.wait_for(asyncio.gather(background, *critical), 2)
        assert order.index("background") == 3
        assert scheduler.snapshot()["counts"]["fairness_grants"] >= 1
        assert scheduler.snapshot()["in_flight"] == 0
    asyncio.run(run())


def test_deferred_background_keeps_fairness_credit_but_never_bypasses_cooldown():
    async def run():
        scheduler = PublicAdmission(RateLimitManager(), max_priority_bypass=2)
        quota = rule("shared", 100)
        foreground = PublicDemand(TrafficClass.INTERACTIVE, defer=True)
        background = PublicDemand(TrafficClass.BACKGROUND, defer=True)
        scheduler.protect(foreground, quota.bucket_key)
        with pytest.raises(RateLimitDeferred):
            await scheduler.acquire([quota], request(), demand=background)
        scheduler.protect(background, quota.bucket_key)
        for _ in range(2):
            permit = await scheduler.acquire([quota], request(), demand=foreground)
            permit.finish(status_code=200)
        with pytest.raises(RateLimitDeferred, match="critical_demand"):
            await scheduler.acquire([quota], request(), demand=foreground)
        scheduler.forget(background)  # Business worker resumes its delayed chunk.
        permit = await scheduler.acquire([quota], request(), demand=background)
        permit.finish(status_code=429, retry_after=60)
        assert background.bypasses == 0
        scheduler.forget(foreground)
        with pytest.raises(RateLimitDeferred, match="cooldown"):
            await scheduler.acquire([quota], request(), demand=background)
    asyncio.run(run())


def test_stale_fairness_interest_cannot_block_foreground():
    async def run():
        scheduler = PublicAdmission(RateLimitManager(), max_priority_bypass=1)
        quota = rule("shared")
        alive = True
        background = PublicDemand(TrafficClass.BACKGROUND, alive=lambda: alive, bypasses=1)
        scheduler.protect(background, quota.bucket_key)
        alive = False
        permit = await scheduler.acquire([quota], request(), demand=PublicDemand(TrafficClass.INTERACTIVE, defer=True))
        permit.finish(status_code=200)
        assert scheduler.snapshot()["protected"] == 0
    asyncio.run(run())


def test_aged_background_cohort_does_not_burst_ahead_of_foreground():
    async def run():
        scheduler = PublicAdmission(RateLimitManager(), max_in_flight=1, max_priority_bypass=3)
        quota = rule("shared", 100)
        held = await scheduler.acquire([quota], request())
        order = []
        async def work(label, traffic):
            permit = await scheduler.acquire([quota], request(), demand=PublicDemand(traffic))
            order.append(label)
            permit.finish(status_code=200)
        tasks = [asyncio.create_task(work(f"bg{i}", TrafficClass.BACKGROUND)) for i in range(5)]
        tasks += [asyncio.create_task(work(f"fg{i}", TrafficClass.INTERACTIVE)) for i in range(12)]
        while scheduler.snapshot()["pending"] != len(tasks):
            await asyncio.sleep(0)
        held.finish(status_code=200)
        await asyncio.wait_for(asyncio.gather(*tasks), 2)
        assert [name[:2] for name in order[:12]] == ["fg", "fg", "fg", "bg"] * 3
        assert len([name for name in order if name.startswith("bg")]) == 5
    asyncio.run(run())
