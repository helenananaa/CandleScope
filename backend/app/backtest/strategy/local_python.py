"""SDK-compatible calls inside an already isolated TRUSTED_LOCAL run worker.

Never used for SANDBOXED_LOCAL. Keeps JSON normalization and the original
transcript contract so only transport and scheduling change.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from app.backtest.identity import canonical_json, sha256_hex
from .python_runner import MAX_MESSAGE_BYTES, PythonRunnerError, _require_trusted_local


class LocalPythonRunner:
    def __init__(self, *, bound_transcript: bool) -> None:
        _require_trusted_local(confirmed=True)
        self._bound = bound_transcript
        self._count = 0
        self._transcript_hash = hashlib.sha256(b"[")
        self._chain = "sha256:GENESIS"
        self._strategy = None

    def start(self) -> None:
        self.call("ping")

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
            params = request["params"]
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
        wire = json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"
        if len(wire.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise PythonRunnerError("MESSAGE_TOO_LARGE", "worker JSON exceeded budget")
        response = json.loads(wire)
        record = {"request": request, "response": response}
        if self._bound:
            self._chain = "sha256:" + sha256_hex({"previous": self._chain, "record": record})
        else:
            # Hash exactly the old canonical JSON array without retaining all
            # observations until close(). Copying the hash keeps close idempotent.
            if self._count:
                self._transcript_hash.update(b",")
            self._transcript_hash.update(canonical_json(record).encode("utf-8"))
        self._count += 1
        if not response["ok"]:
            raise PythonRunnerError("PROVIDER_PROTOCOL_VIOLATION", response["error"])
        return response["result"]

    def close(self):
        digest = self._transcript_hash.copy()
        digest.update(b"]")
        return {"transcriptHash": self._chain if self._bound else "sha256:" + digest.hexdigest()}
