"""A source-only recovered prefix must retain the existing preview contract."""

import asyncio
from dataclasses import replace

import pytest

from app.data_engine.bar_aggregator.models import BarInputSource
from app.data_engine.storage import klines_repo, kline_sources
from tests.test_source_window_recovery import database, record, incoming, manager_for, feed, W


@pytest.mark.parametrize('preserve_updates', [False, True])
@pytest.mark.parametrize('trigger', ['forming', 'closed_correction'])
def test_recovered_source_prefix_coalesces_previews_and_preserves_close(
    database, monkeypatch, preserve_updates, trigger,
):
    clock = [6 * W + 1000]
    monkeypatch.setattr('time.time', lambda: clock[0] / 1000)

    async def run():
        with klines_repo._connect() as conn:
            kline_sources._schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            for index in range(6):
                record(index, conn=conn)
            conn.commit()
        manager = manager_for('7m')
        agg = manager.bar_aggregator
        agg.publisher.set_update_throttle_ms(1000)
        agg.publisher.set_update_requirement(lambda state: preserve_updates)
        agg._previews.start()
        observed = []
        planes = []
        provider = agg.acquisition_revision_provider
        def acquire():
            planes.append(True)
            return provider()
        monkeypatch.setattr(agg, 'acquisition_revision_provider', acquire)
        async def receive(event):
            observed.append((event.event_type.value, event.bar.quote_volume))
        manager.event_bus.subscribe(receive)
        try:
            if trigger == 'closed_correction':
                await feed(manager, '7m', incoming(0))
            for update in range(50):
                quote = 2.0 + update
                ref = record(6, quote=quote, closed=False, sequence=clock[0] + update)['ref']
                value = replace(incoming(6, quote=quote, closed=False, ref=ref),
                                source=BarInputSource.REALTIME)
                await feed(manager, '7m', value)
            state = agg.get_pipeline('7m').bar_state.get_active('binance', 'futures', 'BTCUSDT', 0)
            assert state._source_recovery is not None
            assert not klines_repo.query_klines('BTCUSDT', '1m', market_type='futures')
            # Two acquisitions can occur during cold recursive preparation;
            # the pending deadline captures one. Do not reacquire per update.
            assert len(planes) <= 3
            if preserve_updates:
                assert not state._preview_dirty
                assert state.preview_computed_version == state.preview_input_version
                assert [value for kind, value in observed if kind == 'bar.updated'] == (
                    ([None] if trigger == 'closed_correction' else []) + list(range(14, 64)))
            else:
                assert state._preview_dirty
                assert state.preview_computed_version < state.preview_input_version
                assert state._preview_deferred_inputs >= 40
                assert state._preview_calculations <= 4
                clock[0] += 2000
                for entry in agg._previews.pending.values():
                    entry.due = asyncio.get_running_loop().time()
                await agg._previews._drain()
                assert not state._preview_dirty
                assert state.preview_published_version == state.preview_input_version
                assert observed[-1] == ('bar.updated', 63.0)
            clock[0] = 7 * W + 1000
            ref = record(6, quote=52.0, closed=True, sequence=clock[0])['ref']
            await feed(manager, '7m', incoming(6, quote=52.0, ref=ref))
            closed = agg.get_pipeline('7m').bar_state.get_state('binance', 'futures', 'BTCUSDT', 0)
            assert closed.status.value == 'closed' and not closed._preview_dirty, (
                closed.tick_count, closed.quote_volume, closed._source_recovery.version,
                list(closed.source_snapshots.values()), closed.last_close_received)
            assert closed.quote_volume == 64.0
            stored = klines_repo.query_klines('BTCUSDT', '7m', market_type='futures')
            assert len(stored) == 1 and stored[0]['quote_volume'] == 64.0
            assert observed[-1] == ('bar.closed', 64.0)
            assert [kind for kind, _ in observed].count('bar.closed') == 1
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())


@pytest.mark.parametrize('mutation', ['none', 'prefix', 'tail', 'target_delete', 'source_delete', 'epoch', 'capability'])
def test_source_prefix_preview_revalidates_original_proof_before_publication(database, monkeypatch, mutation):
    clock = [6 * W + 1000]
    monkeypatch.setattr('time.time', lambda: clock[0] / 1000)

    async def run():
        for index in range(6):
            record(index)
        manager = manager_for('7m')
        agg = manager.bar_aggregator
        agg.publisher.set_update_throttle_ms(1000)
        agg.publisher.set_update_requirement(lambda state: False)
        agg._previews.start()
        observed, recoveries = [], []
        async def receive(event):
            observed.append((event.event_type.value, event.bar.quote_volume))
        manager.event_bus.subscribe(receive)
        manager.aggregator_bridge._require_recovery = recoveries.append
        try:
            for update in range(3):
                ref = record(6, quote=2.0 + update, closed=False, sequence=clock[0] + update)['ref']
                await feed(manager, '7m', replace(incoming(6, quote=2.0 + update, closed=False, ref=ref),
                                                source=BarInputSource.REALTIME))
            state = agg.get_pipeline('7m').bar_state.get_active('binance', 'futures', 'BTCUSDT', 0)
            assert state._preview_dirty and len(agg._previews.pending) == 1
            before = list(observed)
            if mutation == 'prefix':
                record(0, quote=1.0, sequence=clock[0] + 100)
            elif mutation == 'tail':
                record(6, quote=99.0, closed=False, sequence=clock[0] + 100)
            elif mutation in {'target_delete', 'source_delete'}:
                klines_repo.delete_klines('BTCUSDT', '7m' if mutation == 'target_delete' else '1m',
                                         market_type='futures')
            elif mutation == 'epoch':
                agg.source_recovery_reader.reset_binding()
            elif mutation == 'capability':
                from app.data_engine.market_data import kline_metrics
                monkeypatch.setattr(kline_metrics, 'kline_available_fields', lambda *args: frozenset())
            clock[0] += 2000
            for entry in agg._previews.pending.values():
                entry.due = asyncio.get_running_loop().time()
            await agg._previews._drain()
            if mutation == 'none':
                assert observed[-1] == ('bar.updated', 16.0) and len(observed) == len(before) + 1
                assert state.preview_published_version == state.preview_input_version
            else:
                assert observed == before
                assert state.preview_published_version < state.preview_input_version
            assert bool(recoveries) == (mutation in {'target_delete', 'source_delete'})
            assert not agg._previews.pending and not agg._previews.inflight
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())


