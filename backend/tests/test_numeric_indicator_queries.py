"""Actual canonical SQLite inputs and public formulas, without alert side effects."""
import asyncio
from dataclasses import replace

import pytest

from app.indicator import create_engine
from app.indicator.query_contracts import BuiltinOutput, IndicatorQuery
from app.indicator.numeric_queries import NumericIndicatorService
from app.indicator.range_result_service import IndicatorRangeResultService
from app.data_engine.data_manager.indicator_inputs import IndicatorInputPort
from tests.test_shared_blocks_integration import dm, read_rows, write, KEY, DAY

OUTPUTS = (BuiltinOutput('RSI', (('period', 14), ('source', 'close')), 'rsi'),
           BuiltinOutput('MACD', (('fast', 12), ('slow', 26), ('signal', 9), ('source', 'close')), 'hist'),
           BuiltinOutput('MA', (('period', 20), ('source', 'close')), 'ma'))


def compute(name, meta, bars):
    engine = create_engine()
    try:
        return engine.compute(meta['symbol'], meta['interval'], meta['market_type'], name,
                              meta['params'], list(bars), exchange=meta['exchange'])
    finally:
        engine.stop()


@pytest.fixture
def query(dm):
    dm.query_engine._cfg.max_limit = 500
    return IndicatorQuery(KEY, OUTPUTS, through_ms=119 * DAY, source_slots=100)


def test_same_semantic_snapshot_shares_public_computation_and_exact_values(dm, query):
    calls = []
    async def actual(name, meta, bars):
        calls.append(name)
        await asyncio.sleep(0.01)
        return compute(name, meta, bars)
    service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=actual)
    async def run():
        first, second = await asyncio.gather(service.query(query), service.query(query))
        assert first.status == second.status == 'ready', (first, second)
        assert first.values == second.values
        assert len(calls) == 3
        again = await service.query(query)
        assert again.cache_hits == 3 and len(calls) == 3
        rows = read_rows(dm)[-100:]
        for output, value in first.values:
            result = compute(output.name, {'symbol': KEY.symbol, 'interval': KEY.interval,
                'market_type': KEY.market_type, 'exchange': KEY.exchange, 'params': dict(output.params)}, rows)
            assert value == result.get_latest()[output.output_id]
        assert first.source_slots == first.closed_rows == 100
        assert first.closed_through == rows[-1].time
    asyncio.run(run())


def test_canonical_amendment_during_calculation_rejects_old_value_and_requeries(dm, query):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def actual(name, meta, bars):
            entered.set()
            await release.wait()
            return compute(name, meta, bars)
        service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=actual)
        pending = asyncio.create_task(service.query(query))
        await asyncio.wait_for(entered.wait(), 5)
        rows = read_rows(dm)
        write([replace(rows[-2], close=rows[-2].close + 100, high=rows[-2].high + 100)])
        release.set()
        stale = await pending
        assert stale.status == 'stale' and stale.values == ()
        current = await service.query(query)
        assert current.status == 'ready', current
        assert current.storage_revision > 0
    asyncio.run(run())


def test_event_frontier_must_match_canonical_confirmed_prices(dm, query):
    async def actual(name, meta, bars):
        pytest.fail('Superseded input entered the calculator')
    old = read_rows(dm)[-1]
    write([replace(old, close=old.close + 1, high=old.high + 1)])
    service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=actual)
    result = asyncio.run(service.query(replace(query, expected_bar=old)))
    assert result.status == 'stale' and result.reason == 'event_values_superseded'


def test_retention_or_configured_page_cap_cannot_silently_change_recursive_seed(dm, query):
    dm.query_engine._cfg.max_limit = 11
    async def actual(name, meta, bars):
        pytest.fail('A clipped seed entered the calculator')
    service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=actual)
    result = asyncio.run(service.query(query))
    assert result.status == 'stale'


