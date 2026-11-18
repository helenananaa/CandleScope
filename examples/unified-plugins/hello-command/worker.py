"""Unified Hello Command worker using the standard library only."""

import json
import re
import sys
from pathlib import Path

PROTOCOL = "candlescope.unified-entry/1"
MAX_FRAME_BYTES = 1024 * 1024
MAX_GENERATION = 2**53 - 1
MANIFEST = json.loads(Path(__file__).with_name("manifest.json").read_bytes())


def activation(params, generation):
    if not isinstance(params, dict) or params.get("protocol") != PROTOCOL:
        raise ValueError("invalid unified activation protocol")
    identity = params.get("identity")
    if not isinstance(identity, dict) or set(identity) != {
        "pluginId",
        "version",
        "packageSha256",
        "generation",
        "entryId",
        "instanceId",
    }:
        raise ValueError("invalid unified activation identity")
    digest, instance = identity["packageSha256"], identity["instanceId"]
    if (
        identity["pluginId"] != MANIFEST["id"]
        or identity["version"] != MANIFEST["version"]
        or type(identity["generation"]) is not int
        or identity["generation"] != generation
        or identity["entryId"] != "main"
        or not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
        or not isinstance(instance, str)
        or not re.fullmatch(r"[a-f0-9]{32}", instance)
    ):
        raise ValueError("invalid unified activation identity")
    return {"protocol": PROTOCOL, "identity": identity}


def greet(params):
    if (
        not isinstance(params, dict)
        or set(params) != {"input"}
        or not isinstance(params["input"], dict)
    ):
        raise ValueError("hello input must be an object")
    values = params["input"]
    if set(values) - {"name"}:
        raise ValueError("hello input accepts only name")
    name = values.get("name", "world")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError(
            "hello input name must be a non-empty string of at most 80 characters"
        )
    return {"message": f"Hello, {name.strip()}!", "contributionId": "hello"}


def serve():
    current = None
    while line := sys.stdin.buffer.readline(MAX_FRAME_BYTES + 2):
        if not line.endswith(b"\n") or len(line.rstrip(b"\r\n")) > MAX_FRAME_BYTES:
            return 2
        try:
            request = json.loads(line)
        except (UnicodeError, ValueError):
            return 2
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return 2
        method = request.get("method")
        if method == "cancel" and "id" not in request:
            continue
        generation = request.get("generation")
        if (
            "id" not in request
            or type(generation) is not int
            or not 1 <= generation <= MAX_GENERATION
        ):
            return 2
        response = {"jsonrpc": "2.0", "id": request["id"], "generation": generation}
        try:
            if method == "activate" and current is None:
                response["result"] = activation(request.get("params"), generation)
                current = generation
            elif method == "invoke" and generation == current:
                response["result"] = greet(request.get("params"))
            else:
                raise ValueError("unsupported method or inactive generation")
        except ValueError as error:
            response["error"] = {
                "code": -32602,
                "message": str(error),
                "data": {"code": "INVALID_CONTRACT"},
            }
        sys.stdout.buffer.write(
            json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n"
        )
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
