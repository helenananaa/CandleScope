"""One-shot native strategy transport, independent of indicator rendering.

The original engine output is authoritative. No host orders or fills are made.
"""
from __future__ import annotations

import contextlib
from copy import deepcopy
import hashlib
import importlib.metadata
import json
import sys
from typing import Any, Callable

PROTOCOL = "candlescope.native-strategy/1"
SESSION_IDENTITY_CONTRACT = "candlescope.session-identity/1"


def identity_reference(current: dict[str, Any]) -> str:
    data = json.dumps(current, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _SessionIdentity:
    """References belong to one worker after its first full identity exchange."""

    def __init__(self, current):
        self.current = deepcopy(current)
        self._current_json = json.dumps(current, ensure_ascii=False, allow_nan=False)
        self.reference = identity_reference(current)
        self.enabled = current.get("session_identity") == SESSION_IDENTITY_CONTRACT
        self.bound = False

    def decode(self, request):
        referenced = "identity_ref" in request
        if request.get("protocol") != PROTOCOL:
            raise ValueError("NATIVE_IDENTITY_MISMATCH: session protocol changed")
        if referenced:
            if (not self.enabled or not self.bound or "identity" in request
                    or request["identity_ref"] != self.reference):
                raise ValueError("NATIVE_IDENTITY_MISMATCH: unbound or changed session identity")
            return {**{key: value for key, value in request.items() if key != "identity_ref"},
                    "identity": json.loads(self._current_json)}, True
        if identity_reference(request.get("identity")) != self.reference:
            raise ValueError("NATIVE_IDENTITY_MISMATCH: session runtime changed")
        self.bound = True
        return request, False

    def encode(self, output, referenced):
        return {"ok": True, **output,
                **({"identity_ref": self.reference} if referenced else {"identity": self.current})}


def _utf8_stdio():
    """Native IPC is UTF-8 regardless of the Windows process code page."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")


def identity(package: str, engine: str, *, adapter: str) -> dict[str, Any]:
    def distribution(name: str) -> dict[str, str]:
        dist = importlib.metadata.distribution(name)
        digest = hashlib.sha256()
        # Bind actual installed code, including native binaries, not just a version label.
        for item in sorted(dist.files or (), key=str):
            if str(item).endswith((".py", ".pyd", ".so", "METADATA")):
                digest.update(str(item).encode())
                digest.update(dist.locate_file(item).read_bytes())
        return {"package": name, "version": dist.version, "code_sha256": digest.hexdigest()}
    return {"protocol": PROTOCOL, "adapter": adapter,
            "session_identity": SESSION_IDENTITY_CONTRACT,
            "plugin": distribution(package), "engine": distribution(engine),
            "transport": distribution("candlescope-plugin-sdk")}


def serve(describe: Callable, execute: Callable) -> int:
    _utf8_stdio()
    try:
        request = json.load(sys.stdin)
        current = describe()
        if request.get("operation") == "describe":
            result = {"ok": True, "identity": current}
        else:
            if (request.get("protocol") != PROTOCOL or request.get("identity") != current
                    or "identity_ref" in request):
                raise ValueError("NATIVE_IDENTITY_MISMATCH: installed runtime changed")
            # User print() must never corrupt the wire response.
            with contextlib.redirect_stdout(sys.stderr):
                output = execute(request)
            result = {"ok": True, "identity": current, **output}
    except Exception as exc:
        result = {"ok": False, "diagnostics": [{"severity": "error", "message": str(exc),
                  "code": getattr(exc, "code", "NATIVE_EXECUTION_FAILED")} ]}
    json.dump(result, sys.stdout, ensure_ascii=False, allow_nan=False)
    return 0


def serve_evaluator(describe, execute):
    """One isolated run per process; each request still evaluates its full prefix.

    Identity is frozen once. No native broker state or script globals are carried
    between requests, and the first error terminates the worker.
    """
    _utf8_stdio()
    current = describe()
    binding = _SessionIdentity(current)
    for line in sys.stdin:
        try:
            request, referenced = binding.decode(json.loads(line))
            with contextlib.redirect_stdout(sys.stderr):
                output = execute(request)
            response = binding.encode(output, referenced)
        except Exception as exc:
            response = {"ok": False, "diagnostics": [{"code": "NATIVE_EXECUTION_FAILED", "message": str(exc)}]}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()
        if not response["ok"]:
            return 1
    return 0


def serve_session(describe, factory):
    """JSON-lines transport. State belongs to this process; errors terminate it."""
    _utf8_stdio()
    session = None
    current = describe()
    binding = _SessionIdentity(current)
    for line in sys.stdin:
        try:
            request, referenced = binding.decode(json.loads(line))
            with contextlib.redirect_stdout(sys.stderr):
                if request["operation"] == "open":
                    if session is not None:
                        raise ValueError("session already open")
                    session = factory(request)
                    output = {"supported": session is not None}
                elif request["operation"] == "advance" and session is not None:
                    output = session.advance(request["target"])
                else:
                    raise ValueError("invalid historical session operation")
            response = binding.encode(output, referenced)
        except Exception as exc:
            response = {"ok": False, "diagnostics": [{"code": "NATIVE_SESSION_FAILED", "message": str(exc)}]}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()
        if not response["ok"]:
            return 1
    return 0