@pytest.mark.parametrize('action', ['cancel', 'detach'])
def test_source_prefix_preview_holds_budget_until_physical_read_finishes(database, monkeypatch, action):
    import threading
    clock = [6 * W + 1000]
    monkeypatch.setattr('time.time', lambda: clock[0] / 1000)

    async def run():
        for index in range(6):
            record(index)
        manager = manager_for('7m')
        agg = manager.bar_aggregator
        agg.publisher.set_update_throttle_ms(1000)
        agg.publisher.set_update_requirement(lambda state: False)
        agg._previews.start()
        entered, released = threading.Event(), threading.Event()
        try:
            for update in range(3):
                ref = record(6, quote=2.0 + update, closed=False, sequence=clock[0] + update)['ref']
                await feed(manager, '7m', replace(incoming(6, quote=2.0 + update, closed=False, ref=ref),
                                                source=BarInputSource.REALTIME))
            validate = kline_sources.validate_component_preview
            def held(*args, **kwargs):
                entered.set()
                assert released.wait(10)
                return validate(*args, **kwargs)
            monkeypatch.setattr(kline_sources, 'validate_component_preview', held)
            clock[0] += 2000
            for entry in agg._previews.pending.values():
                entry.due = asyncio.get_running_loop().time()
            agg._previews._wake()
            task = agg._previews.task
            async with asyncio.timeout(5):
                while not entered.is_set():
                    await asyncio.sleep(.01)
            reserved = manager.memory_budget.snapshot()['reserved_bytes']
            assert reserved > 2 * 16384
            before = agg._previews.metrics['published']
            if action == 'cancel':
                task.cancel()
            else:
                agg.remove_target('BTCUSDT', '7m', market_type='futures')
            await asyncio.sleep(.02)
            assert not task.done() and manager.memory_budget.snapshot()['reserved_bytes'] >= reserved
            released.set()
            if action == 'cancel':
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
            assert agg._previews.metrics['published'] == before
            assert not agg._previews.pending and not agg._previews.inflight
        finally:
            released.set()
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())


@pytest.mark.parametrize('custom_validator', ['source_window', 'component_preview'])
def test_custom_source_validators_keep_eager_contract(database, monkeypatch, custom_validator):
    clock = [6 * W + 1000]
    monkeypatch.setattr('time.time', lambda: clock[0] / 1000)

    async def run():
        for index in range(6):
            record(index)
        manager = manager_for('7m')
        agg = manager.bar_aggregator
        agg.publisher.set_update_throttle_ms(1000)
        agg.publisher.set_update_requirement(lambda state: False)
        agg._previews.start()
        storage = manager.query_engine.storage
        name = 'validate_' + custom_validator
        original = getattr(storage, name)
        def custom(*args, **kwargs):
            return original(*args, **kwargs)
        monkeypatch.setattr(storage, name, custom)
        try:
            for update in range(5):
                ref = record(6, quote=2.0 + update, closed=False, sequence=clock[0] + update)['ref']
                await feed(manager, '7m', replace(incoming(6, quote=2.0 + update, closed=False, ref=ref),
                                                source=BarInputSource.REALTIME))
            state = agg.get_pipeline('7m').bar_state.get_active('binance', 'futures', 'BTCUSDT', 0)
            assert state._source_recovery is not None and not state._preview_dirty
            assert state.preview_input_version == state.preview_computed_version
            assert state.quote_volume == 18.0
            assert not agg._previews.pending and state._preview_deferred_inputs == 0
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())


def test_source_only_quiet_tail_is_published_by_original_deadline(database, monkeypatch):
    clock = [6 * W + 1000]
    monkeypatch.setattr('time.time', lambda: clock[0] / 1000)

    async def run():
        for index in range(6):
            record(index)
        manager = manager_for('7m')
        agg = manager.bar_aggregator
        agg.publisher.set_update_requirement(lambda state: False)
        agg._previews.start()
        observed = []
        async def receive(event):
            observed.append(event.bar.quote_volume)
        manager.event_bus.subscribe(receive)
        try:
            for update in range(2):
                ref = record(6, quote=2.0 + update, closed=False, sequence=clock[0] + update)['ref']
                await feed(manager, '7m', replace(incoming(6, quote=2.0 + update, closed=False, ref=ref),
                                                source=BarInputSource.REALTIME))
            state = agg.get_pipeline('7m').bar_state.get_active('binance', 'futures', 'BTCUSDT', 0)
            assert state._preview_dirty and agg._previews.timer is not None
            clock[0] += 1000
            # No explicit drain, wake, new input or alternate timer.
            async with asyncio.timeout(5):
                while state.preview_published_version < state.preview_input_version:
                    await asyncio.sleep(.01)
            assert not state._preview_dirty and observed == [14.0, 15.0]
            assert agg._previews.metrics['published'] == 1
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())
