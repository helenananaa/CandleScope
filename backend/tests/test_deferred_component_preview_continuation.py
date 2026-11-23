"""Recovered source-only previews must keep working across source minutes."""

import asyncio
from dataclasses import replace

import pytest

from app.data_engine.bar_aggregator.models import BarInputSource
from app.data_engine.storage import klines_repo, kline_sources
from tests.test_source_window_recovery import database, record, incoming, manager_for, feed, W


@pytest.mark.parametrize('preserve_updates', [False, True])
def test_source_minute_close_keeps_next_quiet_preview_delivery(database, monkeypatch, preserve_updates):
    clock = [6 * W + 1000]
    monkeypatch.setattr('time.time', lambda: clock[0] / 1000)

    async def run():
        for index in range(6):
            record(index)
        manager = manager_for('8m')
        agg = manager.bar_aggregator
        agg.publisher.set_update_throttle_ms(1000)
        agg.publisher.set_update_requirement(lambda state: preserve_updates)
        agg._previews.start()
        observed = []
        async def receive(event):
            observed.append((event.event_type.value, event.bar.quote_volume))
        manager.event_bus.subscribe(receive)

        async def send(index, quote, closed=False):
            ref = record(index, quote=quote, closed=closed, sequence=clock[0])['ref']
            value = replace(incoming(index, quote=quote, closed=closed, ref=ref),
                            source=BarInputSource.REALTIME)
            await feed(manager, '8m', value)

        try:
            await send(6, 2.0)
            clock[0] += 1
            await send(6, 3.0)
            clock[0] = 7 * W + 1000
            await send(6, 4.0, True)
            clock[0] += 1000
            await send(7, 2.0)
            clock[0] += 1
            await send(7, 3.0)
            state = agg.get_pipeline('8m').bar_state.get_active('binance', 'futures', 'BTCUSDT', 0)
            assert state._source_recovery is not None and state.status.value == 'forming'
            assert not klines_repo.query_klines('BTCUSDT', '1m', market_type='futures')
            clock[0] += 2000
            # The original deadline must deliver without another source input.
            async with asyncio.timeout(5):
                while state.preview_published_version < state.preview_input_version:
                    await asyncio.sleep(.01)
            assert observed[-1] == ('bar.updated', 19.0)
            assert not state._preview_dirty
            clock[0] = 8 * W + 1000
            await send(7, 4.0, True)
            assert state.status.value == 'closed' and state.finality.value == 'authoritative'
            stored = klines_repo.query_klines('BTCUSDT', '8m', market_type='futures')
            assert len(stored) == 1 and stored[0]['quote_volume'] == 20.0
            assert observed[-1] == ('bar.closed', 20.0)
            assert sum(kind == 'bar.closed' for kind, _ in observed) == 1
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())


def test_source_continuation_crosses_original_overlay_compaction_and_target_boundary(database, monkeypatch):
    clock = [6 * W + 1000]
    monkeypatch.setattr('time.time', lambda: clock[0] / 1000)

    async def run():
        for index in range(6):
            record(index)
        manager = manager_for('137m')
        agg = manager.bar_aggregator
        agg.publisher.set_update_throttle_ms(1000)
        agg.publisher.set_update_requirement(lambda state: False)
        agg._previews.start()
        observed = []
        async def receive(event):
            observed.append((event.event_type.value, event.bar.time * 1000, event.bar.quote_volume))
        manager.event_bus.subscribe(receive)
        async def send(index, quote, closed=False):
            ref = record(index, quote=quote, closed=closed, sequence=clock[0])['ref']
            await feed(manager, '137m', replace(incoming(index, quote=quote, closed=closed, ref=ref),
                                               source=BarInputSource.REALTIME))
            clock[0] += 1
        async def wait_latest(state):
            clock[0] += 2000
            async with asyncio.timeout(5):
                while state.preview_published_version < state.preview_input_version:
                    await asyncio.sleep(.01)
        try:
            for index in range(6, 136):
                clock[0] = index * W + 1000
                await send(index, 2.0)
                await send(index, 3.0)
                clock[0] = (index + 1) * W + 1000
                await send(index, 4.0, True)
            await send(136, 2.0)
            await send(136, 3.0)
            state = agg.get_pipeline('137m').bar_state.get_active('binance', 'futures', 'BTCUSDT', 0)
            assert state._source_recovery.version.through_ms > 6 * W
            assert len(state.source_snapshots) <= 128
            await wait_latest(state)
            assert observed[-1] == ('bar.updated', 0, 535.0)
            clock[0] = 137 * W + 1000
            await send(136, 4.0, True)
            stored = klines_repo.query_klines('BTCUSDT', '137m', market_type='futures')
            assert len(stored) == 1
            assert [stored[0][name] for name in ('open', 'high', 'low', 'close', 'volume',
                    'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote')] == (
                    [10., 20., 5., 11., 137., 536., 137, 68.5, 137.])
            assert observed[-1] == ('bar.closed', 0, 536.0)
            await send(137, 2.0)
            await send(137, 3.0)
            next_state = agg.get_pipeline('137m').bar_state.get_active('binance', 'futures', 'BTCUSDT', 137 * W)
            await wait_latest(next_state)
            assert observed[-1] == ('bar.updated', 137 * W, 3.0)
            assert stored == klines_repo.query_klines('BTCUSDT', '137m', market_type='futures')
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())


