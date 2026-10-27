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
from itertools import compress, count as counter
from operator import is_not
from .native import MAX_BYTES, PROTOCOL, encoded, digest
from .errors import BacktestError
TICK_CONTRACT = "candlescope.pine-tick-schedule/1"

SCHEDULE_CONTRACT = "candlescope.pine-execution-schedule/1"
PREFIX_SCHEDULE_CONTRACT = "candlescope.pine-prefix-schedule/1"
REQUEST_UPDATE_CONTRACT = "candlescope.pine-request-updates/1"
STREAM_CONTRACT = "candlescope.pine-external-stream/1"
STREAM_CHAIN_CONTRACT = "candlescope.pine-external-stream-chain/1"
SESSION_IDENTITY_CONTRACT = "candlescope.session-identity/1"
PREFIX_REPLY_CONTRACT = "candlescope.pine-prefix-reply/1"

if os.name == "nt":
    import ctypes
    import msvcrt
    _get_file_size = ctypes.WinDLL("kernel32", use_last_error=True).GetFileSizeEx
    _get_file_size.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]
    _get_file_size.restype = ctypes.c_int


def _file_size(stream):
    # The stderr guard needs only length. Querying the existing Windows handle
    # avoids fstat's unrelated metadata work and never changes the shared offset.
    if os.name == "nt":
        size = ctypes.c_longlong()
        if not _get_file_size(msvcrt.get_osfhandle(stream.fileno()), ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return size.value
    return os.fstat(stream.fileno()).st_size


_PREFIX_FIELDS = frozenset({"bars", "accounts", "execution_passes", "execution_times", "execution_schedule",
                            "request_updates", "prefix_reply"})
_PREFIX_ENVELOPE = ("prefix_reply",)


def _open_groups(groups, *, schedule):
    """Count pass groups whose last evaluation could still be followed by another."""
    if groups is None:
        return 0
    if schedule:
        return sum(not (group and group[-1].get("evaluation", {}).get("confirmed") is True) for group in groups)
    return sum(not (group and group[-1].get("confirmed") is True) for group in groups)


class _SentPrefix:
    """The prefix one evaluator already holds, kept without copying its history.

    Elements are held by reference and compared by identity, so an append costs
    only its new rows. A caller changes an earlier element by replacing it; a
    rebuilt but equal element still matches by value. The newest element of
    each list is also kept as a detached snapshot, so an in-place change to the
    current bar, account frame or pass group still forces a full request.
    """

    __slots__ = ("static", "lists", "last", "open")

    def __init__(self, static, lists):
        self.static = static
        self.lists = [None if value is None else list(value) for value in lists]
        self.last = [deepcopy(value[-1]) if value else None for value in lists]
        self.open = (_open_groups(lists[2], schedule=False), _open_groups(lists[4], schedule=True))

    def extended_by(self, static, lists):
        count = len(self.lists[0])
        if static != self.static or len(lists[0]) <= count or self.open != (0, 0):
            return False
        for value, sent, last in zip(lists, self.lists, self.last, strict=True):
            if (value is None) != (sent is None):
                return False
            if not sent:
                continue
            # Values decide only from the first row the caller rebuilt.
            first = next(compress(counter(), map(is_not, value, sent)), count)
            if value[first:count] != sent[first:]:
                return False
            if value[count - 1] != last:
                return False
        return True

    def advance(self, static, lists, count):
        self.static = static
        for value, sent in zip(lists, self.lists, strict=True):
            if value is not None:
                sent.extend(value[count:])
        self.last = [deepcopy(value[-1]) if value else None for value in lists]
        self.open = (_open_groups(lists[2][count:] if lists[2] is not None else None, schedule=False),
                     _open_groups(lists[4][count:] if lists[4] is not None else None, schedule=True))


def _json_container_copier(value):
    """Prepare detached copies of a private, already decoded JSON container.

    Immutable scalar values can be shared; each dict/list occurrence gets a
    fresh container on every call. No returned value exposes the template.
    """
    template = value.copy()
    children = []
    items = template.items() if isinstance(template, dict) else enumerate(template)
    for key, child in items:
        if isinstance(child, (dict, list)):
            children.append((key, _json_container_copier(child)))
            template[key] = None
    copy = template.copy
    if not children:
        return copy

    def cloned():
        result = copy()
        for key, clone in children:
            result[key] = clone()
        return result

    return cloned


class SessionWorker:
    def __init__(self, plugin, wire, cancelled, *, evaluator=False):
        self._close_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._closed = False
        # The request lock allows only one exchange in flight; close can add
        # only one sentinel. SimpleQueue avoids three Conditions per response
        # while keeping this transport bounded by its serialized ownership.
        self._pending = queue.SimpleQueue()
        self.close_errors = []
        self.identity = deepcopy(wire["identity"])
        self._identity_json = encoded(self.identity)
        self._identity_ref = digest(self.identity)
        self._identity_ref_enabled = self.identity.get("session_identity") == SESSION_IDENTITY_CONTRACT
        self._identity_copy = (_json_container_copier(json.loads(self._identity_json))
                               if self._identity_ref_enabled else None)
        self._identity_bound = False
        self._stream_chain_enabled = evaluator and self.identity.get("external_stream_chain_contract") == STREAM_CHAIN_CONTRACT
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
        self._io_thread = threading.Thread(target=self._exchange, name="native-worker-io", daemon=True)
        try:
            self._io_thread.start()
        except Exception:
            self.close()
            raise
        self.supported = True if evaluator else self.request({**wire, "operation": "open"}, cancelled).get("supported") is True

    def _exchange(self):
        while True:
            pending = self._pending.get()
            if pending is None:
                return
            raw, response = pending
            try:
                response.put(raw() if callable(raw) else self._exchange_one(raw))
            except Exception as exc:
                response.put(exc)
            if self._closed:
                return

    def _exchange_one(self, raw):
        self.process.stdin.write(raw)
        self.process.stdin.flush()
        line = self.process.stdout.readline(MAX_BYTES + 1)
        if len(line) > MAX_BYTES:
            raise BacktestError("BUDGET_EXCEEDED", "native session output exceeds 64 MiB")
        return json.loads(line)

    def _check_payload(self, payload):
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
        return streaming

    def request(self, payload, cancelled, timeout=120):
        streaming = self._check_payload(payload)
        started = time.monotonic()
        if not self._request_lock.acquire(timeout=max(0, timeout)):
            raise BacktestError("NATIVE_TIMEOUT", "native session exceeded host deadline waiting for transport")
        try:
            return self._request_serial(payload, cancelled, timeout-(time.monotonic()-started), streaming)
        finally:
            self._request_lock.release()

    def _request_serial(self, payload, cancelled, timeout, streaming):
        if self._closed:
            raise BacktestError("NATIVE_RUNTIME_UNAVAILABLE", "native session is closed")
        response = queue.SimpleQueue()
        try:
            raw = self._encode_payload(payload)
        except Exception:
            self.close()
            raise
        # One bounded exchange and one response at a time. The transport thread
        # survives successful calls; request-scoped queues prevent stale replies
        # from crossing cancellation/timeout boundaries.
        self._pending.put_nowait((raw, response))
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancelled.is_set():
                    raise BacktestError("NATIVE_CANCELLED", "native session cancelled")
                if time.monotonic() > deadline:
                    raise BacktestError("NATIVE_TIMEOUT", "native session exceeded host deadline")
                if _file_size(self.stderr) > MAX_BYTES:
                    raise BacktestError("BUDGET_EXCEEDED", "native session stderr exceeds 64 MiB")
                try:
                    result = response.get(timeout=.05)
                except queue.Empty:
                    continue
                if isinstance(result, Exception):
                    raise result
                return self._validate_result(payload, result, streaming)
        except Exception:
            self.close()
            raise

    def _encode_payload(self, payload, *, _bounded_chain=False):
        wire_payload = self._prefix_payload(payload) if self._prefix_enabled else payload
        header = ({"identity_ref": self._identity_ref} if self._identity_ref_enabled and self._identity_bound
                  else {"identity": self.identity})
        envelope = {key: value for key, value in wire_payload.items() if key not in {"identity", "protocol"}}
        raw = (encoded({**envelope, "protocol": PROTOCOL, **header}) + "\n").encode("utf-8")
        if len(raw) > MAX_BYTES:
            if _bounded_chain:
                return None
            raise BacktestError("BUDGET_EXCEEDED", "native session input exceeds 64 MiB")
        self.input_bytes += len(raw)
        return raw

    def _validate_result(self, payload, result, streaming):
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise BacktestError("NATIVE_EXECUTION_FAILED", "native session rejected the operation", details=result)
        if "identity_ref" in result:
            if (not self._identity_ref_enabled or not self._identity_bound or "identity" in result
                    or result["identity_ref"] != self._identity_ref):
                raise BacktestError("NATIVE_IDENTITY_MISMATCH", "unexpected session identity reference")
            result = {key: value for key, value in result.items() if key != "identity_ref"}
            result["identity"] = self._identity_copy()
        elif digest(result.get("identity")) != self._identity_ref:
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

    def request_chain(self, payloads, cancelled, timeout=120):
        """Replay at most eight frozen stream commands without Host callbacks.

        Negotiated workers accept one bounded frame containing all commands;
        older workers retain one wire line per command. Every acknowledgement
        is bound to the checked worker identity and returned to the caller.
        Later cursors come from the preceding acknowledgement; callers must
        validate every returned decision before publishing any restored state.
        No ledger or matching work runs on the I/O thread.
        """
        if not 1 <= len(payloads) <= 8 or any(payload.get("operation") not in {
                "stream_begin", "stream_observe", "stream_commit", "stream_rebase", "stream_snapshot"} for payload in payloads):
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine stream command chain")
        for payload in payloads:
            self._check_payload(payload)
        started = time.monotonic()
        if not self._request_lock.acquire(timeout=max(0, timeout)):
            raise BacktestError("NATIVE_TIMEOUT", "native session exceeded host deadline waiting for transport")
        try:
            if self._closed:
                raise BacktestError("NATIVE_RUNTIME_UNAVAILABLE", "native session is closed")
            def exchange():
                if (self._stream_chain_enabled and self._identity_ref_enabled and self._identity_bound
                        and all(payload["operation"] != "stream_snapshot" for payload in payloads)):
                    chained = self._exchange_stream_chain(payloads)
                    if chained is not None:
                        return chained
                results = []
                for payload in payloads:
                    if results:
                        previous = results[-1]
                        payload = {**payload, "bar_cursor": previous["bar_cursor"],
                                   "intent_base": previous["intent_cursor"]}
                    result = self._exchange_one(self._encode_payload(payload))
                    results.append(self._validate_result(payload, result, True))
                return results
            response = queue.SimpleQueue()
            self._pending.put_nowait((exchange, response))
            deadline = started + timeout
            while True:
                if cancelled.is_set():
                    raise BacktestError("NATIVE_CANCELLED", "native session cancelled")
                if time.monotonic() > deadline:
                    raise BacktestError("NATIVE_TIMEOUT", "native session exceeded host deadline")
                if _file_size(self.stderr) > MAX_BYTES:
                    raise BacktestError("BUDGET_EXCEEDED", "native session stderr exceeds 64 MiB")
                try:
                    results = response.get(timeout=.05)
                except queue.Empty:
                    continue
                if isinstance(results, Exception):
                    raise results
                return results
        except Exception:
            self.close()
            raise
        finally:
            self._request_lock.release()

    def _exchange_stream_chain(self, payloads):
        reserved = {"protocol", "identity", "external_stream_contract", "bar_cursor", "intent_base"}
        payload = {**payloads[0], "operation": "stream_chain", "external_stream_chain_contract": STREAM_CHAIN_CONTRACT,
                   "commands": [{key: value for key, value in item.items() if key not in reserved}
                                for item in payloads]}
        # Operation-specific fields belong only to their original command.
        payload = {key: value for key, value in payload.items()
                   if key in reserved | {"operation", "external_stream_chain_contract", "commands"}}
        raw = self._encode_payload(payload, _bounded_chain=True)
        if raw is None:
            return None
        result = self._validate_result(payload, self._exchange_one(raw), True)
        rows = result.get("results")
        if (result.get("external_stream_chain_contract") != STREAM_CHAIN_CONTRACT
                or not isinstance(rows, list) or len(rows) != len(payloads)
                or any(not isinstance(row, dict) or set(row) & {"ok", "identity", "identity_ref"} for row in rows)):
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine stream command acknowledgements")
        # Each result receives its own detached full identity as on the legacy
        # path. Only the verified outer envelope supplies that identity.
        return [self._validate_result(original, {**row, "ok": True, "identity_ref": self._identity_ref}, True)
                for original, row in zip(payloads, rows, strict=True)]

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
        static = {key: value for key, value in payload.items() if key not in _PREFIX_FIELDS}
        # The reply shape belongs to this request only, never to the prefix.
        envelope = {key: payload[key] for key in _PREFIX_ENVELOPE if key in payload}
        lists = (bars, accounts, passes, clocks, schedule, updates)
        previous = self._prefix_state
        if previous is None or not previous.extended_by(static, lists):
            self._prefix_state = _SentPrefix(static, lists)
            return payload
        count = len(previous.lists[0])
        account_payload={"accounts":accounts[count:]}
        fields={"time","position_size","position_avg_price","equity","initial_capital","netprofit","openprofit"}
        if (self.identity.get("prefix_append")=="candlescope.pine-prefix/2" and count
                and all(isinstance(account,dict) and set(account)==fields for account in accounts[count-1:])):
            prior=previous.last[1]
            deltas=[]
            for account in accounts[count:]:
                deltas.append({key:value for key,value in account.items()
                               if type(value) is not type(prior[key]) or value!=prior[key]})
                prior=account
            account_payload={"account_deltas":deltas}
        previous.advance(static, lists, count)
        return {"operation": "append_prefix", "prefix_base": count,
                "bars": bars[count:], **account_payload,
                **({"execution_passes": passes[count:]} if passes is not None else {}),
                **({"execution_schedule": schedule[count:]} if schedule is not None else {}),
                **({"request_updates": updates[count:]} if updates is not None else {}),
                **({"execution_times": clocks[count:]} if clocks is not None else {}),
                **envelope}

    def close(self):
        # Cancellation can race with request()'s exception cleanup. Only one
        # owner reaps the process and closes the pipes; later calls are no-ops.
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
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
            self._pending.put_nowait(None)
            if self._io_thread.ident is not None and self._io_thread is not threading.current_thread():
                self._io_thread.join(timeout=2)
