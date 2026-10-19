import pytest
import pine_compat

from candlescope_plugin_pine_compat import external_strategy as adapter
from candlescope_plugin_pine_compat.entry_risk import CONTRACT
from candlescope_plugin_pine_compat.entry_risk import STOP_CONTRACT
from test_external_incremental import wire, data

pytestmark = pytest.mark.skipif(
    getattr(pine_compat, "STRATEGY_RISK_CONFIGURATION_SCHEMA_VERSION", 0) != 1,
    reason="requires declarative risk runtime candidate")


def test_workbench_control_query_resolves_settings_and_inputs_without_execution_bars():
    request=wire('if false\n    strategy.risk.max_position_size(input.int(2,"Cap"))')
    request["source"]=request["source"].replace('strategy("external")','strategy("external",process_orders_on_close=true)')
    result=adapter.execute({**request,"operation":"host_control","bars":[],"accounts":[],
        "parameters":{"Cap":3},"risk_contract":STOP_CONTRACT})
    assert result["contract"]=="candlescope.pine-workbench-control/1"
    assert result["execution"]["processOrdersOnClose"] is True
    assert result["risk_rules"]["rules"][0]["value"]==3
    assert "intents" not in result and "raw_output" not in result


def test_legacy_external_callers_cannot_silently_ignore_unreachable_risk_rules():
    request = wire('if false\n    strategy.risk.max_position_size(2)')
    bar, account = data(0)
    with pytest.raises(ValueError, match="EXTERNAL_UNSUPPORTED"):
        adapter.execute({**request, "bars": [bar], "accounts": [account]})


def test_explicit_host_contract_retains_rules_across_incremental_prefixes():
    request = {**wire('if false\n    strategy.risk.max_position_size(2)\nstrategy.entry("L",strategy.long,qty=5)'),
        "risk_contract": CONTRACT}
    bar, account = data(0)
    first = adapter.execute({**request, "bars": [bar], "accounts": [account]})
    # The interpreter exports the requested quantity. Only the Host may cap it.
    assert first["intents"][0]["qty"] == 5
    assert first["risk_rules"]["rules"][0]["value"] == 2
    bar, account = data(1)
    second = adapter.execute({"operation": "append_prefix", "prefix_base": 1, "bars": [bar], "accounts": [account]})
    assert second["risk_rules"] == first["risk_rules"]


def test_entry_handshake_does_not_authorize_unconnected_drawdown_rules():
    request = {**wire('if false\n    strategy.risk.max_drawdown(5,strategy.cash)'), "risk_contract": CONTRACT}
    bar, account = data(0)
    with pytest.raises(ValueError, match="EXTERNAL_UNSUPPORTED"):
        adapter.execute({**request, "bars": [bar], "accounts": [account]})


def test_explicit_stop_handshake_exports_declarations_without_native_enforcement():
    request = {**wire('if false\n    strategy.risk.max_drawdown(5,strategy.cash)\nstrategy.entry("L",strategy.long,qty=5)'),
        "risk_contract": STOP_CONTRACT}
    bar, account = data(0)
    result = adapter.execute({**request, "bars": [bar], "accounts": [account]})
    assert result["risk_rules"]["rules"][0]["function"] == "strategy.risk.max_drawdown"
    assert result["intents"][0]["qty"] == 5
    assert not result["raw_output"].get("strategy")
