"""External broker adapter. Account state belongs exclusively to the host."""
from dataclasses import replace
from pyne_runtime.external import run_external
from pyne_runtime.metadata import SymbolInfo, TimeframeInfo
from candlescope_plugin_sdk.native_strategy import identity, serve, serve_evaluator
from .host_policy import host_settings
from .native_strategy import FrozenProvider


def describe():
    return identity("candlescope-plugin-pyne", "pyne-runtime", adapter="pyne-external/4")


def execute(request):
    symbol = SymbolInfo.from_value(request["context"]["symbol"])
    tick = request.get("host_settings", {}).get("price_tick")
    if tick is not None:
        symbol = replace(symbol, mintick=float(tick))
    settings = replace(host_settings(security_mode="safe"), timeout_seconds=None,
                       data_provider=FrozenProvider(request.get("contexts", [])),
                       syminfo=symbol,
                       timeframe=TimeframeInfo.from_value(request["context"]["timeframe"]))
    result = run_external(request["source"], request["bars"], request["accounts"], params=request.get("parameters"), settings=settings, execution_passes=request.get("execution_passes"), allow_requests=True)
    return {"contract": result["protocol"], "pyramiding": result.get("pyramiding", 1), "intents": result["intents"], "graphics": result["graphics"],
            "raw_output": result["output"], "execution_mode": "CANDLESCOPE", "account_authority": "candlescope"}


if __name__ == "__main__":
    import sys
    raise SystemExit((serve_evaluator if "--worker" in sys.argv else serve)(describe, execute))
