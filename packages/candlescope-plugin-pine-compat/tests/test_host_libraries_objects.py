from dataclasses import replace

from app.indicator.serialization import serialize_plugin_runtime_result
from candlescope_plugin_sdk import AnalyzeRequest
from test_host_inputs import BARS, CONTEXT, request

from candlescope_plugin_pine_compat import PineCompatRuntimePlugin

LIBRARY = '//@version=6\nlibrary("Math")\nexport twice(float x) => x * 2\n'
SOURCE = "import local/Math/1 as math\nplot(math.twice(close))"


def test_library_analysis_execution_and_changed_source_reset_same_session():
    plugin = PineCompatRuntimePlugin()
    req = request(SOURCE, pineLibrarySources={"local/Math/1": LIBRARY}, pineSessionId="imports")
    analysis = plugin.analyze(
        AnalyzeRequest(source=req.source, context=CONTEXT, options=req.options)
    )
    assert analysis.executable, analysis.diagnostics
    first = plugin.execute_batch(req)
    assert first.ok, first.diagnostics
    assert first.output.series[0].points[-1].value == 20
    changed = replace(
        req,
        options={
            **req.options,
            "pineLibrarySources": {"local/Math/1": LIBRARY.replace("x * 2", "x * 3")},
        },
    )
    second = plugin.execute_batch(changed)
    assert second.ok, second.diagnostics
    assert second.output.series[0].points[-1].value == 30
    assert second.meta["sessionReset"]
    missing = plugin.execute_batch(request(SOURCE))
    assert not missing.ok


def test_tables_vertical_lines_and_curved_filled_polylines_reach_public_payload():
    source = """var l = line.new(0, 9, 0, 12, style=line.style_arrow_both)
var points = array.new<chart.point>()
if barstate.isfirst
    array.push(points, chart.point.from_index(0, 9))
    array.push(points, chart.point.from_index(1, 12))
    array.push(points, chart.point.from_index(2, 10))
    polyline.new(points, curved=true, closed=true, fill_color=color.red)
var box b = box.new(0, 12, 2, 8, text="Range")
var table grid = table.new(position.top_right, 2, 2)
table.cell(grid, 0, 0, "Merged")
table.merge_cells(grid, 0, 0, 1, 0)
"""
    result = PineCompatRuntimePlugin().execute_batch(request(source))
    assert result.ok, result.diagnostics
    payload = serialize_plugin_runtime_result(result)
    scene = payload["drawings"][0]
    assert {item["kind"] for item in scene["objects"]} == {"lines", "boxes", "polylines", "tables"}
    line = next(item["row"] for item in scene["objects"] if item["kind"] == "lines")
    assert line["x1"] == line["x2"]
    table = next(item["row"] for item in scene["objects"] if item["kind"] == "tables")
    assert table["mergedCells"] and table["cells"][0]["text"] == "Merged"


def test_invalid_library_map_reports_actionable_host_error():
    result = PineCompatRuntimePlugin().execute_batch(
        request(SOURCE, pineLibrarySources={"unversioned": LIBRARY})
    )
    assert not result.ok
    assert result.diagnostics[0].code == "PINE_HOST_LIBRARIES_INVALID"


def test_calculation_window_keeps_object_indices_on_the_actual_seed_timeline():
    source = '//@version=6\nindicator("window", calc_bars_count=2)\nplot(bar_index)\nline.new(bar_index, close, bar_index+1, close)'
    bars = tuple(replace(BARS[0], time=BARS[0].time + i * 60) for i in range(4))
    plugin = PineCompatRuntimePlugin()
    req = replace(request("", pineSessionId="window"), source=source, bars=bars[:3])
    seeded = plugin.execute_batch(req)
    assert seeded.ok, seeded.diagnostics
    assert [point.time for point in seeded.output.series[0].points] == [
        bar.time for bar in bars[1:3]
    ]
    appended = plugin.execute_batch(replace(req, bars=bars))
    assert appended.ok, appended.diagnostics
    assert not appended.meta["sessionReset"]
    assert appended.output.collections.objects["pineScenes"][0]["times"] == [
        bar.time for bar in bars[1:]
    ]


def test_all_native_plot_families_and_gradient_fill_reach_the_object_renderer():
    source = """plotchar(close>open, char="x", location=location.abovebar)
plotarrow(close-open)
plotbar(open, high, low, close, color=color.blue)
plotcandle(open, high, low, close, color=color.orange)
p1=plot(high)
p2=plot(low)
fill(p1,p2,high,low,color.green,color.red)
"""
    result = PineCompatRuntimePlugin().execute_batch(
        replace(request(source), bars=BARS + (replace(BARS[0], time=BARS[0].time + 60),))
    )
    assert result.ok, result.diagnostics
    objects = serialize_plugin_runtime_result(result)["drawings"][0]["objects"]
    assert [item["row"]["family"] for item in objects if item["kind"] == "plotseries"] == [
        "plotChars",
        "plotArrows",
        "plotBars",
        "plotCandles",
    ]
    gradient = next(item["row"] for item in objects if item["kind"] == "gradientfills")
    assert gradient["firstValues"] == [11, 11]
    assert gradient["secondValues"] == [9, 9]


def test_old_hosts_reject_the_native_scene_requirement_in_handshake():
    import pytest
    from candlescope_plugin_sdk import (
        FEATURE_RENDER_NATIVE_SCENE_V1,
        KNOWN_FEATURES_V1,
        ProtocolError,
        RuntimeDispatcher,
    )
    dispatcher = RuntimeDispatcher(PineCompatRuntimePlugin())
    with pytest.raises(ProtocolError, match="features"):
        dispatcher.dispatch("handshake", {"protocols":["candlescope.script-runtime/1"], "host":{"name":"old-host","version":"1"}, "hostFeatures":[feature for feature in KNOWN_FEATURES_V1 if feature != FEATURE_RENDER_NATIVE_SCENE_V1]})
