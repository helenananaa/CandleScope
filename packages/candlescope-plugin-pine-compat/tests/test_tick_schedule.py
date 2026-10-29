"""Additive tick clocks require explicit capability, transport and acknowledgement."""
from copy import deepcopy

import pine_compat
import pytest

from candlescope_plugin_pine_compat import chart_strategy, external_strategy
from candlescope_plugin_pine_compat.execution_schedule import CONTRACT, TICK_CONTRACT, capabilities, execution_input
from candlescope_plugin_pine_compat.prefix_transport import PrefixInput
from test_execution_schedule import request
from test_external_incremental import data


def ticks(count=1):
    value=request(count)
    value["source"]='//@version=6\nstrategy("ticks",calc_on_every_history_tick=true)\nvar int ordinary=0\nvarip int count=0\nordinary+=1\ncount+=1\nplot(ordinary)\nplot(count)\nplot(barstate.isconfirmed?1:0)\n'
    value["execution_tick_contract"]=TICK_CONTRACT
    for group in value["execution_schedule"]:
        template=deepcopy(group[-1])
        group[:]=[deepcopy(template) for _ in range(4)]
        for index,item in enumerate(group):
            item["evaluation"]["confirmed"]=index==3
            item["evaluation"]["event_time_ms"]=item["evaluation"]["bar"]["time"]*1000+index
            item["context"]={"bar_state":"historical","trigger":"historical_tick","is_new":True}
    return value


def advertise(monkeypatch):
    monkeypatch.setattr(pine_compat,"EXTERNAL_TICK_SCHEDULE_SCHEMA_VERSION",1,raising=False)
    monkeypatch.setattr(pine_compat,"MAX_STRATEGY_OBSERVATIONS_PER_BAR",100_000,raising=False)


def test_tick_capability_is_additive_and_never_claimed_by_old_or_malformed_core(monkeypatch):
    advertise(monkeypatch)
    assert capabilities()["execution_tick_contract"] == TICK_CONTRACT
    for name,value in [("EXTERNAL_TICK_SCHEDULE_SCHEMA_VERSION",0),("MAX_STRATEGY_OBSERVATIONS_PER_BAR",True),("MAX_STRATEGY_OBSERVATIONS_PER_BAR",100_001)]:
        with monkeypatch.context() as control:
            control.setattr(pine_compat,name,value)
            assert "execution_tick_contract" not in capabilities()
            with pytest.raises(ValueError,match="EXTERNAL_TICK_SCHEDULE_INVALID"):
                execution_input(ticks())


def test_historical_tick_transport_requires_negotiation_and_converts_seconds_once(monkeypatch):
    advertise(monkeypatch)
    value=ticks(2)
    converted=execution_input(value)["execution_schedule"]
    assert converted[1][0]["evaluation"]["bar"]["time"] == value["bars"][1]["time"]*1000
    assert converted[1][0]["evaluation"]["event_time_ms"] == value["bars"][1]["time"]*1000
    value.pop("execution_tick_contract")
    with pytest.raises(ValueError,match="were not negotiated"):
        execution_input(value)


def test_larger_tick_groups_require_explicit_budget_and_cannot_change_prefix_contract(monkeypatch):
    advertise(monkeypatch)
    value=ticks()
    value["execution_schedule"][0]=[deepcopy(value["execution_schedule"][0][0]) for _ in range(66)]
    assert len(execution_input(value)["execution_schedule"][0]) == 66
    prefix=PrefixInput()
    prefix.decode(value)
    before=deepcopy(prefix.request)
    bar,account=data(1)
    for contract in [None,"unknown"]:
        with pytest.raises(ValueError,match="tick schedule mode changed"):
            prefix.decode(dict(operation="append_prefix",prefix_base=1,bars=[bar],accounts=[account],execution_schedule=[value["execution_schedule"][0]],execution_tick_contract=contract))
        assert prefix.request == before
    value.pop("execution_tick_contract")
    with pytest.raises(ValueError,match="one to 65"):
        execution_input(value)


@pytest.mark.skipif(getattr(pine_compat,"EXTERNAL_TICK_SCHEDULE_SCHEMA_VERSION",0)!=1,reason="requires installed tick-capable core")
@pytest.mark.parametrize("route",[chart_strategy.execute,external_strategy.execute])
def test_actual_tick_schedule_crosses_each_bridge_with_explicit_acknowledgement(route):
    value=ticks(2)
    result=route(value)
    assert result["execution_tick_contract"] == TICK_CONTRACT
    assert result["execution_schedule_contract"] == CONTRACT
    assert [row["values"] for row in result["raw_output"]["plots"]] == [[1,2],[4,8],[1,1]]
