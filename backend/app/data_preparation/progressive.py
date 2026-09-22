"""Deterministic BAR prefix and subsequent publication ranges."""
from .models import PreparationError, split_requirement


PREFIX_MS = 256 * 60_000


def plan(request):
    setup = request.intent.get("replay_setup", {})
    if (request.consumer != "REPLAY" or len(request.requirements) != 1
            or setup.get("source_kind") != "BAR" or setup.get("start_mode") != "MANUAL"
            or setup.get("account_data_mode", "APPROX_PROXY") != "APPROX_PROXY"
            or setup.get("position_mode", "ONE_WAY") != "ONE_WAY"
            or setup.get("book_mode") != "OFF"):
        raise PreparationError("PROGRESSIVE_UNAVAILABLE",
            "Progressive preparation requires a fixed BAR replay with proxy account inputs and no order book")
    requirement = request.requirements[0]
    start = setup.get("requested_start_ms")
    horizon = setup.get("forward_cache_ms")
    if (requirement.role != "BARS" or requirement.interval != "1m"
            or type(start) is not int or type(horizon) is not int
            or start % 60_000 or horizon < 60_000 or horizon % 60_000
            or requirement.start_ms > start or requirement.end_ms != start + horizon):
        raise PreparationError("PROGRESSIVE_INPUT_INVALID", "Progressive input must cover its exact fixed horizon")
    initial_horizon = min(PREFIX_MS, horizon)
    initial_end = start + initial_horizon
    initial = requirement.model_copy(update={"end_ms": initial_end})
    fragments = split_requirement(initial)
    if initial_end < requirement.end_ms:
        fragments.extend(split_requirement(requirement.model_copy(update={"start_ms": initial_end})))
    return {"start_ms": start, "end_ms": requirement.end_ms,
            "initial_horizon_ms": initial_horizon, "initial_end_ms": initial_end}, fragments
