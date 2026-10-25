"""Public Pine host inputs shared by all three execution entry points.

Times in this contract are milliseconds; OHLCV context rows use the same
    seconds convention as the strategy bridge. No data is fetched.
"""
from collections.abc import Mapping
from .strategy_time import engine_bars

SOURCE_FIELDS = frozenset({"open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "hlcc4"})
FIELDS = frozenset({"schemaVersion", "libraries", "contexts", "chartMetadata", "symbolMetadata",
                    "currencyRates", "barCalendars", "executionTimes", "sessionWindows", "requestWarmupBars"})


def host_inputs(value=None):
    if value is None:
        return {}
    if not isinstance(value, Mapping) or set(value) - FIELDS:
        raise ValueError("PINE_HOST_INPUT_INVALID: unknown host input fields")
    result = dict(value)
    if result.get("schemaVersion", 1) != 1:
        raise ValueError("PINE_HOST_INPUT_INVALID: unsupported host input schema")
    libraries = result.get("libraries", {})
    if not isinstance(libraries, Mapping) or len(libraries) > 64 or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in libraries.items()
    ) or sum(len(v) for v in libraries.values()) > 2_000_000:
        raise ValueError("PINE_HOST_INPUT_INVALID: libraries must be a bounded source mapping")
    for name in ("chartMetadata", "symbolMetadata"):
        if name in result and not isinstance(result[name], Mapping):
            raise ValueError(f"PINE_HOST_INPUT_INVALID: {name} must be an object")
    contexts = result.get("contexts", [])
    if not isinstance(contexts, list) or len(contexts) > 32 or any(
        not isinstance(item, Mapping) or set(item) - {"symbol", "timeframe", "bars", "forming"}
        or not isinstance(item.get("symbol"), str) or not item["symbol"]
        or not isinstance(item.get("timeframe"), str) or not item["timeframe"]
        or ("forming" in item and type(item["forming"]) is not bool)
        or not isinstance(item.get("bars"), list) or len(item["bars"]) > 100000 for item in contexts
    ):
        raise ValueError("PINE_HOST_INPUT_INVALID: invalid requested context list")
    warmups = result.get("requestWarmupBars", {})
    if not isinstance(warmups, Mapping) or len(warmups) > 32 or any(type(v) is not int or not 0 <= v <= 5000 for v in warmups.values()):
        raise ValueError("PINE_HOST_INPUT_INVALID: request warmup must be 0-5000 bars")
    times = result.get("executionTimes")
    if times is not None and (not isinstance(times, list) or len(times) > 100000 or any(type(t) is not int or t < 0 for t in times)):
        raise ValueError("PINE_HOST_INPUT_INVALID: executionTimes must contain millisecond timestamps")
    return result


def request_environment(inputs, contexts=()):
    supplied = {}
    rows = [*contexts, *inputs.get("contexts", [])]
    if len(rows) > 32:
        raise ValueError("PINE_HOST_INPUT_INVALID: at most 32 requested contexts")
    for item in rows:
        key = f"{item['symbol']}:{item['timeframe']}"
        if key.startswith("$") or key in supplied:
            raise ValueError("PINE_HOST_INPUT_INVALID: duplicate or reserved requested context")
        supplied[key] = engine_bars(item["bars"][:-1] if item.get("forming") else item["bars"])
    for name, key in (("chartMetadata", "$chart"), ("symbolMetadata", "$symbolMetadata"),
                      ("currencyRates", "$currencyRates"), ("barCalendars", "$barCalendars")):
        if inputs.get(name):
            supplied[key] = inputs[name]
    return supplied


def native_inputs(request):
    inputs = host_inputs(request.get("host_inputs"))
    libraries = {**inputs.get("libraries", {}), **request.get("libraries", {})}
    supplied = request_environment(inputs, request.get("contexts", []))
    options = {"request_bars": supplied or None}
    if inputs.get("executionTimes") is not None:
        options["execution_times"] = inputs["executionTimes"]
    if inputs.get("sessionWindows") is not None:
        options["session_windows"] = inputs["sessionWindows"]
    return libraries, options


def diagnostic_code(error):
    message = str(error)
    prefix = message.partition(":")[0]
    if prefix.startswith(("E_", "PINE_")) and " " not in prefix:
        return prefix
    if "execution timestamp" in message or "execution_times" in message:
        return "PINE_EXECUTION_CLOCK_REQUIRED"
    if "request" in message.lower() and any(word in message.lower() for word in ("missing", "unavailable", "not found", "no data")):
        return "PINE_REQUEST_DATA_MISSING"
    return "PINE_EXECUTION_INPUT_INVALID"
