"""Workbench freeze and recovery must retain the negotiated risk identity."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.external_orders import ExternalOrders
from app.backtest.pine_workbench import CONTRACT, freeze_control, configure_risk, check_risk_response
from app.backtest.pine_risk_stops import CONTRACT as RISK_CONTRACT
from app.simulation.kernel import SimulationKernel
from tests.test_pine_risk_stops import configuration,rule


def test_metadata_negotiation_carries_no_future_bars_or_tape():
    identity={"workbench_control":CONTRACT,"risk_stop_contract":RISK_CONTRACT,
        "closing_tick_contract":"candlescope.pine-closing-tick/1"}
    controls=configuration(rule("max_drawdown",2,"cash"))
    def runner(plugin,request,**kwargs):
        assert request["bars"]==[] and request["contexts"][0]["bars"]==[]
        assert "execution_events" not in request and "execution_times" not in request
        assert request["contexts"][0]["metadata"]=={"priceTickSize":".25"}
        return {"identity":identity,"contract":CONTRACT,"execution":{"processOrdersOnClose":True,"calcOnOrderFills":False},
            "risk_rules":controls}
    wire={"identity":identity,"bars":[{"close":999}],"execution_events":[{"future":True}],"execution_times":[999],
        "contexts":[{"bars":[{"close":123}],"metadata":{"priceTickSize":".25"}}],"interval":"1m","execution_fidelity":"BAR_APPROX"}
    freeze_control(SimpleNamespace(runner=runner),{},wire,{})
    assert wire["closing_ticks"] and wire["risk_contract"]==RISK_CONTRACT
    controls["rules"][0]["value"]=99
    assert wire["pine_host_control"]["risk_rules"]["rules"][0]["value"]==2


def prepared():
    kernel=SimulationKernel(initial_balance=Decimal(1000))
    orders=ExternalOrders(kernel)
    wire={"pine_host_control":{"contract":CONTRACT,"risk_rules":configuration(rule("max_drawdown",2,"cash"))},
        "pine_risk_context":{}}
    return kernel,orders,wire


def test_missing_risk_stop_state_cannot_reopen_a_restored_workbench_run():
    _,orders,wire=prepared()
    with pytest.raises(BacktestError,match="checkpoint missing"):
        configure_risk(orders,wire,resume={"cursor":1})


def test_engine_cannot_change_frozen_risk_rules_on_a_later_prefix():
    _,orders,wire=prepared()
    configure_risk(orders,wire)
    bad=deepcopy(wire["pine_host_control"]["risk_rules"])
    bad["rules"][0]["value"]=200
    with pytest.raises(BacktestError,match="risk configuration changed"):
        check_risk_response(orders,wire,{"risk_rules":bad})


def test_risk_state_from_another_configuration_cannot_be_reused():
    _,orders,wire=prepared()
    stop=configure_risk(orders,wire)
    saved={"pine_risk_stops":stop.snapshot()}
    _,other,foreign=prepared()
    foreign["pine_host_control"]["risk_rules"]["rules"][0]["value"]=3
    with pytest.raises(BacktestError,match="configuration differs"):
        configure_risk(other,foreign,resume=saved)


@pytest.mark.parametrize("schedule,calc", [(False, True), (True, False)])
def test_bar_callbacks_require_both_source_setting_and_negotiated_schedule(schedule, calc):
    identity = {"workbench_control": CONTRACT}
    if schedule:
        identity["execution_schedule_contract"] = "candlescope.pine-execution-schedule/1"
    native = SimpleNamespace(runner=lambda *args, **kwargs: {"identity": identity, "contract": CONTRACT,
        "execution": {"processOrdersOnClose": False, "calcOnOrderFills": calc}, "risk_rules": None})
    wire = {"identity": identity, "bars": [], "contexts": [], "fill_recalculation": True,
            "execution_fidelity": "BAR_APPROX"}
    with pytest.raises(BacktestError, match="explicit schedule support and calc_on_order_fills"):
        freeze_control(native, {}, wire, {})
    assert "pine_bar_path_contract" not in wire
