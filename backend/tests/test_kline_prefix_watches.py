"""Persistent source prefix protection across real SQLite writer interleavings."""
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import subprocess
import sys

import pytest

from app.data_engine.storage import klines_repo
from app.data_engine.storage.revisions import series_values, StaleAcquisition
from app.data_engine.storage.prefix_watches import PrefixReceipt, PrefixContinuityUnavailable, ProcessedPrefixChanged, PrefixWatchStore
from tests.test_kline_revision_contract import storage as storage, write
from tests.test_query_cache_fencing import START, STEP, SOURCE, _row

SERIES=series_values("BTCUSDT","1m","binance","spot")
END=START+STEP-1


def begin(storage,owner="strategy:test"):
    store=storage.revision_store.prefix_watches
    receipt=store.register(owner,SERIES,from_ms=START,committed_through_ms=START-1)
    return store,receipt


def prepare(store,receipt,*,through=END):
    return store.prepare(receipt,committed_through_ms=receipt.through_ms,through_ms=through)


def persist_financial(path,proof):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS financial_cursor (singleton INTEGER PRIMARY KEY,receipt TEXT)")
        conn.execute("INSERT OR REPLACE INTO financial_cursor VALUES(1,?)",(json.dumps(proof.to_dict()),))


def load_financial(path):
    with sqlite3.connect(path) as conn:
        return PrefixReceipt.from_dict(json.loads(conn.execute("SELECT receipt FROM financial_cursor").fetchone()[0]))


def test_normal_tail_append_is_not_a_historical_repair(storage):
    write();store,initial=begin(storage);proof=prepare(store,initial)
    with store.commit_guard(proof):pass
    before=store.inspect(proof.owner);head=storage.revision_store.head()
    klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+STEP)],source=SOURCE)
    assert storage.revision_store.head()==head+1
    assert store.inspect(proof.owner)["version"]==before["version"]
    write(symbol="ETHUSDT");assert store.inspect(proof.owner)["version"]==before["version"]
    write(200)
    with pytest.raises(ProcessedPrefixChanged) as error:prepare(store,proof,through=END+STEP)
    assert error.value.start_ms==START and error.value.end_ms==END


def test_physical_writer_rollback_noop_and_another_process_are_observed(storage):
    write();store,initial=begin(storage);proof=prepare(store,initial)
    with store.commit_guard(proof):pass
    version=store.inspect(proof.owner)["version"]
    with closing(klines_repo._connect()) as conn:
        conn.execute("UPDATE klines SET close=300");conn.rollback()
    write(100)
    assert store.inspect(proof.owner)["version"]==version
    subprocess.run([sys.executable,"-B","-c","import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('UPDATE klines SET close=200'); c.commit(); c.close()",str(klines_repo.KLINES_DB_PATH)],check=True)
    fresh=klines_repo.KlinesRepoAdapter().revision_store.prefix_watches
    restored=PrefixReceipt.from_dict(json.loads(json.dumps(proof.to_dict())))
    with pytest.raises(ProcessedPrefixChanged):prepare(fresh,restored,through=END+STEP)


@pytest.mark.parametrize("delete",[True,False])
def test_committed_prefix_insert_update_or_empty_deletion_requires_repair(storage,delete):
    write();store,initial=begin(storage);proof=prepare(store,initial,through=END+STEP)
    with store.commit_guard(proof):pass
    if delete:
        # There is no physical row in this part of the committed prefix.
        storage.delete_bars("BTCUSDT","1m",start_ms=START+STEP,end_ms=START+STEP)
    else:
        klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+STEP)],source=SOURCE)
    with pytest.raises(ProcessedPrefixChanged):prepare(store,proof,through=END+2*STEP)


def test_failed_uncommitted_acquisition_can_be_reacquired_without_false_repair(storage):
    write();store,initial=begin(storage);pending=prepare(store,initial)
    write(200)
    with pytest.raises(StaleAcquisition):
        with store.commit_guard(pending):pytest.fail("changed acquisition cannot enter financial commit")
    retry=prepare(store,initial)
    # Crash again before committing any new financial input. This still refers
    # to the old empty financial cursor, not the pending protected range.
    retry2=prepare(store,initial)
    assert retry2.version==retry.version and retry2.acquisition>retry.acquisition
    with store.commit_guard(retry2):pass