@pytest.mark.parametrize('permission', [None, 0, 1])
@pytest.mark.parametrize('deleted_symbol', ['BTCUSDT', 'ETHUSDT'])
def test_preview_read_does_not_lend_fresh_prefix_permission_to_old_tail(database, monkeypatch, permission, deleted_symbol):
    from app.data_engine.ingestion.models import DataSource
    from app.data_engine.storage.revisions import Acquisition, acquisition_scope
    from tests.test_source_window_recovery import KEY
    clock = [W + 1000]
    monkeypatch.setattr('time.time', lambda: clock[0] / 1000)

    async def run():
        record(0)
        ref = record(1, closed=False)['ref']
        watermark = kline_sources.rest_watermark()
        klines_repo.delete_klines(deleted_symbol, '2m', market_type='futures')
        with acquisition_scope(Acquisition(1, delete_revision=1)):
            record(0, source=DataSource.HTTP_BACKFILL, watermark=watermark, sequence=9 * W)
        assert kline_sources.capture_source_window(KEY, 0, W, W).permission_floor == 1
        if permission == 1:
            ref = record(1, quote=3.0, closed=False, sequence=10 * W)['ref']
        manager = manager_for('2m')
        recovered = []
        try:
            value = replace(incoming(1, quote=3.0 if permission == 1 else 2.0, closed=False, ref=ref),
                            source=BarInputSource.REALTIME)
            if permission is not None:
                value.extra['source_permission_floor'] = permission
            await feed(manager, '2m', value)
            state = manager.bar_aggregator.get_pipeline('2m').bar_state.get_active('binance', 'futures', 'BTCUSDT', 0)
            assert state._source_recovery.version.permission_floor == 1
            manager.aggregator_bridge._require_recovery = recovered.append
            status = await manager.aggregator_bridge.validate_component_preview(state, revision_floor=1)
            valid = permission == 1 or deleted_symbol == 'ETHUSDT'
            assert status == ('current' if valid else 'canonical_changed')
            assert bool(recovered) == (not valid)
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())


@pytest.mark.parametrize('mutation', ['none', 'closed_leaf', 'canonical', 'target_delete', 'source_delete', 'legacy'])
def test_continued_preview_validates_closed_overlay_outside_original_prefix(database, monkeypatch, mutation):
    clock = [6 * W + 1000]
    monkeypatch.setattr('time.time', lambda: clock[0] / 1000)

    async def run():
        for index in range(6):
            record(index)
        manager = manager_for('9m')
        agg = manager.bar_aggregator
        agg.publisher.set_update_throttle_ms(1000)
        agg.publisher.set_update_requirement(lambda state: False)
        agg._previews.start()
        observed, recoveries = [], []
        async def receive(event):
            observed.append(event.bar.quote_volume)
        manager.event_bus.subscribe(receive)
        manager.aggregator_bridge._require_recovery = recoveries.append
        async def send(index, quote, closed=False):
            ref = record(index, quote=quote, closed=closed, sequence=clock[0])['ref']
            await feed(manager, '9m', replace(incoming(index, quote=quote, closed=closed, ref=ref),
                                            source=BarInputSource.REALTIME))
            clock[0] += 1
        try:
            await send(6, 2.0)
            await send(6, 3.0)
            clock[0] = 7 * W + 1000
            await send(6, 4.0, True)
            await send(7, 2.0)
            await send(7, 3.0)
            clock[0] = 8 * W + 1000
            await send(7, 4.0, True)
            await send(8, 2.0)
            await send(8, 3.0)
            state = agg.get_pipeline('9m').bar_state.get_active('binance', 'futures', 'BTCUSDT', 0)
            assert state._source_recovery.version.through_ms == 6 * W
            assert state._preview_dirty and len(agg._previews.pending) == 1
            before = list(observed)
            if mutation == 'closed_leaf':
                record(6, quote=99.0, sequence=clock[0] + 100)
            elif mutation == 'canonical':
                assert klines_repo.upsert_klines('BTCUSDT', '1m', [dict(open_time=6 * W,
                    close_time=7 * W - 1, open=10., high=20., low=5., close=11., volume=1.,
                    is_closed=True, quote_volume=4., trades=1, taker_buy_base=.5, taker_buy_quote=1.)],
                    source='backfill', market_type='futures') == 1
                with klines_repo._connect() as conn:
                    conn.execute("UPDATE klines SET quote_volume=99 WHERE symbol='BTCUSDT' AND interval='1m'")
                    conn.commit()
            elif mutation in {'target_delete', 'source_delete'}:
                klines_repo.delete_klines('BTCUSDT', '9m' if mutation == 'target_delete' else '1m',
                                         market_type='futures')
            elif mutation == 'legacy':
                with klines_repo._connect() as conn:
                    conn.execute('ALTER TABLE kline_source_heads DROP COLUMN permission_floor')
                    conn.commit()
            clock[0] += 2000
            for entry in agg._previews.pending.values():
                entry.due = asyncio.get_running_loop().time()
            await agg._previews._drain()
            if mutation in {'none', 'legacy'}:
                assert observed == before + [23.0]
                assert state.preview_published_version == state.preview_input_version
            else:
                assert observed == before
                assert state.preview_published_version < state.preview_input_version
            assert bool(recoveries) == (mutation.endswith('delete') or mutation == 'canonical')
            if mutation == 'legacy':
                with klines_repo._connect() as conn:
                    assert 'permission_floor' not in {r[1] for r in conn.execute('PRAGMA table_info(kline_source_heads)')}
        finally:
            await manager.shutdown()
        assert manager.memory_budget.snapshot()['reserved_bytes'] == 0

    asyncio.run(run())
