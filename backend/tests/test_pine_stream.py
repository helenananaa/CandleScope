"""Real worker deltas and restart before matching ledger restoration."""
from copy import deepcopy
import os
import threading

import pytest

from app.backtest.errors import BacktestError
from app.backtest.native import PROTOCOL, invoke, encoded
from app.backtest.native_session import SessionWorker, STREAM_CONTRACT
from app.backtest.pine_stream import PineStream, journal_entry, canonical_observations, observations_match, COMPACT_JOURNAL_CONTRACT, JOURNAL_CONTRACT
from app.backtest.strategy.pine_engine import plugin


def test_stream_cannot_cross_an_unnegotiated_transport():
    worker = object.__new__(SessionWorker)
    worker.identity = {}
    with pytest.raises(BacktestError, match="not negotiated"):
        worker.request(dict(operation="stream_open", external_stream_contract=STREAM_CONTRACT),threading.Event())


installed = pytest.mark.skipif(not os.environ.get("NATIVE_TEST_PINE_PYTHON"), reason="requires isolated source worker")
SOURCE='''//@version=6
strategy("restart",calc_on_every_tick=true,calc_on_every_history_tick=true)
varip int n=0
n+=1
plot(n)
plot(strategy.position_size)
plot(timenow)
strategy.entry(str.tostring(n),strategy.long,qty=1)
'''


def runtime_for(route):
    runtime = plugin()
    runtime["command"][-1] = f"candlescope_plugin_pine_compat.{route}"
    identity = invoke(runtime, dict(operation="describe"))["identity"]
    return runtime, dict(protocol=PROTOCOL,identity=identity)


def observation(index, ordinal, count=4):
    bar=dict(time=index*60,open=10,high=10,low=10,close=10,volume=100)
    account=dict(time=bar["time"],position_size=ordinal,position_avg_price=10 if ordinal else None,
                 initial_capital=10000,equity=10000,netprofit=0,openprofit=0)
    return dict(evaluation=dict(bar=bar,account=account,event_time_ms=bar["time"]*1000+ordinal,confirmed=ordinal==count-1),
                context=dict(bar_state="realtime",trigger="bar_close" if ordinal==count-1 else "realtime_tick",is_new=ordinal==0))


@installed
@pytest.mark.parametrize("route",["chart_strategy","external_strategy"])
@pytest.mark.parametrize("owned",[False,True])
@pytest.mark.parametrize("compact",[False,True])
def test_actual_worker_keeps_forming_state_and_replays_identical_deltas_after_restart(route,owned,compact):
    runtime,wire=runtime_for(route)
    cancel=threading.Event()
    stream=PineStream(runtime,wire,dict(source=SOURCE,parameters={},context=dict(symbol="A",timeframe="1")),cancel)
    recovered=None
    try:
        bar=observation(0,0)["evaluation"]["bar"]
        stream.begin(bar,bar_state="realtime")
        bar["close"]=999
        for ordinal in range(2):
            observed=observation(0,ordinal)
            result=stream.observe(observed,_owned=owned)
            observed["evaluation"]["account"]["position_size"]=999
            assert len(result["intents"])==1 and result["intent_base"]==ordinal and "output" not in result
        saved=stream.checkpoint(compact=compact)
        assert journal_entry(saved,0)["command"]["bar"]["close"]==10
        assert [item["command"]["observation"]["evaluation"]["account"]["position_size"]
                for item in (journal_entry(saved,i) for i in range(1,len(saved["journal"]))) ]==[0,1]
        inspected=stream.checkpoint()
        inspected["journal"][0]["command"]["bar"]["close"]=999
        inspected["opening"]["source"]="caller mutation"
        inspected["wire"]["identity"]["adapter"]="caller mutation"
        assert stream.matches_checkpoint(saved) and stream.checkpoint(compact=compact)==saved
        assert not stream.matches_checkpoint(inspected)
        assert not stream.matches_checkpoint({**saved,"unknown":True})
        # Caller mutation cannot rewrite the durable checkpoint or its transcript.
        edited=deepcopy(saved)
        entry=journal_entry(edited,1);entry["command"]["observation"]["evaluation"]["account"]["position_size"]=99
        edited["journal"][1]=encoded(entry) if compact else entry
        with pytest.raises(BacktestError): PineStream.restore(runtime,edited,cancel)
        stream.close()
        recovered=PineStream.restore(runtime,saved,cancel)
        for ordinal in range(2,4):
            result=recovered.observe(observation(0,ordinal))
            assert result["intents"][0]["id"]==str(ordinal+1)
        recovered.commit()
        result=recovered.output(include_intents=True)
        assert [p["values"] for p in result["output"]["plots"]]==[[4],[3],[3]]
        assert len(result["intents"])==4 and result["intent_base"]==0
        assert saved["passes"]==2 and len(saved["journal"])==3
        assert result["output"].get("strategy") is None
    finally:
        stream.close()
        if recovered is not None: recovered.close()


