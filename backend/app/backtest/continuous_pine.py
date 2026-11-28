"""Pine forward runs (B-333b): close-bar ORDER_INTENT scripts on the Host bar account.

A forward Pine run is the same Host run a fixed-history PINE_ENGINE revision makes
(``service.execute_bar_run``): the compiled ``candlescope.chart-pine/1`` envelope,
``PineEngineProvider``, the Pine Host order planner and the account view the script
reads. It runs the smallest qualified subset of that run and refuses the rest:

- orders only (ORDER_INTENT): the script places its own entries, exits and cancels;
- no fill callbacks, history or realtime ticks, closing ticks, stop windows or
  requested datasets, which need a bar path or stream the forward host does not have;
- no signal chart, practice account rules or execution realism (fixed Pine runs
  refuse practice rules too);
- no FOLLOW: the chart follows its Pine strategies on the Pine engine (ADR O1).

Creation compiles the code once with the installed Pine runtime and stores the
envelope in the run definition. Every later host start checks that stored
compilation and ``PineEngineProvider`` refuses a changed Pine installation.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from .errors import BacktestError
from .pine_host_config import forward_pine_refusals

PINE_FIELDS = frozenset({"execution_source", "dependency_hash"})


def _invalid(message):
    raise BacktestError("CONTINUOUS_INPUT_INVALID", message)


def _unsupported(message):
    raise BacktestError("FIDELITY_UNSUPPORTED", message)


def refusal_message(refused):
    return ("Forward runs place close-bar Pine orders; this script uses " + ", ".join(refused)
            + ". Run it over history instead.")


def _refuse(refused):
    if refused:
        _unsupported(refusal_message(refused))


def _compile(source, libraries):
    """Analyze Pine code on the installed runtime: its execution source, identity and forward refusals."""
    from .strategy.pine_engine import analyze
    from .strategy.protocol import StrategyProviderError
    from .strategy.workspace import pine_dependency_hash, pine_execution_source
    try:
        analysis = analyze(source, libraries)
    except StrategyProviderError as failure:
        raise BacktestError(failure.code, str(failure)) from failure
    execution_source = pine_execution_source(source, libraries, analysis)
    refused = forward_pine_refusals(json.loads(execution_source), (analysis.get("requirements") or {}).get("requests"))
    return execution_source, pine_dependency_hash(analysis, libraries), refused


def forward_support(source: str, libraries: object) -> dict[str, object]:
    """Whether a Pine script can run forward, compiled as creation would compile it; no run is made.

    The chart's strategy list asks before it offers forward tracking for a Pine strategy.
    """
    from .strategy.pine_engine import validate_libraries
    from .strategy.protocol import StrategyProviderError
    if type(source) is not str or not source.strip():
        _invalid("Pine source is required")
    try:
        checked = validate_libraries(libraries if libraries is not None else {})
    except StrategyProviderError as failure:
        raise BacktestError(failure.code, str(failure)) from failure
    _source, _identity, refused = _compile(source, checked)
    return {"supported": not refused, "uses": refused, "reason": refusal_message(refused) if refused else None}


def prepare_pine(payload: Mapping[str, object], source: str, mode: str, *, stored: bool) -> dict[str, object]:
    """Compile current Pine code, or check a stored compilation, without running the script."""
    from .strategy.pine_engine import ORDER_CONTRACT, SOURCE_SCHEMA, validate_libraries
    from .strategy.protocol import StrategyProviderError
    from .strategy.workspace import pine_dependency_hash

    if mode != "ORDER_INTENT":
        _unsupported("A Pine forward run places the script's own orders: choose ORDER_INTENT")
    if not source.strip():
        _invalid("Pine source is required")
    try:
        libraries = validate_libraries(payload.get("libraries", {}))
    except StrategyProviderError as failure:
        raise BacktestError(failure.code, str(failure)) from failure
    if stored:
        compiled = payload.get("pine")
        if (not isinstance(compiled, Mapping) or set(compiled) != PINE_FIELDS
                or any(type(value) is not str for value in compiled.values())):
            _invalid("A stored Pine provider requires its compilation")
        try:
            envelope = json.loads(compiled["execution_source"])
        except ValueError:
            _invalid("A stored Pine compilation must be JSON")
        if (not isinstance(envelope, dict) or envelope.get("schema") != SOURCE_SCHEMA
                or envelope.get("source") != source or envelope.get("libraries") != libraries
                or envelope.get("orderContract") != ORDER_CONTRACT or not isinstance(envelope.get("identity"), dict)
                or compiled["dependency_hash"] != pine_dependency_hash({"identity": envelope["identity"]}, libraries)):
            _invalid("A stored Pine compilation must match its source, libraries and runtime")
        _refuse(forward_pine_refusals(envelope))
        return {"libraries": libraries, "pine": dict(compiled)}
    execution_source, dependency_hash, refused = _compile(source, libraries)
    _refuse(refused)
    return {"libraries": libraries, "pine": {"execution_source": execution_source, "dependency_hash": dependency_hash}}


def refuse_before_compile(provider: object, execution: Mapping[str, object], *, follow: bool) -> None:
    """Refuse what no Pine forward run supports before compiling any code."""
    if not isinstance(provider, Mapping) or provider.get("language") != "pine":
        return
    if follow:
        _unsupported("The chart follows its Pine strategies on the Pine engine; FOLLOW here runs built-in and Python strategies")
    if execution.get("signal_chart") is not None:
        _unsupported("A Pine forward run follows its own chart's bars, without a signal chart")
    if "account_rules" in execution:
        _unsupported("Practice account rules run built-in and Python strategies; a Pine forward run uses the "
                     "CandleScope bar account at leverage 1")


def pine_definition_config(provider: Mapping[str, object], *, realism_enabled: bool) -> dict[str, object]:
    """The Pine identities a fixed-history run of the same compilation would hold."""
    if realism_enabled:
        _unsupported("A Pine forward run matches closed bars without execution realism")
    from .strategy.pine_planner import host_identity
    return {"pine_runtime_identity": provider["pine"]["dependency_hash"], "pine_order_runtime_identity": host_identity()}


def pine_input_plan(config: Mapping[str, object]) -> dict[str, object]:
    """The chart context ``execute_bar_run`` gives PineEngineProvider for the same configuration."""
    return {
        "pineChartMetadata": ({"priceTickSize": str(config["price_tick"])} if config.get("price_tick") is not None else None),
        "pineChartInterval": config.get("interval"),
        "pineChartMarketType": config.get("market_type"),
        "pineRequestedContexts": [],
        "pineLocalDataRoot": None,
    }
