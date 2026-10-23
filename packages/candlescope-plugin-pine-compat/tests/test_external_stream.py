"""Per-observation transport over actual native state, including forming recovery."""
from copy import deepcopy

import pine_compat
import pytest

from candlescope_plugin_pine_compat import chart_strategy, external_strategy, external_stream
from candlescope_plugin_pine_compat.execution_schedule import CONTRACT as SCHEDULE, TICK_CONTRACT, engine_pass
from candlescope_plugin_pine_compat.strategy_time import engine_bars

pytestmark = pytest.mark.skipif(getattr(pine_compat, "EXTERNAL_STREAM_SCHEMA_VERSION", 0) != 1,
                                reason="requires external streaming runtime")
SOURCE = '''//@version=6
strategy("stream",calc_on_every_tick=true,calc_on_every_history_tick=true)
var int ordinary=0
varip int n=0
ordinary+=1
n+=1
plot(ordinary)
plot(n)
plot(ta.cum(volume))
plot(strategy.position_size)
plot(last_bar_index)
strategy.entry(str.tostring(n),strategy.long,qty=1)
'''


def opening(state):
    return dict(source=SOURCE, parameters={}, context=dict(symbol="A", timeframe="1"),
                external_stream_contract=external_stream.CONTRACT,
                execution_schedule_contract=SCHEDULE, execution_tick_contract=TICK_CONTRACT,
                **({"historical_plan": [data(i, state)[0] for i in range(2)]} if state == "historical" else {}))


