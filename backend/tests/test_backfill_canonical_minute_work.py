import asyncio

import pytest

from app.data_engine.backfill.canonical_minute_work import CanonicalMinuteWork
from app.data_engine.storage.revisions import StaleAcquisition, series_values
from tests.test_backfill_dependency_pipeline import setup_pipeline, request, mixed_query, MINUTE


def test_overlapping_minute_waiter_takes_over_after_owner_cancellation():
    async def run():
        work = CanonicalMinuteWork()
        entered = asyncio.Event()

        async def owner():
            claim = await work.claim('BTC', ((0, 3),))
            try:
                entered.set()
                await asyncio.Future()
            finally:
                work.release(claim)

        producer = asyncio.create_task(owner())
        await entered.wait()
        waiter = asyncio.create_task(work.claim('BTC', ((2, 5),)))
        other = await asyncio.wait_for(work.claim('BTC', ((6, 6),)), 1)
        assert not waiter.done()
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        work.release(await asyncio.wait_for(waiter, 1))
        work.release(other)
        assert not work._active

    asyncio.run(run())


def test_waiting_chart_reuses_committed_minutes_and_only_requests_uncovered_tail(mixed_query, monkeypatch):
    async def run():
        coordinator, engine, transport, server, started, release, calls = await setup_pipeline(mixed_query, monkeypatch)
        # Trigger identical historical gaps via the read-repair path, without
        # using the separate forced-refresh contract.
        async def detect(**kwargs):
            return engine._trusted_finality_refresh_gaps(**kwargs)
        monkeypatch.setattr(engine.detector, 'detect', detect)

        def demand(period):
            item = request(period)
            item.metadata.pop('requires_trusted_finality')
            return item

        pending = [asyncio.create_task(coordinator.request_and_wait(demand(89)))]
        try:
            await asyncio.wait_for(started.wait(), 5)
            claimed = asyncio.Event()
            original = engine._minute_work.claim

            async def claim(*args):
                claimed.set()
                return await original(*args)

            monkeypatch.setattr(engine._minute_work, 'claim', claim)
            pending.append(asyncio.create_task(coordinator.request_and_wait(demand(97))))
            await asyncio.wait_for(claimed.wait(), 5)
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*pending), 20)
            assert all(result.status == 'completed' for result in results), [r.error for r in results]
            minute_requests = [(start, stop) for _, iv, start, stop in calls if iv == '1m']
            opens = [at for start, stop in minute_requests for at in range(start, stop+1, MINUTE)]
            assert sorted(opens) == list(range(0, 97*MINUTE, MINUTE)), calls
            assert engine.metrics.snapshot()['counters']['minute_rows_reused_after_admission'] == 89
            for period in (89, 97):
                result = mixed_query.query('BTCUSDT', f'{period}m', start_ms=0, end_ms=period*MINUTE-1,
                    market_type='futures', limit=1, min_revision=mixed_query.storage.revision_store.head())
                assert result.complete and result.bars[0].volume == period
                assert result.bars[0].taker_buy_quote == 2*period
        finally:
            release.set()
            await coordinator.shutdown()
            await asyncio.gather(*pending, return_exceptions=True)
            await engine.close()
            await transport.stop()
            await server.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize('deleted', [False, True])
def test_family_retry_distinguishes_content_from_deletion(mixed_query, deleted):
    from app.data_engine.storage import klines_repo
    from tests.test_mixed_history_reader import row

    storage = mixed_query.storage
    store = storage.revision_store
    scope = store.acquisition()
    storage.upsert_bars('BTCUSDT', '1m', [row(0, MINUTE)], source='backfill', market_type='futures')
    if deleted:
        storage.delete_bars('BTCUSDT', '1h', 0, 0, exchange='binance', market_type='futures')
    with klines_repo._connect() as conn, pytest.raises(StaleAcquisition) as error:
        scope.check(conn, series_values('BTCUSDT', '10007m', 'binance', 'futures'))
    assert error.value.can_replan is not deleted
