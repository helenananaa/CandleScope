"""R129 prefix preparation against canonical SQLite, H127 and B130."""
import asyncio
from dataclasses import replace
import threading

import pytest

from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.data_manager.history_prefix import HistoryPrefixReader, PREFIX_BYTES
from tests.test_shared_blocks_integration import dm, write, read_rows, KEY, DAY
from tests.test_shared_aggregation_blocks import assert_idle


@pytest.mark.parametrize('page_rows', [1, 7, 16, 33, 256])
def test_complete_prefix_folds_without_retaining_pages_and_reuses_shared_blocks(dm, page_rows):
    async def check():
        reader = HistoryPrefixReader(dm.query_engine)
        expected = sum(row.volume for row in read_rows(dm))
        async with reader.stage(KEY, 0, 120 * DAY, page_rows=page_rows) as prefix:
            assert prefix.summary.is_authoritative(0, 120 * DAY)
            assert prefix.summary.values.volume == pytest.approx(expected)
            assert prefix.summary.coverage.count == 120
            assert prefix.summary.coverage.ranges == ((0, 120 * DAY),)
            assert prefix.storage_rows == 120
            blocks = dm.shared_blocks.snapshot()
            assert blocks['leases'] == blocks['views'] == blocks['inflight'] == 0
            assert dm.memory_budget.snapshot()['reserved_bytes'] == PREFIX_BYTES * 2
        assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
        async with reader.stage(KEY, 0, 120 * DAY, page_rows=page_rows) as warm:
            assert warm.summary == prefix.summary
            assert warm.storage_rows == 0 and warm.cache_hits > 0
    asyncio.run(check())


def test_gap_discards_partial_prefix_without_inventing_completion(dm):
    dm.query_engine.storage.delete_bars('BTCUSDT', '1d', start_ms=17 * DAY,
                                       end_ms=17 * DAY, market_type='futures')
    async def check():
        with pytest.raises(BlockUnavailable):
            async with HistoryPrefixReader(dm.query_engine).stage(KEY, 0, 120 * DAY, page_rows=16):
                pytest.fail('gap prefix adopted')
    asyncio.run(check())
    assert_idle(dm.shared_blocks)
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0


@pytest.mark.parametrize('when', ['between_pages', 'after_last_page'])
def test_revision_change_never_returns_a_mixed_prefix(dm, monkeypatch, when):
    reader = HistoryPrefixReader(dm.query_engine)
    original = reader._read_page
    calls = 0
    def changing(*a, **kw):
        nonlocal calls
        result = original(*a, **kw)
        calls += 1
        if calls == (1 if when == 'between_pages' else 8):
            write([replace(read_rows(dm)[0], volume=3)])
        return result
    monkeypatch.setattr(reader, '_read_page', changing)
    async def check():
        with pytest.raises(BlockRevisionChanged):
            async with reader.stage(KEY, 0, 120 * DAY, page_rows=16):
                pytest.fail('stale prefix adopted')
    asyncio.run(check())
    assert_idle(dm.shared_blocks)
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0


def test_cancel_running_page_drains_physical_work_and_releases_reservation(dm, monkeypatch):
    reader = HistoryPrefixReader(dm.query_engine)
    original = reader._read_page
    entered, release = threading.Event(), threading.Event()
    def blocked(*a, **kw):
        entered.set()
        assert release.wait(5)
        return original(*a, **kw)
    monkeypatch.setattr(reader, '_read_page', blocked)
    async def check():
        async def acquire():
            async with reader.stage(KEY, 0, 120 * DAY):
                pytest.fail('cancelled prefix adopted')
        task = asyncio.create_task(acquire())
        try:
            for _ in range(500):
                if entered.is_set():
                    break
                await asyncio.sleep(.01)
            assert entered.is_set()
            task.cancel()
            await asyncio.sleep(.02)
            assert not task.done()
            assert dm.memory_budget.snapshot()['reserved_bytes'] >= PREFIX_BYTES * 2
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(check())
    assert_idle(dm.shared_blocks)
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0


def test_oversized_range_is_rejected_before_io(dm, monkeypatch):
    reader = HistoryPrefixReader(dm.query_engine)
    monkeypatch.setattr(reader, '_read_page', lambda *a, **kw: pytest.fail('oversized read'))
    async def check():
        with pytest.raises(ValueError):
            async with reader.stage(KEY, 0, 65_537 * DAY):
                pytest.fail('oversized prefix')
    asyncio.run(check())
