"""External broker adapter. Never evaluates the native broker ledger."""
import pine_compat
from .strategy_time import engine_bars
from candlescope_plugin_sdk.native_strategy import identity, serve, serve_evaluator
from functools import lru_cache


def describe():
    if not hasattr(pine_compat.Program, "run_external"):
        raise ValueError("EXTERNAL_RUNTIME_UNAVAILABLE: install external-broker/1 runtime")
    return identity("candlescope-plugin-pine-compat", "pine-compat-runtime", adapter="pine-external/5")


@lru_cache(maxsize=1)
def prepare(source):
    return pine_compat.compile_script(source), pine_compat.analyze_script(source).get("inputs", [])


def execute(request):
    program, inputs = prepare(request["source"])
    parameters = {}
    for name, value in request.get("parameters", {}).items():
        matches = [item for item in inputs if str(item["callSiteId"]) == name or item.get("title") == name]
        if len(matches) != 1 or str(matches[0]["callSiteId"]) in parameters:
            raise ValueError("EXTERNAL_PARAMETER_INVALID: " + name)
        parameters[str(matches[0]["callSiteId"])] = value
    passes = request.get("execution_passes")
    if passes is not None:
        passes = [[{**item, "bar": engine_bars([item["bar"]])[0],
            "account": {**item["account"], "time": item["account"]["time"] * 1000},
            **({"request_data": [{**stream, "bars": engine_bars(stream["bars"])} for stream in item["request_data"]]} if "request_data" in item else {})} for item in group] for group in passes]
    accounts = [{**item, "time": item["time"] * 1000} for item in request["accounts"]]
    supplied = {f'{item["symbol"]}:{item["timeframe"]}': engine_bars(item["bars"]) for item in request.get("contexts", [])}
    tick = request.get("host_settings", {}).get("price_tick")
    if tick is not None:
        from fractions import Fraction
        grid = Fraction(str(tick))
        if grid <= 0 or max(grid.numerator, grid.denominator) > 4294967295:
            raise ValueError("EXTERNAL_UNSUPPORTED: tick size exceeds the runtime price grid")
        supplied["$chart"] = {"minMove":grid.numerator, "priceScale":grid.denominator}
    result = program.run_external(engine_bars(request["bars"]), accounts, input_overrides=parameters or None,
                                  chart_symbol=request["context"]["symbol"], chart_timeframe=request["context"]["timeframe"], execution_passes=passes,
                                  request_bars=supplied or None)
    if result["output"].get("diagnostics"):
        raise ValueError(str(result["output"]["diagnostics"]))
    return {"contract": result["protocol"], "pyramiding": result.get("pyramiding", 1), "intents": result["intents"], "graphics": result["output"].get("plots", []),
            "raw_output": result["output"], "execution_mode": "CANDLESCOPE", "account_authority": "candlescope"}


if __name__ == "__main__":
    import sys
    raise SystemExit((serve_evaluator if "--worker" in sys.argv else serve)(describe, execute))
