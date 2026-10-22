"""Host-owned persistent worker, with bounded IPC, cancellation and deadlines."""
from __future__ import annotations
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from copy import deepcopy
from .native import MAX_BYTES, PROTOCOL, encoded, digest
from .errors import BacktestError
TICK_CONTRACT = "candlescope.pine-tick-schedule/1"

SCHEDULE_CONTRACT = "candlescope.pine-execution-schedule/1"
PREFIX_SCHEDULE_CONTRACT = "candlescope.pine-prefix-schedule/1"
REQUEST_UPDATE_CONTRACT = "candlescope.pine-request-updates/1"
STREAM_CONTRACT = "candlescope.pine-external-stream/1"
SESSION_IDENTITY_CONTRACT = "candlescope.session-identity/1"


class SessionWorker:
    def __init__(self, plugin, wire, cancelled, *, evaluator=False):
        self._close_lock = threading.Lock()
        self._closed = False
        self.close_errors = []
        self.identity = deepcopy(wire["identity"])
        self._identity_ref = digest(self.identity)
        self._identity_ref_enabled = self.identity.get("session_identity") == SESSION_IDENTITY_CONTRACT
        self._identity_bound = False
        self._prefix_enabled = evaluator and self.identity.get("prefix_append") in {
            "candlescope.pine-prefix/1", "candlescope.pine-prefix/2"}
        self._prefix_state = None
        self.input_bytes = 0
        self.stderr = tempfile.TemporaryFile()
        command = [*plugin["command"], "--worker"] if evaluator else [*plugin["command"][:-1], plugin["command"][-1].replace(".native_strategy", ".native_session")]
        try:
            self.process = subprocess.Popen(command, executable=command[0], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.stderr, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            self.stderr.close()
            raise
        self.supported = True if evaluator else self.request({**wire, "operation": "open"}, cancelled).get("supported") is True

    def request(self, payload, cancelled, timeout=120):
        if "identity_ref" in payload:
            raise BacktestError("NATIVE_IDENTITY_MISMATCH", "session identity references belong to the transport")
        streaming = payload.get("operation", "").startswith("stream_")
        if streaming and (payload.get("external_stream_contract") != STREAM_CONTRACT
                or self.identity.get("external_stream_contract") != STREAM_CONTRACT):
            raise BacktestError("EXTERNAL_UNSUPPORTED", "Pine external stream was not negotiated")
        if not streaming and "execution_tick_contract" in payload:
            if (payload["execution_tick_contract"] != TICK_CONTRACT
                    or self.identity.get("execution_tick_contract") != TICK_CONTRACT
                    or payload.get("execution_schedule") is None):
                raise BacktestError("EXTERNAL_UNSUPPORTED", "Pine tick schedule was not negotiated")
        if payload.get("request_updates") is not None or payload.get("request_update_contract") is not None:
            if (self.identity.get("request_update_contract") != REQUEST_UPDATE_CONTRACT
                    or payload.get("request_update_contract") != REQUEST_UPDATE_CONTRACT):
                raise BacktestError("EXTERNAL_UNSUPPORTED", "Pine requested updates were not negotiated")
        if not streaming and (payload.get("execution_schedule") is not None or payload.get("execution_schedule_contract") is not None):
            if (self.identity.get("execution_schedule_contract") != SCHEDULE_CONTRACT
                    or payload.get("execution_schedule_contract") != SCHEDULE_CONTRACT
                    or payload.get("execution_schedule") is None or payload.get("execution_passes") is not None):
                raise BacktestError("EXTERNAL_UNSUPPORTED", "explicit Pine execution schedule was not negotiated")
        response = queue.Queue(maxsize=1)
        wire_payload = self._prefix_payload(payload) if self._prefix_enabled else payload
        header = ({"identity_ref": self._identity_ref} if self._identity_ref_enabled and self._identity_bound
                  else {"identity": self.identity})
        envelope = {key: value for key, value in wire_payload.items() if key not in {"identity", "protocol"}}
        raw = (encoded({**envelope, "protocol": PROTOCOL, **header}) + "\n").encode("utf-8")
        self.input_bytes += len(raw)
        if len(raw) > MAX_BYTES:
            self.close()
            raise BacktestError("BUDGET_EXCEEDED", "native session input exceeds 64 MiB")
        def exchange():
            try:
                self.process.stdin.write(raw)
                self.process.stdin.flush()
                line = self.process.stdout.readline(MAX_BYTES + 1)
                if len(line) > MAX_BYTES:
                    raise BacktestError("BUDGET_EXCEEDED", "native session output exceeds 64 MiB")
                response.put(json.loads(line))
            except Exception as exc:
                response.put(exc)
        worker = threading.Thread(target=exchange, daemon=True)
        worker.start()
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancelled.is_set():
                    raise BacktestError("NATIVE_CANCELLED", "native session cancelled")
                if time.monotonic() > deadline:
                    raise BacktestError("NATIVE_TIMEOUT", "native session exceeded host deadline")
                if os.fstat(self.stderr.fileno()).st_size > MAX_BYTES:
                    raise BacktestError("BUDGET_EXCEEDED", "native session stderr exceeds 64 MiB")
                try:
                    result = response.get(timeout=.05)
                except queue.Empty:
                    continue
                if isinstance(result, Exception):
                    raise result
                if not isinstance(result, dict) or result.get("ok") is not True:
                    raise BacktestError("NATIVE_EXECUTION_FAILED", "native session rejected the operation", details=result)
                if "identity_ref" in result:
                    if (not self._identity_ref_enabled or not self._identity_bound or "identity" in result
                            or result["identity_ref"] != self._identity_ref):
                        raise BacktestError("NATIVE_IDENTITY_MISMATCH", "unexpected session identity reference")
                    result = {key: value for key, value in result.items() if key != "identity_ref"}
                    result["identity"] = deepcopy(self.identity)
                if digest(result.get("identity")) != self._identity_ref:
                    raise BacktestError("NATIVE_IDENTITY_MISMATCH", "unexpected session runtime")
                if streaming and (result.get("external_stream_contract") != STREAM_CONTRACT
                        or result.get("execution_schedule_contract") != SCHEDULE_CONTRACT
                        or result.get("execution_tick_contract") != TICK_CONTRACT):
                    raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Pine stream acknowledgement missing")
                if payload.get("execution_schedule") is not None and result.get("execution_schedule_contract") != SCHEDULE_CONTRACT:
                    raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Pine execution schedule acknowledgement missing")
                if payload.get("request_update_contract") is not None and result.get("request_update_contract") != REQUEST_UPDATE_CONTRACT:
                    raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Pine requested-update acknowledgement missing")
                if payload.get("execution_tick_contract") is not None and result.get("execution_tick_contract") != TICK_CONTRACT:
                    raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "Pine tick schedule acknowledgement missing")
                self._identity_bound = True
                return result
        except Exception:
            self.close()
            raise
        finally:
            worker.join(timeout=2)

    def advance(self, target, cancelled):
        return self.request({"operation": "advance", "target": target}, cancelled)

    def _prefix_payload(self, payload):
        bars, accounts, passes = payload.get("bars"), payload.get("accounts"), payload.get("execution_passes")
        clocks = payload.get("execution_times")
        schedule = payload.get("execution_schedule")
        updates = payload.get("request_updates")
        if (not isinstance(bars, list) or not isinstance(accounts, list) or len(bars) != len(accounts)
                or any(payload.get(key) for key in ("libraries", "magnifier"))
                or (clocks is not None and (self.identity.get("prefix_clocks") != "candlescope.pine-prefix-clocks/1"
                    or not isinstance(clocks, list) or len(clocks) != len(bars)))
                or (passes is not None and (self.identity.get("prefix_passes") != "candlescope.pine-prefix-passes/1"
                    or not isinstance(passes, list) or len(passes) != len(bars)))
                or (schedule is not None and (self.identity.get("prefix_schedule") != PREFIX_SCHEDULE_CONTRACT
                    or not isinstance(schedule, list) or len(schedule) != len(bars)))
                or (updates is not None and (self.identity.get("request_update_contract") != REQUEST_UPDATE_CONTRACT
                    or payload.get("request_update_contract") != REQUEST_UPDATE_CONTRACT
                    or not isinstance(updates, list) or len(updates) != len(bars)))):
            self._prefix_state = None
            return payload
        static = {key: value for key, value in payload.items() if key not in {"bars", "accounts", "execution_passes", "execution_times", "execution_schedule", "request_updates"}}
        previous = self._prefix_state
        self._prefix_state = deepcopy((static, bars, accounts, passes, clocks, schedule, updates))
        if previous is not None:
            old_static, old_bars, old_accounts, old_passes, old_clocks, old_schedule, old_updates = previous
            count = len(old_bars)
            stable_passes = passes is None and old_passes is None or (passes is not None and old_passes is not None
                and passes[:count] == old_passes and all(group and group[-1].get("confirmed") is True for group in old_passes))
            stable_clocks = clocks is None and old_clocks is None or (clocks is not None and old_clocks is not None
                and clocks[:count] == old_clocks)
            stable_schedule = schedule is None and old_schedule is None or (
                schedule is not None and old_schedule is not None and schedule[:count] == old_schedule
                and all(group and group[-1].get("evaluation", {}).get("confirmed") is True for group in old_schedule))
            stable_updates = updates is None and old_updates is None or (
                updates is not None and old_updates is not None and updates[:count] == old_updates)
            if (static == old_static and len(bars) > count and bars[:count] == old_bars
                    and accounts[:count] == old_accounts and stable_passes and stable_clocks and stable_schedule and stable_updates):
                account_payload={"accounts":accounts[count:]}
                fields={"time","position_size","position_avg_price","equity","initial_capital","netprofit","openprofit"}
                if (self.identity.get("prefix_append")=="candlescope.pine-prefix/2" and old_accounts
                        and all(isinstance(account,dict) and set(account)==fields for account in accounts[count-1:])):
                    prior=old_accounts[-1]
                    deltas=[]
                    for account in accounts[count:]:
                        deltas.append({key:value for key,value in account.items()
                                       if type(value) is not type(prior[key]) or value!=prior[key]})
                        prior=account
                    account_payload={"account_deltas":deltas}
                return {"operation": "append_prefix", "prefix_base": count,
                        "bars": bars[count:], **account_payload,
                        **({"execution_passes": passes[count:]} if passes is not None else {}),
                        **({"execution_schedule": schedule[count:]} if schedule is not None else {}),
                        **({"request_updates": updates[count:]} if updates is not None else {}),
                        **({"execution_times": clocks[count:]} if clocks is not None else {})}
        return payload

    def close(self):
        # Cancellation can race with request()'s exception cleanup. Only one
        # owner reaps the process and closes the pipes; later calls are no-ops.
        with self._close_lock:
            if self._closed:
                return
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait()
            for name, stream in (("stdin", self.process.stdin), ("stdout", self.process.stdout), ("stderr", self.stderr)):
                if not stream.closed:
                    try:
                        stream.close()
                    except OSError as exc:
                        # A terminated Windows pipe may fail its buffered
                        # close/flush. Preserve the original timeout/cancel
                        # and still release every remaining stream.
                        self.close_errors.append({"stream": name, "errno": exc.errno})
            self._closed = True
