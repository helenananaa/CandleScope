"""Actual editor subprocess reconstruction without user StrategyRevision rows."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_provider import ContinuousProviderFactory, prepare_provider
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json
from app.backtest.strategy.builtin import BUILTIN_SMA_REVISION
from app.backtest.strategy.protocol import StrategyProviderError
from app.backtest.strategy.python_runner import PythonRunnerError
from tests.test_continuous_bar_host import prepare, apply
from tests.test_strategy_bar_continuation import events

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT/'packages/candlescope-backtest-sdk/templates/sma_cross/strategy.py').read_text()


def spec(*, python=False):
    return {"language": "python" if python else "builtin", "parameters": {"fast":3,"slow":5},
            **({"source_text":SOURCE,"runtime_mode":"TRUSTED_LOCAL","trusted_confirmed":True}
               if python else {"builtin_id":BUILTIN_SMA_REVISION})}


def bind(definition, prepared):
    configuration = {key:value for key,value in definition["configuration"].items()
                     if key not in {"strategy_source","output_mode","parameters"}}
    return {**definition,"provider":prepared,"language":prepared["language"],
        "configuration":configuration,"input_plan":{"roles":["BARS"]}}


@pytest.mark.parametrize("python", [False, True])
def test_actual_current_code_resumes_same_account_without_revision_or_snapshot_binding(tmp_path,monkeypatch,python):
    service,row,definition,_,store=prepare(tmp_path,monkeypatch)
    factory=ContinuousProviderFactory(scratch_root=tmp_path)
    editor=spec(python=python)
    prepared=prepare_provider(editor)
    definition=bind(definition,prepared)
    # Editing the mutable request cannot alter the owned run preparation.
    editor["parameters"]["fast"]=10
    editor["source_text"]="raise RuntimeError('later edit')"
    assert prepared["parameters"]["fast"]==3
    processes=[];scratch=[]
    def tracked(value):
        provider=factory(value)
        if python:
            scratch.append(provider.bundle_dir.parent)
            original=provider.prepare
            def started(context):
                original(context);processes.append(provider.runner._process)
            provider.prepare=started
        return provider
    host=None
    try:
        ContinuousBarHost.create_run(store,"cs_code",definition=definition,mode="LIVE_ONLY",
            data_revision="r1",event_time_ms=0,provider_factory=tracked)
        host=ContinuousBarHost.resume(store,"cs_code",tracked)
        apply(host,events()[:11]);saved=store.load("cs_code")
        host.close();store.close()
        store=ContinuousStrategyStore(tmp_path/'continuous.db')
        restored=store.describe("cs_code")["definition"]
        assert restored["provider"]==prepared
        assert not {"strategy_source","output_mode","parameters"} & restored["configuration"].keys()
        assert restored["input_plan"]=={"roles":["BARS"]}
        host=ContinuousBarHost.resume(store,"cs_code",tracked)
        apply(host,events()[11:20]);apply(host,events()[20:],caught_up=True)
        actual=asdict(host.kernel.run((),host._observe,finalize=True))
        reference=service.execute_bar_run(row["run_id"],events=events(),provider=tracked(restored),now_ms=3)["result"]
        for key in ("decision_hash","fill_hash","ledger_hash","fills","ledger","orders","equity_curve"):
            assert canonical_json(actual[key])==canonical_json(reference[key]),key
        assert saved["run"]["sequence"]==11 and store.summary("cs_code")["sequence"]==25
        assert service.repository.list_strategy_revisions()==[]
        assert not any(key in restored["provider"] for key in ("revision_id","dataset_id","snapshot_hash"))
    finally:
        if host is not None:host.close()
        store.close();service.shutdown()
    if python:
        assert len(processes)==4 and all(process.poll() is not None for process in processes)
        assert all(not path.exists() for path in scratch)
        assert list(tmp_path.glob("candlescope-continuous-*"))==[]


@pytest.mark.parametrize("change", [
    {"language":"pyne"}, {"language":"pine"}, {"language":[]},
    {"builtin_id":"pine-engine-v1"}, {"source_text":"unaccepted source"},
    {"output_mode":"ORDER_INTENT"}, {"dataset_id":"invented"},
    {"parameters":{"x":float("nan")}}, {"parameters":{1:"non-text key"}},
    {"parameters":{"x":(1,2)}}, {"parameters":{"x":"a"*65536}},
    {"source_text":"a"*262145}, {"runtime_mode":"TRUSTED_LOCAL"},
    {"source_text":"\ud800"},
])
def test_bad_preparation_has_no_files_or_strategy_execution(tmp_path,change):
    with pytest.raises((BacktestError,StrategyProviderError)):
        prepare_provider({**spec(),**change})
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize("change", [
    {"runtime_mode":None}, {"runtime_mode":[]}, {"trusted_confirmed":False},
    {"trusted_confirmed":"true"}, {"runtime_mode":"SANDBOXED_LOCAL"},
    {"builtin_id":BUILTIN_SMA_REVISION}, {"source_text":"invalid Python!"},
    {"source_text":SOURCE+"\nimport socket\n"},
])
def test_python_author_and_explicit_trust_contracts(change):
    with pytest.raises((BacktestError,StrategyProviderError)):
        prepare_provider({**spec(python=True),**change})


@pytest.mark.parametrize("field", ["language","parameters","output_mode","source","schema"])
def test_stored_execution_cannot_relabel_or_reconfigure_provider(tmp_path,monkeypatch,field):
    service,_,definition,_,store=prepare(tmp_path,monkeypatch)
    try:
        value=bind(definition,prepare_provider(spec(python=True)))
        if field=="language":value["language"]="builtin"
        elif field=="parameters":value["configuration"]["parameters"]={"fast":4,"slow":5}
        elif field=="output_mode":value["input_plan"]["outputMode"]="SIGNAL"
        elif field=="source":value["input_plan"]["source"]=SOURCE+"\n# other code"
        else:del value["provider"]["schema"]
        with pytest.raises(BacktestError):ContinuousProviderFactory(scratch_root=tmp_path)(value)
        assert list(tmp_path.glob("candlescope-continuous-*"))==[]
    finally:store.close();service.shutdown()


def test_sandbox_unavailable_never_falls_back_to_trusted_python(tmp_path,monkeypatch):
    monkeypatch.setattr("app.backtest.strategy.python_runner.sandbox_available",lambda:False)
    service,_,definition,_,store=prepare(tmp_path,monkeypatch)
    try:
        value=bind(definition,prepare_provider({**spec(python=True),"runtime_mode":"SANDBOXED_LOCAL","trusted_confirmed":False}))
        with pytest.raises(PythonRunnerError,match="SANDBOX_UNAVAILABLE"):
            ContinuousProviderFactory(scratch_root=tmp_path)(value)
        assert list(tmp_path.glob("candlescope-continuous-*"))==[]
    finally:store.close();service.shutdown()


def test_failed_physical_close_keeps_owned_source_until_explicit_retry(tmp_path,monkeypatch):
    service,_,definition,_,store=prepare(tmp_path,monkeypatch)
    try:
        provider=ContinuousProviderFactory(scratch_root=tmp_path)(bind(definition,prepare_provider(spec(python=True))))
        bundle=provider.bundle_dir
        close=provider.runner.close
        def fail():raise RuntimeError("physical close failed")
        monkeypatch.setattr(provider.runner,"close",fail)
        with pytest.raises(RuntimeError,match="physical close failed"):provider.close()
        assert bundle.is_dir()
        monkeypatch.setattr(provider.runner,"close",close)
        provider.abort();assert not bundle.exists()
    finally:store.close();service.shutdown()


def test_cyclic_and_excessively_nested_parameters_reject_before_json_copy():
    cyclic={};cyclic["self"]=cyclic
    with pytest.raises(BacktestError,match="structure budget"):prepare_provider({**spec(),"parameters":cyclic})


def test_python_definition_and_checkpoint_restore_in_new_backend_process(tmp_path,monkeypatch):
    service,row,definition,_,store=prepare(tmp_path,monkeypatch)
    factory=ContinuousProviderFactory(scratch_root=tmp_path)
    definition=bind(definition,prepare_provider(spec(python=True)))
    host=None
    try:
        ContinuousBarHost.create_run(store,"cs_process",definition=definition,mode="HISTORY_LIVE",
            data_revision="r1",event_time_ms=0,provider_factory=factory)
        host=ContinuousBarHost.resume(store,"cs_process",factory)
        apply(host,events()[:11]);host.close();store.close()
        child = subprocess.run([sys.executable,"-B","-c",'''
from dataclasses import asdict
import json, os, sys
from pathlib import Path
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_provider import ContinuousProviderFactory
from tests.test_continuous_bar_host import apply
from tests.test_strategy_bar_continuation import events
root=Path(sys.argv[1]);store=ContinuousStrategyStore(root/'continuous.db')
host=ContinuousBarHost.resume(store,'cs_process',ContinuousProviderFactory(scratch_root=root))
process=host.session.provider.runner._process
try:
    assert host.row['sequence']==11
    apply(host,events()[11:],caught_up=True)
    result=asdict(host.kernel.run((),host._observe,finalize=True))
    row=store.summary('cs_process')
finally:host.close();store.close()
assert process.poll() is not None
assert not list(root.glob('candlescope-continuous-*'))
print(json.dumps({'pid':os.getpid(),'row':row,'result':result},default=str))
''',str(tmp_path)],capture_output=True,text=True,timeout=30,check=True)
        actual=json.loads(child.stdout)
        reference=service.execute_bar_run(row["run_id"],events=events(),provider=factory(definition),now_ms=3)["result"]
        assert actual["pid"] != __import__('os').getpid()
        assert actual["row"]["sequence"]==25 and actual["row"]["phase"]=="LIVE"
        for key in ("decision_hash","fill_hash","ledger_hash","fills","ledger","orders","equity_curve"):
            assert canonical_json(actual["result"][key])==canonical_json(reference[key]),key
        assert service.repository.list_strategy_revisions()==[]
    finally:
        if host is not None:host.close()
        store.close();service.shutdown()
