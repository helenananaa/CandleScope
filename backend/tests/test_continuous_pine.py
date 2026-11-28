"""Pine forward runs (B-333b) without a Pine runtime: compilation, refusals and Host wiring.

The installed-runtime equality against ``execute_bar_run`` is in
``test_continuous_pine_engine.py`` (Pine Host qualification).
"""
from copy import deepcopy
from decimal import Decimal
import json

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_definition import prepare_definition
from app.backtest.continuous_provider import ContinuousProviderFactory, execution_inputs, prepare_provider
from app.backtest.errors import BacktestError
from app.backtest.strategy import pine_engine
from app.backtest.strategy.pine_engine import PineEngineProvider
from app.backtest.strategy.pine_planner import PineHostPlanner, host_identity
from app.backtest.strategy.protocol import ProviderCapabilities
from app.backtest.strategy.workspace import pine_dependency_hash, pine_execution_source
from tests.test_continuous_bar_host import apply, prepare
from tests.test_continuous_definition import KEY
from tests.test_strategy_bar_continuation import events

SOURCE = '//@version=6\nstrategy("Forward")\nif close > open\n    strategy.entry("L", strategy.long, qty=1)\n'
ANALYSIS = {"identity": {"runtime": "fake-pine/1", "external_orders": 2},
            "requirements": {"execution": {"clock": "notUsed"}, "account": {}, "requests": []},
            "analysis": {"compatibility": {"supported": [{"feature": "strategy.entry"}]}}}


@pytest.fixture
def analyzed(monkeypatch):
    """Stand in for the Pine runtime's analysis; record each compilation."""
    state = {"analysis": deepcopy(ANALYSIS), "calls": []}

    def analyze(source, libraries=None):
        state["calls"].append(source)
        return deepcopy(state["analysis"])
    monkeypatch.setattr(pine_engine, "analyze", analyze)
    return state


def spec(**overrides):
    return {"language": "pine", "source_text": SOURCE, "output_mode": "ORDER_INTENT", **overrides}


def test_creation_compiles_the_envelope_a_pine_revision_holds(analyzed):
    prepared = prepare_provider(spec(parameters={"length": 3}))
    assert prepared["language"] == "pine" and prepared["libraries"] == {} and prepared["parameters"] == {"length": 3}
    assert prepared["pine"] == {"execution_source": pine_execution_source(SOURCE, {}, ANALYSIS),
                                "dependency_hash": pine_dependency_hash(ANALYSIS, {})}
    envelope = json.loads(prepared["pine"]["execution_source"])
    assert envelope["schema"] == "candlescope.chart-pine/1" and envelope["source"] == SOURCE
    assert analyzed["calls"] == [SOURCE]


@pytest.mark.parametrize("change,named", [
    ({"execution": {"clock": "notUsed", "calcOnOrderFills": True}}, "calc_on_order_fills"),
    ({"execution": {"clock": "notUsed", "calcOnEveryHistoryTick": True}}, "calc_on_every_history_tick"),
    ({"execution": {"clock": "notUsed", "calcOnEveryTick": True}}, "calc_on_every_tick"),
    ({"execution": {"clock": "notUsed", "processOrdersOnClose": True}}, "process_orders_on_close"),
    ({"requests": [{"function": "request.security"}]}, "request"),
])
def test_features_outside_the_close_bar_subset_are_refused_by_name(analyzed, change, named):
    analyzed["analysis"]["requirements"].update(change)
    with pytest.raises(BacktestError, match=named) as raised:
        prepare_provider(spec())
    assert raised.value.code == "FIDELITY_UNSUPPORTED"


def test_stop_rules_are_refused(analyzed):
    analyzed["analysis"]["analysis"]["compatibility"]["supported"].append({"feature": "strategy.risk.max_drawdown"})
    with pytest.raises(BacktestError, match="strategy.risk stop rules"):
        prepare_provider(spec())