def test_crash_after_financial_commit_before_source_ack_retains_protection(storage,tmp_path):
    write();store,initial=begin(storage);proof=prepare(store,initial);financial=tmp_path/'financial.db'
    with pytest.raises(RuntimeError,match="crash-before-source-ack"):
        with store.commit_guard(proof):
            persist_financial(financial,proof)
            raise RuntimeError("crash-before-source-ack")
    restored=load_financial(financial)
    assert store.inspect(proof.owner)["verified_through_ms"]==START-1
    write(200)
    with pytest.raises(ProcessedPrefixChanged):prepare(store,restored,through=END+STEP)


def test_crash_without_financial_commit_does_not_advance_cursor_or_require_old_repair(storage,tmp_path):
    write();store,initial=begin(storage);financial=tmp_path/'financial.db';persist_financial(financial,initial)
    pending=prepare(store,initial)
    with pytest.raises(RuntimeError):
        with store.commit_guard(pending):raise RuntimeError("financial-write-failed")
    write(200)
    retry=prepare(store,load_financial(financial))
    with store.commit_guard(retry):persist_financial(financial,retry)
    assert load_financial(financial)==retry


def test_source_guard_excludes_a_second_process_writer_until_financial_commit(storage,tmp_path):
    write();store,initial=begin(storage);proof=prepare(store,initial)
    script="import sqlite3,sys; c=sqlite3.connect(sys.argv[1],timeout=0); c.execute('UPDATE klines SET close=200'); c.commit(); c.close()"
    with store.commit_guard(proof):
        result=subprocess.run([sys.executable,"-B","-c",script,str(klines_repo.KLINES_DB_PATH)],capture_output=True,text=True)
        assert result.returncode!=0 and "database is locked" in result.stderr
        persist_financial(tmp_path/'financial.db',proof)
    subprocess.run([sys.executable,"-B","-c",script,str(klines_repo.KLINES_DB_PATH)],check=True)
    with pytest.raises(ProcessedPrefixChanged):prepare(store,proof,through=END+STEP)


def test_empty_registration_retry_and_newer_acquisition_identity(storage):
    write();store,initial=begin(storage)
    storage.delete_bars("BTCUSDT","1m",start_ms=START+STEP,end_ms=START+STEP)
    assert store.register(initial.owner,SERIES,from_ms=START,committed_through_ms=START-1)==initial
    first=prepare(store,initial);new=prepare(store,initial)
    with pytest.raises(StaleAcquisition):
        with store.commit_guard(first):pytest.fail("old acquisition must not commit")
    with pytest.raises(StaleAcquisition):store.release(first)
    store.release(new)
    with pytest.raises(PrefixContinuityUnavailable):prepare(store,initial)
    replacement=store.register(initial.owner,SERIES,from_ms=START,committed_through_ms=START-1)
    assert replacement.incarnation!=initial.incarnation
    with pytest.raises(PrefixContinuityUnavailable):prepare(store,initial)


def test_capacity_scope_and_source_database_regression_are_explicit(storage):
    store=PrefixWatchStore(storage.revision_store.connect,max_watches=1)
    initial=store.register("one",SERIES,from_ms=START,committed_through_ms=START-1)
    with pytest.raises(PrefixContinuityUnavailable,match="capacity"):
        store.register("two",SERIES,from_ms=START,committed_through_ms=START-1)
    write();proof=prepare(store,initial)
    with store.commit_guard(proof):pass
    # Simulate restoration of an older canonical source clock. No content hash
    # or anti-tamper scan is needed to reject a known older source database.
    with closing(klines_repo._connect()) as conn,conn:
        conn.execute("UPDATE kline_revision_clock SET revision=0")
    with pytest.raises(PrefixContinuityUnavailable,match="no longer covers"):prepare(store,proof)


