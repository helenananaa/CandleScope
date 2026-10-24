"""Default sizing is discovered structurally and frozen before Host execution."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.backtest.errors import BacktestError
from app.backtest.pine_sizing import declaration, supported
from app.backtest.pine_workbench import CONTRACT, freeze_control
from app.backtest.strategy import pine_engine
from app.backtest.strategy.protocol import StrategyProviderError


@pytest.mark.parametrize("flag,expected", [(1,True),(0,False),(None,False),(True,False),(1.0,False)])
def test_sizing_schema_is_an_explicit_integer(flag, expected):
    assert supported({"external_sizing":flag}) is expected


@pytest.mark.parametrize("kind", ["fixed","cash","percent_of_equity"])
@pytest.mark.parametrize("value", ["0","70","0.7000"])
def test_compiled_declaration_is_preserved_without_float_conversion(kind, value):
    raw={"kind":kind,"value":value}
    frozen=declaration(raw)
    raw["value"]="999"
    assert frozen=={"kind":kind,"value":value}


@pytest.mark.parametrize("value", [None, [], {}, {"kind":"cash"},
    {"kind":[],"value":"1"}, {"kind":"invented","value":"1"},
    {"kind":"cash","value":True}, {"kind":"cash","value":1},
    {"kind":"cash","value":"NaN"}, {"kind":"cash","value":"Infinity"},
    {"kind":"cash","value":"-0.1"}, {"kind":"cash","value":"x"},
    {"kind":"cash","value":"1"*1025}, {"kind":"cash","value":"1","extra":True}])
def test_malformed_declarations_fail_before_any_quantity_is_used(value):
    with pytest.raises(ValueError):
        declaration(value)


def test_workbench_freezes_the_default_quantity_and_rejects_missing_inventory():
    identity={"workbench_control":CONTRACT,"external_sizing":1}
    quantity={"kind":"percent_of_equity","value":"0.7"}
    response={"identity":identity,"contract":CONTRACT,"execution":{"calcOnOrderFills":False,"processOrdersOnClose":False},
              "default_quantity":quantity}
    native=SimpleNamespace(runner=lambda *args,**kwargs: response)
    wire={"identity":identity,"bars":[],"contexts":[],"interval":"1m","execution_fidelity":"BAR_APPROX"}
    freeze_control(native,{},wire,{})
    quantity["value"]="99"
    assert wire["pine_host_control"]["default_quantity"]=={"kind":"percent_of_equity","value":"0.7"}
    del response["default_quantity"]
    with pytest.raises(BacktestError) as failure:
        freeze_control(native,{},wire,{})
    assert failure.value.code=="EXTERNAL_PROTOCOL_ERROR"


@pytest.mark.parametrize("kind,features,flag,code", [
    ("cash",[],0,"FIDELITY_UNSUPPORTED"),
    ("percent_of_equity",[],0,"FIDELITY_UNSUPPORTED"),
    ("fixed",["strategy.default_entry_qty"],0,"FIDELITY_UNSUPPORTED"),
    ("fixed",[],0,None),("cash",[],1,None)])
def test_chart_admission_uses_the_compiled_inventory(monkeypatch,kind,features,flag,code):
    import app.backtest.native as native
    identity={"external_sizing":flag}
    result={"identity":identity,"pyramiding":1,"analysis":{"executable":True,"scriptMode":"strategy",
        "compatibility":{"supported":[{"feature":feature} for feature in features]}},
        "requirements":{"account":{"defaultQuantity":{"kind":kind,"value":"100"}},
                        "execution":{"clock":"notUsed"},"requests":[]}}
    monkeypatch.setattr(pine_engine,"plugin",lambda:{})
    monkeypatch.setattr(native,"invoke",lambda plugin,wire,**kwargs:
        {"identity":identity} if wire["operation"]=="describe" else deepcopy(result))
    if code:
        with pytest.raises(StrategyProviderError) as failure:
            pine_engine.analyze("compiled declaration fixture")
        assert failure.value.code==code
    else:
        assert pine_engine.analyze("compiled declaration fixture")==result
