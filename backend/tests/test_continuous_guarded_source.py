"""Real DataManager, canonical SQLite and continuing financial SQLite together."""
from dataclasses import asdict,replace
import json
import sqlite3

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.storage import klines_repo
from app.data_engine.storage.prefix_watches import PrefixAcquisitionChanged
from app.local_data.service import LocalDatasetService
from app.market_dataset.snapshot import MarketEvent
from tests.test_kline_revision_contract import storage as storage
from tests.test_query_cache_fencing import START,STEP,SOURCE,_row
from tests.test_continuous_bar_host import prepare

KEY=SeriesKey("BTCUSDT","1m")
END=START+25*STEP-1


def setup_host(storage,tmp_path,monkeypatch,*,frozen=False):
    service,row,definition,factory,store=prepare(tmp_path,monkeypatch)
    manager=DataManager();manager.set_storage(storage)
    klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+i*STEP,100+i%7) for i in range(25)],source=SOURCE)
    initial=manager.bars.prefixes.register("strategy:cs_guarded",KEY,from_ms=START,committed_through_ms=START-1)
    definition.update(source_kind="MARKET_BAR",source_series=list(initial.series),market={"venue":"binance","symbol":"BTCUSDT"})
    if frozen:definition["initial_snapshot"]={"through_ms":END,"source_version":initial.version}
    ContinuousBarHost.create_run(store,"cs_guarded",definition=definition,mode="HISTORY_LIVE",data_revision=initial.incarnation,
        event_time_ms=START-1,provider_factory=factory,source_receipt=initial)
    host=ContinuousBarHost.resume(store,"cs_guarded",factory)
    return service,row,definition,factory,store,manager,host


def acquire(manager,host,count):
    through=START+count*STEP-1
    frozen=host.definition.get("initial_snapshot")
    protected=max(through,frozen["through_ms"]) if frozen else through
    proof=manager.bars.prefixes.prepare(host.source_receipt,committed_through_ms=host.row["event_time_ms"],through_ms=protected,
        **({"frozen_version":frozen["source_version"]} if frozen else {}))
    query=manager.bars.query("BTCUSDT","1m",start_ms=host.row["event_time_ms"]+1,end_ms=through-STEP+1,
        limit=1000,auto_backfill=False,min_revision=proof.storage_revision)
    assert query.complete and query.bars and all(bar.trusted_final for bar in query.bars)
    values=[]
    for index,bar in enumerate(query.bars,start=host.row["sequence"]+1):
        payload={key:LocalDatasetService._decimal_text(LocalDatasetService._host_decimal(bar,key,index))
            for key in ["open","high","low","close","volume"]}
        stamp=int(bar.time)*1000
        payload.update(open_time_ms=stamp,close_time_ms=stamp+STEP-1,is_closed=True)
        values.append(MarketEvent(index,stamp+STEP-1,"BARS",payload))
    return proof,tuple(values)


def apply(manager,host,proof,values,*,guard=None):
    through=values[-1].event_time_ms
    point=replace(proof,through_ms=through)
    return host.apply_batch(values,data_revision=proof.incarnation,revealed_through_ms=through,coverage_complete=True,
        caught_up=through==END,source_receipt=point,
        commit_checkpoint=guard or (lambda publish:manager.bars.prefixes.commit(proof,publish,committed_through_ms=through)))


def cleanup(service,store,host):
    host.close();store.close();service.shutdown()


