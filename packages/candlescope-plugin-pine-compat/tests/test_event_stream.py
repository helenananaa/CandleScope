"""Actual Core event requests use closed cohorts and whole-trial resets."""
from copy import deepcopy
import json
import sys

import pytest
from candlescope_plugin_pine_compat import chart_strategy, external_strategy, external_stream
from candlescope_plugin_pine_compat.event_stream import available, CONTRACT
import pine_compat
from candlescope_plugin_pine_compat.execution_schedule import CONTRACT as SCHEDULE, TICK_CONTRACT


def opening():
    bars=[dict(time=i*60,open=p,high=p,low=p,close=p,volume=6) for i,p in enumerate((10,13,15))]
    return dict(source='''//@version=6
strategy("event windows",calc_on_every_history_tick=true)
varip int n=0
n+=1
strategy.entry(str.tostring(n),strategy.long,qty=1)
r=ticker.renko("A","Traditional",1)
plot(request.security(r,"1",ta.cum(close),calc_bars_count=1))
plot(n)
''',parameters={},context=dict(symbol="A",timeframe="1"),historical_plan=bars,
        event_request_contract=CONTRACT,event_sources=[dict(symbol="A",timeframe="1",bars=bars,
            closes=[59999,119999,179999])],window_feedback_contract=external_stream.FEEDBACK_CONTRACT,
        external_stream_contract=external_stream.CONTRACT,execution_schedule_contract=SCHEDULE,
        execution_tick_contract=TICK_CONTRACT)


def observation(bar):
    return dict(evaluation=dict(bar=deepcopy(bar),account=dict(time=bar["time"],position_size=0,
        position_avg_price=None,equity=1000,initial_capital=1000,netprofit=0,openprofit=0),
        event_time_ms=bar["time"]*1000+59999,confirmed=True),
        context=dict(bar_state="historical",trigger="historical_tick",is_new=True))


@pytest.fixture(autouse=True)
def isolate():
    external_stream._active=None
    yield
    external_stream._active=None


@pytest.mark.parametrize("route",[chart_strategy.execute,external_strategy.execute])
def test_event_discovery_discards_partial_intents_and_replays_a_stable_causal_window(route):
    assert available(), "requires the newly qualified event-window Core"
    value=opening()
    state=route({**value,"operation":"stream_open"})
    assert state["window_status"]["requires_discovery"]
    def command(operation,**values):
        return route(dict(operation=operation,external_stream_contract=external_stream.CONTRACT,
            bar_cursor=state["bar_cursor"],intent_base=state["intent_cursor"],**values))
    for attempt in range(8):
        interrupted=False
        for index,bar in enumerate(value["historical_plan"]):
            state=command("stream_begin",bar=bar,bar_state="historical")
            state=command("stream_observe",observation=observation(bar))
            if state["window_status"]["rebase_required"]:
                assert state["intents"]==[]
                state=command("stream_rebase",seal=False)
                assert state["bar_cursor"]==state["intent_cursor"]==0
                interrupted=True
                break
            state=command("stream_commit")
        if not interrupted:
            break
    else:
        pytest.fail("event context discovery did not converge")
    assert attempt>0
    state=command("stream_rebase",seal=True)
    assert not state["window_status"]["requires_discovery"]
    intents=[]
    for bar in value["historical_plan"]:
        state=command("stream_begin",bar=bar,bar_state="historical")
        state=command("stream_observe",observation=observation(bar))
        assert not state["window_status"]["rebase_required"]
        intents.extend(state["intents"])
        state=command("stream_commit")
    state=command("stream_snapshot",include_intents=True)
    assert [plot["values"] for plot in state["output"]["plots"]]==[[None,None,15],[1,2,3]]
    assert [intent["id"] for intent in intents]==["1","2","3"]
    assert state["event_request_state"]["streams"][0]["cursor"]==5


def test_ordinary_script_failure_is_not_a_discoverable_event_request():
    value=opening()
    value["source"]='//@version=6\nstrategy("fatal",calc_on_every_history_tick=true)\nruntime.error("fatal")'
    state=chart_strategy.execute({**value,"operation":"stream_open"})
    common=dict(external_stream_contract=external_stream.CONTRACT,bar_cursor=0,intent_base=0)
    chart_strategy.execute({**common,"operation":"stream_begin","bar":value["historical_plan"][0],"bar_state":"historical"})
    with pytest.raises(ValueError,match="fatal"):
        chart_strategy.execute({**common,"operation":"stream_observe","observation":observation(value["historical_plan"][0])})
    assert external_stream._active is None


def test_user_runtime_error_cannot_impersonate_a_missing_requested_context():
    value=opening()
    key='{"chart":"renko","style":"Traditional","param":1,"symbol":"A"}'
    message=f'missing request data for symbol `{key}` timeframe `1`'
    value["source"]='//@version=6\nstrategy("typed failure",calc_on_every_history_tick=true)\nruntime.error('+json.dumps(message)+')'
    chart_strategy.execute({**value,"operation":"stream_open"})
    common=dict(external_stream_contract=external_stream.CONTRACT,bar_cursor=0,intent_base=0)
    chart_strategy.execute({**common,"operation":"stream_begin","bar":value["historical_plan"][0],"bar_state":"historical"})
    with pytest.raises(ValueError,match="missing request data"):
        chart_strategy.execute({**common,"operation":"stream_observe","observation":observation(value["historical_plan"][0])})
    assert external_stream._active is None


