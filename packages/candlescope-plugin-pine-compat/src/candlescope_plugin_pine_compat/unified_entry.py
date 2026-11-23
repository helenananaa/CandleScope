"""Pine entry for the unified lifecycle. The engine and render model are shared."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from pathlib import Path

from candlescope_plugin_sdk import AnalyzeRequest, Bar, ExecuteBatchRequest, MarketContext
from candlescope_plugin_sdk.platform_v2 import RpcError
from candlescope_plugin_sdk.unified.chart import validate_chart_frame, validate_chart_result

from .runtime import PineCompatRuntimePlugin

PROTOCOL = "candlescope.unified-entry/1"
MAX_BYTES = 64 * 1024 * 1024
MAX_LINE = 64 * 1024


def compute_chart(engine, params):
    scope, bars, value = params["scope"], params["bars"], params["input"]
    validate_chart_frame(scope, bars)
    if not isinstance(value, dict) or set(value) != {"source", "parameters"}:
        raise ValueError("Pine chart computation requires source and parameters")
    if any(bar["volume"] is None for bar in bars):
        raise ValueError("Pine requires volume on each supplied chart bar")
    # A scoped frame is a self-contained preview. Host request.* data providers,
    # live sessions and account bindings are not available through this call.
    request = ExecuteBatchRequest(
        source=value["source"],
        context=MarketContext(
            exchange="candlescope",
            market_type="spot",
            symbol=scope["symbol"],
            interval=scope["interval"],
        ),
        bars=tuple(
            Bar(
                time=bar["openTimeMs"],
                open=bar["open"],
                high=bar["high"],
                low=bar["low"],
                close=bar["close"],
                volume=bar["volume"],
                is_closed=bar["closed"],
            )
            for bar in bars
        ),
        params=value["parameters"],
    )
    result = engine.execute_batch(request)
    if not result.ok or result.output is None:
        raise ValueError("Pine rejected the scoped chart computation")
    collections = result.output.collections
    if (
        len(result.output.series) != 1
        or result.output.series[0].series_type != "line"
        or (collections is not None and set(collections.to_wire()) - {"lines"})
    ):
        raise ValueError("Scoped point results require one Pine line without graphics")
    times = {bar["openTimeMs"] for bar in bars}
    output = {
        "points": [
            {"timeMs": point.time * 1000, "value": point.value}
            for point in result.output.series[0].points
            if point.value is not None
        ]
    }
    validate_chart_result(output, times)
    return output


def _file_operation(engine, name, scratch):
    if not isinstance(name, str) or not re.fullmatch(r"[a-f0-9]{32}", name):
        raise ValueError("invalid Pine exchange id")
    with (scratch / f"{name}.input").open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Pine input exceeds 64 MiB")
    request = json.loads(raw)
    operation, payload = request["operation"], request["payload"]
    if operation == "describe":
        result = engine.describe().to_wire()
    elif operation == "analyze":
        result = engine.analyze(AnalyzeRequest.from_wire(payload)).to_wire()
    elif operation == "calculate":
        batch = ExecuteBatchRequest.from_wire(payload)
        # Each message owns the complete input window. Nonstandard bar axes,
        # forming bars, parameters, requested contexts and session options stay intact.
        result = engine.execute_batch(
            replace(batch, bars_stream=None, bars_base=None, output_base=None)
        ).to_wire()
    elif operation == "release":
        engine.release_stream(payload["stream"])
        result = {"released": True}
    else:
        raise ValueError("unsupported Pine operation")
    size = 0
    with (scratch / f"{name}.output").open("xb") as output:
        for chunk in json.JSONEncoder(
            ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).iterencode(result):
            block = chunk.encode()
            size += len(block)
            if size > MAX_BYTES:
                raise ValueError("Pine output exceeds 64 MiB")
            output.write(block)
    return {"exchangeId": name, "size": size}


def main():
    engine = None
    context = None
    # The scratch directory is owned by this activation. The caller cannot
    # specify a path in a message, only the random name of one Host exchange.
    scratch = Path.cwd() / ".pine-exchange"
    try:
        while line := sys.stdin.buffer.readline(MAX_LINE + 1):
            if len(line) > MAX_LINE:
                return 2
            frame = json.loads(line)
            if frame["method"] == "cancel":
                continue
            reply = {"jsonrpc": "2.0", "id": frame["id"], "generation": frame["generation"]}
            try:
                params = frame["params"]
                if frame["method"] == "activate":
                    identity = params["identity"]
                    if (
                        context is not None
                        or params["protocol"] != PROTOCOL
                        or identity["generation"] != frame["generation"]
                    ):
                        raise ValueError("invalid Pine activation")
                    storage = Path(params["storage"])
                    engine = PineCompatRuntimePlugin(
                        journal_path=storage / "observations-v1.sqlite3"
                    )
                    context = identity
                    reply["result"] = {"protocol": PROTOCOL, "identity": identity}
                elif engine is None or frame["generation"] != context["generation"]:
                    raise ValueError("Pine activation is not current")
                elif frame["method"] == "pine.exchange":
                    reply["result"] = _file_operation(engine, params["exchangeId"], scratch)
                elif frame["method"] == "chart.compute":
                    reply["result"] = compute_chart(engine, params)
                else:
                    raise ValueError("unsupported unified Pine entry method")
            except Exception as exc:  # noqa: BLE001 -- return failures as protocol frames
                reply["error"] = RpcError(
                    -32000, str(exc)[:1024] or type(exc).__name__, "PINE_REQUEST_FAILED"
                ).to_wire()
            print(json.dumps(reply, ensure_ascii=False, allow_nan=False), flush=True)
    finally:
        if engine is not None:
            engine.shutdown()
    return 0
