"""Atomic strategy/account/cursor recovery and stale publisher fencing."""
import asyncio
import json
import sqlite3
import subprocess
import sys

import pytest

from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from tests.test_strategy_bar_continuation import events, make_kernel, strategy

DEFINITION = {"language":"python", "source":"owned-test-strategy", "parameters":{"size":"2"},
              "execution":{"fees":"3bps"}, "market":{"exchange":"local", "symbol":"TEST", "interval":"1m"}}

def checkpoint(kernel, calls):
    return {"engine":kernel.snapshot(), "provider":{"seen":list(calls)}, "planner":{}}

def create(store, kernel=None):
    return store.create("cs_test", definition=DEFINITION, mode="HISTORY_LIVE", data_revision="r1",
                        event_time_ms=0, checkpoint=checkpoint(kernel or make_kernel(), []))

def resume(store, row):
    return store.resume(row["id"], generation=row["generation"], revision=row["revision"])

def commit(store, row, kernel, calls, **overrides):
    return store.commit(row["id"], generation=row["generation"], revision=row["revision"],
        sequence=overrides.get("sequence",calls[-1]), event_time_ms=overrides.get("time",calls[-1]*60000),
        data_revision=overrides.get("data_revision","r1"), checkpoint=checkpoint(kernel,calls), phase="LIVE")


def test_fresh_process_restores_same_account_cursor_and_unfinished_orders(tmp_path):
    path=tmp_path/'continuing.db';store=ContinuousStrategyStore(path)
    kernel=make_kernel(sparse=True);calls=[]
    row=resume(store,create(store,kernel))
    kernel.advance(events()[:7], strategy(calls));row=commit(store,row,kernel,calls)
    assert row["sequence"]==7 and row["phase"]=="LIVE" and "checkpoint" not in row
    store.close()
    # A genuinely new interpreter reads the same committed SQLite state.
    result=subprocess.run([sys.executable,"-B","-c",
        "from pathlib import Path; import json,sys; from app.backtest.continuous_store import ContinuousStrategyStore; "
        "s=ContinuousStrategyStore(Path(sys.argv[1])); print(json.dumps(s.load('cs_test'))); s.close()",str(path)],
        capture_output=True,text=True,check=True)
    saved=json.loads(result.stdout)
    restored=make_kernel(sparse=True);restored.restore(saved["checkpoint"]["engine"])
    restored_calls=saved["checkpoint"]["provider"]["seen"]
    store=ContinuousStrategyStore(path);row=resume(store,saved["run"])
    assert row["phase"]=="CATCHING_UP" and row["sequence"]==7 and row["generation"]>saved["run"]["generation"]
    restored.advance(events()[7:],strategy(restored_calls));row=commit(store,row,restored,restored_calls)
    expected=make_kernel(sparse=True);expected.run(events(),strategy([]),finalize=True)
    actual=restored.run((),strategy(restored_calls),finalize=True)
    assert actual==expected.result() and restored_calls==list(range(1,26))
    assert store.load("cs_test")["run"]["sequence"]==25
    store.close()


def test_two_writers_cannot_publish_old_generation_or_reinitialize_an_existing_run(tmp_path):
    path=tmp_path/'two.db';one=ContinuousStrategyStore(path);two=ContinuousStrategyStore(path)
    kernel=make_kernel();calls=[];initial=create(one,kernel);old=resume(one,initial);new=resume(two,old)
    kernel.advance(events()[:3],strategy(calls))
    with pytest.raises(BacktestError,match="CONTINUOUS_COMMIT_CONFLICT"):commit(one,old,kernel,calls)
    current=commit(two,new,kernel,calls)
    assert create(one,make_kernel())["sequence"]==3
    before=two.load("cs_test")
    with pytest.raises(BacktestError,match="CONTINUOUS_COMMIT_CONFLICT"):
        one.create("cs_test",definition={**DEFINITION,"source":"different"},mode="HISTORY_LIVE",data_revision="r1",event_time_ms=0,checkpoint=checkpoint(make_kernel(),[]))
    assert one.load("cs_test")==before and current["sequence"]==3
    one.close();two.close()


def test_failed_transaction_preserves_account_cursor_and_checkpoint_pointer(tmp_path):
    store=ContinuousStrategyStore(tmp_path/'rollback.db');kernel=make_kernel();calls=[]
    row=resume(store,create(store,kernel));before=store.load("cs_test")
    # Fail after the checkpoint INSERT but before the summary UPDATE commits.
    store.db.execute("CREATE TRIGGER fail_cursor BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT,'disk-write-failure'); END")
    kernel.advance(events()[:4],strategy(calls))
    with pytest.raises(sqlite3.IntegrityError,match="disk-write-failure"):commit(store,row,kernel,calls)
    assert store.load("cs_test")==before
    assert store.db.execute("SELECT count(*) FROM checkpoints").fetchone()[0]==1
    store.db.execute("DROP TRIGGER fail_cursor")
    commit(store,row,kernel,calls)
    assert store.load("cs_test")["run"]["sequence"]==4
    store.close()


