"""One isolated external-account stream; the Host records and replays its inputs."""
from copy import deepcopy

import pine_compat

from .entry_risk import options as risk_options
from .execution_schedule import CONTRACT as SCHEDULE, TICK_CONTRACT, engine_pass, capabilities as schedules
from .host_inputs import require_price_grid, require_quote_currency
from .libraries import library_sources
from .request_updates import CONTRACT as REQUESTS, eligible as requested_eligible, validate_contract
from .strategy_time import engine_bars

CONTRACT = "candlescope.pine-external-stream/1"
WINDOW_CONTRACT = "candlescope.pine-request-window-plan/1"
FEEDBACK_CONTRACT = "candlescope.pine-window-feedback/1"
OPERATIONS = {"stream_open", "stream_begin", "stream_observe", "stream_commit", "stream_snapshot", "stream_rebase"}
_active = None


def capabilities():
    methods = ("begin_bar", "observe", "commit_bar", "snapshot", "initialize_history")
    session = getattr(pine_compat, "ExternalSession", None)
    schema = getattr(pine_compat, "EXTERNAL_STREAM_SCHEMA_VERSION", 0)
    if (type(schema) is int and schema == 1
            and schedules().get("execution_tick_contract") == TICK_CONTRACT
            and session is not None and all(callable(getattr(session, name, None)) for name in methods)):
        window=getattr(pine_compat,"EXTERNAL_REQUEST_WINDOW_PLAN_SCHEMA_VERSION",0)
        feedback=getattr(pine_compat,"EXTERNAL_WINDOW_FEEDBACK_SCHEMA_VERSION",0)
        return {"external_stream_contract": CONTRACT,
                **({"request_window_plan_contract":WINDOW_CONTRACT} if type(window) is int and window==1 else {}),
                **({"window_feedback_contract":FEEDBACK_CONTRACT} if type(feedback) is int and feedback==1
                   and all(callable(getattr(session,name,None)) for name in ("window_status","rebase_window")) else {})}
    return {}


