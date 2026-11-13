"""Consumer update preservation must reach the producer throttle boundary."""
import asyncio
import time
from types import SimpleNamespace

import pytest

from app.core import config
from app.data_engine.bar_aggregator.models import BarState
from app.data_engine.bar_aggregator import BarAggregatorConfig, BarAggregatorPublisher
from app.data_engine.bar_aggregator import publisher as publisher_module
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.event_bus import DataEventBus
from app.data_engine.data_manager.models import DataEventType, SeriesKey
from app.data_engine.series_identity import KlineSeriesIdentity
from app.data_engine.storage import klines_repo


@pytest.mark.parametrize('wildcard', [False, True])
def test_default_manager_preserves_each_enabled_update_before_queue_delivery(tmp_path, monkeypatch, wildcard):
    path = tmp_path/'bars.sqlite'
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', path)
    monkeypatch.setattr(config, 'KLINES_DB_PATH', path)
    monkeypatch.setattr(publisher_module, 'time', SimpleNamespace(time=lambda: 2000000))
    klines_repo.init_klines_storage()

    async def run():
        dm = DataManager()
        dm.set_storage(klines_repo.KlinesRepoAdapter())
        # The complete default bridge and bus, without starting network owners.
        dm.aggregator_bridge._is_started = lambda: True
        dm.bar_aggregator.publisher.set_update_throttle_ms(1000)
        seen = []
        async def receive(event):
            seen.append(event.bar.close)
        handle = dm.subscribe(receive, symbol=None if wildcard else 'BTCUSDT',
            interval=None if wildcard else '3m', event_types={DataEventType.BAR_UPDATED},
            preserve_updates=True)
        state = BarState('BTCUSDT', '3m', 0, 180000, 100, 104, 99, 100, 1)
        try:
            for close in [101, 102, 103]:
                state.close = close
                await dm.bar_aggregator.publisher.emit_updated(state)
            for _ in range(100):
                if len(seen) == 3:
                    break
                await asyncio.sleep(0)
            assert seen == [101, 102, 103]
            assert dm.event_bus.snapshot()['callback_lag'][handle.id]['coalesced'] == 0
        finally:
            await dm.event_bus.close()
            await dm.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize('scope', ['exact', 'wildcard', 'foreign', 'other-symbol', 'closed-only'])
def test_requirement_uses_live_semantic_routing_and_filters(scope):
    async def run():
        bus = DataEventBus()
        key = SeriesKey('BTCUSDT', '7m')
        subscribed = (None if scope == 'wildcard' else
            SeriesKey.create('BTCUSDT', '7m', identity=KlineSeriesIdentity.for_exchange('binance', provider_id='other'))
            if scope == 'foreign' else SeriesKey('ETHUSDT', '7m') if scope == 'other-symbol' else key)
        async def receive(event):
            pass
        handle = bus.subscribe(receive, key=subscribed, preserve_updates=True,
            event_types={DataEventType.BAR_CLOSED} if scope == 'closed-only' else {DataEventType.BAR_UPDATED})
        try:
            assert bus.requires_every_update(key) is (scope in {'exact', 'wildcard'})
            if scope == 'foreign':
                assert bus.requires_every_update(subscribed)
            bus.unsubscribe(handle)
            assert not bus.requires_every_update(key)
        finally:
            await bus.close()
    asyncio.run(run())


def test_terminal_and_closed_bus_do_not_request_more_updates():
    async def run():
        bus = DataEventBus()
        key = SeriesKey('BTCUSDT', '7m')
        async def receive(event):
            pass
        bus.subscribe(receive, key=key, preserve_updates=True)
        assert bus.requires_every_update(key)
        bus.require_recovery(key, 'controlled_test')
        assert not bus.requires_every_update(key)
        await bus.close()
        assert not bus.requires_every_update(key)
    asyncio.run(run())


def test_demand_lookup_does_not_scan_unrelated_subscriptions():
    class NoScan(dict):
        def __iter__(self):
            raise AssertionError('global subscription scan')
        def items(self):
            raise AssertionError('global subscription scan')
        def values(self):
            raise AssertionError('global subscription scan')
    async def run():
        bus = DataEventBus()
        async def receive(event):
            pass
        key = SeriesKey('BTCUSDT', '7m')
        bus.subscribe(receive, key=key, preserve_updates=True)
        for index in range(50):
            bus.subscribe(receive, key=SeriesKey('OTHER'+str(index), '7m'), preserve_updates=True)
        original = bus._callback_subs
        bus._callback_subs = NoScan(original)
        try:
            assert bus.requires_every_update(key)
            assert not bus.requires_every_update(SeriesKey('ABSENT', '7m'))
        finally:
            bus._callback_subs = original
            await bus.close()
    asyncio.run(run())


