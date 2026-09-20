"""One-shot native strategy transport, independent of indicator rendering.

The original engine output is authoritative. No host orders or fills are made.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import sys
from typing import Any, Callable

PROTOCOL = "candlescope.native-strategy/1"


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
            "plugin": distribution(package), "engine": distribution(engine),
            "transport": distribution("candlescope-plugin-sdk")}


def serve(describe: Callable, execute: Callable) -> int:
    try:
        request = json.load(sys.stdin)
        current = describe()
        if request.get("operation") == "describe":
            result = {"ok": True, "identity": current}
        else:
            if request.get("protocol") != PROTOCOL or request.get("identity") != current:
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
    current = describe()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("protocol") != PROTOCOL or request.get("identity") != current:
                raise ValueError("NATIVE_IDENTITY_MISMATCH: evaluator runtime changed")
            with contextlib.redirect_stdout(sys.stderr):
                output = execute(request)
            response = {"ok": True, "identity": current, **output}
        except Exception as exc:
            response = {"ok": False, "diagnostics": [{"code": "NATIVE_EXECUTION_FAILED", "message": str(exc)}]}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()
        if not response["ok"]:
            return 1
    return 0


def serve_session(describe, factory):
    """JSON-lines transport. State belongs to this process; errors terminate it."""
    session = None
    current = describe()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("protocol") != PROTOCOL or request.get("identity") != current:
                raise ValueError("NATIVE_IDENTITY_MISMATCH: session runtime changed")
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
            response = {"ok": True, "identity": current, **output}
        except Exception as exc:
            response = {"ok": False, "diagnostics": [{"code": "NATIVE_SESSION_FAILED", "message": str(exc)}]}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()
        if not response["ok"]:
            return 1
    return 0
