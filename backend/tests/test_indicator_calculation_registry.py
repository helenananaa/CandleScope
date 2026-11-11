"""Transport cancellation and resource ownership, without mocking script math."""
import asyncio
from types import SimpleNamespace

import pytest

from app.indicator.calculation_owner import CalculationOwnerError
from app.indicator.calculation_registry import CalculationRegistry


class Runtime:
    def __init__(self, owner_id):
        self.owner_id = owner_id
        self.owner = SimpleNamespace(plan=SimpleNamespace(owner_id=owner_id))
        self.close_entered = asyncio.Event()
        self.close_allowed = asyncio.Event()
        self.close_allowed.set()
        self.closes = 0
        self.fail = False

    async def close(self):
        self.closes += 1
        self.close_entered.set()
        await self.close_allowed.wait()
        if self.fail:
            raise RuntimeError('dependency release failed')


@pytest.mark.anyio
async def test_cancelled_open_keeps_reserved_capacity_and_shutdown_drains_factory():
    registry = CalculationRegistry(max_entries=1)
    entered, allowed = asyncio.Event(), asyncio.Event()
    created = []
    async def create(owner_id):
        entered.set()
        await allowed.wait()
        runtime = Runtime(owner_id)
        created.append(runtime)
        return runtime
    opening = asyncio.create_task(registry.open(create))
    await entered.wait()
    opening.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opening
    with pytest.raises(CalculationOwnerError, match='CAPACITY'):
        await registry.open(create)
    assert registry.snapshot()['opening'] == 1
    stopping = asyncio.create_task(registry.stop())
    try:
        await asyncio.sleep(0)
        stopping.cancel()
        await asyncio.sleep(0)
        assert not stopping.done() and not created
        with pytest.raises(CalculationOwnerError, match='CLOSED'):
            await registry.open(create)
    finally:
        allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(stopping, 5)
        await registry.stop()
    assert created[0].closes == 1 and registry.snapshot()['entries'] == 0


@pytest.mark.anyio
async def test_borrows_share_one_owner_and_retirement_waits_for_last_transport():
    registry = CalculationRegistry(max_entries=1)
    created = []
    async def create(owner_id):
        runtime = Runtime(owner_id)
        created.append(runtime)
        return runtime
    owner_id = await registry.open(create)
    try:
        async with registry.borrow(owner_id) as http:
            async with registry.borrow(owner_id) as websocket:
                assert http is websocket is created[0]
                assert registry.snapshot()['borrowers'] == 2
                retiring = asyncio.create_task(registry.retire(owner_id))
                await asyncio.sleep(0)
                assert not retiring.done() and not http.close_entered.is_set()
                with pytest.raises(CalculationOwnerError, match='NOT_FOUND'):
                    async with registry.borrow(owner_id):
                        pytest.fail('Retired owner was admitted')
                with pytest.raises(CalculationOwnerError, match='CAPACITY'):
                    await registry.open(create)
            assert registry.snapshot()['borrowers'] == 1
        await asyncio.wait_for(retiring, 5)
        assert created[0].closes == 1
        await registry.retire(owner_id)
        assert created[0].closes == 1 and registry.snapshot()['entries'] == 0
    finally:
        await registry.stop()


@pytest.mark.anyio
async def test_idle_expiry_does_not_evict_pinned_or_physically_closing_owners():
    now = [0.0]
    registry = CalculationRegistry(max_entries=1, idle_seconds=10, clock=lambda: now[0])
    runtime = None
    async def create(owner_id):
        nonlocal runtime
        runtime = Runtime(owner_id)
        runtime.close_allowed.clear()
        return runtime
    owner_id = await registry.open(create)
    try:
        async with registry.borrow(owner_id):
            now[0] = 1000
            async with registry.borrow(owner_id) as shared:
                assert shared is runtime
        now[0] = 1009
        async with registry.borrow(owner_id):
            pass
        now[0] = 1020
        with pytest.raises(CalculationOwnerError, match='NOT_FOUND'):
            async with registry.borrow(owner_id):
                pytest.fail('Expired owner was admitted')
        await asyncio.wait_for(runtime.close_entered.wait(), 5)
        with pytest.raises(CalculationOwnerError, match='CAPACITY'):
            await registry.open(create)
        assert registry.snapshot()['retiring'] == 1
        runtime.close_allowed.set()
        await registry.retire(owner_id)
        replacement = await registry.open(create)
        assert replacement != owner_id
    finally:
        runtime.close_allowed.set()
        await registry.stop()


