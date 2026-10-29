"""Close-only observations against a negotiated, immutable history horizon."""
from copy import deepcopy

from .strategy_time import engine_bars
from .window_alignment import align_output

CONTRACT = "candlescope.pine-fixed-history/1"


class FixedHistory:
    def __init__(self, program, request, options):
        plan = request["planned_bars"]
        if not isinstance(plan, list) or not plan:
            raise ValueError("PINE_HISTORY_INVALID: a frozen history plan is required")
        self.plan = plan
        self.session = program.external_session(scheduled=True, **options)
        self.skip = self.session.initialize_history(engine_bars(plan), requested_history=request.get("requested_history"))
        self.count = 0

    def advance(self, request, accounts, evaluations, *, output=True):
        bars = request["bars"]
        # Earlier bars were checked when they arrived; a retained prefix only grows.
        if not self.count <= len(bars) <= len(self.plan) or bars[self.count:] != self.plan[self.count:len(bars)]:
            raise ValueError("PINE_HISTORY_INVALID: observed bars differ from the frozen plan")
        if "execution_passes" in evaluations:
            raise ValueError("PINE_HISTORY_UNSUPPORTED: fill callbacks require the negotiated stream")
        groups = evaluations.get("execution_schedule")
        clocks = request.get("execution_times")
        for index in range(self.count, len(bars)):
            if index < self.skip:
                continue
            bar = engine_bars([bars[index]])[0]
            group = groups[index] if groups is not None else [{
                "evaluation": {"bar": bar, "account": accounts[index], "confirmed": True,
                               "event_time_ms": clocks[index] if clocks is not None else bar["time"]},
                "context": {"bar_state": "historical", "trigger": "bar_close", "is_new": True},
            }]
            if len(group) != 1 or group[0]["context"]["bar_state"] != "historical" or not group[0]["evaluation"]["confirmed"]:
                raise ValueError("PINE_HISTORY_UNSUPPORTED: only historical close observations are admitted")
            self.session.begin_bar(bar, bar_state="historical")
            self.session.observe(group[0], snapshot=False)
            self.session.commit_bar(snapshot=False)
        self.count = len(bars)
        result = self.session.snapshot()
        if self.skip and not output:
            # A compact reply reads only intents and diagnostics from this
            # freshly built snapshot; its chart output is never returned.
            for intent in result["intents"]:
                intent["bar_index"] += self.skip
        elif self.skip:
            result = deepcopy(result)
            for intent in result["intents"]:
                intent["bar_index"] += self.skip
            align_output(result["output"], self.skip)
        # Close-only execution keeps the public bar-only intent coordinates.
        for intent in result["intents"]:
            intent.pop("pass_index", None)
        return result