def test_older_runtime_without_typed_failure_state_does_not_advertise_event_support(monkeypatch):
    available.cache_clear()
    with monkeypatch.context() as patch:
        patch.setattr(pine_compat,"ExternalSession",type("LegacyExternalSession",(),{}))
        assert not available()
    available.cache_clear()
    assert available()


def test_older_sdk_does_not_break_ordinary_runtime_description(monkeypatch):
    available.cache_clear()
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules,"candlescope_plugin_sdk.event_requests",None)
        assert not available()
        assert "event_request_contract" not in chart_strategy.describe()
    available.cache_clear()
    assert available()
    from candlescope_plugin_sdk import event_requests
    with monkeypatch.context() as patch:
        patch.setattr(event_requests,"CONTRACT","unsupported")
        available.cache_clear()
        assert not available()
    available.cache_clear()
    assert available()


def test_event_stream_rejects_static_price_provider_bypassing_closed_cohorts():
    value=opening()
    value["contexts"]=[dict(symbol="B",timeframe="1",bars=[value["historical_plan"][-1]])]
    with pytest.raises(ValueError,match="empty prices"):
        chart_strategy.execute({**value,"operation":"stream_open"})


def test_realtime_event_plan_keeps_partial_chart_data_and_closed_request_cohorts_separate():
    value=opening()
    value["plan_state"]="realtime"
    value["realtime_window_plan_contract"]=external_stream.REALTIME_WINDOW_CONTRACT
    value["source"]='''//@version=6
strategy("realtime events",calc_on_every_tick=true)
varip int n=0
n+=1
r=ticker.renko("A","Traditional",1)
plot(request.security(r,"1",ta.cum(close),calc_bars_count=1))
plot(n)
plot(last_bar_index)
plot(request.security(syminfo.tickerid,timeframe.period,close))
'''
    for bar in value["historical_plan"]:
        bar.update(high=bar["open"]+2,low=bar["open"]-1,close=bar["open"]+1)
    # event_sources owns the same frozen physical tuple as the plan.
    state=chart_strategy.execute({**value,"operation":"stream_open"})
    def command(operation,**fields):
        return chart_strategy.execute(dict(operation=operation,external_stream_contract=external_stream.CONTRACT,
            bar_cursor=state["bar_cursor"],intent_base=state["intent_cursor"],**fields))
    def play():
        nonlocal state
        for index,bar in enumerate(value["historical_plan"]):
            partial={**bar,"high":bar["open"],"low":bar["open"],"close":bar["open"],"volume":1}
            state=command("stream_begin",bar=partial,bar_state="realtime")
            for closing,observed in ((False,partial),(True,bar)):
                item=observation(observed)
                item["context"]=dict(bar_state="realtime",trigger="bar_close" if closing else "realtime_tick",is_new=not closing)
                item["evaluation"].update(confirmed=closing,event_time_ms=bar["time"]*1000+(59999 if closing else 0))
                state=command("stream_observe",observation=item)
                if state["window_status"]["rebase_required"]:
                    return False
                output=command("stream_snapshot")
                assert output["output"]["plots"][2]["values"][-1]==index
                assert output["output"]["plots"][3]["values"][-1]==observed["close"]
            state=command("stream_commit")
        return True
    for _ in range(8):
        if play():break
        state=command("stream_rebase",seal=False)
    else:pytest.fail("realtime event discovery did not converge")
    state=command("stream_rebase",seal=True)
    assert play()
    state=command("stream_snapshot")
    assert [plot["values"] for plot in state["output"]["plots"]]==[[None,None,16],[2,4,6],[0,1,2],[11,14,16]]


def test_older_core_retains_historical_capabilities_without_advertising_realtime_windows(monkeypatch):
    from types import SimpleNamespace
    names=("begin_bar","observe","commit_bar","snapshot","initialize_history","window_status","rebase_window")
    legacy=SimpleNamespace(**{name:getattr(pine_compat.ExternalSession,name) for name in names})
    monkeypatch.setattr(pine_compat,"ExternalSession",legacy)
    caps=external_stream.capabilities()
    assert caps["window_feedback_contract"]==external_stream.FEEDBACK_CONTRACT
    assert "realtime_window_plan_contract" not in caps
    value=opening()
    value.update(plan_state="realtime",realtime_window_plan_contract=external_stream.REALTIME_WINDOW_CONTRACT)
    with pytest.raises(ValueError,match="qualified observed feedback"):
        chart_strategy.execute({**value,"operation":"stream_open"})


@pytest.mark.parametrize("change",[{},dict(realtime_window_plan_contract="unknown"),
    dict(realtime_window_plan_contract=external_stream.REALTIME_WINDOW_CONTRACT,window_feedback_contract=None)])
def test_realtime_plan_requires_explicit_contract_and_feedback(change):
    value={**opening(),"plan_state":"realtime",**change}
    with pytest.raises(ValueError,match="qualified observed feedback"):
        chart_strategy.execute({**value,"operation":"stream_open"})
