"""Rule reconciliation cannot orphan a subscription while startup awaits I/O."""
import asyncio
import pytest

from app.alerts.facade import AlertFacade
from app.alerts.runtime import AlertRuntimeEngine
from tests.test_alerts_runtime import FakeDataManager


def test_parallel_reconciliation_owns_one_numeric_subscription(tmp_path):
    async def run():
        entered, resume = asyncio.Event(), asyncio.Event()
        class Held(FakeDataManager):
            async def subscribe_indicator(self, *args, **kwargs):
                entered.set()
                await resume.wait()
                return await super().subscribe_indicator(*args, **kwargs)
        dm = Held()
        facade = AlertFacade(store_path=tmp_path / 'rules.json')
        rule = facade.save_rule(dict(name='concurrent', target=dict(symbol='BTCUSDT', interval='1m'),
            expression=dict(left='rsi', comparator='>', right=dict(type='number', value=0))))
        runtime = AlertRuntimeEngine(facade=facade, data_manager=dm)
        runtime._started = True
        first = asyncio.create_task(runtime.sync_rule(rule))
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(runtime.sync_rule(rule))
        await asyncio.sleep(.02)
        resume.set()
        await asyncio.wait_for(asyncio.gather(first, second), 5)
        assert len(dm.subscriptions) == len(runtime._subscriptions) == 1
        await runtime.stop()
        assert len(dm.release_calls) == 1
    asyncio.run(run())


def test_stop_waits_for_inflight_subscription_and_releases_it(tmp_path):
    async def run():
        entered, resume = asyncio.Event(), asyncio.Event()
        class Held(FakeDataManager):
            async def subscribe_indicator(self, *args, **kwargs):
                entered.set()
                await resume.wait()
                return await super().subscribe_indicator(*args, **kwargs)
        dm = Held()
        facade = AlertFacade(store_path=tmp_path / 'rules.json')
        rule = facade.save_rule(dict(name='stopping', target=dict(symbol='BTCUSDT', interval='1m'),
            expression=dict(left='rsi', comparator='>', right=dict(type='number', value=0))))
        runtime = AlertRuntimeEngine(facade=facade, data_manager=dm)
        runtime._started = True
        start = asyncio.create_task(runtime.sync_rule(rule))
        await asyncio.wait_for(entered.wait(), 2)
        stop = asyncio.create_task(runtime.stop())
        await asyncio.sleep(.02)
        resume.set()
        await asyncio.wait_for(asyncio.gather(start, stop), 5)
        assert not runtime._subscriptions
        assert len(dm.subscriptions) == len(dm.release_calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize('mutation', ['disable', 'delete'])
def test_waiting_old_sync_cannot_reinstall_mutated_rule(tmp_path, mutation):
    async def run():
        entered, resume = asyncio.Event(), asyncio.Event()
        class Held(FakeDataManager):
            async def subscribe_indicator(self, *args, **kwargs):
                entered.set()
                await resume.wait()
                return await super().subscribe_indicator(*args, **kwargs)
        dm = Held()
        facade = AlertFacade(store_path=tmp_path / 'rules.json')
        rule = facade.save_rule(dict(name='mutating', target=dict(symbol='BTCUSDT', interval='1m'),
            expression=dict(left='rsi', comparator='>', right=dict(type='number', value=0))))
        runtime = AlertRuntimeEngine(facade=facade, data_manager=dm)
        runtime._started = True
        first = asyncio.create_task(runtime.sync_rule(rule))
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(runtime.sync_rule(rule))
        await asyncio.sleep(.02)
        if mutation == 'disable':
            facade.set_enabled(rule['id'], False)
        else:
            facade.delete_rule(rule['id'])
        resume.set()
        await asyncio.wait_for(asyncio.gather(first, second), 5)
        assert not runtime._subscriptions
        assert len(dm.subscriptions) == len(dm.release_calls) == 1
        await runtime.stop()
    asyncio.run(run())
