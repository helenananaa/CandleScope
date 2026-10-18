"""Causal close-source Renko input; market bars remain the broker authority.

Rows retain their source open time, so multiple bricks can share a timestamp.
Their list ordinal is the synthetic history index. The source timeframe closes
the whole cohort; no fictional milliseconds or synthetic execution prices.
"""
from candlescope_plugin_sdk.synthetic_ohlcv import renko_rows
import json


CONTRACT = "renko-event-rows/1"


def _missing_context(output):
    for diagnostic in output.get("diagnostics", []):
        message = diagnostic.get("message", "")
        prefix = "missing request data for symbol `"
        separator = "` timeframe `"
        if message.startswith(prefix) and message.endswith("`") and separator in message:
            return message[len(prefix):-1].rsplit(separator, 1)
    return None


def run_with_event_requests(run, request, supplied, engine_bars, runtime):
    """Resolve actual evaluated ticker descriptors, never parse script text."""
    for _ in range(17):
        failure = None
        try:
            result = run(supplied or None)
        except ValueError as exc:
            failure = exc
            result = {"diagnostics": [{"message": str(exc)}]}
        missing = _missing_context(result.get("output", result))
        if missing is None:
            if failure is not None:
                raise failure
            return result
        symbol, timeframe = missing
        try:
            descriptor = json.loads(symbol)
        except (ValueError, TypeError):
            if failure is not None:
                raise failure
            return result
        if not isinstance(descriptor, dict) or descriptor.get("chart") != "renko":
            if failure is not None:
                raise failure
            return result
        if getattr(runtime, "EVENT_REQUEST_SERIES_CONTRACT", None) != CONTRACT:
            raise ValueError("SYNTHETIC_RUNTIME_REQUIRED: install the Renko event-series runtime")
        key = f"{symbol}:{timeframe}"
        if key in supplied:
            if failure is not None:
                raise failure
            return result
        source_symbol = descriptor.get("symbol")
        context = request["context"]
        source = request["bars"] if (source_symbol, timeframe) == (context["symbol"], context["timeframe"]) else next(
            (item["bars"] for item in request.get("contexts", [])
             if (item["symbol"], item["timeframe"]) == (source_symbol, timeframe)), None)
        if source is None:
            raise ValueError("SYNTHETIC_SOURCE_REQUIRED: freeze the requested market and timeframe first")
        supplied[key] = engine_bars(renko_rows(source, descriptor.get("style"), descriptor.get("param")))
    raise ValueError("SYNTHETIC_INPUT_BUDGET: at most 16 synthetic request contexts")