def test_financial_database_rollback_is_not_confused_with_failed_uncommitted_acquisition(storage):
    write();store,initial=begin(storage);proof=prepare(store,initial)
    with store.commit_guard(proof):pass
    with pytest.raises(PrefixContinuityUnavailable,match="older than acknowledged"):
        prepare(store,initial)
    # A pending later acquisition is allowed to exceed the last financial
    # receipt, while an older restored source acquisition cannot cover it.
    pending=prepare(store,proof,through=END+STEP)
    with store.commit_guard(pending):pass
    with closing(klines_repo._connect()) as conn,conn:
        conn.execute("UPDATE kline_prefix_watches SET acquisition=0,committed_acquisition=0")
    with pytest.raises(PrefixContinuityUnavailable,match="no longer covers"):
        prepare(store,pending,through=END+2*STEP)


def test_data_manager_is_the_source_entry_and_holds_guard_around_financial_commit(storage,tmp_path):
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.models import SeriesKey
    manager=DataManager();manager.set_storage(storage);write()
    api=manager.bars.prefixes
    first=api.register("manager-owned",SeriesKey("BTCUSDT","1m"),from_ms=START,committed_through_ms=START-1)
    proof=api.prepare(first,committed_through_ms=first.through_ms,through_ms=END)
    path=tmp_path/'committed-via-manager.db'
    assert api.commit(proof,lambda:(persist_financial(path,proof),"committed")[1])=="committed"
    assert load_financial(path)==proof
    write(200)
    with pytest.raises(ProcessedPrefixChanged):api.prepare(proof,committed_through_ms=END,through_ms=END+STEP)
    assert api.inspect(first.owner)["version"]>proof.version
    # A profile with no durable canonical storage explicitly lacks this
    # capability; constructing the facade does not create feeds or databases.
    unavailable=DataManager()
    with pytest.raises(PrefixContinuityUnavailable,match="no durable prefix"):
        unavailable.bars.prefixes.register("unsupported",SeriesKey("BTCUSDT","1m"),from_ms=START,committed_through_ms=START-1)


def test_updating_bar_end_protects_the_original_overlapping_prefix(storage):
    write();store=storage.revision_store.prefix_watches;start=START+STEP//2
    initial=store.register("partial-source-window",SERIES,from_ms=start,committed_through_ms=start-1)
    proof=store.prepare(initial,committed_through_ms=start-1,through_ms=END)
    with store.commit_guard(proof):pass
    with closing(klines_repo._connect()) as conn,conn:
        conn.execute("UPDATE klines SET close_time=? WHERE open_time=?",(START+STEP//4,START))
    with pytest.raises(ProcessedPrefixChanged):prepare(store,proof,through=END+STEP)


def test_same_symbol_other_semantic_identity_does_not_dirty_the_original_prefix(storage):
    from app.data_engine.series_identity import KlineSeriesIdentity
    write();store,initial=begin(storage);proof=prepare(store,initial)
    with store.commit_guard(proof):pass
    version=store.inspect(proof.owner)["version"]
    alternate=KlineSeriesIdentity.for_exchange("binance",price_adjustment="split_adjusted")
    write(200,identity=alternate);write(300,identity=alternate)
    assert store.inspect(proof.owner)["version"]==version
    with store.commit_guard(proof):pass


def test_manager_does_not_acknowledge_an_unawaited_financial_callback(storage):
    from app.data_engine.data_manager import DataManager
    from app.data_engine.data_manager.models import SeriesKey
    manager=DataManager();manager.set_storage(storage);write();api=manager.bars.prefixes
    first=api.register("async-rejected",SeriesKey("BTCUSDT","1m"),from_ms=START,committed_through_ms=START-1)
    proof=api.prepare(first,committed_through_ms=first.through_ms,through_ms=END);calls=[]
    async def asynchronous_financial_commit():calls.append("committed")
    with pytest.raises(TypeError,match="synchronous durable callback"):
        api.commit(proof,asynchronous_financial_commit)
    with pytest.raises(TypeError,match="cannot acknowledge asynchronous work"):
        api.commit(proof,lambda:asynchronous_financial_commit())
    assert not calls and api.inspect(first.owner)["committed_acquisition"]==0


def test_uncommitted_initial_partial_bar_is_not_mistaken_for_processed_history(storage):
    write();store=storage.revision_store.prefix_watches;start=START+STEP//2
    initial=store.register("initial-partial-window",SERIES,from_ms=start,committed_through_ms=start-1)
    pending=store.prepare(initial,committed_through_ms=start-1,through_ms=END)
    write(200)
    from app.data_engine.storage.prefix_watches import PrefixAcquisitionChanged
    with pytest.raises(PrefixAcquisitionChanged) as changed:
        with store.commit_guard(pending):pytest.fail("mutated acquisition must not commit")
    assert changed.value.start_ms==START and changed.value.end_ms==END
    retry=store.prepare(initial,committed_through_ms=start-1,through_ms=END)
    with store.commit_guard(retry):pass


def test_frozen_initial_snapshot_can_protect_more_than_the_financial_cursor(storage,tmp_path):
    from dataclasses import replace
    write();klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+STEP)],source=SOURCE)
    store,initial=begin(storage);full=prepare(store,initial,through=END+STEP)
    partial=replace(full,through_ms=END)
    with store.commit_guard(full,committed_through_ms=END):persist_financial(tmp_path/'partial.db',partial)
    row=store.inspect(full.owner)
    assert row["through_ms"]==END+STEP and row["committed_through_ms"]==END
    next_proof=store.prepare(load_financial(tmp_path/'partial.db'),committed_through_ms=END,
                             through_ms=END+STEP,frozen_version=full.version)
    assert next_proof.version==full.version
    klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+STEP,200)],source=SOURCE)
    with pytest.raises(ProcessedPrefixChanged):
        store.prepare(partial,committed_through_ms=END,through_ms=END+STEP,frozen_version=full.version)


