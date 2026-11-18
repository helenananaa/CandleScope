"""Unified entry for the trusted-local Hello Command sample."""

import json
import re
import sys
from pathlib import Path

from candlescope_plugin_sdk.platform_v2 import (
    JsonLimits,
    RpcError,
    RpcFailure,
    RpcRequest,
    RpcSuccess,
    canonical_dumps,
    loads_strict,
)
from candlescope_plugin_sdk.unified import ActivationIdentity

PROTOCOL = "candlescope.unified-entry/1"
MAX_FRAME_BYTES = JsonLimits().max_message_bytes
MANIFEST = json.loads(Path(__file__).with_name("manifest.json").read_bytes())


def activation(request):
    try:
        identity = request.params["identity"]
        package = ActivationIdentity(
            identity["pluginId"],
            identity["version"],
            identity["packageSha256"],
            identity["generation"],
        )
        if (
            request.params["protocol"] == PROTOCOL
            and package.plugin_id == MANIFEST["id"]
            and package.plugin_version == MANIFEST["version"]
            and package.generation == request.generation
            and identity
            == {
                **package.to_wire(),
                "entryId": "main",
                "instanceId": identity["instanceId"],
            }
            and re.fullmatch(r"[a-f0-9]{32}", identity["instanceId"])
        ):
            return {"protocol": PROTOCOL, "identity": identity}
    except (ValueError, KeyError, TypeError):
        pass
    raise ValueError("invalid unified activation identity")


def greet(params):
    if set(params) != {"input"} or not isinstance(params["input"], dict):
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
        request = RpcRequest.from_wire(loads_strict(line.rstrip(b"\r\n")))
        try:
            if request.method == "activate" and current is None:
                result = activation(request)
                current = request.generation
            elif request.method == "invoke" and request.generation == current:
                result = greet(request.params)
            else:
                raise ValueError("unsupported method or inactive generation")
            response = RpcSuccess(request.id, result, request.generation)
        except ValueError as error:
            response = RpcFailure(
                request.id,
                RpcError(-32602, str(error), "INVALID_CONTRACT"),
                request.generation,
            )
        wire = canonical_dumps(response.to_wire()).encode("utf-8")
        sys.stdout.buffer.write(wire + b"\n")
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
