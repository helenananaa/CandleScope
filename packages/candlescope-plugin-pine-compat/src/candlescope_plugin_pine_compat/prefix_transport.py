"""Append-only input transport for one isolated external evaluator process."""

CONTRACT = "candlescope.pine-prefix/1"
PASSES_CONTRACT = "candlescope.pine-prefix-passes/1"
CLOCKS_CONTRACT = "candlescope.pine-prefix-clocks/1"


class PrefixInput:
    def __init__(self):
        self.request = None

    def decode(self, request):
        if request.get("operation") != "append_prefix":
            self.request = dict(request)
            for key in ("bars", "accounts", "execution_passes", "execution_times"):
                if isinstance(self.request.get(key), list):
                    self.request[key] = list(self.request[key])
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
        clocks = request.get("execution_times")
        if self.request.get("execution_times") is not None:
            if not isinstance(clocks, list) or len(clocks) != len(bars):
                raise ValueError("PINE_PREFIX_INVALID: append requires matching execution clocks")
        elif clocks is not None:
            raise ValueError("PINE_PREFIX_INVALID: execution clock mode changed")
        self.request["bars"].extend(bars)
        self.request["accounts"].extend(accounts)
        if passes is not None:
            self.request["execution_passes"].extend(passes)
        if clocks is not None:
            self.request["execution_times"].extend(clocks)
        return self.request
