import json
import pytest

from app.backtest.strategy.pine_engine import PineEngineProvider, analyze
from app.backtest.strategy.protocol import StrategyProviderError
from app.backtest.strategy.workspace import compile_revision
from tests.test_chart_pine_orders import run_chart
from tests.test_native_backtests import runtime as runtime, pytestmark as pytestmark


def test_unreachable_duplicate_limits_cap_actual_same_bar_fills(runtime):
    host, main = runtime
    report = run_chart(host, main, '''if false
    strategy.risk.max_position_size(2)
if bar_index==9
    strategy.risk.max_position_size(7)
if bar_index==0
    strategy.entry("A",strategy.long,qty=5)
    strategy.entry("B",strategy.long,qty=5)
''')
    assert [float(fill["qty"]) for fill in report["fills"]] == [2]
    rules = report["pine_orders"]["risk_configuration"]["rules"]
    assert [row["value"] for row in rules] == [2, 7]


@pytest.mark.parametrize("prepared", [False, True])
def test_direction_and_cap_run_through_queued_and_cost_scenario_matchers(runtime, prepared):
    host, main = runtime
    report = run_chart(host, main, '''if false
    strategy.risk.allow_entry_in(strategy.direction.long)
strategy.risk.max_position_size(2)
if bar_index==0
    strategy.entry("L",strategy.long,qty=5)
if bar_index==1
    strategy.entry("S",strategy.short,qty=5,limit=100000)
if bar_index==3
    strategy.order("G",strategy.short,qty=4)
''', prepared=prepared)
    assert [float(fill["qty"]) for fill in report["fills"]] == [2, 2, 4]
    assert report["orders"][1]["type"] == "MARKET"
    assert float(report["pine_orders"]["open_entries"][0]["qty"]) == -4


def test_input_override_resolves_the_rule_in_the_real_chart_context(runtime):
    host, main = runtime
    report = run_chart(host, main, '''n=input.int(2,"Maximum")
f(simple float x)=>x*2
if false
    strategy.risk.max_position_size(f(n*syminfo.mintick))
if bar_index==0
    strategy.entry("L",strategy.long,qty=9)
''', parameters={"Maximum": 3}, price_tick=".5")
    assert [float(fill["qty"]) for fill in report["fills"]] == [3]
    assert report["pine_orders"]["risk_configuration"]["rules"][0]["value"] == 3


@pytest.mark.parametrize("call", [
    'max_drawdown(20,strategy.cash)', 'max_intraday_loss(20,strategy.cash)',
    'max_intraday_filled_orders(2)', 'max_cons_loss_days(2)',
])
def test_stop_rule_analysis_declares_the_required_host_execution_contract(call):
    result = analyze('//@version=6\nstrategy("Risk")\nif false\n    strategy.risk.' + call)
    assert result["identity"]["risk_stop_contract"] == "candlescope.pine-risk-stops/1"


def test_risk_revision_cannot_use_legacy_target_position_execution():
    revision = compile_revision({"language": "PINE_ENGINE", "name": "Risk", "source_text":
        '//@version=6\nstrategy("Risk")\nstrategy.risk.max_position_size(2)\nstrategy.entry("L",strategy.long,qty=5)'}, now_ms=1)
    provider = PineEngineProvider()
    with pytest.raises(StrategyProviderError, match="FIDELITY_UNSUPPORTED"):
        provider.prepare({"source": json.loads(revision["compiled_json"])["executionSource"], "outputMode": "TARGET_POSITION"})