def data(index, state):
    bar = dict(time=index*60, open=10, high=12, low=9, close=11, volume=100)
    group=[]; high=low=10
    for tick, price in enumerate([10, 12, 9, 11]):
        high, low = max(high, price), min(low, price)
        account=dict(time=bar["time"], position_size=tick, position_avg_price=10 if tick else None,
                     equity=1000, initial_capital=1000, netprofit=0, openprofit=0)
        group.append(dict(evaluation=dict(bar=bar | dict(high=high, low=low, close=price, volume=25*(tick+1)),
            account=account, confirmed=tick==3, event_time_ms=bar["time"]*1000+tick*59999//3),
            context=dict(bar_state=state, trigger="historical_tick" if state=="historical" else "bar_close" if tick==3 else "realtime_tick",
                         is_new=state=="historical" or tick==0)))
    return bar, group


@pytest.fixture(autouse=True)
def isolated_stream():
    external_stream._active = None
    yield
    external_stream._active = None


@pytest.mark.parametrize("route", [chart_strategy.execute, external_strategy.execute])
@pytest.mark.parametrize("state", ["historical", "realtime"])
def test_bridges_keep_one_native_session_and_only_return_new_intents(route, state):
    request=opening(state)
    assert route(dict(request, operation="stream_open"))["bar_cursor"] == 0
    native=external_stream._active.engine
    intents=[]
    def command(operation, cursor, **values):
        return route(dict(operation=operation, external_stream_contract=external_stream.CONTRACT,
                          bar_cursor=cursor, intent_base=len(intents), **values))
    for index in range(2):
        bar,group=data(index,state)
        command("stream_begin",index,bar=bar,bar_state=state)
        for ordinal,observation in enumerate(group):
            original = deepcopy(observation)
            result=command("stream_observe",index,observation=observation)
            assert observation == original
            retained = native.snapshot(include_intents=True)
            observation["evaluation"]["bar"]["close"] = -999
            observation["evaluation"]["account"]["equity"] = -999
            observation["context"]["trigger"] = "changed-after-call"
            assert native.snapshot(include_intents=True) == retained
            assert "output" not in result and result["pass_cursor"] == ordinal+1
            assert result["intent_base"] == len(intents) and len(result["intents"]) == 1
            intents.extend(result["intents"])
            assert external_stream._active.engine is native
        result=command("stream_commit",index)
        assert result["intents"] == [] and result["bar_cursor"] == index+1
    result=command("stream_snapshot",2,include_intents=True)
    bars=[data(i,state)[0] for i in range(2)]
    groups=[[dict(item,evaluation=engine_pass(item["evaluation"])) for item in data(i,state)[1]] for i in range(2)]
    baseline=pine_compat.compile_script(SOURCE).run_external(engine_bars(bars),
        [g[-1]["evaluation"]["account"] for g in groups], execution_schedule=groups,
        chart_symbol="A",chart_timeframe="1")
    assert result["output"] == baseline["output"] and result["intents"] == intents == baseline["intents"]
    assert result["intent_base"] == 0 and result["intent_cursor"] == 8


@pytest.mark.parametrize("mutation", ["cursor", "clock", "environment", "legacy"])
def test_invalid_input_discards_worker_state_instead_of_reusing_partial_execution(mutation):
    route=external_strategy.execute
    route(dict(opening("realtime"),operation="stream_open"))
    bar,group=data(0,"realtime")
    command=dict(operation="stream_begin",external_stream_contract=external_stream.CONTRACT,
                 bar_cursor=0,intent_base=0,bar=bar,bar_state="realtime")
    route(command)
    command=dict(operation="stream_observe",external_stream_contract=external_stream.CONTRACT,
                 bar_cursor=0,intent_base=0,observation=deepcopy(group[0]))
    if mutation=="cursor": command["bar_cursor"]=True
    if mutation=="clock": command["observation"]["evaluation"]["bar"]["time"]=0.5
    if mutation=="environment": command["source"]="changed"
    if mutation=="legacy": command=dict(source=SOURCE,bars=[],accounts=[])
    with pytest.raises(ValueError): route(command)
    # Direct adapter errors are fatal too, just like the evaluator JSON-lines loop.
    assert external_stream._active is None


def test_old_core_does_not_advertise_the_stream_contract(monkeypatch):
    assert external_stream.capabilities()["external_stream_contract"] == external_stream.CONTRACT
    monkeypatch.setattr(pine_compat,"EXTERNAL_STREAM_SCHEMA_VERSION",0)
    assert external_stream.capabilities() == {}


@pytest.mark.parametrize("route", [chart_strategy.execute, external_strategy.execute])
@pytest.mark.parametrize("state", ["historical", "realtime"])
def test_bounded_chain_returns_every_original_acknowledgement_and_final_native_state(route, state):
    def run(chained):
        external_stream._active = None
        result = route(dict(opening(state), operation="stream_open"))
        acknowledgements = []
        for index in range(2):
            bar, observations = data(index, state)
            commands = [dict(operation="stream_begin", bar=bar, bar_state=state),
                        *(dict(operation="stream_observe", observation=item) for item in observations),
                        dict(operation="stream_commit")]
            original = deepcopy(commands)
            if chained:
                envelope = route(dict(operation="stream_chain", external_stream_contract=external_stream.CONTRACT,
                    external_stream_chain_contract=external_stream.CHAIN_CONTRACT,
                    bar_cursor=result["bar_cursor"], intent_base=result["intent_cursor"], commands=commands))
                assert envelope["external_stream_chain_contract"] == external_stream.CHAIN_CONTRACT
                acknowledgements.extend(envelope["results"])
                result = envelope["results"][-1]
            else:
                for command in commands:
                    result = route(dict(command, external_stream_contract=external_stream.CONTRACT,
                        bar_cursor=result["bar_cursor"], intent_base=result["intent_cursor"]))
                    acknowledgements.append(result)
            assert commands == original
        output = route(dict(operation="stream_snapshot", external_stream_contract=external_stream.CONTRACT,
            bar_cursor=2, intent_base=result["intent_cursor"], include_intents=True))
        return acknowledgements, output
    assert run(True) == run(False)


@pytest.mark.parametrize("failure", ["empty", "over-budget", "nested", "identity", "cursor", "contract", "bad-second"])
def test_bad_chain_discards_native_state_without_returning_partial_success(failure):
    route = external_strategy.execute
    route(dict(opening("realtime"), operation="stream_open"))
    bar, observations = data(0, "realtime")
    commands = [dict(operation="stream_begin", bar=bar, bar_state="realtime"),
                dict(operation="stream_observe", observation=observations[0])]
    request = dict(operation="stream_chain", external_stream_contract=external_stream.CONTRACT,
        external_stream_chain_contract=external_stream.CHAIN_CONTRACT, bar_cursor=0, intent_base=0, commands=commands)
    if failure == "empty": request["commands"] = []
    if failure == "over-budget": request["commands"] = commands * 5
    if failure == "nested": commands[1] = dict(operation="stream_chain", commands=[])
    if failure == "identity": commands[1]["identity"] = {}
    if failure == "cursor": request["bar_cursor"] = True
    if failure == "contract": request["external_stream_chain_contract"] = "wrong"
    if failure == "bad-second": observations[0]["evaluation"]["event_time_ms"] = False
    with pytest.raises(ValueError): route(request)
    assert external_stream._active is None


@pytest.mark.parametrize("unknown", ["bars", "accounts", "execution_schedule", "execution_passes", "request_updates"])
def test_stream_open_cannot_silently_ignore_legacy_execution_fields(unknown):
    request=opening("realtime")
    request[unknown]=[]
    with pytest.raises(ValueError,match="unknown opening fields"):
        external_strategy.execute(dict(request,operation="stream_open"))
    assert external_stream._active is None


def test_streaming_requested_updates_cannot_preload_a_future_context():
    from candlescope_plugin_pine_compat.request_updates import CONTRACT as REQUESTS
    request=opening("realtime")
    request.update(request_update_contract=REQUESTS,contexts=[dict(symbol="B",timeframe="1",bars=[data(1,"realtime")[0]])])
    with pytest.raises(ValueError,match="initial requested contexts must be empty"):
        external_strategy.execute(dict(request,operation="stream_open"))


def test_requested_transactions_advance_without_replaying_previous_observations():
    from candlescope_plugin_pine_compat.request_updates import CONTRACT as REQUESTS
    request=opening("realtime")
    request.update(request_update_contract=REQUESTS, contexts=[dict(symbol="B",timeframe="1",bars=[])])
    request["source"] += '\nx=request.security("B","1",close)\nplot(x)\n'
    route=external_strategy.execute
    route(dict(request,operation="stream_open"))
    intents=[]
    def command(operation,cursor,**values):
        return route(dict(operation=operation,external_stream_contract=external_stream.CONTRACT,
                          bar_cursor=cursor,intent_base=len(intents),**values))
    for index in range(2):
        bar,group=data(index,"realtime")
        command("stream_begin",index,bar=bar,bar_state="realtime")
        for ordinal,frame in enumerate(group):
            observed=frame["evaluation"]["event_time_ms"]
            updates=[]
            if ordinal==3:
                update=bar|dict(open=100*(index+1),high=100*(index+1),low=100*(index+1),close=100*(index+1))
                updates=[dict(symbol="B",timeframe="1",kind="confirmed",available_at_ms=observed,bar=update)]
            frame["evaluation"].update(request_observed_at_ms=observed,request_updates=updates)
            original = deepcopy(frame)
            result=command("stream_observe",index,observation=frame)
            assert frame == original
            retained = external_stream._active.engine.snapshot(include_intents=True)
            if updates:
                updates[0]["bar"]["close"] = -999
            frame["evaluation"]["account"]["equity"] = -999
            assert external_stream._active.engine.snapshot(include_intents=True) == retained
            intents.extend(result["intents"])
        command("stream_commit",index)
    output=command("stream_snapshot",2)["output"]
    assert output["plots"][1]["values"]==[4,8]
    assert output["plots"][-1]["values"]==[100,200]
