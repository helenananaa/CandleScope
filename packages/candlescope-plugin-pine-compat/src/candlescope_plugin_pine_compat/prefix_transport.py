"""Append-only input transport for one isolated external evaluator process."""
from copy import deepcopy

CONTRACT = "candlescope.pine-prefix/1"
PASSES_CONTRACT = "candlescope.pine-prefix-passes/1"
CLOCKS_CONTRACT = "candlescope.pine-prefix-clocks/1"


class PrefixInput:
    def __init__(self):
        self.request = None

    def decode(self, request):
        if request.get("operation") != "append_prefix":
            if request.get("execution_schedule") is not None and request.get("execution_passes") is not None:
                raise ValueError("PINE_PREFIX_INVALID: execution formats are mutually exclusive")
            self.request = deepcopy(request)
            return request
        if (
            self.request is None
            or type(request.get("prefix_base")) is not int
            or request["prefix_base"] != len(self.request["bars"])
        ):
            raise ValueError("PINE_PREFIX_MISMATCH: evaluator prefix differs from the Host")
        bars, accounts = request.get("bars"), request.get("accounts")
        if (
            not isinstance(bars, list)
            or not isinstance(accounts, list)
            or not bars
            or len(bars) != len(accounts)
        ):
            raise ValueError("PINE_PREFIX_INVALID: append requires matching bars and accounts")
        if len(self.request["bars"]) + len(bars) > 100_000:
            raise ValueError("PINE_PREFIX_BUDGET: at most 100000 chart bars")
        passes = request.get("execution_passes")
        if self.request.get("execution_passes") is not None:
            if not isinstance(passes, list) or len(passes) != len(bars):
                raise ValueError("PINE_PREFIX_INVALID: append requires matching execution passes")
        elif passes is not None:
            raise ValueError("PINE_PREFIX_INVALID: execution mode changed")
        schedule = request.get("execution_schedule")
        if self.request.get("execution_schedule") is not None:
            if (passes is not None or not isinstance(schedule, list) or len(schedule) != len(bars)
                    or request.get("execution_schedule_contract", self.request.get("execution_schedule_contract"))
                    != self.request.get("execution_schedule_contract")):
                raise ValueError("PINE_PREFIX_INVALID: append requires matching execution schedule")
        elif schedule is not None or request.get("execution_schedule_contract") is not None:
            raise ValueError("PINE_PREFIX_INVALID: execution schedule mode changed")
        clocks = request.get("execution_times")
        if self.request.get("execution_times") is not None:
            if not isinstance(clocks, list) or len(clocks) != len(bars):
                raise ValueError("PINE_PREFIX_INVALID: append requires matching execution clocks")
        elif clocks is not None:
            raise ValueError("PINE_PREFIX_INVALID: execution clock mode changed")
        self.request["bars"].extend(deepcopy(bars))
        self.request["accounts"].extend(deepcopy(accounts))
        if passes is not None:
            self.request["execution_passes"].extend(deepcopy(passes))
        if schedule is not None:
            self.request["execution_schedule"].extend(deepcopy(schedule))
        if clocks is not None:
            self.request["execution_times"].extend(deepcopy(clocks))
        return self.request
