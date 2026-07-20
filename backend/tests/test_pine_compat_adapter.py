from __future__ import annotations

from typing import Any

import asyncio

import pytest

from app.api.v1 import indicators as indicators_api
from app.api.v1 import stream_indicator_payloads as payload_api
from app.api.v1 import stream_pyne_subscriptions as stream_subscriptions
from app.data_engine.data_manager.models import BarData, DataEventType
from app.indicator.custom_store import CustomIndicatorStore
from app.indicator.runtimes import PINE_COMPAT_RUNTIME_ID, ScriptRuntimeContext
from app.indicator.runtimes import pine_compat_adapter as pine_adapter


def _analysis(*features: str) -> dict[str, Any]:
    return {
        "schemaVersion": 5,
        "languageVersion": 6,
        "diagnostics": [],
        "compatibility": {
            "supported": [
                {"feature": feature, "span": {"line": 2, "column": 1}}
                for feature in features
            ],
            "unsupported": [],
        },
        "executable": True,
        "inputs": [{"callSiteId": 1, "name": "input.int", "title": "Length"}],
    }


def _runtime_output(**updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schemaVersion": 8,
        "renderMetadataVersion": 1,
        "plots": [{"id": 2, "values": [None, 2.0, 3.0]}],
        "plotChars": [],
        "plotShapes": [],
        "plotArrows": [],
        "plotBars": [],
        "plotCandles": [],
        "bgColors": [],
        "barColors": [],
        "hlines": [],
        "fills": [],
        "labels": [],
        "lines": [],
        "lineFills": [],
        "polylines": [],
        "boxes": [],
        "tables": [],
        "alerts": [],
        "diagnostics": [],
    }
    value.update(updates)
    return value


def _bars() -> list[dict[str, Any]]:
    return [
        {
            "time": 1_700_000_000 + index * 60,
            "open": 1.0 + index,
            "high": 2.0 + index,
            "low": 0.5 + index,
            "close": 1.5 + index,
            "volume": 10.0,
        }
        for index in range(3)
    ]


class _FakePineModule:
    ANALYSIS_SCHEMA_VERSION = 5
    RUNTIME_SCHEMA_VERSION = 8
    RENDER_METADATA_VERSION = 1

    def __init__(self, analysis: dict[str, Any], output: dict[str, Any]) -> None:
        self.analysis = analysis
        self.output = output
        self.run_calls: list[
            tuple[str, list[dict[str, Any]], dict[int, Any], str | None, str | None]
        ] = []

    def analyze_script(self, script: str) -> dict[str, Any]:
        assert script
        return self.analysis

    def run_script(
        self,
        script: str,
        bars: list[dict[str, Any]],
        *,
        input_overrides: dict[int, Any],
        chart_symbol: str | None = None,
        chart_timeframe: str | None = None,
    ) -> dict[str, Any]:
        self.run_calls.append((script, bars, input_overrides, chart_symbol, chart_timeframe))
        return self.output


