"""Host transcript and cursor ownership for one external Pine evaluator.

Recovery only reconstructs Pine decisions. It never calls the matching ledger.
The run coordinator must restore its ledger at the same transcript checkpoint.
"""
from copy import deepcopy
import hashlib
import json
import time

from .errors import BacktestError
from .native_session import SessionWorker, STREAM_CONTRACT, SCHEDULE_CONTRACT, TICK_CONTRACT

JOURNAL_CONTRACT = "candlescope.pine-stream-journal/1"
WINDOW_FEEDBACK_CONTRACT = "candlescope.pine-window-feedback/1"
REALTIME_WINDOW_CONTRACT = "candlescope.pine-realtime-window/1"


class WindowRebaseRequired(BacktestError):
    """Control transfer: discard the whole tentative ledger before retrying."""
    def __init__(self):
        super().__init__("PINE_WINDOW_REBASE_REQUIRED", "observed request window changed; discard tentative execution")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def canonical_observations(saved):
    """Only observations after the final plan reset belong to the live ledger."""
    observations=[]
    for entry in saved.get("journal",[]):
        command=entry.get("command",{})
        if command.get("operation")=="stream_rebase": observations.clear()
        elif command.get("operation")=="stream_observe": observations.append(command.get("observation"))
    return observations


class PineStream:
    def __init__(self, runtime, wire, opening, cancelled, *, deadline=None):
        self.cancelled = cancelled
        self.deadline = deadline
        self.worker = SessionWorker(runtime, wire, cancelled, evaluator=True)
        self.wire = deepcopy(wire)
        self.journal = []
        self.cursor = self.intents = self.passes = 0
        self.bar_open = False
        self.input_skip = 0
        self.last = None
        try:
            self.opening = deepcopy(opening)
            if set(opening) & {"operation", "external_stream_contract", "bar_cursor", "intent_base"}:
                raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Pine stream opening overrides protocol fields")
            self._request({**opening, "operation": "stream_open", "execution_schedule_contract": SCHEDULE_CONTRACT,
                           "execution_tick_contract": TICK_CONTRACT}, record=False)
        except Exception:
            self.close()
            raise

    def _request(self, command, *, record=True):
        if record:
            command = deepcopy(command)
        payload = {**self.wire, **command, "external_stream_contract": STREAM_CONTRACT}
        if command["operation"] != "stream_open":
            payload.update(bar_cursor=self.cursor, intent_base=self.intents)
        try:
            timeout = 120 if self.deadline is None else min(120, self.deadline-time.monotonic())
            if timeout <= 0:
                raise BacktestError("NATIVE_TIMEOUT", "Pine stream execution deadline exceeded")
            result = self.worker.request(payload, self.cancelled, timeout=timeout)
            integers = ("bar_cursor", "pass_cursor", "intent_cursor", "intent_base", "input_skip")
            if (any(type(result.get(key)) is not int or result[key] < 0 for key in integers)
                    or type(result.get("bar_open")) is not bool
                    or not isinstance(result.get("intents"), list)
                    or result.get("contract") != "external-broker/1"
                    or result.get("account_authority") != "candlescope"
                    or result.get("stream_schema") != 1):
                raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine stream response")
            operation = command["operation"]
            realtime=self.opening.get("plan_state")=="realtime"
            if realtime and (self.opening.get("realtime_window_plan_contract")!=REALTIME_WINDOW_CONTRACT
                    or self.wire["identity"].get("realtime_window_plan_contract")!=REALTIME_WINDOW_CONTRACT
                    or result.get("realtime_window_plan_contract")!=REALTIME_WINDOW_CONTRACT
                    or result.get("plan_state")!="realtime"):
                raise BacktestError("EXTERNAL_PROTOCOL_ERROR","Pine realtime window acknowledgement differs")
            event_contract=self.opening.get("event_request_contract")
            if event_contract is not None:
                from .pine_event_requests import CONTRACT as EVENT_CONTRACT
                event_status=result.get("event_request_state")
                if (event_contract!=EVENT_CONTRACT or self.wire["identity"].get("event_request_contract")!=EVENT_CONTRACT
                        or result.get("event_request_contract")!=EVENT_CONTRACT or not isinstance(event_status,dict)
                        or set(event_status)!={"contract","pending","requires_discovery","streams"}
                        or event_status.get("contract")!=EVENT_CONTRACT
                        or any(type(event_status.get(name)) is not bool for name in ("pending","requires_discovery"))
                        or not isinstance(event_status.get("streams"),list) or len(event_status["streams"])>16
                        or any(not isinstance(item,dict) or set(item)!={"symbol","timeframe","recipe_hash","cursor"}
                            or type(item.get("cursor")) is not int or item["cursor"]<0
                            or any(not isinstance(item.get(name),str) or not item[name] for name in ("symbol","timeframe","recipe_hash"))
                            for item in event_status.get("streams",[]))):
                    raise BacktestError("EXTERNAL_PROTOCOL_ERROR","invalid Pine event request state")
            reset = operation == "stream_rebase"
            feedback = self.opening.get("window_feedback_contract") == WINDOW_FEEDBACK_CONTRACT
            status = result.get("window_status")
            if feedback and (result.get("window_feedback_contract") != WINDOW_FEEDBACK_CONTRACT
                    or not isinstance(status,dict) or set(status)!={"schema_version","requires_discovery","rebase_required","input_skip"}
                    or type(status.get("schema_version")) is not int or status["schema_version"]!=1
                    or any(type(status.get(key)) is not bool for key in ("requires_discovery","rebase_required"))
                    or type(status.get("input_skip")) is not int or status["input_skip"]<0
                    or (status["rebase_required"] and operation!="stream_observe")):
                raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine window feedback status")
            if reset and not feedback:
                raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Pine window feedback was not negotiated")
            cursor = 0 if reset else self.cursor + (operation == "stream_commit")
            passes = 0 if operation in {"stream_open", "stream_begin", "stream_rebase"} else self.passes + (operation == "stream_observe")
            opened = True if operation == "stream_begin" else False if operation in {"stream_open", "stream_commit", "stream_rebase"} else self.bar_open
            delta = result["intents"]
            if reset:
                valid_intents = result["intent_base"] == 0 and not delta
                total = 0
            elif operation == "stream_snapshot" and command.get("include_intents", False):
                valid_intents = result["intent_base"] == 0 and len(delta) == self.intents
                total = self.intents
            else:
                valid_intents = result["intent_base"] == self.intents and (operation == "stream_observe" or not delta)
                total = self.intents + len(delta)
            if (result["bar_cursor"] != cursor or result["pass_cursor"] != passes
                    or result["bar_open"] != opened or not valid_intents or result["intent_cursor"] != total
                    or (operation not in {"stream_open","stream_rebase"} and result["input_skip"] != self.input_skip)
                    or (feedback and status["rebase_required"] and delta)
                    or any(item.get("bar_index") != self.cursor or item.get("pass_index") != self.passes
                           for item in delta if operation == "stream_observe")):
                raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Pine stream cursor or intent delta differs")
            self.cursor, self.passes, self.bar_open, self.intents = cursor, passes, opened, total
            self.input_skip = result["input_skip"]
            self.last = result
            if record:
                self.journal.append({"command": command, "result_sha256": digest(result)})
            return result
        except Exception:
            self.close()
            raise

    def begin(self, bar, *, bar_state):
        return self._request(dict(operation="stream_begin", bar=bar, bar_state=bar_state))

    def observe(self, observation):
        result = self._request(dict(operation="stream_observe", observation=observation))
        if result.get("window_status",{}).get("rebase_required"):
            raise WindowRebaseRequired()
        return result

    def rebase(self, *, seal=False):
        return self._request(dict(operation="stream_rebase", seal=seal))

    def commit(self):
        return self._request(dict(operation="stream_commit"))

    def output(self, *, include_intents=False):
        return self._request(dict(operation="stream_snapshot", include_intents=include_intents))

    def checkpoint(self,*,detached=True):
        value=dict(contract=JOURNAL_CONTRACT, wire=self.wire, opening=self.opening, journal=self.journal,
                             cursor=self.cursor, intents=self.intents, passes=self.passes, bar_open=self.bar_open,
                             input_skip=self.input_skip, last_sha256=digest(self.last))
        return deepcopy(value) if detached else value

    @classmethod
    def restore(cls, runtime, payload, cancelled, *, deadline=None, verify=None):
        saved = deepcopy(payload)
        if (saved.get("contract") != JOURNAL_CONTRACT or not isinstance(saved.get("journal"), list)
                or any(type(saved.get(key)) is not int or saved[key]<0 for key in ("cursor", "intents", "passes", "input_skip"))
                or type(saved.get("bar_open")) is not bool):
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine stream journal")
        stream = cls(runtime, saved["wire"], saved["opening"], cancelled, deadline=deadline)
        try:
            for entry in saved["journal"]:
                result = stream._request(entry["command"])
                if digest(result) != entry["result_sha256"]:
                    raise BacktestError("LOOKAHEAD_VIOLATION", "Pine stream replay changed an observed decision")
                if verify is not None: verify(entry["command"],result)
            if stream.checkpoint(detached=False) != saved:
                raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Pine stream checkpoint cursor differs")
            return stream
        except Exception:
            stream.close()
            raise

    def close(self):
        self.worker.close()