@pytest.mark.parametrize("payload,code", [
    (spec(output_mode="TARGET_POSITION"), "FIDELITY_UNSUPPORTED"),
    (spec(runtime_mode="TRUSTED_LOCAL"), "CONTINUOUS_INPUT_INVALID"),
    (spec(builtin_id="builtin.sma"), "CONTINUOUS_INPUT_INVALID"),
    # Only a stored definition carries the Host's compilation.
    (spec(pine={"execution_source": "{}", "dependency_hash": "x"}), "CONTINUOUS_INPUT_INVALID"),
    (spec(source_text="  "), "CONTINUOUS_INPUT_INVALID"),
    (spec(libraries={"bad key": "x"}), "PINE_HOST_LIBRARIES_INVALID"),
    ({"language": "python", "source_text": "x", "libraries": {}}, "CONTINUOUS_INPUT_INVALID"),
])
def test_invalid_pine_editor_input_is_refused_before_compiling(analyzed, payload, code):
    with pytest.raises(BacktestError) as raised:
        prepare_provider(payload)
    assert raised.value.code == code and analyzed["calls"] == []


def _definition(tmp_path, monkeypatch, prepared, **configuration):
    service, row, base, _, store = prepare(tmp_path, monkeypatch)
    config = {key: value for key, value in base["configuration"].items()
              if key not in {"strategy_source", "output_mode", "parameters"}}
    config.update(pine_runtime_identity=prepared["pine"]["dependency_hash"],
                  pine_order_runtime_identity=host_identity(), price_tick="0.5", interval="1m",
                  market_type="futures", **configuration)
    return service, store, {**base, "language": "pine", "provider": prepared, "configuration": config,
                            "input_plan": {"roles": ["BARS"]}}


def test_stored_compilation_is_checked_without_compiling_again(tmp_path, monkeypatch, analyzed):
    prepared = prepare_provider(spec())
    service, store, definition = _definition(tmp_path, monkeypatch, prepared)
    try:
        provider = ContinuousProviderFactory()(definition)
        assert isinstance(provider, PineEngineProvider) and analyzed["calls"] == [SOURCE]
        config, plan = execution_inputs(definition)
        assert config["strategy_source"] == plan["source"] == prepared["pine"]["execution_source"]
        assert plan["outputMode"] == "ORDER_INTENT" and plan["pineChartInterval"] == "1m"
        assert plan["pineChartMetadata"] == {"priceTickSize": "0.5"} and plan["pineRequestedContexts"] == []
        envelope = json.loads(prepared["pine"]["execution_source"])
        for tampered in ({**prepared, "source_text": SOURCE + "\n"},
                         {**prepared, "pine": {**prepared["pine"], "dependency_hash": "sha256:" + "0" * 64}},
                         {**prepared, "pine": {**prepared["pine"], "execution_source": json.dumps({**envelope, "libraries": {"a/b/1": "x"}})}}):
            with pytest.raises(BacktestError, match="CONTINUOUS_INPUT_INVALID|must match"):
                ContinuousProviderFactory()({**definition, "provider": tampered})
        forged = json.dumps({**envelope, "fillCallbacks": True}, sort_keys=True)
        with pytest.raises(BacktestError, match="calc_on_order_fills"):
            ContinuousProviderFactory()({**definition, "provider": {**prepared, "pine": {**prepared["pine"], "execution_source": forged}}})
        with pytest.raises(BacktestError, match="identity must agree"):
            execution_inputs({**definition, "configuration": {**definition["configuration"], "pine_runtime_identity": "other"}})
        assert analyzed["calls"] == [SOURCE]
    finally:
        store.close()
        service.shutdown()


def test_definition_holds_the_identities_of_a_fixed_pine_run(analyzed):
    definition = prepare_definition(spec(), {"account_model": "LINEAR_PERP_ONE_WAY_V1"}, KEY)
    config = definition["configuration"]
    assert definition["language"] == "pine" and definition["provider"]["pine"]["dependency_hash"] == config["pine_runtime_identity"]
    assert config["pine_order_runtime_identity"] == host_identity()
    assert config["interval"] == KEY.interval and config["market_type"] == KEY.market_type


