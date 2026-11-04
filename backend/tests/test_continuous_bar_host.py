"""Actual providers + shared fixed-history execution as the financial oracle."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json
from app.backtest.models import ENGINE_VERSION
from app.backtest.service import BacktestService
from app.backtest.strategy.builtin import BuiltinSmaCrossProvider
from app.backtest.strategy.python_provider import PythonHostProvider
from tests.test_backtest_control_plane import _payload,_settings
from tests.test_strategy_bar_continuation import events


def prepare(tmp_path,monkeypatch,*,python=False):
    monkeypatch.setenv("BACKTEST_COLOCATED_BAR_ENABLED","0")
    monkeypatch.setenv("BACKTEST_PYTHON_TRUSTED_LOCAL_ENABLED","1")
    settings=_settings(tmp_path)
    service=BacktestService.start(settings,now_ms=1)
    row=service.create_run(_payload(parameters={"fast":3,"slow":5},warmup_bars=3,
        taker_fee_bps="3",maker_fee_bps="1"),idempotency_key="reference",now_ms=2)
    config=json.loads(row["config_json"])
    definition={"engine_version":ENGINE_VERSION,"configuration":config,
        "input_plan":{"roles":["BARS"],"parameters":config["parameters"]},
        "market":{"venue":"local","symbol":str(row["dataset_id"])}}
    def factory(_):
        if not python:return BuiltinSmaCrossProvider()
        bundle=Path(__file__).resolve().parents[2]/'packages/candlescope-backtest-sdk/templates/sma_cross'
        return PythonHostProvider(bundle,parameters={"fast":3,"slow":5},mode="TRUSTED_LOCAL",trusted_confirmed=True)
    store=ContinuousStrategyStore(tmp_path/'continuous.db')
    return service,row,definition,factory,store


def apply(host,rows,**kwargs):
    return host.apply_batch(rows,data_revision=kwargs.pop("data_revision","r1"),
        revealed_through_ms=kwargs.pop("revealed_through_ms",rows[-1].event_time_ms if rows else host.row["event_time_ms"]),coverage_complete=kwargs.pop("coverage_complete",True),**kwargs)


@pytest.mark.parametrize("python",[False,True])
def test_actual_provider_account_and_planner_resume_match_fixed_service(tmp_path,monkeypatch,python):
    service,row,definition,factory,store=prepare(tmp_path,monkeypatch,python=python)
    created=ContinuousBarHost.create_run(store,"cs_actual",definition=definition,mode="HISTORY_LIVE",
        data_revision="r1",event_time_ms=0,provider_factory=factory)
    assert created["phase"]=="PAUSED"
    host=ContinuousBarHost.resume(store,"cs_actual",factory)
    try:
        apply(host,events()[:11]);first=store.load("cs_actual")
        assert first["checkpoint"]["provider"]["lastSequence"]==11
        host.close();store.close()
        store=ContinuousStrategyStore(tmp_path/'continuous.db')
        host=ContinuousBarHost.resume(store,"cs_actual",factory)
        assert host.row["phase"]=="CATCHING_UP" and host.row["sequence"]==11
        apply(host,events()[11:20]);apply(host,events()[20:],caught_up=True)
        actual=asdict(host.kernel.run((),host._observe,finalize=True))
        reference=service.execute_bar_run(row["run_id"],events=events(),provider=factory(definition),now_ms=3)["result"]
        for key in ["decision_hash","fill_hash","ledger_hash","fills","ledger","orders","equity_curve"]:
            assert canonical_json(actual[key])==canonical_json(reference[key]),key
        assert actual["fills"] and store.summary("cs_actual")["sequence"]==25
    finally:
        host.close();store.close();service.shutdown()


def test_exact_create_retry_does_not_prepare_provider_again(tmp_path,monkeypatch):
    service,row,definition,factory,store=prepare(tmp_path,monkeypatch);calls=[]
    def counted(value):calls.append(1);return factory(value)
    args=dict(definition=definition,mode="LIVE_ONLY",data_revision="r1",event_time_ms=0,provider_factory=counted)
    try:
        first=ContinuousBarHost.create_run(store,"cs_retry",**args)
        assert ContinuousBarHost.create_run(store,"cs_retry",**args)==first and calls==[1]
        with pytest.raises(BacktestError,match="CONTINUOUS_COMMIT_CONFLICT"):
            ContinuousBarHost.create_run(store,"cs_retry",**{**args,"data_revision":"different"})
        assert calls==[1]
    finally:store.close();service.shutdown()


def test_unrevealed_or_unclosed_bar_never_reaches_provider(tmp_path,monkeypatch):
    service,row,definition,factory,store=prepare(tmp_path,monkeypatch)
    ContinuousBarHost.create_run(store,"cs_future",definition=definition,mode="LIVE_ONLY",data_revision="r1",event_time_ms=0,provider_factory=factory)
    host=ContinuousBarHost.resume(store,"cs_future",factory)
    try:
        before=store.load("cs_future");snapshot=host.checkpoint()
        for rows,kwargs in [((events()[0],),{"revealed_through_ms":1}),
            ((replace(events()[0],payload={**events()[0].payload,"is_closed":False}),),{})]:
            with pytest.raises(BacktestError,match="LOOKAHEAD_VIOLATION"):apply(host,rows,**kwargs)
            assert store.load("cs_future")==before and host.checkpoint()==snapshot
        with pytest.raises(BacktestError,match="final admitted source boundary"):
            apply(host,(events()[0],),revealed_through_ms=25*60000,caught_up=True)
        assert store.load("cs_future")==before and host.checkpoint()==snapshot
    finally:host.close();store.close();service.shutdown()


def test_missing_source_coverage_preserves_state_then_recovers_same_run(tmp_path,monkeypatch):
    service,row,definition,factory,store=prepare(tmp_path,monkeypatch)
    ContinuousBarHost.create_run(store,"cs_gap",definition=definition,mode="HISTORY_LIVE",data_revision="r1",event_time_ms=0,provider_factory=factory)
    host=ContinuousBarHost.resume(store,"cs_gap",factory)
    try:
        apply(host,events()[:10],caught_up=True);old=store.load("cs_gap")
        with pytest.raises(BacktestError,match="CONTINUOUS_SOURCE_GAP"):
            apply(host,events()[11:14],coverage_complete=False)
        waiting=store.load("cs_gap")
        assert waiting["run"]["phase"]=="CATCHING_UP" and waiting["run"]["error"]["code"]=="CONTINUOUS_SOURCE_GAP"
        assert waiting["checkpoint"]==old["checkpoint"] and host.closed
        host=ContinuousBarHost.resume(store,"cs_gap",factory)
        apply(host,events()[10:],caught_up=True)
        assert store.summary("cs_gap")["sequence"]==25
    finally:host.close();store.close();service.shutdown()


def test_failed_storage_commit_never_publishes_partial_account_and_explicit_retry_restores(tmp_path,monkeypatch):
    service,row,definition,factory,store=prepare(tmp_path,monkeypatch)
    ContinuousBarHost.create_run(store,"cs_rollback",definition=definition,mode="HISTORY_LIVE",data_revision="r1",event_time_ms=0,provider_factory=factory)
    host=ContinuousBarHost.resume(store,"cs_rollback",factory)
    try:
        apply(host,events()[:10]);old=store.load("cs_rollback")
        store.db.execute("CREATE TRIGGER reject_checkpoint BEFORE INSERT ON checkpoints BEGIN SELECT RAISE(ABORT,'disk-full'); END")
        with pytest.raises(sqlite3.IntegrityError,match="disk-full"):apply(host,events()[10:20])
        failed=store.load("cs_rollback")
        assert failed["run"]["phase"]=="FAILED" and failed["checkpoint"]==old["checkpoint"] and host.closed
        store.db.execute("DROP TRIGGER reject_checkpoint")
        with pytest.raises(BacktestError,match="CONTINUOUS_NOT_READY"):ContinuousBarHost.resume(store,"cs_rollback",factory)
        host=ContinuousBarHost.resume(store,"cs_rollback",factory,retry_failed=True)
        assert host.row["sequence"]==10
        apply(host,events()[10:],caught_up=True)
        assert store.summary("cs_rollback")["sequence"]==25
    finally:host.close();store.close();service.shutdown()


def test_historical_revision_stops_publishing_until_explicit_repair(tmp_path,monkeypatch):
    service,row,definition,factory,store=prepare(tmp_path,monkeypatch)
    ContinuousBarHost.create_run(store,"cs_repair",definition=definition,mode="HISTORY_LIVE",data_revision="r1",event_time_ms=0,provider_factory=factory)
    host=ContinuousBarHost.resume(store,"cs_repair",factory)
    try:
        apply(host,events()[:10]);old=store.load("cs_repair")
        with pytest.raises(BacktestError,match="CONTINUOUS_REPAIR_REQUIRED"):apply(host,events()[10:],data_revision="r2")
        saved=store.load("cs_repair")
        assert saved["run"]["phase"]=="REPAIR_REQUIRED" and saved["checkpoint"]==old["checkpoint"]
        with pytest.raises(BacktestError,match="CONTINUOUS_NOT_READY"):ContinuousBarHost.resume(store,"cs_repair",factory,retry_failed=True)
    finally:host.close();store.close();service.shutdown()