@pytest.mark.anyio
async def test_cancelled_transport_releases_its_pin_without_awaiting_idle_ttl():
    registry = CalculationRegistry()
    entered = asyncio.Event()
    runtime = None
    async def create(owner_id):
        nonlocal runtime
        runtime = Runtime(owner_id)
        return runtime
    owner_id = await registry.open(create)
    async def transport():
        async with registry.borrow(owner_id):
            entered.set()
            await asyncio.Event().wait()
    request = asyncio.create_task(transport())
    try:
        await entered.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert registry.snapshot()['borrowers'] == 0 and runtime.closes == 0
        async with registry.borrow(owner_id) as next_transport:
            assert next_transport is runtime
    finally:
        await registry.stop()
    assert runtime.closes == 1


@pytest.mark.anyio
async def test_cleanup_failure_retains_capacity_and_shutdown_retries_before_dependencies():
    registry = CalculationRegistry(max_entries=1)
    runtime = None
    async def create(owner_id):
        nonlocal runtime
        runtime = Runtime(owner_id)
        runtime.fail = True
        return runtime
    owner_id = await registry.open(create)
    with pytest.raises(RuntimeError, match='dependency release failed'):
        await registry.retire(owner_id)
    with pytest.raises(CalculationOwnerError, match='CAPACITY'):
        await registry.open(create)
    with pytest.raises(CalculationOwnerError, match='CLEANUP_FAILED'):
        await registry.stop()
    assert runtime.closes == 2 and registry.snapshot()['entries'] == 1
    runtime.fail = False
    await registry.stop()
    await registry.stop()
    assert runtime.closes == 3 and registry.snapshot()['entries'] == 0


@pytest.mark.anyio
async def test_bad_factory_identity_is_not_adopted_or_leaked():
    registry = CalculationRegistry(max_entries=1)
    runtime = Runtime('another-chart-owner')
    async def create(_owner_id): return runtime
    try:
        with pytest.raises(CalculationOwnerError, match='OUTPUT_IDENTITY_CHANGED'):
            await registry.open(create)
        await asyncio.wait_for(runtime.close_entered.wait(), 5)
    finally:
        await registry.stop()
    assert runtime.closes == 1 and registry.snapshot()['entries'] == 0


@pytest.mark.anyio
async def test_failed_factory_frees_only_unallocated_slot():
    registry = CalculationRegistry(max_entries=1)
    async def broken(_owner_id): raise RuntimeError('startup failed before allocation')
    async def good(owner_id): return Runtime(owner_id)
    try:
        with pytest.raises(RuntimeError, match='startup failed'):
            await registry.open(broken)
        owner_id = await registry.open(good)
        async with registry.borrow(owner_id) as runtime:
            assert runtime.owner.plan.owner_id == owner_id
    finally:
        await registry.stop()


@pytest.mark.anyio
async def test_collector_releases_orphaned_open_without_next_request():
    now = [0.0]
    registry = CalculationRegistry(idle_seconds=1, sweep_seconds=0.01, clock=lambda: now[0])
    runtime = None
    async def create(owner_id):
        nonlocal runtime
        runtime = Runtime(owner_id)
        return runtime
    await registry.open(create)
    try:
        now[0] = 2
        await asyncio.wait_for(runtime.close_entered.wait(), 5)
        assert registry.snapshot()['entries'] == 0
    finally:
        await registry.stop()


@pytest.mark.anyio
async def test_idle_transport_hold_prevents_expiry_but_cannot_block_explicit_retire():
    now = [0.0]
    registry = CalculationRegistry(idle_seconds=1, clock=lambda:now[0])
    async def create(owner_id): return Runtime(owner_id)
    owner_id = await registry.open(create)
    try:
        async with registry.hold(owner_id) as transport:
            now[0] = 100
            async with registry.borrow(owner_id) as command:
                assert command is transport
            assert registry.snapshot()['holders'] == 1
            await asyncio.wait_for(registry.retire(owner_id),5)
            assert transport.closes == 1 and registry.snapshot()['entries'] == 0
            with pytest.raises(CalculationOwnerError,match='NOT_FOUND'):
                async with registry.borrow(owner_id): pytest.fail('Retired idle hold executed')
    finally:
        await registry.stop()
