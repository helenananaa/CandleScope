"""Owned shutdown drains an in-flight provider without committing a half batch."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost, ContinuousExecutionStopping
from tests.test_kline_revision_contract import storage as storage
from tests.test_continuous_bar_source import source_setup,create_frozen,START,STEP,END,DATASET


def test_shutdown_signal_interrupts_active_provider_then_same_run_recovers(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    host=None
    entered,release=Event(),Event()
    try:
        create_frozen(source,receipt,definition,factory,store)
        host=ContinuousBarHost.resume(store,"cs_source",factory)
        source.acquire(host,revealed_through_ms=END,limit=7).apply(host,manager)
        before=store.load("cs_source")
        ack=manager.bars.prefixes.inspect(receipt.owner)["committed_acquisition"]
        batch=source.acquire(host,revealed_through_ms=END)
        observe=host.adapter.observe
        def paused(**kwargs):
            entered.set()
            assert release.wait(10),"test provider was not released"
            return observe(**kwargs)
        monkeypatch.setattr(host.adapter,"observe",paused)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(batch.apply,host,manager)
            try:
                assert entered.wait(10),"provider did not begin observation"
                # This must return while provider owns the batch lock.
                host.request_stop()
            finally:release.set()
            with pytest.raises(ContinuousExecutionStopping):future.result(timeout=10)
        assert host.closed and store.load("cs_source")==before
        assert manager.bars.prefixes.inspect(receipt.owner)["committed_acquisition"]==ack
        host=ContinuousBarHost.resume(store,"cs_source",factory)
        source.acquire(host,revealed_through_ms=END).apply(host,manager)
        source.acquire(host,revealed_through_ms=END).apply(host,manager)
        assert host.row["sequence"]==25 and host.row["phase"]=="LIVE"
    finally:
        release.set()
        if host is not None:host.close()
        source.close();store.close();service.shutdown()


def test_shutdown_after_state_preparation_does_not_publish_checkpoint(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    host=None
    try:
        create_frozen(source,receipt,definition,factory,store)
        host=ContinuousBarHost.resume(store,"cs_source",factory)
        batch=source.acquire(host,revealed_through_ms=END)
        before=store.load("cs_source")
        original=store.prepare_checkpoint
        def stopped(*args,**kwargs):
            prepared=original(*args,**kwargs)
            host.request_stop()
            return prepared
        monkeypatch.setattr(store,"prepare_checkpoint",stopped)
        with pytest.raises(ContinuousExecutionStopping):batch.apply(host,manager)
        assert store.load("cs_source")==before
        assert manager.bars.prefixes.inspect(receipt.owner)["committed_acquisition"]==1
    finally:
        if host is not None:host.close()
        source.close();store.close();service.shutdown()


def test_shutdown_during_initial_query_publishes_neither_copy_nor_account(storage,tmp_path,monkeypatch):
    service,_,_,_,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    query=manager.bars.query
    def stopped(*args,**kwargs):
        result=query(*args,**kwargs)
        source.request_stop()
        return result
    monkeypatch.setattr(manager.bars,"query",stopped)
    try:
        with pytest.raises(ContinuousExecutionStopping):
            source.freeze_initial(receipt,through_ms=START+20*STEP-1,dataset_id=DATASET)
        assert source.local_datasets.list_datasets()==[]
        assert list((source.local_datasets.root/'.staging').iterdir())==[]
        assert manager.bars.prefixes.inspect(receipt.owner)["committed_acquisition"]==0
    finally:source.close();store.close();service.shutdown()
