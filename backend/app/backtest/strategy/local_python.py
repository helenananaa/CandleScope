"""SDK-compatible calls inside an already isolated TRUSTED_LOCAL run worker.

Never used for SANDBOXED_LOCAL. Keeps JSON normalization and the original
transcript contract so only transport and scheduling change.
"""

from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from pathlib import Path

from app.backtest.identity import canonical_json
from .python_runner import MAX_MESSAGE_BYTES, PythonRunnerError, _require_trusted_local
from app.core.config import getenv


class LocalPythonRunner:
    def __init__(self, *, bound_transcript: bool) -> None:
        _require_trusted_local(confirmed=True)
        self._bound = bound_transcript
        self._count = 0
        self._transcript_hash = hashlib.sha256(b"[")
        self._chain = "sha256:GENESIS"
        self._strategy = None
        self._direct_objects = getenv("BACKTEST_DIRECT_OBJECTS_ENABLED", "1").strip() == "1"
        self._fused_output = getenv("BACKTEST_FUSED_OUTPUT_ENABLED", "1").strip() == "1"
        self._host_hotpath = getenv("BACKTEST_HOST_HOTPATH_ENABLED", "1").strip() == "1"
        self._native_output_fields = getenv("BACKTEST_NATIVE_OUTPUT_FIELDS_ENABLED", "1").strip() == "1"
        self._direct_feedback_enabled = getenv("BACKTEST_DIRECT_FEEDBACK_ENABLED", "1").strip() == "1"
        from .python_provider import _target_state_hash
        from .protocol import StrategyOutput
        self._native_target_hash, self._native_output_type = _target_state_hash, StrategyOutput
        from .python_provider import _author_observation, _to_host_output
        from .direct_observation import bounded_observation, make_observation, encode_output
        self._author_frame = _author_observation
        self._host_output = _to_host_output
        self._bounded_frame = bounded_observation
        self._make_frame = make_observation
        self._encode_output = encode_output
        from .direct_observation import encode_prepared_output
        from .qualified_json import encode_ascii_tree
        self._encode_prepared_output = encode_prepared_output
        self._wire_encoder = encode_ascii_tree
        from candlescope_backtest_sdk import models
        self._native_sdk_signature = (models.Bar, models.Observation, models.Bar.__init__,
                                      models.Observation.__init__, models._decimal_string,
                                      models.Bar.__new__, models.Observation.__new__)

    def observe_prepared(self, prepared, *, warmup=False, factory=None, _provided=False, _output=None, _error=None):
        """Sequential V1 call with native-built input and immutable receipt bytes."""
        observation, observation_wire = prepared
        method = "warmup" if warmup else "step"
        request_id = (min(self._count, 1) if self._bound else self._count) + 1
        native_success = self._host_hotpath and factory is not None and hasattr(factory, "record_success")
        id_bytes = None if native_success else str(request_id).encode("ascii")
        request = (None if factory is not None else
                   b'{"id":' + id_bytes + b',"method":"' + method.encode("ascii")
                   + b'","params":{"observation":' + observation_wire + b'}}')
        fast_response = False
        encoded_result = None
        host_args = None
        try:
            if _error is not None:
                raise _error
            output = _output if _provided else getattr(self._strategy, method)(observation)
            if warmup or output is None:
                result, fast_response = None, True
                encoded_result = b"null"
            elif factory is not None:
                fused = self._fused_output and hasattr(factory, "output_parts")
                result, fast_response, encoded_result = self._encode_prepared_output(
                    observation.sequence, output, factory, host_parts=fused, object_fields=self._native_output_fields)
                if fused and fast_response:
                    host_args, result = result, None
            else:
                result, fast_response = self._encode_output(observation.sequence, output)
            response = (None if host_args is not None or (native_success and fast_response and encoded_result is not None)
                        else {"id": request_id, "ok": True, "result": result})
        except Exception as exc:
            response = {"id": request_id, "ok": False, "error": str(exc)}
        if native_success and fast_response and encoded_result is not None:
            chain = factory.record_success(request_id, warmup, observation_wire, encoded_result,
                                           self._chain if self._bound else None)
            if self._bound:
                self._chain = chain
            self._count += 1
            if host_args is not None:
                from .protocol import StrategyOutput
                return StrategyOutput(*host_args)
            return None if result is None else self._host_output(observation.sequence, result)
        if not fast_response:
            wire = json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"
            if len(wire.encode("utf-8")) > MAX_MESSAGE_BYTES:
                raise PythonRunnerError("MESSAGE_TOO_LARGE", "worker JSON exceeded budget")
            response = json.loads(wire)
            encoded_response = canonical_json(response).encode("utf-8")
        elif encoded_result is not None:
            encoded_response = b'{"id":' + id_bytes + b',"ok":true,"result":' + encoded_result + b'}'
        else:
            encoded_response = self._wire_encoder(response)
        record = None if factory is not None else b'{"request":' + request + b',"response":' + encoded_response + b'}'
        if factory is not None:
            chain = factory.record_v1(request_id, warmup, observation_wire, encoded_response, self._chain if self._bound else None)
            if self._bound:
                self._chain = chain
        elif self._bound:
            self._chain = "sha256:" + hashlib.sha256(
                b'{"previous":"' + self._chain.encode("ascii") + b'","record":' + record + b'}'
            ).hexdigest()
        else:
            if self._count:
                self._transcript_hash.update(b",")
            self._transcript_hash.update(record)
        self._count += 1
        if host_args is not None:
            from .protocol import StrategyOutput
            return StrategyOutput(*host_args)
        if not response["ok"]:
            raise PythonRunnerError("PROVIDER_PROTOCOL_VIOLATION", response["error"])
        return self._host_output(observation.sequence, response["result"])

    def _complete_native(self, prepared, warmup, output, error, factory):
        return self.observe_prepared(prepared, warmup=warmup, factory=factory,
                                     _provided=True, _output=output, _error=error)

    def observe_frame(self, frame, *, warmup=False):
        method = "warmup" if warmup else "step"
        value = self._author_frame(frame)
        if not self._direct_objects or self._count >= 9007199254740991 or not self._bounded_frame(value):
            return self._host_output(frame.sequence, self.call(method, {"observation": value}))
        request = {"id": (min(self._count, 1) if self._bound else self._count) + 1,
                   "method": method, "params": {"observation": value}}
        fast_response = False
        try:
            observation = self._make_frame(value)
            output = getattr(self._strategy, method)(observation)
            if warmup or output is None:
                result, fast_response = None, True
            else:
                result, fast_response = self._encode_output(frame.sequence, output)
            response = {"id": request["id"], "ok": True, "result": result}
        except Exception as exc:
            response = {"id": request["id"], "ok": False, "error": str(exc)}
        result = self._finish(request, response, normalized=fast_response)
        return self._host_output(frame.sequence, result)

    def start(self) -> None:
        self.call("ping")

    def on_execution_report(self, report):
        if not self._direct_feedback_enabled:
            return self.call("on_execution_report", {"report": report})
        from .direct_feedback import prepare_feedback
        request_id = (min(self._count, 1) if self._bound else self._count) + 1
        request = {"id": request_id, "method": "on_execution_report", "params": {"report": report}}
        prepared = prepare_feedback(request)
        if prepared is None:
            return self.call("on_execution_report", {"report": report})
        detached, wire = prepared
        try:
            self._strategy.on_execution_report(detached["params"]["report"])
        except Exception as exc:
            # Exact old error normalization/receipt, without repeating callback.
            return self._finish(json.loads(wire), {"id": request_id, "ok": False, "error": str(exc)})
        response = b'{"id":' + str(request_id).encode() + b',"ok":true,"result":null}'
        record = b'{"request":' + wire + b',"response":' + response + b'}'
        if self._bound:
            self._chain = "sha256:" + hashlib.sha256(
                b'{"previous":"' + self._chain.encode("ascii") + b'","record":' + record + b'}').hexdigest()
        else:
            if self._count:
                self._transcript_hash.update(b",")
            self._transcript_hash.update(record)
        self._count += 1

    def call(self, method, params=None):
        from candlescope_backtest_sdk import (
            Observation, StrategyContext, encode_output, encode_snapshot, loads_strict,
        )
        from candlescope_backtest_sdk.worker import _load_strategy

        raw_request = {
            "id": (min(self._count, 1) if self._bound else self._count) + 1,
            "method": method, "params": dict(params or {}),
        }
        request_wire = json.dumps(raw_request, default=str) + "\n"
        if len(request_wire.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise PythonRunnerError("MESSAGE_TOO_LARGE", "request JSON exceeded budget")
        try:
            # Retain the SDK's finite-number, integer, nesting and string limits.
            # A single encoding supplies both byte accounting and normalization.
            request = loads_strict(request_wire)
            # The JSON transport has separate host receipt and worker objects.
            # Keep that alias boundary for the general/fallback call path too.
            params = deepcopy(request["params"])
            if method == "ping":
                result = {"ready": True}
            elif method == "prepare":
                self._strategy = _load_strategy(Path(params["bundleDir"]), params["entrypoint"])
                self._strategy.prepare(StrategyContext(
                    run_id=str(params.get("runId") or "bt_local"),
                    revision_id=str(params.get("revisionId") or "rev_local"),
                    parameters=dict(params.get("parameters") or {}),
                ))
                result = {"ok": True}
            elif method in {"warmup", "step"}:
                observation = Observation.from_wire(params["observation"])
                output = getattr(self._strategy, method)(observation)
                result = None if method == "warmup" or output is None else encode_output(observation.sequence, output)
            elif method == "on_execution_report":
                self._strategy.on_execution_report(params["report"])
                result = None
            elif method == "snapshot":
                result = encode_snapshot(self._strategy.snapshot())
            elif method == "restore":
                self._strategy.restore(dict(params["payload"]))
                result = None
            elif method == "close":
                if self._strategy is not None:
                    self._strategy.close()
                result = {"closed": True}
            else:
                raise ValueError(f"unknown method {method}")
            response = {"id": request["id"], "ok": True, "result": result}
        except Exception as exc:
            request = json.loads(request_wire)
            response = {"id": request["id"], "ok": False, "error": str(exc)}
        return self._finish(request, response)

    def _finish(self, request, response, *, normalized=False):
        if not normalized:
            wire = json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"
            if len(wire.encode("utf-8")) > MAX_MESSAGE_BYTES:
                raise PythonRunnerError("MESSAGE_TOO_LARGE", "worker JSON exceeded budget")
            response = json.loads(wire)
        record = {"request": request, "response": response}
        if normalized:
            from .qualified_json import encode_ascii_tree
            encode = encode_ascii_tree
        else:
            encode = lambda value: canonical_json(value).encode("utf-8")
        if self._bound:
            self._chain = "sha256:" + hashlib.sha256(encode({"previous": self._chain, "record": record})).hexdigest()
        else:
            # Hash exactly the old canonical JSON array without retaining all
            # observations until close(). Copying the hash keeps close idempotent.
            if self._count:
                self._transcript_hash.update(b",")
            self._transcript_hash.update(encode(record))
        self._count += 1
        if not response["ok"]:
            raise PythonRunnerError("PROVIDER_PROTOCOL_VIOLATION", response["error"])
        return response["result"]

    def close(self):
        digest = self._transcript_hash.copy()
        digest.update(b"]")
        return {"transcriptHash": self._chain if self._bound else "sha256:" + digest.hexdigest()}
