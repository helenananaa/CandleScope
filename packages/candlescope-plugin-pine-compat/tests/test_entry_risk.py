import pytest
import pine_compat

from candlescope_plugin_pine_compat import external_strategy as adapter
from candlescope_plugin_pine_compat.entry_risk import CONTRACT
from test_external_incremental import wire, data

pytestmark = pytest.mark.skipif(
    getattr(pine_compat, "STRATEGY_RISK_CONFIGURATION_SCHEMA_VERSION", 0) != 1,
    reason="requires declarative risk runtime candidate")


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
