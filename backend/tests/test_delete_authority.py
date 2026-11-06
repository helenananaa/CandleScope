"""Deletion permission is durable; disposable derived invalidation is separate."""
import subprocess
import sys
import sqlite3

import pytest

from app.data_engine.storage import klines_repo


@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setattr(klines_repo,'KLINES_DB_PATH',tmp_path/'bars.sqlite')
    klines_repo.init_klines_storage()
    return klines_repo.KlinesRepoAdapter()


def write(interval='1s',close=10):
    return klines_repo.upsert_klines('BTCUSDT',interval,[dict(
        open_time=91000,close_time=91999 if interval=='1s' else 97999,
        open=10,high=20,low=1,close=close,volume=1,quote_volume=10,
        trades=1,taker_buy_base=0,taker_buy_quote=0)],
        source='backfill' if interval=='1s' else 'backfill_aggregated')


def permissions():
    with klines_repo._connect() as conn:
        return {r['interval']:r['revision'] for r in conn.execute('SELECT * FROM kline_delete_permissions')}


def test_native_edit_invalidates_derived_without_granting_deletion_intent(store):
    write();write('7s');write(close=15)
    assert store.query_bars('BTCUSDT','7s')==[]
    assert permissions()=={}
    with klines_repo._connect() as conn:
        assert conn.execute("SELECT delete_revision FROM kline_series_changes WHERE interval='7s'").fetchone()[0]>0
        assert conn.execute('SELECT depth FROM kline_projection_invalidation').fetchone()[0]==0


@pytest.mark.parametrize('interval',['1s','7s'])
def test_direct_sql_delete_tracks_exact_owner_not_automatic_dependents(store,interval):
    write();write('7s')
    with klines_repo._connect() as conn:
        conn.execute('DELETE FROM klines WHERE interval=?',(interval,))
    assert set(permissions())=={interval}


def test_empty_range_delete_and_restart_retain_permission(store):
    store.delete_bars('BTCUSDT','7s',91000,97999)
    first=permissions();assert first['7s']>0
    klines_repo.init_klines_storage()
    assert permissions()==first


def test_delete_and_counter_markers_roll_back_with_rows(store):
    write();write('7s')
    with klines_repo._connect() as conn:
        conn.execute("DELETE FROM klines WHERE interval='1s'")
        assert conn.execute('SELECT COUNT(*) FROM kline_delete_permissions').fetchone()[0]==1
        conn.rollback()
    assert permissions()=={}
    assert len(store.query_bars('BTCUSDT','1s'))==len(store.query_bars('BTCUSDT','7s'))==1


def test_other_process_raw_sql_cannot_bypass_delete_permission(store):
    write();write('7s')
    subprocess.run([sys.executable,'-c',"import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute(\"DELETE FROM klines WHERE interval='1s'\");c.commit()",str(klines_repo.KLINES_DB_PATH)],check=True)
    assert set(permissions())=={'1s'}
    assert store.query_bars('BTCUSDT','7s')==[]


def test_old_schema_seeds_conservative_floor_once_only(store):
    write();write('7s');write(close=15)
    with klines_repo._connect() as conn:
        conn.execute('DROP TABLE kline_delete_permissions')
    klines_repo.init_klines_storage()
    seeded=permissions();assert seeded['7s']>0
    write('7s');write(close=17)
    with klines_repo._connect() as conn:
        assert conn.execute("SELECT delete_revision FROM kline_series_changes WHERE interval='7s'").fetchone()[0]>seeded['7s']
    klines_repo.init_klines_storage()
    assert permissions()==seeded


def test_legacy_seed_and_trigger_upgrade_hold_one_physical_writer_lock(store):
    from app.data_engine.storage.revisions import init_revision_storage
    write()
    with klines_repo._connect() as conn:
        conn.execute('DROP TABLE kline_delete_permissions')
    attempted=[]
    with klines_repo._connect() as conn:
        def interleave(sql):
            if sql.strip().startswith('CREATE TRIGGER IF NOT EXISTS kline_identity_immutable'):
                # An offline writer cannot slip a deletion between migration
                # seeding and replacement of its old physical DELETE trigger.
                with sqlite3.connect(klines_repo.KLINES_DB_PATH,timeout=0) as other:
                    try:
                        other.execute('BEGIN IMMEDIATE')
                        other.execute("DELETE FROM klines WHERE interval='1s'")
                    except sqlite3.OperationalError as error:
                        attempted.append(str(error))
                    else:
                        attempted.append('unexpected delete permission gap')
        conn.set_trace_callback(interleave)
        init_revision_storage(conn)
        conn.set_trace_callback(None)
    assert attempted==['database is locked']
    assert len(store.query_bars('BTCUSDT','1s'))==1
    with klines_repo._connect() as conn:
        conn.execute("DELETE FROM klines WHERE interval='1s'")
    assert set(permissions())=={'1s'}
