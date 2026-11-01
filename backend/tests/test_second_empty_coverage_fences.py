"""Empty-second evidence cannot outlive deletion or cross semantic identities."""
import subprocess
import sys

import pytest

from app.data_engine.series_identity import KlineSeriesIdentity
from app.data_engine.storage import klines_repo, native_empty_seconds, trade_empty_buckets
from app.data_engine.storage.revisions import StaleAcquisition, acquisition_scope

START = 1_793_232_000_000


@pytest.fixture(params=['upbit', 'kraken'])
def coverage(request, tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', tmp_path / 'bars.sqlite')
    klines_repo.init_klines_storage()
    exchange = request.param
    symbol = 'BTC/KRW' if exchange == 'upbit' else 'BTC/USD'
    store = klines_repo.KlinesRepoAdapter()
    if exchange == 'upbit':
        record = lambda ranges: native_empty_seconds.record(symbol, ranges)
        read = lambda: native_empty_seconds.read(symbol, START, START + 9000)
        calendar = lambda: native_empty_seconds.make_calendar(symbol)
    else:
        record = lambda ranges: trade_empty_buckets.record(exchange, 'spot', symbol, '1s', ranges)
        read = lambda: trade_empty_buckets.read(exchange, 'spot', symbol, '1s', START, START + 9000)
        calendar = lambda: trade_empty_buckets.make_calendar(exchange, 'spot', symbol, '1s')
    return store, exchange, symbol, record, read, calendar


def test_late_empty_receipt_cannot_resurrect_deleted_coverage(coverage):
    store, exchange, symbol, record, read, _ = coverage
    before = store.revision_store.acquisition()
    klines_repo.delete_klines(symbol, '1s', START, START + 9000, exchange=exchange)
    with acquisition_scope(before), pytest.raises(StaleAcquisition):
        record([(START, START + 9000)])
    assert read() == []
    with acquisition_scope(store.revision_store.acquisition()):
        record([(START, START + 9000)])
    assert read() == [(START, START + 9000)]


def test_coverage_revision_invalidates_cached_range_after_another_process_deletes(coverage):
    store, exchange, symbol, record, read, make_calendar = coverage
    before = store.revision_store.head()
    record([(START, START + 9000)])
    assert store.revision_store.head() > before
    calendar = make_calendar()
    assert calendar.first_expected_open(START, START + 9000, '1s') is None
    code = f'''from app.data_engine.storage import klines_repo
klines_repo.KLINES_DB_PATH={str(klines_repo.KLINES_DB_PATH)!r}
klines_repo.delete_klines({symbol!r}, '1s', {START}, {START + 9000}, exchange={exchange!r})
'''
    child = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, timeout=60)
    assert child.returncode == 0, child.stderr
    assert read() == []
    assert calendar.first_expected_open(START, START + 9000, '1s') == START


def test_foreign_vendor_candle_does_not_invalidate_or_hide_default_empty_proof(coverage):
    store, exchange, symbol, record, read, _ = coverage
    record([(START, START + 9000)])
    identity = KlineSeriesIdentity.for_exchange(exchange, provider_id='another-vendor')
    row = dict(open_time=START, close_time=START + 999, open=10, high=10, low=10,
               close=10, volume=1, quote_volume=10, trades=1, taker_buy_base=0, taker_buy_quote=0)
    store.upsert_bars(symbol, '1s', [row], 'backfill_rest_verified', exchange=exchange, series_identity=identity)
    assert read() == [(START, START + 9000)]
    record([(START, START + 9000)])
    assert read() == [(START, START + 9000)]


def test_record_is_atomic_when_later_range_is_invalid(coverage):
    store, _, _, record, read, _ = coverage
    revision = store.revision_store.head()
    with pytest.raises(ValueError):
        record([(START, START + 1000), (START + 2001, START + 3000)])
    assert read() == []
    assert store.revision_store.head() == revision
