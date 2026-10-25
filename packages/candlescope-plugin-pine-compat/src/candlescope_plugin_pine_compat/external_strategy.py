"""Pine observations over an authoritative external account. No native broker."""
from copy import deepcopy
from functools import lru_cache
import json
import pine_compat
from .strategy_time import engine_bars
from .event_requests import run_with_event_requests
from .host_inputs import native_inputs
from candlescope_plugin_sdk.native_strategy import identity, serve, serve_evaluator


def describe():
    if getattr(pine_compat, "EXTERNAL_STREAM_SCHEMA_VERSION", None) != 1:
        raise ValueError("EXTERNAL_RUNTIME_UNAVAILABLE: install Pine 0.3.3")
    return identity("candlescope-plugin-pine-compat", "pine-compat-runtime", adapter="pine-external/6")


@lru_cache(maxsize=8)
def prepare(source, libraries="{}"):
    sources = json.loads(libraries) or None
    return pine_compat.compile_script(source, library_sources=sources), pine_compat.analyze_script(source, library_sources=sources).get("inputs", [])


def _clock(bar, timeframe):
    from datetime import datetime, timezone
    import re
    match = re.fullmatch(r"(\d+)?([SDWM]?)", timeframe)
    if not match:
        raise ValueError("EXTERNAL_TIMEFRAME_INVALID")
    count, unit = int(match[1] or 1), match[2]
    if unit == "M":
        instant = datetime.fromtimestamp(bar["time"] / 1000, timezone.utc)
        month = instant.year * 12 + instant.month - 1 + count
        return int(datetime(month // 12, month % 12 + 1, 1, tzinfo=timezone.utc).timestamp() * 1000) - 1
    return bar["time"] + count * {"": 60000, "S": 1000, "D": 86400000, "W": 604800000}[unit] - 1


def inputs(request):
    libraries, options = native_inputs(request)
    if options.get("execution_times") is not None:
        raise ValueError("EXTERNAL_CLOCK_INVALID: scheduled observations own the clock; omit executionTimes")
    if options.pop("session_windows", None):
        raise ValueError("EXTERNAL_UNSUPPORTED: account window rules must be enforced by the host")
    program, declarations = prepare(request["source"], json.dumps(libraries, sort_keys=True))
    parameters = {}
    for name, value in request.get("parameters", {}).items():
        matches = [item for item in declarations if str(item["callSiteId"]) == name or item.get("title") == name]
        if len(matches) != 1 or str(matches[0]["callSiteId"]) in parameters:
            raise ValueError("EXTERNAL_PARAMETER_INVALID: " + name)
        parameters[str(matches[0]["callSiteId"])] = value
    supplied = options.get("request_bars") or {}
    tick = request.get("host_settings", {}).get("price_tick")
    if tick is not None:
        from fractions import Fraction
        grid = Fraction(str(tick))
        if grid <= 0 or max(grid.numerator, grid.denominator) > 4294967295:
            raise ValueError("EXTERNAL_UNSUPPORTED: tick size exceeds the runtime price grid")
        existing = supplied.get("$chart", {})
        if existing and Fraction(existing["minMove"], existing["priceScale"]) != grid:
            raise ValueError("EXTERNAL_METADATA_MISMATCH: matching and Pine price grids differ")
        supplied["$chart"] = {**existing, "minMove": grid.numerator, "priceScale": grid.denominator}
    bars = engine_bars(request["bars"])
    accounts = [{**row, "time": row["time"] * 1000} for row in request["accounts"]]
    passes = request.get("execution_passes")
    schedule = request.get("execution_schedule")
    if schedule is not None and passes is not None:
        raise ValueError("EXTERNAL_SCHEDULE_INVALID: supply one execution schedule")
    if schedule is None:
        groups = passes or [[{"bar": raw, "account": frame, "confirmed": True,
            "event_time_ms": _clock(bar, request["context"]["timeframe"])}]
            for raw, bar, frame in zip(request["bars"], bars, request["accounts"], strict=True)]
        if passes is None and request.get("contexts"):
            for group in groups:
                row = group[0]
                row["request_data"] = [{**stream, "bars": [bar for bar in stream["bars"]
                    if _clock(engine_bars([bar])[0], stream["timeframe"]) <= row["event_time_ms"]]}
                    for stream in request["contexts"]]
        # Print-driven host matching evaluates a developing candle. Historical
        # bar-only execution has different Pine barstate/rollback semantics.
        schedule = [[{"evaluation": row, "context": {"bar_state": "realtime" if passes is not None else "historical",
            "trigger": "bar_close" if row["confirmed"] else "order_fill", "is_new": index == 0}}
            for index, row in enumerate(group)] for group in groups]
    converted = []
    for group in schedule:
        values = []
        for item in group:
            row = item["evaluation"]
            evaluation = {**row, "bar": engine_bars([row["bar"]])[0],
                "account": {**row["account"], "time": row["account"]["time"] * 1000}}
            if "request_data" in row:
                evaluation["request_data"] = [{**stream, "bars": engine_bars(stream["bars"])} for stream in row["request_data"]]
            values.append({"evaluation": evaluation, "context": item["context"]})
        converted.append(values)
    options.update(input_overrides=parameters or None, chart_symbol=request["context"]["symbol"],
        chart_timeframe=request["context"]["timeframe"], request_bars=supplied or None)
    return program, bars, accounts, converted, options


def pack(result):
    if result["output"].get("diagnostics"):
        raise ValueError(str(result["output"]["diagnostics"]))
    return {"contract": result["protocol"], "pyramiding": result.get("pyramiding", 1),
        "intents": result["intents"], "graphics": result["output"].get("plots", []),
        "raw_output": result["output"], "execution_mode": "CANDLESCOPE", "account_authority": "candlescope"}


def execute(request):
    return Evaluator().execute({**request, "planned_bars": request.get("planned_bars") or request["bars"]})


class Evaluator:
    """Apply only new observations. The host stores the authoritative transcript."""
    def __init__(self):
        self.session = None
        self.groups = []
        self.identity = None
        self.skip = 0

    def execute(self, request):
        program, bars, _accounts, schedule, options = inputs(request)
        if any(item.get("symbol", {}).get("kind") == "runtimeExpression"
               for item in program.host_requirements().get("requests", [])):
            # Preserve the existing evaluated-descriptor path for event series.
            # Rebuild from the frozen observed prefix with the caller's accounts;
            # this never invokes the native broker or supplies future feedback.
            supplied = options.pop("request_bars") or {}
            passes = ([[item["evaluation"] for item in group] for group in schedule]
                      if request.get("execution_passes") is not None
                      or request.get("execution_schedule") is not None else None)
            result = run_with_event_requests(lambda request_bars: program.run_external(
                bars, _accounts, execution_passes=passes, request_bars=request_bars, **options),
                request, supplied, engine_bars, pine_compat)
            return pack(result)
        signature = (request["source"], request.get("parameters"), request.get("libraries"),
                     request.get("host_inputs"), request["context"])
        if self.session is None:
            self.identity = deepcopy(signature)
            self.session = program.external_session(scheduled=True, **options)
            planned = request.get("planned_bars")
            if planned:
                initialize = self.session.initialize_realtime_history if schedule[0][0]["context"]["bar_state"] == "realtime" else self.session.initialize_history
                self.skip = initialize(engine_bars(planned), requested_history=request.get("requested_history"))
        elif signature != self.identity:
            raise ValueError("EXTERNAL_IDENTITY_CHANGED: frozen strategy inputs changed")
        for index, group in enumerate(schedule):
            previous = self.groups[index] if index < len(self.groups) else []
            if group[:len(previous)] != previous:
                raise ValueError("EXTERNAL_NONCAUSAL_PREFIX: committed observations changed")
            if len(group) == len(previous):
                continue
            if index < self.skip:
                if index == len(self.groups):
                    self.groups.append(deepcopy(group))
                continue
            if index - self.skip != self.session.cursor:
                raise ValueError("EXTERNAL_SCHEDULE_INVALID: attempted to revise a committed chart bar")
            if not self.session.bar_open:
                header = (group[0]["evaluation"]["bar"] if group[0]["context"]["bar_state"] == "realtime"
                    else engine_bars(request["planned_bars"])[index] if request.get("planned_bars") else bars[index])
                self.session.begin_bar(header, bar_state=group[0]["context"]["bar_state"])
            for observation in group[len(previous):]:
                self.session.observe(observation, snapshot=False)
            if index == len(self.groups):
                self.groups.append(deepcopy(group))
            else:
                self.groups[index] = deepcopy(group)
            if group[-1]["evaluation"]["confirmed"]:
                self.session.commit_bar(snapshot=False)
        result = self.session.snapshot()
        if self.skip:
            from .window_alignment import align_output
            result = deepcopy(result)
            for intent in result["intents"]:
                intent["bar_index"] += self.skip
            align_output(result["output"], self.skip)
        return pack(result)


if __name__ == "__main__":
    import sys
    raise SystemExit(serve_evaluator(describe, Evaluator().execute) if "--worker" in sys.argv else serve(describe, execute))
