"""Explicit Host execution contexts, with chart seconds and event milliseconds."""
import pine_compat

from .strategy_time import engine_bars
from .request_updates import engine_updates

CONTRACT = "candlescope.pine-execution-schedule/1"
PREFIX_CONTRACT = "candlescope.pine-prefix-schedule/1"
TICK_CONTRACT = "candlescope.pine-tick-schedule/1"


def capabilities():
    if getattr(pine_compat, "EXTERNAL_SCHEDULE_SCHEMA_VERSION", 0) != 1:
        return {}
    result = {"execution_schedule_contract": CONTRACT, "prefix_schedule": PREFIX_CONTRACT}
    if (getattr(pine_compat, "EXTERNAL_TICK_SCHEDULE_SCHEMA_VERSION", 0) == 1
            and type(getattr(pine_compat, "MAX_STRATEGY_OBSERVATIONS_PER_BAR", None)) is int
            and pine_compat.MAX_STRATEGY_OBSERVATIONS_PER_BAR == 100_000):
        result.update(execution_tick_contract=TICK_CONTRACT, max_tick_passes_per_bar=100_000)
    return result


def engine_pass(item):
    updates = engine_updates(item["request_updates"]) if "request_updates" in item else None
    observed = item.get("request_observed_at_ms")
    if "request_observed_at_ms" in item:
        if (updates is None or type(observed) is not int
                or any(update["available_at_ms"] > observed for update in updates)):
            raise ValueError("PINE_REQUEST_UPDATE_INVALID: invalid requested observation boundary")
    return {
        **{key: value for key, value in item.items() if key != "request_observed_at_ms"},
        "bar": engine_bars([item["bar"]])[0],
        "account": {**item["account"], "time": item["account"]["time"] * 1000},
        **({"request_data": [
            {"symbol": stream["symbol"], "timeframe": stream["timeframe"], "bars": engine_bars(stream["bars"])}
            for stream in item["request_data"]
        ]} if "request_data" in item else {}),
        **({"request_updates": updates} if updates is not None else {}),
    }


def execution_input(request, start=0):
    schedule = request.get("execution_schedule")
    contract = request.get("execution_schedule_contract")
    passes = request.get("execution_passes")
    tick = request.get("execution_tick_contract")
    if "execution_tick_contract" in request and (
            tick != TICK_CONTRACT or capabilities().get("execution_tick_contract") != tick
            or schedule is None):
        raise ValueError("EXTERNAL_TICK_SCHEDULE_INVALID: explicit supported tick schedule required")
    if schedule is None and contract is None:
        return ({"execution_passes": [[engine_pass(item) for item in group]
                                      for group in passes[start:]]} if passes is not None else {})
    if (contract != CONTRACT or not capabilities() or passes is not None
            or not isinstance(schedule, list) or len(schedule) != len(request["bars"])):
        raise ValueError("EXTERNAL_SCHEDULE_INVALID: explicit supported contract and one group per bar required")
    converted = []
    for group in schedule[start:]:
        limit = 100_000 if tick == TICK_CONTRACT else 65
        if not isinstance(group, list) or not 1 <= len(group) <= limit:
            raise ValueError(f"EXTERNAL_SCHEDULE_INVALID: one to {limit} evaluations per group required")
        target = []
        for item in group:
            if (not isinstance(item, dict) or set(item) != {"evaluation", "context"}
                    or not isinstance(item["evaluation"], dict) or not isinstance(item["context"], dict)):
                raise ValueError("EXTERNAL_SCHEDULE_INVALID: evaluation and context required")
            evaluation = item["evaluation"]
            if item["context"].get("trigger") == "historical_tick" and tick != TICK_CONTRACT:
                raise ValueError("EXTERNAL_TICK_SCHEDULE_INVALID: historical ticks were not negotiated")
            if (type(evaluation.get("confirmed")) is not bool
                    or type(evaluation.get("event_time_ms")) is not int
                    or not isinstance(evaluation.get("account"), dict)
                    or type(evaluation["account"].get("time")) is not int
                    or not isinstance(evaluation.get("bar"), dict)
                    or type(evaluation["bar"].get("time")) is not int):
                raise ValueError("EXTERNAL_SCHEDULE_INVALID: exact bar/account seconds and event milliseconds required")
            target.append({"evaluation": engine_pass(evaluation), "context": dict(item["context"])})
        converted.append(target)
    return {"execution_schedule": converted}