def test_manager_source_receipt_and_financial_state_restore_without_in_lock_encoding(storage,tmp_path,monkeypatch):
    service,row,definition,factory,store,manager,host=setup_host(storage,tmp_path,monkeypatch)
    try:
        from app.backtest import continuous_store as module
        encoded=module._json;active={"guard":False};counts=[]
        def encoding(value):
            assert not active["guard"],"Full state encoding must precede the canonical source write fence"
            if "engine" in value:counts.append(1)
            return encoded(value)
        monkeypatch.setattr(module,"_json",encoding)
        proof,values=acquire(manager,host,10)
        def guarded(publish):
            active["guard"]=True
            try:return manager.bars.prefixes.commit(proof,publish)
            finally:active["guard"]=False
        apply(manager,host,proof,values,guard=guarded)
        assert counts==[1]
        first=store.load("cs_guarded")
        assert first["checkpoint"]["source"]["through_ms"]==first["run"]["event_time_ms"]==values[-1].event_time_ms
        assert first["checkpoint"]["provider"]["lastSequence"]==10
        host.close();store.close();store=ContinuousStrategyStore(tmp_path/'continuous.db')
        host=ContinuousBarHost.resume(store,"cs_guarded",factory)
        assert host.source_receipt.through_ms==first["run"]["event_time_ms"]
        proof,values=acquire(manager,host,25);apply(manager,host,proof,values)
        actual=asdict(host.kernel.run((),host._observe,finalize=True))
        # The existing fixed service consumes the exact complete acquired BAR
        # sequence as an independent provider/account execution reference.
        all_query=manager.bars.query("BTCUSDT","1m",start_ms=START,end_ms=END-STEP+1,limit=1000,auto_backfill=False)
        all_events=tuple(MarketEvent(i+1,int(b.time)*1000+STEP-1,"BARS",{
            **{k:LocalDatasetService._decimal_text(LocalDatasetService._host_decimal(b,k,i+1)) for k in ["open","high","low","close","volume"]},
            "open_time_ms":int(b.time)*1000,"close_time_ms":int(b.time)*1000+STEP-1}) for i,b in enumerate(all_query.bars))
        reference=service.execute_bar_run(row["run_id"],events=all_events,provider=factory(definition),observation_market=definition["market"],now_ms=3)["result"]
        for key in ["decision_hash","fill_hash","ledger_hash","fills","ledger","orders","equity_curve"]:
            assert canonical_json(actual[key])==canonical_json(reference[key]),key
        assert actual["fills"]
    finally:cleanup(service,store,host)


def test_processed_history_mutation_during_batch_stops_publication_and_retains_old_account(storage,tmp_path,monkeypatch):
    service,row,definition,factory,store,manager,host=setup_host(storage,tmp_path,monkeypatch)
    try:
        proof,values=acquire(manager,host,10);apply(manager,host,proof,values);old=store.load("cs_guarded")
        proof,values=acquire(manager,host,25)
        klines_repo.upsert_klines("BTCUSDT","1m",[_row(START,200)],source=SOURCE)
        with pytest.raises(PrefixAcquisitionChanged):apply(manager,host,proof,values)
        saved=store.load("cs_guarded")
        assert saved["run"]["phase"]=="REPAIR_REQUIRED" and host.closed
        assert saved["checkpoint"]==old["checkpoint"] and saved["run"]["sequence"]==10
    finally:cleanup(service,store,host)


def test_new_uncommitted_input_mutation_retries_same_account_from_trusted_cursor(storage,tmp_path,monkeypatch):
    service,row,definition,factory,store,manager,host=setup_host(storage,tmp_path,monkeypatch)
    try:
        proof,values=acquire(manager,host,10);apply(manager,host,proof,values);old=store.load("cs_guarded")
        proof,values=acquire(manager,host,25)
        klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+15*STEP,200)],source=SOURCE)
        with pytest.raises(PrefixAcquisitionChanged):apply(manager,host,proof,values)
        assert store.summary("cs_guarded")["phase"]=="CATCHING_UP" and store.load("cs_guarded")["checkpoint"]==old["checkpoint"]
        host=ContinuousBarHost.resume(store,"cs_guarded",factory)
        proof,values=acquire(manager,host,25);apply(manager,host,proof,values)
        assert host.row["sequence"]==25 and host.row["phase"]=="LIVE"
    finally:cleanup(service,store,host)