@pytest.mark.parametrize("compact", [False, True])
def test_journal_observations_keep_only_final_rebase_and_require_exact_group_length(compact):
    commands = [dict(operation="stream_observe", observation={"old": True}),
                dict(operation="stream_rebase"), dict(operation="stream_begin"),
                dict(operation="stream_observe", observation={"value": 1}),
                dict(operation="stream_observe", observation={"value": True}),
                dict(operation="stream_commit")]
    entries = [dict(command=command, result_sha256="receipt") for command in commands]
    saved = dict(contract=COMPACT_JOURNAL_CONTRACT if compact else JOURNAL_CONTRACT,
                 journal=[encoded(entry) for entry in entries] if compact else entries)
    assert canonical_observations(saved) == [{"value": 1}, {"value": True}]
    assert observations_match(saved, [[], [{"value": 1}, {"value": True}]])
    assert not observations_match(saved, [[{"value": 1}]])
    assert not observations_match(saved, [[{"value": 1}, {"value": True}, {}]])
    assert not observations_match(saved, [[{"value": True}, {"value": 1}]])


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("reset", [False, True])
def test_observation_validation_checks_every_live_entry_and_preserves_exact_json_values(compact, reset):
    entries = [dict(command=dict(operation="stream_observe", observation={"value": value}),
                    result_sha256="receipt") for value in (1, 1.0, True, 0.0, -0.0)]
    if reset:
        entries[:0] = [dict(command=dict(operation="stream_observe", observation={"old": True}),
                            result_sha256="receipt"),
                       dict(command=dict(operation="stream_rebase"), result_sha256="receipt")]
    groups = [[], [{"value": 1}, {"value": 1.0}], [], [{"value": True}, {"value": 0.0}, {"value": -0.0}]]

    def saved(rows):
        return dict(contract=COMPACT_JOURNAL_CONTRACT if compact else JOURNAL_CONTRACT,
                    journal=[encoded(row) for row in rows] if compact else rows)

    assert observations_match(saved(entries), groups)
    for index, replacement in enumerate((True, 1, 1.0, -0.0, 0.0)):
        changed = [[{"value": value} for value in (1, 1.0, True, 0.0, -0.0)]]
        changed[0][index]["value"] = replacement
        assert not observations_match(saved(entries), changed)
    assert not observations_match(saved(entries), [[{"extra": True}], *groups])
    assert not observations_match(saved(entries), [*groups, [{"extra": True}]])
    assert not observations_match(saved(entries), [*groups[:-1], groups[-1][:-1]])
    assert observations_match(saved([dict(command=dict(operation="stream_commit"), result_sha256="receipt")]), [[], []])
    # Even a non-observation command at the beginning or end must retain its
    # valid journal envelope. Early comparison exhaustion cannot skip it.
    for location in (2 if reset else 0, len(entries)):
        broken = deepcopy(entries)
        broken.insert(location, {"command": {"operation": "stream_commit"}})
        with pytest.raises(BacktestError, match="invalid Pine journal entry"):
            observations_match(saved(broken), groups)


@installed
@pytest.mark.parametrize("damage", ["json", "receipt", "noncanonical", "missing", "type"])
def test_compact_checkpoint_rejects_corruption_before_returning_a_restored_stream(damage):
    runtime, wire = runtime_for("external_strategy")
    cancel = threading.Event()
    stream = PineStream(runtime, wire, dict(source=SOURCE, parameters={}, context=dict(symbol="A", timeframe="1")), cancel)
    try:
        stream.begin(observation(0,0)["evaluation"]["bar"], bar_state="realtime")
        stream.observe(observation(0,0))
        saved = stream.checkpoint(compact=True)
        if damage == "json": saved["journal"][0] = "{"
        if damage == "receipt":
            entry = journal_entry(saved,0); entry["result_sha256"] = "wrong"
            saved["journal"][0] = encoded(entry)
        if damage == "noncanonical": saved["journal"][0] += " "
        if damage == "missing": saved["journal"].pop()
        if damage == "type": saved["journal"][0] = journal_entry(saved,0)
        assert not stream.matches_checkpoint(saved)
        with pytest.raises(BacktestError):
            PineStream.restore(runtime, saved, cancel)
    finally:
        stream.close()


@installed
def test_many_same_bar_observations_do_not_resend_prior_intents_or_output_history():
    runtime,wire=runtime_for("external_strategy")
    cancel=threading.Event()
    stream=PineStream(runtime,wire,dict(source=SOURCE,parameters={},context=dict(symbol="A",timeframe="1")),cancel)
    try:
        stream.begin(observation(0,0)["evaluation"]["bar"],bar_state="realtime")
        sizes=[]
        for ordinal in range(128):
            before=stream.worker.input_bytes
            result=stream.observe(observation(0,ordinal,128))
            sizes.append(stream.worker.input_bytes-before)
            assert len(result["intents"])==1 and result["intent_base"]==ordinal
        stream.commit()
        assert max(sizes)-min(sizes)<100
        assert stream.cursor==1 and stream.intents==128
        assert stream.output()["output"]["plots"][0]["values"]==[128]
    finally:
        stream.close()
