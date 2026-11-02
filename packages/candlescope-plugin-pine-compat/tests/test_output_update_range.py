"""Actual engine changes identify displayed time damage, including deletion."""
from dataclasses import replace

import pytest

from candlescope_plugin_pine_compat import PineCompatRuntimePlugin
from candlescope_plugin_sdk import ExecuteBatchRequest
from test_output_patch import CONTEXT, make_bar


@pytest.mark.parametrize("source", [
    'plot(close, offset=-1)',
    'plot(close > 102 ? close : na, offset=-1)',
    'plotshape(close > 102, offset=-1, style=shape.circle)',
    'bgcolor(close > 102 ? color.red : na, offset=-1)',
])
def test_negative_offset_change_and_removal_include_the_previous_displayed_time(source):
    plugin = PineCompatRuntimePlugin()
    # A real time gap ensures the range uses output timestamps, not interval subtraction.
    history_close = 103 if source.startswith(('bgcolor', 'plotshape')) else 101
    history = tuple(replace(make_bar(i, history_close), time=1_700_000_000 + i * 120) for i in range(20))
    def execute(close, base=None):
        tail = replace(make_bar(20, close, closed=False), time=history[-1].time + 600)
        return plugin.execute_batch(ExecuteBatchRequest(
            source='//@version=6\nindicator("range")\n'+source,
            context=CONTEXT, bars=history+(tail,), options={"pineSessionId": "live"},
            output_stream="live", output_base=base,
        ))
    try:
        seed = execute(103)
        assert seed.ok, seed.diagnostics
        assert seed.meta["outputUpdate"] == {"schema": "render.update-range/1", "mode": "snapshot",
            "range": {"start": history[0].time, "end": history[-1].time + 600}}
        tick = execute(102, seed.output_revision)
        assert tick.ok, tick.diagnostics
        assert tick.output_patch is not None
        assert tick.meta["outputUpdate"] == {
            "schema": "render.update-range/1", "mode": "range",
            "range": {"start": history[-1].time, "end": history[-1].time},
        }
        resolved = tick.patched(seed.output).output
        if source.startswith('plot(close,'):
            assert resolved.series[0].points[-1].value == 102
        elif source.startswith('plot('):
            assert resolved.series[0].points == ()
        elif source.startswith('plotshape'):
            assert all(point["time"] < history[-1].time for point in resolved.collections.markers[0]["data"])
        else:
            assert all(point["time"] < history[-1].time for point in resolved.collections.bgcolors[0]["regions"])
    finally:
        plugin.shutdown()


def test_removing_the_last_marker_record_requests_complete_replacement():
    plugin = PineCompatRuntimePlugin()
    bars = tuple(make_bar(i, 101) for i in range(20))
    request = ExecuteBatchRequest(source='//@version=6\nindicator("range")\nplotshape(close > 102,offset=-1,style=shape.circle)',
        context=CONTEXT, bars=bars+(make_bar(20, 103, closed=False),),
        options={"pineSessionId": "live"}, output_stream="live")
    try:
        seed = plugin.execute_batch(request)
        assert seed.ok and seed.output.collections.markers
        cleared = plugin.execute_batch(replace(request,
            bars=bars+(make_bar(20, 102, closed=False),), output_base=seed.output_revision))
        assert cleared.ok, cleared.diagnostics
        assert cleared.meta["outputUpdate"]["mode"] == "snapshot"
        assert not cleared.patched(seed.output).output.collections.markers
    finally:
        plugin.shutdown()


@pytest.mark.parametrize("size", ["auto", "tiny", "small", "normal", "large", "huge"])
def test_marker_sizes_use_the_symbolic_host_annotation_contract(size):
    plugin = PineCompatRuntimePlugin()
    try:
        result = plugin.execute_batch(ExecuteBatchRequest(
            source='//@version=6\nindicator("size")\nplotshape(true,style=shape.circle,size=size.'+size+')',
            context=CONTEXT, bars=(make_bar(0, 101),)))
        assert result.ok, result.diagnostics
        marker = result.output.collections.markers[0]
        assert marker["size"] == size
        assert marker["data"][0]["size"] == size
    finally:
        plugin.shutdown()


def test_unprovable_show_last_and_history_correction_request_full_replacement():
    plugin = PineCompatRuntimePlugin()
    bars = tuple(make_bar(i, 100+i) for i in range(20))
    request = ExecuteBatchRequest(source='//@version=6\nindicator("range")\nplot(close,show_last=3)',
        context=CONTEXT, bars=bars, options={"pineSessionId": "live"}, output_stream="live")
    try:
        seed = plugin.execute_batch(request)
        for incoming in (
            replace(request, bars=bars+(make_bar(20, 122),), output_base=seed.output_revision),
            replace(request, bars=bars[:5]+(make_bar(5, 130),)+bars[6:], output_base=seed.output_revision),
        ):
            result = plugin.execute_batch(incoming)
            assert result.ok, result.diagnostics
            assert result.output is not None
            assert result.meta["outputUpdate"] == {"schema": "render.update-range/1", "mode": "snapshot",
                "range": {"start": incoming.bars[0].time, "end": incoming.bars[-1].time}}
    finally:
        plugin.shutdown()