def test_partial_financial_ack_cannot_advance_beyond_the_acquired_source(storage):
    write();store,initial=begin(storage);proof=prepare(store,initial)
    with pytest.raises(ValueError,match="inside the acquired"):
        with store.commit_guard(proof,committed_through_ms=END+STEP):pytest.fail("future cursor")
    assert store.inspect(proof.owner)["committed_acquisition"]==0
    with store.commit_guard(proof):pass
    with pytest.raises(StaleAcquisition):
        with store.commit_guard(proof,committed_through_ms=START-1):pytest.fail("acknowledged progress cannot move backwards")


def revised_prefix(storage):
    klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+i*STEP) for i in range(5)],source=SOURCE)
    store,initial=begin(storage);proof=prepare(store,initial,through=END+4*STEP)
    with store.commit_guard(proof):pass
    klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+3*STEP,200)],source=SOURCE)
    return store,proof,store.inspect(proof.owner)


def test_repair_forks_only_unchanged_prefix_and_preserves_original_watch(storage,tmp_path):
    store,original,observed=revised_prefix(storage);financial=tmp_path/'financial.db';persist_financial(financial,original)
    fork=store.fork_unchanged(original,"strategy:test:repair",through_ms=END+2*STEP,expected_version=observed['version'])
    assert fork.incarnation!=original.incarnation and fork.from_ms==original.from_ms
    assert fork.through_ms==END+2*STEP and fork.version==fork.acquisition==0
    assert store.inspect(original.owner)==observed
    assert load_financial(financial)==original
    # New source lease is independently durable before any financial swap.
    fresh=PrefixWatchStore(store.connect)
    retry=prepare(fresh,fork,through=END+4*STEP)
    with fresh.commit_guard(retry):pass
    assert store.inspect(original.owner)==observed
    with pytest.raises(ProcessedPrefixChanged):prepare(store,original,through=END+5*STEP)


