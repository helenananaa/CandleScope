"""Native Pine broker execution. Deliberately bypasses the indicator bridge."""
from __future__ import annotations

import pine_compat
from .strategy_time import engine_bars, engine_magnifier, chart_records
from candlescope_plugin_sdk.native_strategy import identity, serve


def describe():
    if not callable(getattr(pine_compat.Program, "historical_session", None)):
        raise ValueError(
            "NATIVE_CAPABILITY_UNSUPPORTED: this Pine wheel lacks fixed-history replay; "
            "retain the qualified native installation separately from the indicator plugin"
        )
    result = identity("candlescope-plugin-pine-compat", "pine-compat-runtime",
                    adapter="pine-native/2")
    result["historical_session"] = "fixed-history/1"
    return result


def prepare(request):
    inputs = pine_compat.analyze_script(request["source"]).get("inputs", [])
    overrides = {}
    for name, value in request.get("parameters", {}).items():
        matches = [item for item in inputs if str(item["callSiteId"]) == name or item.get("title") == name]
        if len(matches) != 1:
            raise ValueError(f"NATIVE_INPUT_UNKNOWN_OR_AMBIGUOUS: {name}")
        key = str(matches[0]["callSiteId"])
        if key in overrides:
            raise ValueError(f"NATIVE_INPUT_DUPLICATE: {name}")
        overrides[key] = value
    program = pine_compat.compile_script(request["source"],
                                        library_sources=request.get("libraries") or None)
    requirements = program.host_requirements()
    context = request["context"]
    supplied = {f"{item['symbol']}:{item['timeframe']}": engine_bars(item["bars"])
                for item in request.get("contexts", [])}
    execution = requirements.get("execution", {})
    uses_magnifier = execution.get("magnifier") not in (None, "notEnabled", "notRequested", "disabled", False)
    if uses_magnifier and not request.get("magnifier"):
        raise ValueError("NATIVE_DATA_MISSING: Bar Magnifier requires a frozen lower-timeframe dataset")
    return program, overrides, requirements, uses_magnifier


def execute(request):
    program, overrides, requirements, uses_magnifier = prepare(request)
    context = request["context"]
    supplied = {f"{item['symbol']}:{item['timeframe']}": engine_bars(item["bars"]) for item in request.get("contexts", [])}
    output = program.run(engine_bars(request["bars"]), input_overrides=overrides or None,
                         chart_symbol=context["symbol"], chart_timeframe=context["timeframe"],
                         request_bars=supplied or None, magnifier_bars=engine_magnifier(request.get("magnifier")))
    return pack(request, output, requirements, uses_magnifier)


def pack(request, output, requirements, uses_magnifier=False):
    diagnostics = list(output.get("diagnostics", []))
    strategy = output.get("strategy")
    if not isinstance(strategy, dict):
        raise ValueError("NATIVE_STRATEGY_REQUIRED: use a strategy declaration")
    diagnostics += strategy.get("diagnostics", [])
    # Missing data and broker fallbacks must not become a successful empty report.
    failures = [item for item in diagnostics if item.get("code") != "E_STRATEGY_MARGIN"]
    if failures:
        raise ValueError("NATIVE_DIAGNOSTICS: " + str(failures))
    bars = request["bars"]
    equity = [{"time": bars[row["barIndex"]]["time"], "value": row["equity"]}
              for row in strategy.get("equity", [])]
    return {"execution_mode": "NATIVE", "account_authority": "pine-compat-runtime",
            "fill_model": "pine-native-bar-magnifier" if uses_magnifier else "pine-native-standard-ohlcv", "raw_output": output,
            "trades": chart_records(strategy.get("trades", [])), "orders": chart_records(strategy.get("orders", [])),
            "equity": equity, "position": strategy.get("position", []),
            "graphics": output.get("plots", []), "requirements": requirements,
            "diagnostics": diagnostics}


if __name__ == "__main__":
    raise SystemExit(serve(describe, execute))
