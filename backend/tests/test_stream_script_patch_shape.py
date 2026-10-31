"""Live script ``indicator.patch`` messages carry only the patched range.

The frozen fixture is shared with the frontend test
``frontend/src/features/indicators/__tests__/scriptPatchShape.test.ts``, which
replays it through the browser's parser, output reducer and result cache.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from candlescope_plugin_sdk import (
    ExecuteBatchResult,
    LinePoint,
    LineSeries,
    RenderCollections,
    RenderOutput,
)

from app.api.v1 import stream_indicator_payloads as payload_api

FIXTURE = Path(__file__).parent / "fixtures/plugin_runtime/script-live-patch.json"
T0 = 1_700_000_000
STEP = 60
META = {
    "kind": "script",
    "language": "pine",
    "exchange": "binance",
    "market_type": "spot",
    "symbol": "BTCUSDT",
    "interval": "1m",
    "name": "rich",
    "indicatorId": "pine-rich",
    "params": {},
}


def _bars(count: int) -> list[dict[str, Any]]:
    return [
        {
            "time": T0 + index * STEP,
            "open": 100.0 + index % 5,
            "high": 101.0 + index % 5,
            "low": 99.0 + index % 5,
            "close": 100.5 + index % 5,
            "volume": 1.0,
        }
        for index in range(count)
    ]


def _pine_like_result(bars: list[dict[str, Any]]) -> ExecuteBatchResult:
    """Mirror the Pine plugin's Render IR: public series plus collections."""
    times = [bar["time"] for bar in bars]
    closes = [bar["close"] for bar in bars]
    colors = ["#22c55e" if index % 2 else "#ef4444" for index in range(len(bars))]
    color_data = [{"time": t, "color": c} for t, c in zip(times, colors)]
    fast = {
        "id": "pine-plot-0",
        "title": "fast",
        "pane": "main",
        "data": [
            {"time": t, "value": v, "color": c}
            for t, v, c in zip(times, closes, colors)
        ],
        "linewidth": 2,
        "linestyle": 0,
        "base": 0.0,
        "trackPrice": False,
        "visible": True,
        "colorData": color_data,
        "per_bar_color": True,
        "color": colors[0],
    }
    volume = {
        "id": "pine-plot-1",
        "title": "volume",
        "pane": "separate",
        "data": [{"time": t, "value": bar["volume"]} for t, bar in zip(times, bars)],
        "linewidth": 1,
        "linestyle": 0,
        "base": 0.0,
        "trackPrice": False,
        "visible": True,
        "color_up": "#2962ff",
        "color_down": "#2962ff",
    }
    pine_scene = {
        "id": "pine-native-objects-main",
        "pane": "main",
        "asOf": times[-1],
        "times": times,
        "objects": [
            {
                "kind": "lines",
                "row": {"id": 1, "x1": 0, "y1": 99.0, "x2": len(times) - 1, "y2": 104.0},
            },
            {
                "kind": "plotseries",
                "row": {"id": 0, "family": "plotChars", "values": [i % 2 == 0 for i in range(len(times))]},
            },
            {
                "kind": "gradientfills",
                "row": {"id": 1, "firstValues": [c + 2 for c in closes], "secondValues": [c - 2 for c in closes]},
            },
        ],
    }
    collections = RenderCollections(
        lines=(fast,),
        histograms=(volume,),
        markers=(
            {
                "id": "pine-plotshape-0",
                "title": "cross",
                "shape": "arrowUp",
                "color": "#22c55e",
                "text": "",
                "position": "belowBar",
                "size": "normal",
                "pane": "main",
                "data": [
                    {"time": t, "shape": "arrowUp", "color": "#22c55e", "text": "",
                     "position": "belowBar", "size": "normal", "pane": "main"}
                    for t in times[::2]
                ],
            },
        ),
        hlines=(
            {"id": "pine-hline-0", "price": 100.0, "title": "floor", "color": "#787b86",
             "linestyle": "dashed", "linewidth": 1, "pane": "main"},
        ),
        fills=(
            {"id": "pine-fill-0", "plot1_id": "pine-plot-0", "plot2_id": "pine-plot-1",
             "title": "band", "color": colors[0], "fillGaps": True, "pane": "main",
             "colorData": color_data},
        ),
        bgcolors=(
            {"id": "pine-bgcolor-0", "title": "trend", "color": "rgba(34,197,94,0.1)",
             "pane": "main",
             "regions": [{"time": t, "color": "rgba(34,197,94,0.1)"} for t in times[::3]]},
        ),
        barcolors=(
            {"id": "pine-barcolor-0", "title": "bars",
             "data": [{"time": t, "color": c} for t, c in zip(times, colors)]},
        ),
        signals=tuple(
            {"id": f"pine-alert-0-{number}", "name": "alert", "side": "alert", "message": "up",
             "pane": "main",
             "data": [{"time": times[index], "side": "alert", "name": "alert", "message": "up"}]}
            for number, index in enumerate((0, len(times) - 1))
        ),
        objects={"pineScenes": [pine_scene]},
    )
    series = tuple(
        LineSeries(
            id=record["id"],
            title=record["title"],
            points=tuple(
                LinePoint(time=p["time"], value=p["value"], color=p.get("color"))
                for p in record["data"]
            ),
            pane=record["pane"],
            style={
                "color": record.get("color") or record["color_up"],
                "lineWidth": record["linewidth"],
                "lineStyle": record["linestyle"],
                **({"colorData": record["colorData"]} if record.get("colorData") else {}),
            },
            series_type=series_type,
        )
        for record, series_type in ((fast, "line"), (volume, "histogram"))
    )
    return ExecuteBatchResult(
        ok=True,
        output=RenderOutput(
            series=series,
            collections=collections,
            meta={"engine": "pine-compat-runtime", "closedBarsOnly": True},
        ),
    )