def test_repair_fork_protects_unchanged_initial_tail_without_acknowledging_it_as_executed(storage):
    store,original,observed=revised_prefix(storage)
    proof=store.fork_unchanged(original,'repair:protected-initial',through_ms=END,
        protected_through_ms=END+2*STEP,expected_version=observed['version'])
    financial=replace(proof,through_ms=END)
    actual=store.inspect(proof.owner)
    assert proof.through_ms==END+2*STEP and actual['committed_through_ms']==END
    acquired=store.prepare(financial,committed_through_ms=END,through_ms=END+2*STEP,frozen_version=0)
    with store.commit_guard(acquired,committed_through_ms=END+STEP):pass
    assert store.inspect(proof.owner)['committed_through_ms']==END+STEP
    klines_repo.upsert_klines('BTCUSDT','1m',[_row(START+2*STEP,300)],source=SOURCE)
    with pytest.raises(ProcessedPrefixChanged):
        store.prepare(replace(acquired,through_ms=END+STEP),committed_through_ms=END+STEP,
            through_ms=END+2*STEP,frozen_version=0)


@pytest.mark.parametrize('anchor',[START+3*STEP,END+4*STEP])
def test_repair_anchor_cannot_include_revised_input(storage,anchor):
    store,original,observed=revised_prefix(storage)
    with pytest.raises(PrefixContinuityUnavailable):
        store.fork_unchanged(original,"strategy:test:repair",through_ms=anchor,expected_version=observed['version'])
    assert store.inspect("strategy:test:repair") is None and store.inspect(original.owner)==observed


def test_repair_preview_change_and_earlier_revision_invalidate_the_anchor(storage):
    store,original,observed=revised_prefix(storage)
    klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+STEP,250)],source=SOURCE)
    for version in (observed['version'],store.inspect(original.owner)['version']):
        with pytest.raises(PrefixContinuityUnavailable):
            store.fork_unchanged(original,"strategy:test:repair",through_ms=END+2*STEP,expected_version=version)
    assert store.inspect("strategy:test:repair") is None


def test_new_revision_of_a_repair_anchor_is_fenced_before_publication(storage):
    store,original,observed=revised_prefix(storage)
    fork=store.fork_unchanged(original,"strategy:test:repair",through_ms=END+2*STEP,expected_version=observed['version'])
    pending=prepare(store,fork,through=END+4*STEP)
    klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+STEP,300)],source=SOURCE)
    with pytest.raises(StaleAcquisition):
        with store.commit_guard(pending):pytest.fail("changed repair source cannot publish")
    with pytest.raises(ProcessedPrefixChanged):prepare(store,fork,through=END+4*STEP)


def test_repair_watch_budget_and_existing_owners_never_adopt_or_overwrite(storage):
    store,original,observed=revised_prefix(storage)
    limited=PrefixWatchStore(store.connect,max_watches=1)
    with pytest.raises(PrefixContinuityUnavailable,match='capacity'):
        limited.fork_unchanged(original,"strategy:test:repair",through_ms=END+2*STEP,expected_version=observed['version'])
    existing=store.register("strategy:test:repair",SERIES,from_ms=START,committed_through_ms=START-1)
    with pytest.raises(PrefixContinuityUnavailable,match='already exists'):
        store.fork_unchanged(original,existing.owner,through_ms=END+2*STEP,expected_version=observed['version'])
    assert store.inspect(existing.owner)['incarnation']==existing.incarnation


def test_repair_financial_commit_survives_source_ack_failure_without_renaming(storage,tmp_path):
    store,original,observed=revised_prefix(storage)
    fork=store.fork_unchanged(original,"strategy:test:repair",through_ms=END+2*STEP,expected_version=observed['version'])
    pending=prepare(store,fork,through=END+4*STEP);financial=tmp_path/'repaired.db'
    with pytest.raises(RuntimeError):
        with store.commit_guard(pending):
            persist_financial(financial,pending)
            raise RuntimeError('crash after financial swap, before source acknowledgement')
    saved=load_financial(financial);fresh=PrefixWatchStore(store.connect)
    assert fresh.inspect(saved.owner)['incarnation']==saved.incarnation
    next_point=prepare(fresh,saved,through=END+5*STEP)
    with fresh.commit_guard(next_point):pass
    assert fresh.inspect(original.owner)==observed