def test_owned_subscription_queues_startup_and_releases_only_its_stream(dm, query, monkeypatch):
    from app.data_engine.data_manager.models import DataEvent, DataEventType
    calls, observations, recoveries = [], [], []
    async def ensure(**kwargs):
        calls.append(('ensure', kwargs))
    async def release(**kwargs):
        calls.append(('release', kwargs))
    monkeypatch.setattr(dm, 'ensure_stream', ensure)
    monkeypatch.setattr(dm, 'release_stream', release)
    async def actual(name, meta, bars):
        return compute(name, meta, bars)
    service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=actual)
    dm.bind_indicator_queries(service)
    # This fixture contains1970 data. Lifecycle tests retain the actual SQLite
    # query and event bus, but move the latest-query frontier to that dataset.
    original = service.query
    async def bounded(request):
        return await original(replace(request, through_ms=request.through_ms or query.through_ms))
    monkeypatch.setattr(service, 'query', bounded)
    async def received(observation):
        observations.append(observation)
    async def recover(error):
        recoveries.append(error)
    async def run():
        request = replace(query, through_ms=None)
        first = await dm.subscribe_indicator(request, received, on_recovery=recover, consumer_id='numeric:first')
        second = await dm.subscribe_indicator(request, received, on_recovery=recover, consumer_id='numeric:second')
        assert first.snapshot.status == second.snapshot.status == 'ready'
        assert not observations
        old = read_rows(dm)[-1]
        changed = replace(old, close=old.close + 1, high=old.high + 1)
        write([changed])
        await dm.event_bus.emit(DataEvent(DataEventType.BAR_AMENDED, KEY, bar=changed))
        for _ in range(200):
            if len(observations) == 2:
                break
            await asyncio.sleep(.01)
        assert len(observations) == 2
        assert all(o.baseline and o.snapshot.status == 'ready' for o in observations)
        await first.close()
        assert [c[1]['consumer_id'] for c in calls if c[0] == 'release'] == ['numeric:first']
        assert len(service.subscriptions) == 1
        await service.close()
        assert not service.subscriptions and not service.queries
        assert [c[1]['consumer_id'] for c in calls if c[0] == 'release'] == ['numeric:first', 'numeric:second']
        assert not recoveries
    asyncio.run(run())


def test_numeric_close_drains_inflight_query_without_publishing(dm, query):
    async def run():
        entered = asyncio.Event()
        async def held(name, meta, bars):
            entered.set()
            await asyncio.Event().wait()
        service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=held)
        pending = asyncio.create_task(service.query(query))
        await asyncio.wait_for(entered.wait(), 5)
        await service.close()
        assert pending.cancelled() and not service.queries
        result = await service.query(query)
        assert result.status == 'unavailable' and result.reason == 'service_closed'
    asyncio.run(run())


def test_forming_bar_occupies_one_seed_slot_without_entering_confirmed_formulas(dm, query):
    import time
    today = int(time.time() * 1000) // DAY * DAY
    shift = (today - 120 * DAY) // 1000
    rows = [replace(bar, time=bar.time + shift) for bar in read_rows(dm)]
    write(rows)
    forming = replace(rows[-1], time=today // 1000, is_closed=False,
                      close=9000, high=9000, source='live')
    dm.cache.revision_consumer.sync(force=True)
    dm.cache.upsert(KEY, forming)
    async def actual(name, meta, bars):
        assert len(bars) == 99 and all(bar.is_closed for bar in bars)
        return compute(name, meta, bars)
    service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=actual)
    async def run():
        result = await service.query(replace(query, through_ms=today, expected_bar=forming))
        assert result.status == 'ready', result
        assert result.source_slots == 100 and result.closed_rows == 99
        assert result.closed_through == rows[-1].time
    asyncio.run(run())


def test_public_numeric_query_uses_existing_isolated_history_process(dm, query):
    import os
    from app.indicator.history_worker import history_executor_snapshot, shutdown_builtin_history
    service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService())
    async def run():
        try:
            result = await service.query(query)
            assert result.status == 'ready', result
            state = history_executor_snapshot()
            assert state['worker']['pid'] != os.getpid()
            assert state['input_bars'] == 0
            assert len(result.values) == 3
            assert state['submitted'] == 1
            rows = read_rows(dm)[-100:]
            for output, value in result.values:
                oracle = compute(output.name, {'symbol': KEY.symbol, 'interval': KEY.interval,
                    'market_type': KEY.market_type, 'exchange': KEY.exchange, 'params': dict(output.params)}, rows)
                assert value == oracle.get_latest()[output.output_id]
        finally:
            await service.close()
            await shutdown_builtin_history()
        assert history_executor_snapshot()['started'] is False
    asyncio.run(run())


def test_numeric_subscription_recovery_is_terminal_until_replaced(dm, query, monkeypatch):
    from app.data_engine.data_manager.models import DataEvent, DataEventType
    async def lease(**kwargs):
        pass
    monkeypatch.setattr(dm, 'ensure_stream', lease)
    monkeypatch.setattr(dm, 'release_stream', lease)
    async def actual(name, meta, bars):
        return compute(name, meta, bars)
    service = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=actual)
    original = service.query
    async def bounded(request):
        return await original(replace(request, through_ms=request.through_ms or query.through_ms))
    monkeypatch.setattr(service, 'query', bounded)
    async def run():
        recovered, observations = asyncio.Event(), []
        async def receive(value):
            observations.append(value)
        async def recovery(error):
            recovered.set()
        subscription = await service.subscribe(replace(query, through_ms=None), receive,
            on_recovery=recovery, consumer_id='numeric:recovery')
        dm.event_bus.require_recovery(KEY, 'injected_numeric_delivery_loss')
        await asyncio.wait_for(recovered.wait(), 5)
        assert subscription.snapshot.status == 'stale'
        assert (await subscription.refresh()).reason == 'consumer_recovery_required'
        await dm.event_bus.emit(DataEvent(DataEventType.BAR_CLOSED, KEY, bar=read_rows(dm)[-1]))
        await asyncio.sleep(.01)
        assert observations == []
        await service.close()
        assert not service.subscriptions and not service.queries
    asyncio.run(run())


