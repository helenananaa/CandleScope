import threading
from decimal import Decimal
from pathlib import Path

from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore


def test_summary_never_combines_old_fills_with_new_cash_flow(tmp_path, monkeypatch):
    store = TradingStore(tmp_path/'accounts.db')
    service = TradingAccountService(store, snapshot_dir=tmp_path/'images')
    account = service.create_account({'kind':'practice','name':'fixture','settings':{'initialBalance':'1000'}})
    aid = account['id']
    fills_read, committed = threading.Event(), threading.Event()
    errors = []
    original = store.fills
    def fills(account_id):
        rows = original(account_id)
        fills_read.set()
        assert committed.wait(3), 'reading a view must not block the matcher writer'
        return rows
    monkeypatch.setattr(store,'fills',fills)
    def writer():
        try:
            assert fills_read.wait(3)
            with store.transaction() as db:
                db.execute("INSERT INTO cash_flows VALUES('deposit',?,'deposit','50.0000000000000000001',1,'fixture')",(aid,))
                db.execute("INSERT INTO fills(id,account_id,exchange,market_type,symbol,side,qty,price,fee,fee_currency,liquidity,ts_ms,source,created_at_ms) VALUES('fill',?,'binance','futures','BTCUSDT','buy','0.1234567890123456789','100','0','USDT','taker',1,'fixture',1)",(aid,))
        except BaseException as exc:
            errors.append(exc)
        finally:
            committed.set()
    thread = threading.Thread(target=writer);thread.start()
    try:
        view = service.account_summary(aid)
        thread.join(3);assert not thread.is_alive() and not errors
        assert view['balance'] == '1000'
        assert view['positions'] == []
        monkeypatch.setattr(store,'fills',original)
        current = service.account_summary(aid)
        assert Decimal(current['balance']) == Decimal('1050.0000000000000000001')
        assert current['positions'][0]['openQty'] == '0.1234567890123456789'
    finally:
        committed.set();thread.join(3);store.close()


def test_nested_reads_preserve_outer_snapshot_and_writer_rollback_ownership(tmp_path):
    import pytest
    store = TradingStore(tmp_path/'accounts.db')
    service = TradingAccountService(store,snapshot_dir=tmp_path/'images')
    aid = service.create_account({'kind':'practice','name':'fixture','settings':{'initialBalance':'1000'}})['id']
    try:
        with store.read_snapshot():
            assert service.account_summary(aid)['balance'] == '1000'
            # The independent writer may commit while this reader is alive.
            def write():
                with store.transaction() as db:
                    db.execute("UPDATE cash_flows SET amount='1200' WHERE account_id=?",(aid,))
            thread=threading.Thread(target=write);thread.start();thread.join(3)
            assert not thread.is_alive()
            assert service.account_summary(aid)['balance'] == '1000'
        assert service.account_summary(aid)['balance'] == '1200'
        with pytest.raises(ValueError):
            with store.transaction() as db:
                db.execute("UPDATE cash_flows SET amount='1500' WHERE account_id=?",(aid,))
                assert service.account_summary(aid)['balance'] == '1500'
                assert db.in_transaction
                raise ValueError('rollback fixture')
        assert service.account_summary(aid)['balance'] == '1200'
    finally:
        store.close()


def test_failed_read_closes_its_readonly_connection_and_leaves_writer_usable(tmp_path):
    import pytest
    import sqlite3
    store=TradingStore(tmp_path/'accounts.db')
    try:
        with pytest.raises(sqlite3.OperationalError,match='readonly'):
            with store.read_snapshot():
                reader=store._read_state.connection
                store.one("DELETE FROM accounts")
        with pytest.raises(sqlite3.ProgrammingError,match='closed'):
            reader.execute('SELECT 1')
        with store.transaction() as db:
            db.execute("INSERT INTO meta VALUES('after_failed_read','ok')")
        assert store.one("SELECT value FROM meta WHERE key='after_failed_read'") == {'value':'ok'}
    finally:
        store.close()


def test_in_memory_projection_uses_its_existing_database(tmp_path):
    store=TradingStore(Path(':memory:'))
    service=TradingAccountService(store,snapshot_dir=tmp_path/'images')
    try:
        aid=service.create_account({'kind':'practice','name':'memory','settings':{'initialBalance':'1000'}})['id']
        assert service.account_summary(aid)['balance']=='1000'
        assert not store._conn.in_transaction
    finally:
        store.close()



def test_old_ledger_view_cannot_prime_shared_matching_cache_with_old_cursor(tmp_path):
    store=TradingStore(tmp_path/'accounts.db')
    service=TradingAccountService(store,snapshot_dir=tmp_path/'images')
    instrument=('binance','futures','BTCUSDT')
    def cursor(price):
        return dict(exchange=instrument[0],market_type=instrument[1],symbol=instrument[2],
            bar_time=60,seen_high=price,seen_low=price,last_close=price,observed_ms=1,
            closes_only=0,status='live',detail='',updated_at_ms=1)
    try:
        with store.transaction() as db:store.upsert_cursor(db,cursor('100'))
        with store.read_snapshot():
            assert store.cursor(*instrument)['last_close']==Decimal('100')
            with store.transaction() as db:store.upsert_cursor(db,cursor('200'))
            assert store.cursor(*instrument)['last_close']==Decimal('100')
            assert service._feed(instrument).cursor.last_close==Decimal('200')
        assert service._feed(instrument).cursor.last_close==Decimal('200')
    finally:
        store.close()
