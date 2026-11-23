"""Language-neutral unified JSONL entry protocol, implemented using only stdlib."""

import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "cancel":
        continue
    params = request["params"]
    response = {
        "jsonrpc": "2.0",
        "id": request["id"],
        "generation": request["generation"],
    }
    if method == "activate" and params.get("protocol") == "candlescope.unified-entry/1":
        response["result"] = {
            "protocol": params["protocol"],
            "identity": params["identity"],
        }
    elif method == "invoke":
        response["result"] = {"input": params["input"]}
    elif method == "chart.compute":
        response["result"] = {"points": [
            {"timeMs": bar["openTimeMs"], "value": bar["close"]}
            for bar in params["bars"]
        ]}
    else:
        response["error"] = {
            "code": -32601,
            "message": "Unsupported unified entry method",
        }
    print(json.dumps(response, ensure_ascii=False), flush=True)