def test_numeric_same_request_shares_canonical_capture_and_waiter_cancellation(dm, query):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        port = IndicatorInputPort(dm)
        original, captures = port.capture, []
        def capture(request):
            captures.append(request)
            return original(request)
        port.capture = capture
        async def held(name, meta, bars):
            entered.set()
            await release.wait()
            return compute(name, meta, bars)
        service = NumericIndicatorService(port, IndicatorRangeResultService(), compute=held)
        first = asyncio.create_task(service.query(query))
        second = asyncio.create_task(service.query(query))
        await asyncio.wait_for(entered.wait(), 20)
        await asyncio.sleep(.02)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done()
        release.set()
        result = await second
        assert result.status == 'ready'
        assert len(captures) == 1
        assert not service.queries
        await service.close()
    asyncio.run(run())


def test_numeric_new_live_frontier_cannot_join_older_input(dm, query):
    from app.data_engine.data_manager.models import DataEvent, DataEventType
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        port = IndicatorInputPort(dm)
        original, captures = port.capture, []
        def capture(request):
            captures.append(request)
            return original(request)
        port.capture = capture
        async def held(name, meta, bars):
            entered.set()
            await release.wait()
            return compute(name, meta, bars)
        service = NumericIndicatorService(port, IndicatorRangeResultService(), compute=held)
        first = asyncio.create_task(service.query(query))
        await asyncio.wait_for(entered.wait(), 20)
        await dm.event_bus.emit(DataEvent(DataEventType.BAR_UPDATED, KEY, bar=read_rows(dm)[-1]))
        second = asyncio.create_task(service.query(query))
        release.set()
        a, b = await asyncio.gather(first, second)
        assert a.status == b.status == 'ready'
        assert len(captures) == 2
        assert dict(b.stream_version)['sequence'] > dict(a.stream_version)['sequence']
        assert a.latest_closed == b.latest_closed
        await service.close()
        assert not service.flights
    asyncio.run(run())


def test_numeric_input_fingerprint_preserves_sub_wire_precision(dm, query):
    port = IndicatorInputPort(dm)
    before = port.capture(query)
    rows = read_rows(dm)
    dm.cache.upsert(KEY, replace(rows[-1], close=rows[-1].close + 1e-10))
    after = port.capture(query)
    assert before.bars[-1].to_dict() == after.bars[-1].to_dict()
    assert before.fingerprint != after.fingerprint


def test_numeric_process_rejects_unbounded_input_before_submission():
    from app.indicator.history_worker import run_builtin_history_numeric
    async def run():
        with pytest.raises(ValueError, match='bounded input'):
            await run_builtin_history_numeric(OUTPUTS, {}, [None] * 251)
        with pytest.raises(ValueError, match='bounded input'):
            await run_builtin_history_numeric(OUTPUTS * 2, {}, [None])
    asyncio.run(run())


def test_data_manager_shutdown_closes_numeric_and_trading_consumers(dm, query, tmp_path):
    from tests.test_trading_state_stream import make_fixture

    async def run():
        store, accounts, account_id, _, _ = make_fixture(tmp_path)
        trading = dm.bind_trading(accounts)
        subscription = await trading.subscribe_state(account_id)
        events = subscription.events()
        entered = asyncio.Event()

        async def held_compute(_name, _meta, _bars):
            entered.set()
            await asyncio.Event().wait()

        numeric = NumericIndicatorService(IndicatorInputPort(dm), IndicatorRangeResultService(), compute=held_compute)
        dm.bind_indicator_queries(numeric)
        pending = asyncio.create_task(dm.query_indicator(query))
        try:
            first = await anext(events)
            assert first['state']['summary']['balance'] == '1000'
            await asyncio.wait_for(entered.wait(), 5)
            await dm.shutdown()
            assert pending.cancelled()
            assert not numeric.queries and not numeric.flights
            assert trading.diagnostics()['closed'] and trading.diagnostics()['subscriptions'] == 0
            with pytest.raises(StopAsyncIteration):
                await anext(events)
            assert store.updates.diagnostics()['subscriptions'] == 0
            assert accounts.account_summary(account_id)['balance'] == '1000'
        finally:
            await numeric.close()
            await dm.shutdown_trading()
            await events.aclose()
            store.close()

    asyncio.run(run())
