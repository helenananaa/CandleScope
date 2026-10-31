"""Negotiated causal requested-data observations, with explicit timestamp units."""
import pine_compat

from .strategy_time import engine_bars

CONTRACT = "candlescope.pine-request-updates/1"
MAX_TIMESTAMP = 9_007_199_254_740_991


def capabilities():
    return ({"request_update_contract": CONTRACT}
            if getattr(pine_compat, "EXTERNAL_REQUEST_UPDATE_SCHEMA_VERSION", 0) == 1 else {})


def eligible(analysis):
    return bool(capabilities()) and not any(item.get("feature", "").startswith("ticker.")
        for item in analysis.get("compatibility", {}).get("supported", []))


def eligible_stream(analysis):
    from .event_stream import required
    return eligible(analysis) or bool(capabilities()) and required(analysis)


def validate_contract(request):
    contract = request.get("request_update_contract")
    groups = request.get("request_updates")
    if contract is None:
        passes = request.get("execution_passes") or []
        schedule = request.get("execution_schedule") or []
        if (groups is not None or any("request_updates" in item for group in passes for item in group)
                or any("request_updates" in item.get("evaluation", {}) for group in schedule for item in group)):
            raise ValueError("PINE_REQUEST_UPDATE_UNAVAILABLE: requested updates were not negotiated")
        return False
    if contract != CONTRACT or not capabilities():
        raise ValueError("PINE_REQUEST_UPDATE_UNAVAILABLE: requested-update contract is unsupported")
    if any(context.get("bars") for context in request.get("contexts", [])):
        raise ValueError("PINE_REQUEST_UPDATE_INVALID: initial requested contexts must be empty")
    if groups is not None and (not isinstance(groups, list) or len(groups) != len(request["bars"])
            or not isinstance(request.get("accounts"), list) or len(request["accounts"]) != len(request["bars"])
            or request.get("execution_passes") is not None or request.get("execution_schedule") is not None):
        raise ValueError("PINE_REQUEST_UPDATE_INVALID: one standalone group per chart bar is required")
    return groups is not None


def engine_updates(updates):
    if not isinstance(updates, list):
        raise ValueError("PINE_REQUEST_UPDATE_INVALID: requested updates must be a list")
    result = []
    for item in updates:
        if (not isinstance(item, dict) or set(item) != {"symbol", "timeframe", "kind", "bar", "available_at_ms"}
                or not isinstance(item["bar"], dict) or set(item["bar"]) != {"time", "open", "high", "low", "close", "volume"}
                or type(item["bar"]["time"]) is not int or type(item["available_at_ms"]) is not int
                or abs(item["available_at_ms"]) > MAX_TIMESTAMP):
            raise ValueError("PINE_REQUEST_UPDATE_INVALID: exact bar seconds and availability milliseconds required")
        result.append({**item, "bar": engine_bars([item["bar"]])[0]})
    return result


def closed_schedule(request, start):
    result = []
    for index in range(start, len(request["bars"])):
        group = request["request_updates"][index]
        if (not isinstance(group, dict) or set(group) != {"observed_at_ms", "updates"}
                or type(group["observed_at_ms"]) is not int or abs(group["observed_at_ms"]) > MAX_TIMESTAMP):
            raise ValueError("PINE_REQUEST_UPDATE_INVALID: an integer observation clock is required")
        updates = engine_updates(group["updates"])
        if any(item["available_at_ms"] > group["observed_at_ms"] for item in updates):
            raise ValueError("PINE_REQUEST_UPDATE_INVALID: future requested observation")
        clocks = request.get("execution_times")
        clock = clocks[index] if clocks is not None else group["observed_at_ms"]
        result.append([dict(evaluation=dict(bar=engine_bars([request["bars"][index]])[0],
            account={**request["accounts"][index], "time": request["accounts"][index]["time"] * 1000},
            event_time_ms=clock, confirmed=True, request_updates=updates),
            context=dict(bar_state="historical", trigger="bar_close", is_new=True))])
    return {"execution_schedule": result}
