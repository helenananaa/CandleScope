"""Source-bounded Pine wire measurements through real HTTP, WS and the pinned worker."""
import hashlib
import json
import os
from pathlib import Path
import queue
from statistics import median, quantiles
from time import perf_counter_ns

import pytest

from app.api.v1 import chart_calculation, stream_indicator_payloads
from candlescope_plugin_sdk import LinePoint
from app.data_engine.data_manager.config import DataManagerConfig
from app.data_engine.data_manager.models import BarData
from app.plugin_runtime import supervisor
from tests import test_chart_calculation_transports as transport
from tests.test_chart_calculation_real_bus import real_bus_wire, wire, storage  # noqa: F401

SCRIPT = """//@version=6
indicator("wire matrix")
varip int ticks = 0
ticks += 1
plot(ticks, title="counter")
"""
OBSERVATIONS = 24


def receive(ws, *expected):
    while True:
        try:
            frame = ws._send_queue.get(timeout=30)
        except queue.Empty:
            pytest.fail(f"Missing actual WS message: {expected}")
        if isinstance(frame, BaseException):
            raise frame
        message = frame["text"].encode()
        payload = json.loads(message)
        if payload["type"] in expected:
            return payload, len(message)
        assert payload["type"] in ("connected", "heartbeat"), payload


def measure(started):
    return (perf_counter_ns() - started) / 1_000_000


@pytest.fixture
def configured_wire(monkeypatch, request, history):
    if history > 10_000:
        init = transport.DataManager.__init__

        def wider_query_cap(manager, config=None):
            config = config or DataManagerConfig()
            config.query.max_limit = 50_000
            init(manager, config)

        monkeypatch.setattr(transport.DataManager, "__init__", wider_query_cap)
    return request.getfixturevalue("real_bus_wire")