def _message(bars: list[dict[str, Any]], *, bar_time: int) -> dict[str, Any]:
    return payload_api._plugin_snapshot_or_patch_from_result(
        "client", dict(META), bars, _pine_like_result(bars), bar_time=bar_time
    )


def _live_messages(closed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """The subscription snapshot over closed bars, then one forming-bar tick."""
    bars = _bars(closed + 1)
    return _message(bars[:-1], bar_time=0), _message(bars, bar_time=bars[-1]["time"])


def _timed_points(value: Any, path: str = "") -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    if isinstance(value, dict):
        if isinstance(value.get("time"), int):
            found.append((path, value["time"]))
        for key, item in value.items():
            found.extend(_timed_points(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_timed_points(item, f"{path}[{index}]"))
    return found


def test_live_script_patch_matches_frozen_browser_fixture() -> None:
    snapshot, patch = _live_messages(6)

    assert {"snapshot": snapshot, "patch": patch} == json.loads(
        FIXTURE.read_text(encoding="utf-8")
    )


def test_live_script_patch_omits_render_ir_and_slices_every_timed_output() -> None:
    bars = _bars(7)
    full = payload_api._build_plugin_snapshot_from_payload(
        "client",
        dict(META),
        payload_api.serialize_plugin_runtime_result(_pine_like_result(bars)),
        bar_time=bars[-1]["time"],
    )
    untouched = copy.deepcopy(full)
    tick = bars[-1]["time"]

    patch = payload_api._finish_plugin_snapshot_or_patch(
        full, bars, bar_time=tick, reason="bar_update"
    )

    assert full == untouched
    assert patch["type"] == "indicator.patch"
    assert patch["range"] == {"start": tick, "end": tick}
    assert "result" not in patch
    assert set(full) - set(patch) == {"result"}
    # Drawings are authoritative whole scenes indexed by bar, not a time slice.
    assert patch["drawings"] == full["drawings"]
    assert patch["drawings"][0]["times"] == [bar["time"] for bar in bars]
    outside = [
        (path, time)
        for path, time in _timed_points({k: v for k, v in patch.items() if k != "drawings"})
        if time != tick
    ]
    assert outside == []
    assert patch["legacyFills"][0]["colorData"] == [{"time": tick, "color": "#ef4444"}]
    assert patch["legacyFills"][0]["plot1_id"] == "pine-plot-0"
    assert patch["bgcolors"][0]["regions"] == [{"time": tick, "color": "rgba(34,197,94,0.1)"}]
    assert [line["data"] for line in patch["lines"]] == [
        [{"time": tick, "value": 101.5, "color": "#ef4444"}],
        [{"time": tick, "value": 1.0}],
    ]


def test_live_script_patch_size_does_not_grow_with_history() -> None:
    def encoded_without_drawings(closed: int) -> int:
        _snapshot, patch = _live_messages(closed)
        patch.pop("drawings")
        return len(json.dumps(patch, separators=(",", ":")))

    # Same last-bar values and digit counts; only history length differs.
    assert encoded_without_drawings(2000) == encoded_without_drawings(20)


def test_script_snapshot_and_replace_range_keep_render_ir() -> None:
    snapshot, _patch = _live_messages(6)
    times = [bar["time"] for bar in _bars(6)]

    replacement = payload_api._replace_range_from_snapshot(
        snapshot, reason="load_range", start_s=times[2], end_s=times[3]
    )

    assert snapshot["type"] == "indicator.snapshot"
    assert len(snapshot["result"]["lines"][0]["data"]) == 6
    assert replacement["type"] == "indicator.replace_range"
    assert replacement["result"] == snapshot["result"]
    assert replacement["drawings"] == snapshot["drawings"]
    assert [p["time"] for p in replacement["legacyFills"][0]["colorData"]] == times[2:4]
    assert [r["time"] for r in replacement["bgcolors"][0]["regions"]] == [times[3]]


def test_builtin_patch_keeps_its_sliced_result_outputs() -> None:
    payload = {
        "type": "indicator.snapshot",
        "kind": "builtin",
        "lines": [{"name": "MA", "data": [{"time": 10, "value": 1}, {"time": 20, "value": 2}]}],
        "result": {"outputs": {"MA": {"data": [{"time": 10, "value": 1}, {"time": 20, "value": 2}]}}},
    }

    patch = payload_api._patch_from_snapshot(payload, reason="bar_update", start_s=20, end_s=20)

    assert patch["result"] == {"outputs": {"MA": {"data": [{"time": 20, "value": 2}]}}}
