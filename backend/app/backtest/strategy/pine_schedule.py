"""Frozen execution-context transport for the chart Pine provider."""
from copy import deepcopy

from .protocol import StrategyProviderError

CONTRACT = "candlescope.pine-execution-schedule/1"


def frame_context(frame, enabled):
    context = frame.features.get("pineExecutionContext")
    if not enabled:
        if context is not None:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "Pine schedule context was not negotiated")
        return None
    if (not isinstance(context, dict) or set(context) != {"bar_state", "trigger", "is_new"}
            or context["bar_state"] not in {"historical", "realtime"}
            or context["trigger"] not in {"bar_close", "order_fill", "closing_fill", "realtime_tick"}
            or type(context["is_new"]) is not bool):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "an explicit Pine execution context is required")
    return dict(context)


def encode(passes, contexts):
    if len(passes) != len(contexts) or any(len(a) != len(b) for a, b in zip(passes, contexts)):
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "Pine schedule contexts differ from evaluations")
    return [[{"evaluation": item, "context": context} for item, context in zip(group, states)]
            for group, states in zip(passes, contexts)]


def decode(schedule, count):
    if not isinstance(schedule, list) or len(schedule) != count:
        raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "restored Pine execution schedule is missing")
    passes, contexts = [], []
    for group in schedule:
        if (not isinstance(group, list) or not 1 <= len(group) <= 65
                or any(not isinstance(item, dict) or set(item) != {"evaluation", "context"}
                       or not isinstance(item["evaluation"], dict) or not isinstance(item["context"], dict)
                       for item in group)):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid restored Pine execution schedule")
        passes.append([deepcopy(item["evaluation"]) for item in group])
        contexts.append([deepcopy(item["context"]) for item in group])
    return passes, contexts