def test_frozen_initial_input_suffix_cannot_be_silently_replaced(storage,tmp_path,monkeypatch):
    service,row,definition,factory,store,manager,host=setup_host(storage,tmp_path,monkeypatch,frozen=True)
    try:
        proof,values=acquire(manager,host,10);apply(manager,host,proof,values);old=store.load("cs_guarded")
        assert manager.bars.prefixes.inspect(host.source_receipt.owner)["through_ms"]==END
        assert old["run"]["event_time_ms"]<END
        proof,values=acquire(manager,host,25)
        klines_repo.upsert_klines("BTCUSDT","1m",[_row(START+15*STEP,200)],source=SOURCE)
        with pytest.raises(PrefixAcquisitionChanged):apply(manager,host,proof,values)
        assert store.summary("cs_guarded")["phase"]=="REPAIR_REQUIRED"
        assert store.load("cs_guarded")["checkpoint"]==old["checkpoint"]
    finally:cleanup(service,store,host)


def test_financial_failure_does_not_ack_source_or_duplicate_committed_fills(storage,tmp_path,monkeypatch):
    service,row,definition,factory,store,manager,host=setup_host(storage,tmp_path,monkeypatch)
    try:
        proof,values=acquire(manager,host,10);apply(manager,host,proof,values);old=store.load("cs_guarded")
        old_ack=manager.bars.prefixes.inspect(host.source_receipt.owner)["committed_acquisition"]
        proof,values=acquire(manager,host,25)
        store.db.execute("CREATE TRIGGER reject_financial BEFORE INSERT ON checkpoints BEGIN SELECT RAISE(ABORT,'financial-full'); END")
        with pytest.raises(sqlite3.IntegrityError,match="financial-full"):apply(manager,host,proof,values)
        assert store.load("cs_guarded")["checkpoint"]==old["checkpoint"]
        assert manager.bars.prefixes.inspect(proof.owner)["committed_acquisition"]==old_ack
        store.db.execute("DROP TRIGGER reject_financial")
        host=ContinuousBarHost.resume(store,"cs_guarded",factory,retry_failed=True)
        proof,values=acquire(manager,host,25);apply(manager,host,proof,values)
        assert store.summary("cs_guarded")["sequence"]==25
    finally:cleanup(service,store,host)


def test_asynchronous_or_late_source_callback_cannot_publish_after_return(storage,tmp_path,monkeypatch):
    service,row,definition,factory,store,manager,host=setup_host(storage,tmp_path,monkeypatch)
    try:
        proof,values=acquire(manager,host,10);before=store.load("cs_guarded")
        async def asynchronous(publish):return publish()
        with pytest.raises(BacktestError,match="synchronously"):apply(manager,host,proof,values,guard=asynchronous)
        assert store.load("cs_guarded")==before
        pending=[]
        with pytest.raises(BacktestError,match="did not commit"):
            apply(manager,host,proof,values,guard=lambda publish:pending.append(publish))
        assert host.closed and store.load("cs_guarded")["checkpoint"]==before["checkpoint"]
        with pytest.raises(BacktestError,match="owned exactly once"):pending[0]()
    finally:cleanup(service,store,host)


def test_guarded_market_host_requires_exact_closed_minute_before_provider_or_commit(storage,tmp_path,monkeypatch):
    service,_,_,_,store,manager,host=setup_host(storage,tmp_path,monkeypatch)
    try:
        proof,values=acquire(manager,host,2)
        event=values[0]
        old=store.load("cs_guarded")
        checkpoint=host.checkpoint()
        missing_final={key:value for key,value in event.payload.items() if key!="is_closed"}
        for forged in (
            replace(event,payload=missing_final),
            replace(event,payload={**event.payload,"is_closed":0}),
            replace(event,payload={**event.payload,"open_time_ms":START+1}),
            replace(event,event_time_ms=event.event_time_ms+1),
        ):
            with pytest.raises(BacktestError,match="LOOKAHEAD_VIOLATION"):
                apply(manager,host,proof,(forged,values[1]))
            assert store.load("cs_guarded")==old and host.checkpoint()==checkpoint
        apply(manager,host,proof,values)
        assert host.row["sequence"]==2
    finally:cleanup(service,store,host)