def test_revision_gap_and_repair_wait_keep_original_result(tmp_path):
    store=ContinuousStrategyStore(tmp_path/'revision.db');kernel=make_kernel();calls=[]
    row=resume(store,create(store,kernel));kernel.advance(events()[:4],strategy(calls));row=commit(store,row,kernel,calls)
    before=store.load("cs_test")
    for args,code in [({"data_revision":"r2"},"CONTINUOUS_REPAIR_REQUIRED"),({"sequence":4},"CONTINUOUS_CURSOR_INVALID"),({"time":1,"sequence":5},"CONTINUOUS_CURSOR_INVALID")]:
        with pytest.raises(BacktestError,match=code):commit(store,row,kernel,calls,**args)
        assert store.load("cs_test")==before
    stopped=store.stop("cs_test",generation=row["generation"],revision=row["revision"],phase="REPAIR_REQUIRED",error={"code":"HISTORY_REVISED","message":"Await explicit repair"})
    assert store.load("cs_test")["checkpoint"]==before["checkpoint"]
    with pytest.raises(BacktestError,match="CONTINUOUS_NOT_READY"):resume(store,stopped)
    with pytest.raises(BacktestError,match="CONTINUOUS_NOT_READY"):
        store.stop("cs_test",generation=stopped["generation"],revision=stopped["revision"])
    store.close()


def test_retention_preserves_initial_exact_retry_latest_and_capacity(tmp_path):
    store=ContinuousStrategyStore(tmp_path/'retained.db',max_runs=1);kernel=make_kernel();calls=[]
    row=resume(store,create(store,kernel))
    for event in events():
        kernel.advance((event,),strategy(calls));row=commit(store,row,kernel,calls)
    revisions=[row[0] for row in store.db.execute("SELECT revision FROM checkpoints ORDER BY revision")]
    assert len(revisions)==8 and revisions[0]==1 and revisions[-1]==row["checkpoint_revision"]
    assert create(store,make_kernel())["sequence"]==25
    with pytest.raises(BacktestError,match="BUDGET_EXCEEDED"):
        store.create("cs_other",definition=DEFINITION,mode="LIVE_ONLY",data_revision="r1",event_time_ms=0,checkpoint=checkpoint(make_kernel(),[]))
    store.db.execute("DELETE FROM checkpoints WHERE run_id='cs_test' AND revision=?",(row["checkpoint_revision"],))
    with pytest.raises(BacktestError,match="CONTINUOUS_CHECKPOINT_CORRUPT"):store.load("cs_test")
    store.close()


def test_committed_wakeup_and_read_only_views_do_not_own_the_execution(tmp_path):
    async def run():
        store=ContinuousStrategyStore(tmp_path/'wake.db');kernel=make_kernel();calls=[]
        row=resume(store,create(store,kernel));subscription=store.updates.subscribe("cs_test")
        subscription.clear_before_read();before=store.load("cs_test")
        store.summary("cs_test");assert store.load("cs_test")==before
        kernel.advance(events()[:2],strategy(calls));row=await asyncio.to_thread(commit,store,row,kernel,calls)
        assert await asyncio.wait_for(subscription.wait(),1)
        subscription.close()
        assert store.load("cs_test")["run"]["phase"]=="LIVE"
        store.close()
    asyncio.run(run())


def test_storage_budgets_and_unknown_database_preserve_existing_data(tmp_path,monkeypatch):
    from app.backtest import continuous_store as module
    store=ContinuousStrategyStore(tmp_path/'budget.db');row=create(store)
    monkeypatch.setattr(module,"MAX_CHECKPOINT_BYTES",16)
    with pytest.raises(BacktestError,match="BUDGET_EXCEEDED"):
        commit(store,row,make_kernel(),[1])
    assert store.summary("cs_test")==row
    store.close()
    monkeypatch.setattr(module,"MAX_CHECKPOINT_BYTES",64*1024*1024)
    store=ContinuousStrategyStore(tmp_path/'budget.db',max_total_checkpoint_bytes=1)
    assert create(store)["sequence"]==0
    # Exact create retry returns its original result even after a limit changes.
    row=resume(store,row);kernel=make_kernel();calls=[];kernel.advance(events()[:1],strategy(calls))
    before=store.load("cs_test")
    with pytest.raises(BacktestError,match="total disk budget"):commit(store,row,kernel,calls)
    assert store.load("cs_test")==before
    store.close()
    path=tmp_path/'foreign.db';db=sqlite3.connect(path);db.execute("CREATE TABLE personal_data(value TEXT)");db.execute("INSERT INTO personal_data VALUES('preserve')");db.commit();db.close()
    with pytest.raises(BacktestError,match="CONTINUOUS_SCHEMA_UNSUPPORTED"):ContinuousStrategyStore(path)
    db=sqlite3.connect(path);assert db.execute("SELECT value FROM personal_data").fetchone()[0]=="preserve";db.close()
