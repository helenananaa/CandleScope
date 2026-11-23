"""Lifecycle entry for the installed Python indicator runtime."""

from __future__ import annotations

import json
import re
import signal
import sys
from pathlib import Path

from candlescope_plugin_sdk import AnalyzeRequest, ExecuteBatchRequest
from candlescope_plugin_sdk.platform_v2 import RpcError

from .runtime import PythonIndicatorRuntime

PROTOCOL = "candlescope.unified-entry/1"
MAX_BYTES = 64 * 1024 * 1024
MAX_FRAME_BYTES = 64 * 1024


def _calculate(runtime, payload):
    return runtime.execute_batch(ExecuteBatchRequest.from_wire(payload)).to_wire()


def _exchange(runtime, directory, ident):
    if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{32}", ident):
        raise ValueError("invalid Python indicator exchange id")
    with (directory / f"{ident}.input").open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Python indicator input exceeds 64 MiB")
    request = json.loads(raw)
    operation = request["operation"]
    payload = request["payload"]
    if operation == "describe":
        result = runtime.describe().to_wire()
    elif operation == "analyze":
        result = runtime.analyze(AnalyzeRequest.from_wire(payload)).to_wire()
    elif operation == "calculate":
        result = _calculate(runtime, payload)
    elif operation == "release":
        result = {"released": True}
    else:
        raise ValueError("unsupported Python indicator operation")
    raw = json.dumps(result, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("Python indicator output exceeds 64 MiB")
    with (directory / f"{ident}.output").open("xb") as stream:
        stream.write(raw)
    return {"exchangeId": ident, "size": len(raw)}


def main():
    # Allow the runtime's fresh-process cleanup to run on POSIX deactivation.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    directory = Path.cwd() / ".python-exchange"
    runtime = PythonIndicatorRuntime()
    identity = None
    while line := sys.stdin.buffer.readline(MAX_FRAME_BYTES + 1):
        if len(line) > MAX_FRAME_BYTES:
            return 2
        frame = json.loads(line)
        method = frame["method"]
        if method == "cancel":
            continue
        generation = frame["generation"]
        params = frame["params"]
        reply = {"jsonrpc": "2.0", "id": frame["id"], "generation": generation}
        try:
            if method == "activate":
                candidate = params["identity"]
                if (
                    identity is not None
                    or params["protocol"] != PROTOCOL
                    or candidate["generation"] != generation
                ):
                    raise ValueError("invalid Python indicator activation")
                identity = candidate
                reply["result"] = {"protocol": PROTOCOL, "identity": identity}
            elif identity is None or generation != identity["generation"]:
                raise ValueError("Python indicator activation is not current")
            elif method == "python.exchange":
                reply["result"] = _exchange(runtime, directory, params["exchangeId"])
            else:
                raise ValueError(
                    "Python indicator calculations use the typed chart runtime"
                )
        except Exception as exc:  # noqa: BLE001 -- return structured protocol diagnostics
            reply["error"] = RpcError(
                -32000,
                str(exc)[:1024] or type(exc).__name__,
                "PYTHON_INDICATOR_REQUEST_FAILED",
            ).to_wire()
        print(json.dumps(reply, ensure_ascii=True, allow_nan=False), flush=True)
    return 0
