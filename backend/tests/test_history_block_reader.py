"""H127 public facade against real canonical SQLite and D126/B130 owners."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
import gc
import threading
import weakref

import pytest

from app.data_engine.aggregation.blocks import BlockRevisionChanged, BlockUnavailable
from app.data_engine.aggregation.core import combine
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.memory_budget import MemoryBudgetExceeded
from app.data_engine.storage import klines_repo
from tests.test_shared_blocks_integration import dm, write, KEY, DAY, read_rows
from tests.test_shared_aggregation_blocks import assert_idle


def read(dm, start=0, end=120 * DAY, **kwargs):
    with dm.read_history_blocks(KEY, start, end, **kwargs) as page:
        values = tuple(block.summary for block in page.blocks)
    return values, page.receipt


def test_facade_returns_immutable_revisioned_blocks_and_post_exit_receipt(dm):
    with dm.read_history_blocks(KEY, 0, 120 * DAY) as page:
        with pytest.raises(BlockRevisionChanged):
            _ = page.receipt
        blocks = page.blocks
        assert len(blocks) == 8
        result = combine([b.summary for b in blocks])
        assert result.is_authoritative(0, 120 * DAY)
        assert result.values.volume == pytest.approx(sum(b.volume for b in read_rows(dm)))
        assert all(b.key.series == KEY and b.summary.revisions == result.revisions for b in blocks)
        with pytest.raises(FrozenInstanceError):
            blocks[0].version = -1
    receipt = page.receipt
    assert receipt.complete and receipt.page_range == (0, 120 * DAY)
    assert receipt.continuation is None and receipt.storage_rows == 120
    assert not receipt.unavailable_ranges and not receipt.missing_fields
    with pytest.raises(BlockRevisionChanged):
        _ = page.blocks
    with pytest.raises(FrozenInstanceError):
        receipt.complete = False
    assert_idle(dm.shared_blocks)
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0


@pytest.mark.parametrize('direction', ['asc', 'desc'])
@pytest.mark.parametrize('page_size', [1, 7, 16, 33, 256])
def test_bounded_pages_cover_exact_range_in_both_directions(dm, direction, page_size):
    cursor = None
    pieces = []
    receipts = []
    while True:
        values, receipt = read(dm, max_rows=page_size, direction=direction, cursor=cursor)
        assert receipt.complete
        assert (receipt.page_range[1] - receipt.page_range[0]) // DAY <= page_size
        assert receipt.storage_rows <= page_size
        assert_idle(dm.shared_blocks)
        pieces.extend(values)
        receipts.append(receipt)
        cursor = receipt.continuation
        if cursor is None:
            break
    result = combine(sorted(pieces, key=lambda p: p.coverage.ranges[0][0]))
    assert result.is_authoritative(0, 120 * DAY)
    assert result.values.volume == pytest.approx(sum(b.volume for b in read_rows(dm)))
    assert all(r.revisions == receipts[0].revisions for r in receipts)


def test_warm_pages_avoid_candle_row_io_and_do_not_reserve_decode_allowance(dm, monkeypatch):
    first, _ = read(dm)
    builds = dm.shared_blocks.snapshot()['builds']
    monkeypatch.setattr(dm.query_engine.storage, 'query_bars', lambda *a, **k: pytest.fail('warm candle read'))
    limit, usage, roots = dm.memory_budget._owners['history-query']
    dm.memory_budget._owners['history-query'] = (32 * 1024, usage, roots)
    second, receipt = read(dm)
    assert second == first and receipt.cache_hits == 8 and receipt.storage_rows == 0
    assert dm.shared_blocks.snapshot()['builds'] == builds
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0


def test_missing_and_untrusted_slots_are_partial_not_exhausted_or_budget_gaps(dm):
    storage = dm.query_engine.storage
    storage.delete_bars('BTCUSDT', '1d', start_ms=2 * DAY, end_ms=3 * DAY, market_type='futures')
    with klines_repo._connect() as conn:
        conn.execute("UPDATE klines SET source='unverified' WHERE open_time=?", (4 * DAY,))
        conn.commit()
    values, receipt = read(dm, end=10 * DAY)
    assert not receipt.complete and receipt.unavailable_ranges == ((2 * DAY, 5 * DAY),)
    assert receipt.continuation is None  # end of requested page, not proof of listing exhaustion
    assert all(v.all_authoritative for v in values)
    warm, again = read(dm, end=10 * DAY)
    assert warm == values and again.unavailable_ranges == receipt.unavailable_ranges
    assert again.storage_rows == 0


def test_unknown_requested_enhancements_remain_unknown(dm):
    with klines_repo._connect() as conn:
        conn.execute('UPDATE klines SET quote_volume=NULL WHERE open_time=?', (2 * DAY,))
        conn.commit()
    values, receipt = read(dm, end=16 * DAY, required_fields=('close', 'quote_volume'))
    assert not receipt.complete and not receipt.unavailable_ranges
    assert receipt.missing_fields == ('quote_volume',) and values[0].values.quote_volume is None
    _, core = read(dm, end=16 * DAY)
    assert core.complete and core.cache_hits == 1


def test_empty_page_and_large_request_remain_bounded(dm, monkeypatch):
    calls = []
    query = dm.query_engine.storage.query_bars
    def counted(*a, **kw):
        calls.append(kw)
        return query(*a, **kw)
    monkeypatch.setattr(dm.query_engine.storage, 'query_bars', counted)
    values, receipt = read(dm, start=120 * DAY, end=20_000 * DAY)
    assert not values and not receipt.complete
    assert receipt.unavailable_ranges == ((120 * DAY, 376 * DAY),)
    assert receipt.continuation.position_ms == 376 * DAY
    assert len(calls) == 1 and calls[0]['limit'] == 257
    assert calls[0]['start_ms'] == 120 * DAY and calls[0]['end_ms'] == 376 * DAY - 1
    assert_idle(dm.shared_blocks)


@pytest.mark.parametrize('mutation', ['amend', 'delete', 'empty-delete', 'external'])
def test_continuation_rejects_canonical_revision_changes(dm, mutation):
    _, receipt = read(dm, max_rows=16)
    if mutation == 'amend':
        write([replace(read_rows(dm)[20], volume=1, high=2, close=1)])
    elif mutation == 'external':
        import subprocess, sys
        subprocess.run([sys.executable, '-c',
            "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute('UPDATE klines SET volume=1 WHERE open_time=?',(20*86400000,));c.commit()",
            str(klines_repo.KLINES_DB_PATH)], check=True)
    else:
        start = 20 if mutation == 'delete' else 200
        dm.query_engine.storage.delete_bars('BTCUSDT', '1d', start_ms=start * DAY,
                                           end_ms=start * DAY, market_type='futures')
    with pytest.raises(BlockRevisionChanged):
        read(dm, cursor=receipt.continuation)
    _, fresh = read(dm)
    assert fresh.revisions != receipt.revisions
    assert_idle(dm.shared_blocks)


def test_unrelated_writes_and_rollback_preserve_cursor(dm):
    _, receipt = read(dm, max_rows=16)
    write(read_rows(dm)[:2], symbol='ETHUSDT')
    with klines_repo._connect() as conn:
        conn.execute('UPDATE klines SET volume=0')
        conn.rollback()
    _, next_page = read(dm, cursor=receipt.continuation)
    assert next_page.complete and next_page.revisions == receipt.revisions


@pytest.mark.parametrize('point', ['inside', 'read', 'rebind', 'policy'])
def test_old_page_never_receives_success_receipt(dm, monkeypatch, point):
    page = None
    if point == 'read':
        original = dm.query_engine.storage.query_bars
        def changed(*a, **k):
            rows = original(*a, **k)
            dm.query_engine.storage.delete_bars('BTCUSDT', '1d', market_type='futures')
            return rows
        monkeypatch.setattr(dm.query_engine.storage, 'query_bars', changed)
    with pytest.raises(BlockRevisionChanged):
        with dm.read_history_blocks(KEY, 0, 16 * DAY) as page:
            if point == 'inside':
                dm.query_engine.storage.delete_bars('BTCUSDT', '1d', market_type='futures')
            elif point == 'rebind':
                dm.set_storage(klines_repo.KlinesRepoAdapter())
            elif point == 'policy':
                dm.query_engine.set_history_policy(object())
    if page is not None:
        with pytest.raises(BlockRevisionChanged):
            _ = page.receipt
        with pytest.raises(BlockRevisionChanged):
            _ = page.blocks
    assert_idle(dm.shared_blocks)


@pytest.mark.parametrize('point', ['before', 'read', 'consumer'])
def test_cancel_is_local_and_releases_all_admission(dm, monkeypatch, point):
    event = threading.Event()
    page = None
    original = dm.query_engine.storage.query_bars
    def cancelled_read(*a, **kw):
        rows = original(*a, **kw)
        event.set()
        return rows
    if point == 'before':
        event.set()
        monkeypatch.setattr(dm.query_engine.storage, 'query_bars', lambda *a, **k: pytest.fail('cancelled read'))
    elif point == 'read':
        monkeypatch.setattr(dm.query_engine.storage, 'query_bars', cancelled_read)
    with pytest.raises(CancelledError):
        with dm.read_history_blocks(KEY, 0, 16 * DAY, cancel=event) as page:
            if point == 'consumer':
                event.set()
    if page is not None:
        with pytest.raises(BlockRevisionChanged):
            _ = page.receipt
    assert_idle(dm.shared_blocks)
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0


def test_one_consumer_close_preserves_other_lease_then_releases_handles(dm):
    with dm.read_history_blocks(KEY, 0, 16 * DAY) as first:
        reference = weakref.ref(first._leases[0]._entry)
        with dm.read_history_blocks(KEY, 0, 16 * DAY) as second:
            assert first.blocks[0] is second.blocks[0]
        assert first.blocks and second.receipt.complete
        assert dm.shared_blocks.snapshot()['leases'] == 1
    dm.shared_blocks.collect()
    gc.collect()
    assert reference() is None  # retained page handles keep receipts, not payloads
    assert_idle(dm.shared_blocks, empty=True)


@pytest.mark.parametrize('fault', ['duplicate', 'outside', 'grid', 'oversized', 'exception'])
def test_bad_storage_pages_abort_without_false_coverage(dm, monkeypatch, fault):
    query = dm.query_engine.storage.query_bars
    def broken(*a, **kw):
        if fault == 'exception':
            raise OSError('unavailable storage')
        rows = query(*a, **kw)
        if fault == 'duplicate':
            rows[1] = rows[0]
        elif fault == 'outside':
            rows[0]['open_time'] = 999 * DAY
        elif fault == 'grid':
            rows[0]['open_time'] += 1000
        else:
            rows[0]['source'] = 'x' * 500_000
        return rows
    monkeypatch.setattr(dm.query_engine.storage, 'query_bars', broken)
    with pytest.raises((BlockUnavailable, MemoryBudgetExceeded)):
        read(dm, end=16 * DAY)
    assert_idle(dm.shared_blocks, empty=True)
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0


def test_wrong_actual_close_boundary_is_not_accepted(dm, monkeypatch):
    query = dm.query_engine.storage.query_bars
    def altered(*a, **kw):
        rows = query(*a, **kw)
        rows[1]['close_time'] -= 1000
        return rows
    monkeypatch.setattr(dm.query_engine.storage, 'query_bars', altered)
    _, receipt = read(dm, end=16 * DAY)
    assert not receipt.complete and receipt.unavailable_ranges == ((DAY, 2 * DAY),)


@pytest.mark.parametrize('source', [replace(KEY, interval='4d'), replace(KEY, interval='1M'),
    replace(KEY, interval='1w'), replace(KEY, price_adjustment='adjusted'),
    replace(KEY, exchange='unknown')])
def test_unsupported_source_is_explicit(dm, source):
    with pytest.raises(ValueError):
        with dm.read_history_blocks(source, 0, 16 * DAY):
            pytest.fail('unqualified source')


@pytest.mark.parametrize('options', [dict(max_rows=0), dict(max_rows=257), dict(max_rows=True),
    dict(direction='sideways'), dict(required_fields=()), dict(required_fields=('vwap',))])
def test_invalid_options_are_rejected_before_io(dm, monkeypatch, options):
    monkeypatch.setattr(dm.query_engine.storage, 'query_bars', lambda *a, **k: pytest.fail('invalid request I/O'))
    with pytest.raises(ValueError):
        read(dm, **options)


def test_cursor_cannot_cross_identity_range_direction_or_fields(dm):
    _, receipt = read(dm, max_rows=16)
    cursor = receipt.continuation
    for bad in [replace(cursor, source=replace(KEY, symbol='ETHUSDT')),
                replace(cursor, start_ms=DAY), replace(cursor, direction='desc'),
                replace(cursor, position_ms=17), replace(cursor, required_fields=('close',))]:
        with pytest.raises(ValueError):
            read(dm, cursor=bad)


def test_explicit_budget_pressure_does_not_return_a_gap_receipt(dm):
    limit, usage, roots = dm.memory_budget._owners['history-query']
    dm.memory_budget._owners['history-query'] = (32 * 1024, usage, roots)
    with pytest.raises(MemoryBudgetExceeded):
        read(dm)
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
    assert dm.query_engine.history_blocks.snapshot()['accepted_pages'] == 0


def test_no_backfill_no_cache_adoption_no_target_writer(dm, monkeypatch):
    monkeypatch.setattr(dm.query_engine, '_backfill_trigger', lambda *a, **k: pytest.fail('network demand'))
    monkeypatch.setattr(dm.query_engine.storage, 'upsert_bars', lambda *a, **k: pytest.fail('target write'))
    before = dm.cache.snapshot()['total_bars']
    _, receipt = read(dm)
    assert receipt.complete and dm.cache.snapshot()['total_bars'] == before
    assert dm.query_engine.snapshot()['history_blocks']['accepted_pages'] == 1


def test_storage_rebinding_rejects_even_equal_numeric_cursor_versions(dm):
    _, first = read(dm, max_rows=16)
    dm.set_storage(klines_repo.KlinesRepoAdapter())
    with pytest.raises(BlockRevisionChanged):
        read(dm, cursor=first.continuation)


def test_consumer_exception_never_leaves_a_receipt_or_lease(dm):
    with pytest.raises(RuntimeError, match='consumer failed'):
        with dm.read_history_blocks(KEY, 0, 16 * DAY) as page:
            raise RuntimeError('consumer failed')
    with pytest.raises(BlockRevisionChanged):
        _ = page.receipt
    assert_idle(dm.shared_blocks)
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0


@pytest.mark.parametrize('kind', ['session', 'unknown', 'failure'])
def test_calendar_qualification_fails_explicitly(dm, kind):
    class Policy:
        def calendar_for(self, series):
            if kind == 'failure':
                raise OSError('calendar unavailable')
            return object() if kind == 'session' else None
    dm.query_engine.set_history_policy(Policy())
    with pytest.raises((ValueError, BlockUnavailable)):
        read(dm)
    assert dm.query_engine.history_blocks.snapshot()['storage_reads'] == 0


def test_repeated_pagination_uses_bounded_shared_retention(dm):
    dm.shared_blocks.max_entries = 2
    for _ in range(3):
        cursor = None
        while True:
            _, receipt = read(dm, max_rows=16, cursor=cursor)
            assert receipt.complete
            state = dm.shared_blocks.snapshot()
            assert state['entries'] <= 2 and state['retired_entries'] == 0
            assert_idle(dm.shared_blocks)
            assert dm.memory_budget.snapshot()['reserved_bytes'] == 0
            cursor = receipt.continuation
            if cursor is None:
                break
    assert dm.shared_blocks.snapshot()['evictions'] >= 20


@pytest.mark.parametrize('bounds', [(1, DAY), (0, DAY + 1), (DAY, DAY), (-DAY, DAY), (0, 99999 * DAY)])
def test_partial_or_future_source_ranges_are_not_silently_reinterpreted(dm, bounds):
    with pytest.raises(ValueError):
        read(dm, start=bounds[0], end=bounds[1])


def test_forming_storage_row_is_not_a_closed_prefix(dm, monkeypatch):
    query = dm.query_engine.storage.query_bars
    def forming(*a, **kw):
        rows = query(*a, **kw)
        rows[0]['is_closed'] = False
        return rows
    monkeypatch.setattr(dm.query_engine.storage, 'query_bars', forming)
    _, receipt = read(dm, end=16 * DAY)
    assert not receipt.complete and receipt.unavailable_ranges == ((0, DAY),)


@pytest.mark.parametrize('cancel_owner', [True, False])
def test_concurrent_cold_readers_share_build_and_isolate_cancellation(dm, monkeypatch, cancel_owner):
    from concurrent.futures import ThreadPoolExecutor
    import time
    import app.data_engine.data_manager.history_blocks as module
    entered, release = threading.Event(), threading.Event()
    cancel_first, cancel_second = threading.Event(), threading.Event()
    original = module.summarize
    def paused(*a, **kw):
        entered.set()
        assert release.wait(5)
        return original(*a, **kw)
    monkeypatch.setattr(module, 'summarize', paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read, dm, end=16 * DAY, cancel=cancel_first)
        assert entered.wait(5)
        second = pool.submit(read, dm, end=16 * DAY, cancel=cancel_second)
        try:
            deadline = time.monotonic() + 5
            while dm.shared_blocks.snapshot()['joins'] == 0 and time.monotonic() < deadline:
                time.sleep(.01)
            assert dm.shared_blocks.snapshot()['joins'] == 1
            (cancel_first if cancel_owner else cancel_second).set()
        finally:
            release.set()
        cancelled, survivor = (first, second) if cancel_owner else (second, first)
        with pytest.raises(CancelledError):
            cancelled.result(5)
        assert survivor.result(5)[1].complete
    assert dm.shared_blocks.snapshot()['builds'] == 1
    assert dm.query_engine.history_blocks.snapshot()['storage_reads'] == 2
    assert_idle(dm.shared_blocks)
    assert dm.memory_budget.snapshot()['reserved_bytes'] == 0


def test_canonical_reader_requires_a_matching_durable_revision_owner(dm, monkeypatch):
    monkeypatch.setattr(dm.query_engine.storage, 'revision_store', None)
    with pytest.raises(BlockUnavailable):
        read(dm)
    assert dm.query_engine.history_blocks.snapshot()['storage_reads'] == 0
