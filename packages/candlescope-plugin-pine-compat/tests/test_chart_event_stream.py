from copy import deepcopy
import pytest
import pine_compat
from candlescope_plugin_pine_compat import chart_strategy, external_strategy, external_stream
from candlescope_plugin_pine_compat.execution_schedule import CONTRACT as SCHEDULE, TICK_CONTRACT

pytestmark = pytest.mark.skipif(
    getattr(pine_compat, "EXTERNAL_CHART_EVENT_SCHEMA_VERSION", 0) != 1,
    reason="requires chart event engine",
)
SOURCE = """//@version=6
strategy("Event clock",calc_on_every_tick=true,calc_on_order_fills=true)
var int ordinary=0
varip int persistent=0
ordinary+=1
persistent+=1
plot(ordinary)
plot(persistent)
plot(time)
plot(strategy.position_size)
"""


@pytest.mark.parametrize("route", [chart_strategy.execute, external_strategy.execute])
@pytest.mark.parametrize(
    "transform", ["heikin-ashi", "renko", "point-and-figure", "kagi", "line-break"]
)
def test_bridge_stream_preserves_milliseconds_duplicate_bricks_and_preview_rollback(
    route, transform
):
    external_stream._active = None
    request = dict(
        source=SOURCE,
        parameters={},
        context={"symbol": "X:MAIN", "timeframe": "1"},
        external_stream_contract=external_stream.CONTRACT,
        execution_schedule_contract=SCHEDULE,
        execution_tick_contract=TICK_CONTRACT,
        chart_signal_contract="ordered-chart-strategy/1",
        chart_event_contract="candlescope.chart-signal-events/1",
        signal_chart={"transform": transform},
    )
    route({**request, "operation": "stream_open"})
    native = external_stream._active.engine

    def command(operation, index, **kw):
        return route(
            dict(
                operation=operation,
                bar_cursor=index,
                intent_base=0,
                external_stream_contract=external_stream.CONTRACT,
                **kw
            )
        )

    for index in range(2):
        bar = dict(time=1, chart_time_ms=1501, open=10, high=12, low=10, close=12, volume=1)
        command("stream_begin", index, bar=bar, bar_state="realtime")
        for step in range(2):
            account = dict(
                time=1,
                position_size=index,
                position_avg_price=10 if index else None,
                equity=1000,
                initial_capital=1000,
                netprofit=0,
                openprofit=0,
            )
            observation = dict(
                evaluation=dict(
                    bar=deepcopy(bar),
                    account=account,
                    event_time_ms=1510 + index * 10 + step,
                    confirmed=step == 1,
                ),
                context=dict(
                    bar_state="realtime",
                    trigger="bar_close" if step else "realtime_tick",
                    is_new=step == 0,
                ),
            )
            command("stream_observe", index, observation=observation)
        command("stream_commit", index)
        assert external_stream._active.engine is native
    output = command("stream_snapshot", 2)["output"]
    assert output["plots"][0]["values"] == [1, 2]
    assert output["plots"][1]["values"] == [2, 4]
    assert output["plots"][2]["values"] == [1501, 1501]
    assert output["plots"][3]["values"] == [0, 1]
    assert "strategy" not in output
    external_stream._active = None