def test_regular_consumers_keep_throttle_and_removal_restores_it(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(publisher_module, 'time', SimpleNamespace(time=lambda: 2000000))
    async def run():
        bus = DataEventBus()
        publisher = BarAggregatorPublisher(BarAggregatorConfig(update_throttle_ms=1000))
        key = SeriesKey('BTCUSDT', '7m')
        publisher.set_update_requirement(lambda state: bus.requires_every_update(key))
        seen = []
        async def receive(event):
            seen.append(event.bar.close)
        async def ignore(event):
            pass
        publisher.on_bar_updated(receive)
        regular = bus.subscribe(ignore, key=key)
        state = BarState('BTCUSDT', '7m', 0, 420000, 100, 104, 99, 100, 1)
        try:
            for close in [101, 102]:
                state.close = close
                await publisher.emit_updated(state)
            assert seen == [101]
            immediate = bus.subscribe(ignore, key=key, preserve_updates=True)
            for close in [102, 103]:
                state.close = close
                await publisher.emit_updated(state)
            assert seen == [101, 102, 103]
            bus.unsubscribe(immediate)
            state.close = 104
            await publisher.emit_updated(state)
            assert seen == [101, 102, 103]
            assert publisher.snapshot()['required_updates_unthrottled'] == 2
            assert publisher.snapshot()['events_throttled'] == 2
            bus.unsubscribe(regular)
        finally:
            await bus.close()
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['exception', 'invalid-result'])
def test_unavailable_requirement_preserves_enabled_input(monkeypatch, failure):
    monkeypatch.setattr(publisher_module, 'time', SimpleNamespace(time=lambda: 2000000))
    async def run():
        publisher = BarAggregatorPublisher(BarAggregatorConfig(update_throttle_ms=1000))
        def requirement(state):
            if failure == 'exception':
                raise RuntimeError('controlled requirement outage')
            return None
        publisher.set_update_requirement(requirement)
        seen = []
        async def receive(event):
            seen.append(event.bar.close)
        publisher.on_bar_updated(receive)
        state = BarState('BTCUSDT', '7m', 0, 420000, 100, 104, 99, 100, 1)
        for close in [101, 102, 103]:
            state.close = close
            await publisher.emit_updated(state)
        assert seen == [101, 102, 103]
        assert publisher.snapshot()['update_requirement_errors'] == 3
    asyncio.run(run())


def test_explicit_disabled_producer_flag_is_not_reenabled():
    async def run():
        publisher = BarAggregatorPublisher(BarAggregatorConfig(emit_updated_events=False))
        publisher.set_update_requirement(lambda state: True)
        seen = []
        async def receive(event):
            seen.append(event)
        publisher.on_bar_updated(receive)
        await publisher.emit_updated(BarState('BTCUSDT', '7m', 0, 420000, 100, 104, 99, 100, 1))
        assert seen == []
    asyncio.run(run())


@pytest.mark.parametrize('preserve', [False, True])
def test_router_component_updates_reach_default_bridge_with_declared_demand(tmp_path, monkeypatch, preserve):
    from tests.test_shared_component_input import market
    path = tmp_path/'bars.sqlite'
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', path)
    monkeypatch.setattr(config, 'KLINES_DB_PATH', path)
    monkeypatch.setattr(publisher_module, 'time', SimpleNamespace(time=lambda: 2000000))
    klines_repo.init_klines_storage()
    async def run():
        dm = DataManager()
        dm.set_storage(klines_repo.KlinesRepoAdapter())
        dm.aggregator_bridge._is_started = lambda: True
        agg = dm.bar_aggregator
        agg.publisher.set_update_throttle_ms(1000)
        agg.add_target('BTCUSDT', '7m', market_type='futures')
        seen = []
        async def receive(event):
            seen.append(event.bar.volume)
        dm.subscribe(receive, symbol='BTCUSDT', interval='7m', market_type='futures',
            event_types={DataEventType.BAR_UPDATED}, preserve_updates=preserve)
        try:
            minute = int(time.time()*1000)//60000
            for sequence in range(1, 5):
                await agg.on_market_event(market(minute, volume=sequence, sequence=sequence))
            expected = [2., 3., 4.] if preserve else [2.]
            for _ in range(100):
                if len(seen) == len(expected):
                    break
                await asyncio.sleep(0)
            assert seen == expected
        finally:
            await dm.event_bus.close()
            await dm.shutdown()
    asyncio.run(run())
