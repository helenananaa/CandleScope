"""Explicit Host execution contexts, with chart seconds and event milliseconds."""
import pine_compat

from .strategy_time import engine_bars

CONTRACT = "candlescope.pine-execution-schedule/1"
PREFIX_CONTRACT = "candlescope.pine-prefix-schedule/1"


def capabilities():
    if getattr(pine_compat, "EXTERNAL_SCHEDULE_SCHEMA_VERSION", 0) != 1:
        return {}
    return {"execution_schedule_contract": CONTRACT, "prefix_schedule": PREFIX_CONTRACT}


def engine_pass(item):
    return {
        **item,
        "bar": engine_bars([item["bar"]])[0],
        "account": {**item["account"], "time": item["account"]["time"] * 1000},
        **({"request_data": [
            {"symbol": stream["symbol"], "timeframe": stream["timeframe"], "bars": engine_bars(stream["bars"])}
            for stream in item["request_data"]
        ]} if "request_data" in item else {}),
    }


def execution_input(request, start=0):
    schedule = request.get("execution_schedule")
    contract = request.get("execution_schedule_contract")
    passes = request.get("execution_passes")
    if schedule is None and contract is None:
        return ({"execution_passes": [[engine_pass(item) for item in group]
                                      for group in passes[start:]]} if passes is not None else {})
    if (contract != CONTRACT or not capabilities() or passes is not None
            or not isinstance(schedule, list) or len(schedule) != len(request["bars"])):
        raise ValueError("EXTERNAL_SCHEDULE_INVALID: explicit supported contract and one group per bar required")
    converted = []
    for group in schedule[start:]:
        if not isinstance(group, list) or not 1 <= len(group) <= 65:
            raise ValueError("EXTERNAL_SCHEDULE_INVALID: one to 65 evaluations per group required")
        target = []
        for item in group:
            if (not isinstance(item, dict) or set(item) != {"evaluation", "context"}
                    or not isinstance(item["evaluation"], dict) or not isinstance(item["context"], dict)):
                raise ValueError("EXTERNAL_SCHEDULE_INVALID: evaluation and context required")
            evaluation = item["evaluation"]
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