def test_pine_adapter_normalizes_seconds_and_runtime_output(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _FakePineModule(
        _analysis("indicator", "input.int", "ta.sma", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='//@version=6\nindicator("SMA", overlay=true)\nplot(close)',
        ohlcv=_bars(),
        params={"1": 2},
        executor_mode="inline",
    )

    assert result.ok is True
    assert result.lines[0]["id"] == "pine-plot-2"
    assert result.lines[0]["pane"] == "main"
    assert result.lines[0]["data"] == [
        {"time": 1_700_000_060, "value": 2.0},
        {"time": 1_700_000_120, "value": 3.0},
    ]
    assert result.param_schema[0]["key"] == "1"
    assert module.run_calls[0][1][0]["time"] == 1_700_000_000_000
    assert module.run_calls[0][2] == {1: 2}


def test_pine_adapter_rejects_host_context_before_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _FakePineModule(
        _analysis("indicator", "request.security", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Context")\nplot(request.security("AAPL", "D", close))',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.ok is False
    assert result.code == "PINE_HOST_CAPABILITY_UNSUPPORTED"
    assert result.meta["blockedFeatures"] == ["request.security"]
    assert module.run_calls == []


def test_pine_adapter_rejects_unbound_visible_chart_window(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _FakePineModule(
        _analysis("indicator", "chart.right_visible_bar_time", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Visible")\nplot(chart.right_visible_bar_time)',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.ok is False
    assert result.code == "PINE_HOST_CAPABILITY_UNSUPPORTED"
    assert result.meta["blockedFeatures"] == ["chart.right_visible_bar_time"]
    assert module.run_calls == []


@pytest.mark.parametrize(
    ("context", "chart_symbol", "chart_timeframe"),
    [
        (
            ScriptRuntimeContext("binance", "spot", "BTCUSDT", "1m"),
            "BINANCE:BTCUSDT",
            "1",
        ),
        (
            ScriptRuntimeContext("binance", "futures", "BTCUSDT", "1h"),
            "BINANCE:BTCUSDT.P",
            "60",
        ),
        (
            ScriptRuntimeContext("okx", "futures", "BTC-USDT-SWAP", "3d"),
            "OKX:BTC-USDT-SWAP",
            "3D",
        ),
        (
            ScriptRuntimeContext("binance", "spot", "BTCUSDT", "1M"),
            "BINANCE:BTCUSDT",
            "M",
        ),
    ],
)
def test_pine_chart_context_translation_is_exact(
    context: ScriptRuntimeContext,
    chart_symbol: str,
    chart_timeframe: str,
) -> None:
    assert pine_adapter.pine_chart_symbol(context) == chart_symbol
    assert pine_adapter.pine_chart_timeframe(context) == chart_timeframe


@pytest.mark.parametrize("interval", ["2s", "25h", "366d", "53w", "13M", "1H", ""])
def test_pine_chart_timeframe_rejects_unrepresentable_intervals(interval: str) -> None:
    context = ScriptRuntimeContext("binance", "spot", "BTCUSDT", interval)
    assert pine_adapter.pine_chart_timeframe(context) is None


def test_pine_adapter_injects_verified_chart_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(
        _analysis("indicator", "syminfo.tickerid", "timeframe.period", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)
    context = ScriptRuntimeContext("binance", "futures", "BTCUSDT", "1h")

    result = pine_adapter.execute_pine_script(
        script='indicator("Context")\nplot(close)',
        ohlcv=_bars(),
        context=context,
        executor_mode="inline",
    )

    assert result.ok is True
    assert module.run_calls[0][3:] == ("BINANCE:BTCUSDT.P", "60")
    assert result.meta["hostBindings"] == {
        "chartSymbol": "BINANCE:BTCUSDT.P",
        "chartTimeframe": "60",
    }


def test_pine_adapter_keeps_unverified_timeframe_functions_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(
        _analysis("indicator", "timeframe.in_seconds", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Context")\nplot(timeframe.in_seconds())',
        ohlcv=_bars(),
        context=ScriptRuntimeContext("binance", "spot", "BTCUSDT", "1h"),
        executor_mode="inline",
    )

    assert result.code == "PINE_HOST_CAPABILITY_UNSUPPORTED"
    assert result.meta["blockedFeatures"] == ["timeframe.in_seconds"]
    assert module.run_calls == []


def test_installed_pine_runtime_consumes_verified_chart_context() -> None:
    result = pine_adapter.execute_pine_script(
        script=(
            '//@version=6\nindicator("Context")\n'
            'matches = syminfo.tickerid == "BINANCE:BTCUSDT.P" and '
            'timeframe.period == "60" and timeframe.multiplier == 60\n'
            'plot(matches ? 1 : 0)'
        ),
        ohlcv=_bars(),
        context=ScriptRuntimeContext("binance", "futures", "BTCUSDT", "1h"),
        executor_mode="inline",
    )

    assert result.ok is True
    assert [point["value"] for point in result.lines[0]["data"]] == [1.0, 1.0, 1.0]


@pytest.mark.anyio
async def test_script_analysis_api_reports_native_and_host_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(
        _analysis("indicator", "request.security", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    payload = await indicators_api.analyze_script(indicators_api.ScriptAnalysisRequest(
        runtime=PINE_COMPAT_RUNTIME_ID,
        script='indicator("Context")\nplot(request.security("AAPL", "D", close))',
        exchange="binance",
        market_type="spot",
        symbol="BTCUSDT",
        interval="1m",
    ))

    assert payload["schemaVersion"] == 1
    assert payload["runtime"] == PINE_COMPAT_RUNTIME_ID
    assert payload["nativeExecutable"] is True
    assert payload["executable"] is False
    assert payload["hostCompatibility"]["error"]["code"] == "PINE_HOST_CAPABILITY_UNSUPPORTED"
    assert payload["diagnostics"][-1]["code"] == "PINE_HOST_CAPABILITY_UNSUPPORTED"
    assert payload["meta"]["context"] == {
        "exchange": "binance",
        "marketType": "spot",
        "symbol": "BTCUSDT",
        "interval": "1m",
    }


@pytest.mark.anyio
async def test_script_analysis_api_reports_exact_host_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(
        _analysis("indicator", "syminfo.tickerid", "timeframe.period", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    payload = await indicators_api.analyze_script(indicators_api.ScriptAnalysisRequest(
        runtime=PINE_COMPAT_RUNTIME_ID,
        script='indicator("Context")\nplot(close)',
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        interval="4h",
    ))

    assert payload["nativeExecutable"] is True
    assert payload["executable"] is True
    assert payload["meta"]["hostBindings"] == {
        "chartSymbol": "BINANCE:BTCUSDT.P",
        "chartTimeframe": "240",
    }


def test_pine_descriptor_fails_closed_on_installed_schema_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(_analysis("indicator", "plot"), _runtime_output())
    module.ANALYSIS_SCHEMA_VERSION = 4
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    descriptor = pine_adapter.PineCompatRuntimeAdapter().descriptor()

    assert descriptor.available is False
    assert descriptor.capabilities["installedAnalysisSchemaVersion"] == 4
    assert "analysis=4 (expected 5)" in (descriptor.reason or "")


def test_pine_descriptor_distinguishes_native_session_from_hosted_forming_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(_analysis("indicator", "plot"), _runtime_output())
    module.REALTIME_SESSION_SCHEMA_VERSION = 1
    module.create_realtime_session = lambda *_args, **_kwargs: None
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    descriptor = pine_adapter.PineCompatRuntimeAdapter().descriptor()

    assert descriptor.available is True
    assert descriptor.capabilities["formingBar"] is False
    assert descriptor.capabilities["incremental"] is False
    assert descriptor.capabilities["nativeRealtimeSession"] == {
        "available": True,
        "hosted": False,
        "schemaVersion": 1,
        "expectedSchemaVersion": 1,
    }


def test_pine_adapter_rejects_unmapped_native_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _FakePineModule(
        _analysis("indicator", "plot"),
        _runtime_output(labels=[{"id": 1, "snapshots": []}]),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Drawing")\nplot(close)',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.ok is False
    assert result.code == "PINE_HOST_OUTPUT_UNSUPPORTED"
    assert result.meta["unsupportedOutputCollections"] == ["labels"]


def test_pine_adapter_maps_native_plot_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    output = _runtime_output(plots=[{
        "id": 7,
        "values": [1.0, 2.0, 3.0],
        "colors": [0xFF0000, 0x00FF00, 0x0000FF],
        "title": "Histogram",
        "offset": -1,
        "showLast": 2,
        "display": "display.all",
        "forceOverlay": True,
        "lineWidth": 3,
        "style": "plot.style_columns",
        "trackPrice": True,
        "histBase": -1,
        "format": "format.percent",
        "precision": 3,
    }])
    module = _FakePineModule(_analysis("indicator", "plot"), output)
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Histogram", overlay=false)\nplot(close)',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.ok is True
    assert result.lines == [{
        "id": "pine-plot-7",
        "title": "Histogram",
        "type": "histogram",
        "color": "#00ff00",
        "lineWidth": 3,
        "pane": "main",
        "data": [
            {"time": _bars()[0]["time"], "value": 2.0, "color": "#00ff00"},
            {"time": _bars()[1]["time"], "value": 3.0, "color": "#0000ff"},
        ],
        "base": -1.0,
        "trackPrice": True,
        "visible": True,
        "colorData": [
            {"time": _bars()[0]["time"], "color": "#00ff00"},
            {"time": _bars()[1]["time"], "color": "#0000ff"},
        ],
        "priceFormat": "percent",
        "precision": 3,
    }]
    assert result.meta["renderMetadata"] == "pine-native"


def test_pine_adapter_maps_absolute_plotshape_and_marker_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _runtime_output(
        plotShapes=[{
            "id": 8,
            "values": [None, 2.25, None],
            "styles": [None, "shape.triangleup", None],
            "locations": [None, "location.absolute", None],
            "colors": [None, 0x00FF00, None],
            "texts": [None, "Buy", None],
            "textColors": [None, 0x00FF00, None],
            "sizes": [None, "size.large", None],
            "title": "Buy",
            "offset": 0,
            "showLast": None,
            "display": "display.all",
            "forceOverlay": True,
        }],
    )
    module = _FakePineModule(_analysis("indicator", "plotshape"), output)
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Shape")\nplotshape(close)',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.ok is True
    marker = result.output["markers"][0]
    assert marker["pane"] == "main"
    assert marker["title"] == "Buy"
    assert marker["data"] == [{
        "time": _bars()[1]["time"],
        "shape": "arrowUp",
        "color": "#00ff00",
        "text": "Buy",
        "position": "atPrice",
        "size": 4,
        "pane": "main",
        "value": 2.25,
    }]


def test_pine_adapter_maps_hline_fill_endpoints_and_dynamic_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _runtime_output(
        plots=[{
            "id": 2,
            "values": [1.0, 2.0, 3.0],
            "colors": [],
            "style": "plot.style_line",
            "title": "Line",
        }],
        hlines=[{
            "id": 3,
            "price": 2.5,
            "title": "Limit",
            "color": 0x787B86,
            "lineStyle": "hline.style_dotted",
            "lineWidth": 2,
        }],
        fills=[{
            "id": 4,
            "firstId": 2,
            "secondId": 3,
            "firstIsHLine": False,
            "secondIsHLine": True,
            "colors": [0xFF000080, (1 << 32) | 0x00FF0080, (1 << 32) | 0x00FF0080],
            "title": "Band",
            "fillGaps": False,
        }],
    )
    module = _FakePineModule(_analysis("indicator", "plot", "hline", "fill"), output)
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Fill")\np = plot(close)\nh = hline(2.5)\nfill(p, h)',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.ok is True
    assert result.output["hlines"][0]["linestyle"] == 1
    hidden = next(line for line in result.lines if line["id"] == "pine-hline-fill-3")
    assert hidden["visible"] is False
    fill = result.output["fills"][0]
    assert fill["plot1_id"] == "pine-plot-2"
    assert fill["plot2_id"] == "pine-hline-fill-3"
    assert fill["fillGaps"] is False
    assert [point["color"] for point in fill["colorData"]] == [
        "rgba(255,0,0,0.502)",
        "rgba(0,255,0,0.502)",
        "rgba(0,255,0,0.502)",
    ]


def test_pine_adapter_rejects_unknown_params_and_subsecond_time_collisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(_analysis("indicator", "input.int", "plot"), _runtime_output())
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    bad_param = pine_adapter.execute_pine_script(
        script='indicator("Input")\nlength = input.int(2)\nplot(close)',
        ohlcv=_bars(),
        params={"99": 2},
        executor_mode="inline",
    )
    millisecond_bars = _bars()[:2]
    millisecond_bars[0] = {**millisecond_bars[0], "time": 1_700_000_000_100}
    millisecond_bars[1] = {**millisecond_bars[1], "time": 1_700_000_000_900}
    bad_time = pine_adapter.execute_pine_script(
        script='indicator("Close")\nplot(close)',
        ohlcv=millisecond_bars,
        executor_mode="inline",
    )

    assert bad_param.code == "PINE_INVALID_PARAMS"
    assert bad_time.code == "PINE_INVALID_INPUT"
    assert "sub-second" in (bad_time.error or "")


def test_pine_adapter_rejects_unhosted_display_only_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(
        _analysis("indicator", "plot"),
        _runtime_output(plots=[{
            "id": 2,
            "values": [1.0, 2.0, 3.0],
            "display": "display.price_scale",
        }]),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Scale only")\nplot(close, display=display.price_scale)',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.code == "PINE_HOST_DISPLAY_UNSUPPORTED"
    assert "price_scale" in (result.error or "")
    assert module.run_calls


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("input.time", 1.5, "must be an integer"),
        ("input.color", 1.5, "must be a color integer or string"),
        ("input.color", -1, "must fit in u32"),
        ("input.source", "close", "cannot override input.source"),
    ],
)
def test_pine_adapter_rejects_invalid_typed_overrides_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: Any,
    message: str,
) -> None:
    analysis = _analysis("indicator", name, "plot")
    analysis["inputs"][0]["name"] = name
    module = _FakePineModule(analysis, _runtime_output())
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script=f'indicator("Input")\nvalue = {name}(close)\nplot(close)',
        ohlcv=_bars(),
        params={"1": value},
        executor_mode="inline",
    )

    assert result.code == "PINE_INVALID_PARAMS"
    assert message in (result.error or "")
    assert module.run_calls == []


def test_pine_adapter_fails_closed_for_unfaithful_marker_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(_analysis("indicator", "plotarrow"), _runtime_output())
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Arrow")\nplotarrow(close-open)',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.code == "PINE_HOST_CAPABILITY_UNSUPPORTED"
    assert result.meta["blockedFeatures"] == ["plotarrow"]


def test_range_meta_keeps_pine_runtime_in_script_identity() -> None:
    meta = indicators_api._build_range_meta(indicators_api.IndicatorRangeRequest(
        clientId="pine-1",
        kind="script",
        runtime=PINE_COMPAT_RUNTIME_ID,
        symbol="BTCUSDT",
        interval="1m",
        script='indicator("Close")\nplot(close)',
        securityMode="unsafe",
        start=1,
        end=2,
    ))

    assert meta["runtime"] == PINE_COMPAT_RUNTIME_ID
    assert meta["indicatorId"].startswith("script:pine-compat:")
    assert meta["securityMode"] is None
    assert "scriptMode" not in meta


def test_pine_range_execution_preserves_chart_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(
        _analysis("indicator", "syminfo.tickerid", "timeframe.period", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)
    monkeypatch.setattr(pine_adapter.config, "PINE_EXECUTOR_MODE", "inline")
    bars = [BarData.from_dict(item).with_closed_state(True) for item in _bars()]
    meta = {
        "kind": "script",
        "runtime": PINE_COMPAT_RUNTIME_ID,
        "exchange": "okx",
        "market_type": "futures",
        "symbol": "BTC-USDT-SWAP",
        "interval": "4h",
        "name": "Context",
        "script": 'indicator("Context")\nplot(close)',
        "params": {},
        "renderHints": {},
        "indicatorId": "context-1",
    }

    payload_api._compute_pine_range_patch_from_bars(
        "context-1",
        meta,
        bars[0].time,
        bars[-1].time,
        bars,
    )

    assert module.run_calls[0][3:] == ("OKX:BTC-USDT-SWAP", "240")


def test_custom_store_defaults_old_records_to_pyne_and_preserves_pine_updates(tmp_path) -> None:
    store = CustomIndicatorStore(tmp_path / "custom_indicators.json")
    legacy = store.upsert({"name": "Legacy", "script": "plot(close)"})
    pine = store.upsert({
        "name": "Pine",
        "runtime": PINE_COMPAT_RUNTIME_ID,
        "script": 'indicator("Close")\nplot(close)',
    })
    updated = store.upsert({"id": pine["id"], "description": "updated"})

    assert legacy["runtime"] == "pyne"
    assert updated["runtime"] == PINE_COMPAT_RUNTIME_ID
    assert updated["securityMode"] is None


@pytest.mark.anyio
async def test_compute_api_dispatches_explicit_pine_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(_analysis("indicator", "plot"), _runtime_output())
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)
    monkeypatch.setattr(indicators_api.config, "PINE_EXECUTOR_MODE", "inline")

    payload = await indicators_api.compute(indicators_api.ComputeRequest(
        mode="script",
        runtime=PINE_COMPAT_RUNTIME_ID,
        script='indicator("Close")\nplot(close)',
        ohlcv=_bars(),
        exchange="binance",
        market_type="futures",
        symbol="BTCUSDT",
        interval="1h",
    ))

    assert payload["ok"] is True
    assert payload["runtime"] == PINE_COMPAT_RUNTIME_ID
    assert payload["lines"][0]["id"] == "pine-plot-2"
    assert payload["meta"]["closedBarsOnly"] is True
    assert module.run_calls[0][3:] == ("BINANCE:BTCUSDT.P", "60")


@pytest.mark.anyio
async def test_pine_ws_subscription_is_closed_bar_only(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_snapshot(client_id: str, dm: Any, meta: dict[str, Any], bar_time: int = 0):
        del dm, bar_time
        return {
            "type": "indicator.snapshot",
            "clientId": client_id,
            "indicatorId": meta["indicatorId"],
            "runtime": PINE_COMPAT_RUNTIME_ID,
            "ok": True,
            "lines": [],
        }

    monkeypatch.setattr(stream_subscriptions, "_compute_pine_snapshot_message_async", fake_snapshot)

    class FakeDataManager:
        subscribe_kwargs: dict[str, Any] | None = None

        async def ensure_stream(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        def subscribe(self, **kwargs: Any) -> str:
            self.subscribe_kwargs = kwargs
            return "pine-handle"

    dm = FakeDataManager()
    sent: list[dict[str, Any]] = []

    async def send_json(payload: dict[str, Any]) -> bool:
        sent.append(payload)
        return True

    await stream_subscriptions.handle_pyne_indicator_subscribe(
        dm=dm,
        custom_handles={},
        custom_tasks={},
        queue=asyncio.Queue(),
        client_meta={},
        client_id="pine-ws",
        symbol="BTCUSDT",
        interval="1m",
        exchange="binance",
        market_type="spot",
        name="Pine Close",
        custom_id="",
        script='indicator("Close")\nplot(close)',
        params={},
        security_mode=None,
        runtime=PINE_COMPAT_RUNTIME_ID,
        history_limit=100,
        send_json=send_json,
        stream_consumer_id="pine-test",
        unsubscribe_client=lambda _client_id: asyncio.sleep(0),
        queue_message=lambda _queue, _message: None,
    )

    assert sent[0]["type"] == "indicator.subscribed"
    assert sent[0]["runtime"] == PINE_COMPAT_RUNTIME_ID
    assert sent[1]["type"] == "indicator.snapshot"
    assert dm.subscribe_kwargs is not None
    assert dm.subscribe_kwargs["event_types"] == {
        DataEventType.BAR_CLOSED,
        DataEventType.BAR_AMENDED,
        DataEventType.BACKFILL_COMPLETED,
    }


def test_pine_process_boundary_returns_structured_result() -> None:
    descriptor = pine_adapter.PineCompatRuntimeAdapter().descriptor()
    result = pine_adapter.execute_pine_script(
        script=(
            '//@version=6\nindicator("Close", overlay=true)\n'
            'matches = syminfo.tickerid == "BINANCE:BTCUSDT.P" and '
            'timeframe.period == "60"\nplot(matches ? close : 0)'
        ),
        ohlcv=_bars(),
        context=ScriptRuntimeContext("binance", "futures", "BTCUSDT", "1h"),
        executor_mode="process",
        timeout_seconds=10,
    )

    if descriptor.available:
        assert result.ok is True
        assert result.lines[0]["data"][-1]["time"] == _bars()[-1]["time"]
        assert result.lines[0]["data"][-1]["value"] == _bars()[-1]["close"]
        assert result.meta["hostBindings"]["chartTimeframe"] == "60"
    else:
        assert result.ok is False
        assert result.code == "PINE_RUNTIME_UNAVAILABLE"