class Stream:
    def __init__(self, request, prepare, environment):
        allowed = {"protocol", "identity", "operation", "source", "libraries", "parameters", "context", "contexts",
                   "host_settings", "risk_contract", "closing_ticks", "order_metadata_contract", "currency_rates",
                   "request_update_contract", "historical_plan", "requested_history", "execution_schedule_contract", "execution_tick_contract",
                   "external_stream_contract", "window_feedback_contract"}
        if set(request) - allowed:
            raise ValueError("PINE_STREAM_INVALID: unknown opening fields")
        if (request.get("external_stream_contract") != CONTRACT or not capabilities()
                or request.get("execution_schedule_contract") != SCHEDULE
                or request.get("execution_tick_contract") != TICK_CONTRACT):
            raise ValueError("PINE_STREAM_UNSUPPORTED: explicit stream and tick contracts required")
        if "requested_history" in request and ("historical_plan" not in request
                or capabilities().get("request_window_plan_contract")!=WINDOW_CONTRACT):
            raise ValueError("PINE_STREAM_UNSUPPORTED: requested window planning requires known historical endpoints")
        self.feedback = request.get("window_feedback_contract")
        if self.feedback is not None and (self.feedback != FEEDBACK_CONTRACT
                or capabilities().get("window_feedback_contract") != FEEDBACK_CONTRACT
                or "historical_plan" not in request):
            raise ValueError("PINE_STREAM_UNSUPPORTED: observed window feedback requires a negotiated historical plan")
        program, analysis = prepare(request["source"], library_sources({"pineLibrarySources": request.get("libraries", {})}))
        require_price_grid(analysis, request)
        require_quote_currency(analysis, program.host_requirements(), request, external=True)
        parameters = {}
        for name, value in request.get("parameters", {}).items():
            matches = [item for item in analysis.get("inputs", [])
                       if str(item["callSiteId"]) == name or item.get("title") == name]
            if len(matches) != 1 or str(matches[0]["callSiteId"]) in parameters:
                raise ValueError("EXTERNAL_PARAMETER_INVALID: " + name)
            parameters[str(matches[0]["callSiteId"])] = value
        self.requested = request.get("request_update_contract")
        if self.requested is not None and (self.requested != REQUESTS or not requested_eligible(analysis)):
            raise ValueError("PINE_REQUEST_UPDATE_UNSUPPORTED: invalid streaming request contract")
        validate_contract(request)
        annotations = {}
        if request.get("order_metadata_contract") is not None:
            if (request["order_metadata_contract"] != "candlescope.pine-order-metadata/1"
                    or getattr(pine_compat, "EXTERNAL_ORDER_METADATA_SCHEMA_VERSION", 0) != 1):
                raise ValueError("EXTERNAL_UNSUPPORTED: unknown order metadata contract")
            annotations["order_metadata"] = True
        self.engine = program.external_session(input_overrides=parameters or None,
            chart_symbol=request["context"]["symbol"], chart_timeframe=request["context"]["timeframe"],
            request_bars=environment(request), scheduled=True,
            **({"closing_ticks": True} if request.get("closing_ticks") is True else {}),
            **annotations, **risk_options(request, analysis))
        self.skip = self.engine.initialize_history(engine_bars(request["historical_plan"]),
            **({"requested_history":request["requested_history"]} if "requested_history" in request else {}),
            **({"observed_feedback":True} if self.feedback else {})) if "historical_plan" in request else 0
        self.intents = 0
        self.passes = 0
        self.state = None
        profile = self.engine.snapshot(include_intents=False)
        self.profile = {key: profile[key] for key in ("pyramiding", "risk_rules") if key in profile}

    def execute(self, request):
        operation = request["operation"]
        allowed = {"operation", "protocol", "identity", "external_stream_contract", "bar_cursor", "intent_base"}
        allowed |= {"stream_begin": {"bar", "bar_state"}, "stream_observe": {"observation"},
                    "stream_snapshot": {"include_intents"}, "stream_rebase": {"seal"}}.get(operation, set())
        if (set(request) - allowed or type(request.get("bar_cursor")) is not int
                or request["bar_cursor"] != self.engine.cursor
                or type(request.get("intent_base")) is not int or request["intent_base"] != self.intents):
            raise ValueError("PINE_STREAM_CURSOR: cursor differs or frozen environment changed")
        if operation == "stream_begin":
            if self.engine.cursor >= 100_000:
                raise ValueError("PINE_STREAM_BUDGET: at most 100000 chart bars")
            bar = request["bar"]
            if type(bar.get("time")) is not int:
                raise ValueError("PINE_STREAM_INVALID: exact integer chart seconds required")
            self.engine.begin_bar(engine_bars([bar])[0], bar_state=request["bar_state"])
            self.passes, self.state = 0, request["bar_state"]
            result = {"intents": [], "intent_base": self.intents}
        elif operation == "stream_observe":
            observation = deepcopy(request["observation"])
            if (not isinstance(observation, dict) or set(observation) != {"evaluation", "context"}
                    or not isinstance(observation["evaluation"], dict) or not isinstance(observation["context"], dict)):
                raise ValueError("PINE_STREAM_INVALID: evaluation and context required")
            evaluation = observation["evaluation"]
            if (type(evaluation.get("confirmed")) is not bool or type(evaluation.get("event_time_ms")) is not int
                    or type(evaluation.get("bar", {}).get("time")) is not int
                    or type(evaluation.get("account", {}).get("time")) is not int):
                raise ValueError("PINE_STREAM_INVALID: exact seconds and milliseconds required")
            if self.requested is None and any(key in evaluation for key in ("request_updates", "request_observed_at_ms")):
                raise ValueError("PINE_STREAM_INVALID: requested updates were not negotiated")
            observation["evaluation"] = engine_pass(evaluation)
            try:
                result = self.engine.observe(observation, snapshot=False)
            except ValueError:
                status = self.engine.window_status() if self.feedback else None
                if not status or not status.get("rebase_required"):
                    raise
                # The observation may have emitted partial intents before its
                # window changed. Expose none of that interrupted execution.
                self.passes += 1
                return self.pack({"intents":[], "intent_base":self.intents})
            self.passes += 1
        elif operation == "stream_rebase":
            if not self.feedback or type(request.get("seal")) is not bool:
                raise ValueError("PINE_STREAM_INVALID: negotiated feedback and boolean seal required")
            self.skip = self.engine.rebase_window(seal=request["seal"])
            self.intents = self.passes = 0
            self.state = None
            result = {"intents":[], "intent_base":0}
        elif operation == "stream_commit":
            result = self.engine.commit_bar(snapshot=False)
        elif operation == "stream_snapshot":
            include = request.get("include_intents", False)
            if type(include) is not bool:
                raise ValueError("PINE_STREAM_INVALID: include_intents must be boolean")
            result = self.engine.snapshot(include_intents=include)
        else:
            raise ValueError("PINE_STREAM_INVALID: unknown operation")
        if operation == "stream_observe":
            if result["intent_base"] != self.intents:
                raise ValueError("PINE_STREAM_CURSOR: engine intent cursor differs")
            self.intents += len(result["intents"])
        return self.pack(result)

    def pack(self, result=None):
        return {"contract": "external-broker/1", "account_authority": "candlescope",
                "execution_mode": "CANDLESCOPE", "external_stream_contract": CONTRACT,
                "execution_schedule_contract": SCHEDULE, "execution_tick_contract": TICK_CONTRACT,
                **({"request_update_contract": REQUESTS} if self.requested else {}),
                **({"window_feedback_contract":FEEDBACK_CONTRACT,
                    "window_status":self.engine.window_status()} if self.feedback else {}),
                "bar_cursor": self.engine.cursor, "bar_open": self.engine.bar_open,
                "pass_cursor": self.passes, "intent_cursor": self.intents, "input_skip": self.skip,
                **self.profile, "stream_schema": 1, "intent_base": 0,
                **(result or {"intents": [], "intent_base": self.intents})}


def execute(request, prepare, environment):
    global _active
    try:
        if request.get("external_stream_contract") != CONTRACT:
            raise ValueError("PINE_STREAM_UNSUPPORTED: stream contract required")
        if request["operation"] == "stream_open":
            if _active is not None:
                raise ValueError("PINE_STREAM_INVALID: stream already open")
            _active = Stream(request, prepare, environment)
            return _active.pack()
        if _active is None:
            raise ValueError("PINE_STREAM_INVALID: stream not open")
        return _active.execute(request)
    except Exception:
        _active = None
        raise