@pytest.mark.parametrize("execution,follow,named", [
    ({}, True, "Pine engine"),
    ({"signal_chart": {"kind": "HEIKIN_ASHI"}}, False, "signal chart"),
    ({"account_rules": "PRACTICE_V1", "leverage": "5"}, False, "Practice account rules"),
])
def test_definition_refuses_follow_signal_charts_and_practice_rules_before_compiling(analyzed, execution, follow, named):
    with pytest.raises(BacktestError, match=named):
        prepare_definition(spec(), {"account_model": "LINEAR_PERP_ONE_WAY_V1", **execution}, KEY, follow=follow)
    assert analyzed["calls"] == []


def test_definition_refuses_execution_realism(analyzed):
    with pytest.raises(BacktestError, match="execution realism"):
        prepare_definition(spec(), {"account_model": "LINEAR_PERP_ONE_WAY_V1",
                                    "execution_model_revision": "EXECUTION_REALISM_V2"}, KEY)


class RecordingPine:
    """A Pine-shaped provider: it reads the Host account each bar and places no order."""

    def __init__(self):
        self.accounts = []

    def describe(self):
        return ProviderCapabilities(input_modes=("BAR_CLOSE",), output_modes=("ORDER_INTENT",), signal_clock="BAR_CLOSE")

    def prepare(self, context):
        self.context = context

    def warmup(self, frame):
        self.accounts.append(frame.account_view)

    def step(self, frame):
        self.accounts.append(frame.account_view)
        return None

    def on_execution_report(self, report):
        pass

    def snapshot(self):
        return {"bars": len(self.accounts)}

    def restore(self, payload):
        pass

    def close(self):
        return "closed"


def test_host_runs_pine_with_the_account_view_and_chart_context(tmp_path, monkeypatch, analyzed):
    prepared = prepare_provider(spec())
    service, store, definition = _definition(tmp_path, monkeypatch, prepared)
    providers = []

    def factory(_definition):
        providers.append(RecordingPine())
        return providers[-1]
    host = None
    try:
        ContinuousBarHost.create_run(store, "cs_pine", definition=definition, mode="HISTORY_LIVE",
                                     data_revision="r1", event_time_ms=0, provider_factory=factory)
        host = ContinuousBarHost.resume(store, "cs_pine", factory)
        assert isinstance(host.planner, PineHostPlanner) and host.kernel.account.multiplier == Decimal(1)
        assert providers[-1].context["source"] == prepared["pine"]["execution_source"]
        assert providers[-1].context["pineChartMarketType"] == "futures"
        apply(host, events()[:5])
        accounts = providers[-1].accounts
        assert len(accounts) == 5 and all(view and view["position_size"] == 0.0 and view["equity"] == 10000.0
                                          for view in accounts)
    finally:
        if host is not None:
            host.close()
        store.close()
        service.shutdown()


@pytest.mark.parametrize("language,extra", [
    ("pine", {"pine_fill_callbacks": True}),
    ("pine", {"pine_process_on_close": True}),
    ("pine", {"pine_bar_path_contract": "candlescope.pine-bar-path/1"}),
    ("pine", {"signal_chart": {"kind": "HEIKIN_ASHI"}}),
    ("pine", {"account_rules": "PRACTICE_V1"}),
    ("builtin", {}),
])
def test_host_refuses_pine_contracts_outside_the_subset(tmp_path, monkeypatch, analyzed, language, extra):
    prepared = prepare_provider(spec())
    service, store, definition = _definition(tmp_path, monkeypatch, prepared, **extra)

    def forbidden(_):
        raise AssertionError("an unqualified Pine run must not start a provider")
    try:
        with pytest.raises(BacktestError, match="qualified closed-BAR clock"):
            ContinuousBarHost("cs_refused", {**definition, "language": language}, forbidden)
    finally:
        store.close()
        service.shutdown()