@pytest.mark.parametrize("history", [1000, 10000, 40000])
def test_real_wire_history_scaling(configured_wire, monkeypatch, history):
    wire = configured_wire
    source = wire.source
    source.rows = transport.bars(history)
    opening = source.rows[-1].time + 60
    response_mode = os.environ.get("PINE_MATRIX_RESPONSE_MODE", "delta")
    assert response_mode in ("delta", "legacy")
    transactions = []
    builds = []
    writes = []
    encode = supervisor._encode_request
    decode = supervisor.strict_json_loads
    build = stream_indicator_payloads.serialize_plugin_runtime_result
    project = chart_calculation._plugin_snapshot_or_patch_from_result
    point_wire = LinePoint.to_wire
    point_calls = 0

    def track_point(point):
        nonlocal point_calls
        point_calls += 1
        return point_wire(point)

    def track_projection(*args, **kwargs):
        started = perf_counter_ns()
        before = point_calls
        payload = project(*args, **kwargs)
        builds[-1].update(projectionMs=measure(started), pointWireCalls=point_calls - before)
        return payload

    def track_request(request, **kwargs):
        started = perf_counter_ns()
        raw = encode(request, **kwargs)
        if request["method"] == supervisor.METHOD_EXECUTE_BATCH:
            params = request["params"]
            writes.append({
                "id": request["id"],
                "bytes": len(raw) + 1,
                "rows": len(params["bars"]),
                "barsBase": (params.get("barsPatch") or {}).get("base") is not None,
                "outputBase": (params.get("outputPatch") or {}).get("base") is not None,
                "encodeMs": measure(started),
            })
        return raw

    def track_response(message, **kwargs):
        started = perf_counter_ns()
        result = decode(message, **kwargs)
        if isinstance(result, dict) and writes and result.get("id") == writes[-1]["id"]:
            value = result.get("result", {})
            update = value.get("meta", {}).get("outputUpdate", {})
            if update.get("mode") == "range":
                assert update.get("timeOrder") == "ascending"
                if response_mode == "legacy":
                    update.pop("timeOrder")
            transactions.append({
                "id": result["id"],
                "bytes": len(message) + 1,
                "outputPatch": value.get("outputPatch") is not None,
                "fullOutput": value.get("output") is not None,
                "decodeMs": measure(started),
            })
        return result

    def track_build(result, **kwargs):
        started = perf_counter_ns()
        payload = build(result, **kwargs)
        builds.append({
            "retainedPoints": sum(len(series.points) for series in result.output.series),
            "serializeMs": measure(started),
        })
        return payload

    monkeypatch.setattr(LinePoint, "to_wire", track_point)
    monkeypatch.setattr(chart_calculation, "_plugin_snapshot_or_patch_from_result", track_projection)
    monkeypatch.setattr(supervisor, "_encode_request", track_request)
    monkeypatch.setattr(supervisor, "strict_json_loads", track_response)
    monkeypatch.setattr(stream_indicator_payloads, "serialize_plugin_runtime_result", track_build)

    @wire.client.app.post("/fixture/wire-measurement/{observation}")
    async def publish(observation: int):
        bar = BarData(time=opening, open=100, high=140, low=99, close=100 + observation,
                      volume=10, is_closed=False, source="ws_native")
        key = transport.SeriesKey("BTCUSDT", "1m")
        source.now_ms = opening * 1000 + 30_000
        source.cache.upsert(key, bar)
        await source.emit(transport.DataEvent(transport.DataEventType.BAR_UPDATED, key, bar=bar))
        return {"published": True}

    started = perf_counter_ns()
    initial = wire.client.post("/indicators/calculations", json=transport.open_request(script=SCRIPT, end=opening - 60))
    seed_ms = measure(started)
    projection = initial.json()
    assert projection.get("ok") is True, str(projection)[:800]
    assert transport.value(projection) == history
    assert len(writes) == len(transactions) == 1
    seed = {"httpBytes": len(initial.content), "httpMs": seed_ms, "ipcRequest": writes[-1], "ipcResponse": transactions[-1]}
    observations = []
    expected_live_type = "indicator.replace_range"
    with wire.client.websocket_connect("/ws") as socket:
        transport.subscribe(socket, transport.ref(projection), script=SCRIPT)
        assert receive(socket, "indicator.subscribed")[0]["ok"]
        snapshot, snapshot_bytes = receive(socket, "indicator.snapshot")
        counter = next(line for line in snapshot["lines"] if line.get("title", line.get("name")) == "counter")
        expected = {point["time"]: point["value"] for point in counter["data"]}
        assert len(expected) == history
        assert len(writes) == 1
        for index in range(1, OBSERVATIONS + 1):
            before_query = len(source.query_windows)
            started = perf_counter_ns()
            assert wire.client.post(f"/fixture/wire-measurement/{index}").json() == {"published": True}
            live, ws_bytes = receive(socket, "indicator.replace_range", "indicator.patch", "indicator.snapshot", "error")
            latency = measure(started)
            assert live["type"] == expected_live_type, str(live)[:800]
            assert live["calculation"]["generation"] == projection["calculation"]["generation"]
            assert live["calculation"]["sequence"] == projection["calculation"]["sequence"] + index
            assert transport.value(live) == history + index
            assert len(writes) == len(transactions) == index + 1
            assert transactions[-1]["id"] == writes[-1]["id"]
            assert transactions[-1]["outputPatch"] and not transactions[-1]["fullOutput"]
            expected[opening] = history + index
            wire_points = {point["time"]: point["value"] for line in live["lines"] for point in line["data"]}
            assert live["range"] == {"start": opening, "end": opening}
            assert wire_points == {opening: expected[opening]}
            assert builds[-1]["pointWireCalls"] == (1 if response_mode == "delta" else history + 1)
            observations.append({
                "index": index, "wsBytes": ws_bytes, "wsType": live["type"], "publishToAsgiClientMs": latency,
                "queryWindowsMs": source.query_windows[before_query:], "ipcRequest": writes[-1],
                "ipcResponse": transactions[-1], "hostSerialization": builds[-1],
            })
        # Read the same admitted projection across the entire origin range. This
        # is a semantic comparison, not the performance baseline for live events.
        full = transport.view(wire, transport.ref(live), end=opening)
        assert full.get("ok") is True, str(full)[:800]
        assert {point["time"]: point["value"] for line in full["lines"] for point in line["data"]} == expected
        assert len(writes) == OBSERVATIONS + 1
        socket.send_json({"action": "unsubscribe", "clientId": "chart-a"})
        receive(socket, "indicator.unsubscribed")
    assert wire.client.delete("/indicators/calculations/" + transport.ref(projection)["domainId"]).json()["state"] == "closed"
    measured = observations[4:]
    latency = [row["publishToAsgiClientMs"] for row in measured]
    report = {
        "history": history, "dataManagerQueryMax": source._cfg.query.max_limit, "seed": seed, "joinSnapshotBytes": snapshot_bytes,
        "semanticParity": True, "warmupObservations": 4, "observations": observations,
        "responseMode": response_mode,
        "projectionSha256": hashlib.sha256(json.dumps(sorted(expected.items())).encode()).hexdigest(),
        "latencyMs": {"p50": median(latency), "p95": quantiles(latency, n=100, method="inclusive")[94],
                      "p99": quantiles(latency, n=100, method="inclusive")[98]},
    }
    Path(os.environ["PINE_MATRIX_OUT"], f"matrix-{response_mode}-{history}.json").write_text(json.dumps(report, indent=2) + "\n")
