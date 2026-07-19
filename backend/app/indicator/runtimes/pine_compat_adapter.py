"""CandleScope adapter for the vendored ``pine-compat-runtime`` package.

The native module is optional at backend startup and mandatory only when a
Pine script is selected. Version-one execution is historical/closed-bar only.
Capabilities that need host context or renderers CandleScope cannot yet map are
rejected explicitly instead of being silently approximated.
"""
from __future__ import annotations

import importlib
from importlib import metadata as importlib_metadata
import math
import multiprocessing
import os
from pathlib import Path
import re
import sys
from typing import Any

from app.core import config

from .base import PINE_COMPAT_RUNTIME_ID, ScriptRuntimeDescriptor, ScriptRuntimeResult


PINE_ANALYSIS_SCHEMA_VERSION = 3
PINE_RUNTIME_SCHEMA_VERSION = 7
_PACKAGE_NAME = "pine-compat-runtime"
_MODULE_NAME = "pine_compat"
_VENDOR_ROOT = Path(__file__).resolve().parents[4] / "packages" / "pine-compat-runtime"
_PALETTE = (
    "#2962ff",
    "#f59e0b",
    "#10b981",
    "#ef4444",
    "#8b5cf6",
    "#06b6d4",
    "#ec4899",
    "#84cc16",
)
_HOST_BLOCKED_PREFIXES = (
    "strategy",
    "request.",
    "syminfo.",
    "timeframe.",
    "session.",
    "ticker.",
    "label.",
    "line.",
    "linefill.",
    "box.",
    "table.",
    "polyline.",
    "chart.point",
    "import",
    "library",
)
_HOST_BLOCKED_EXACT = {"plotbar", "plotcandle"}
_UNMAPPABLE_OUTPUT_KEYS = (
    "plotBars",
    "plotCandles",
    "labels",
    "lines",
    "lineFills",
    "polylines",
    "boxes",
    "tables",
    "strategy",
)


def _load_module() -> Any:
    override = os.getenv("CANDLESCOPE_PINE_COMPAT_RUNTIME_PATH", "").strip()
    if override:
        resolved = str(Path(override).resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)
    return importlib.import_module(_MODULE_NAME)


def _failure(
    code: str,
    message: str,
    *,
    line: int | None = None,
    column: int | None = None,
    hint: str | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> ScriptRuntimeResult:
    return ScriptRuntimeResult(
        ok=False,
        error=message,
        code=code,
        line=line,
        column=column,
        hint=hint,
        diagnostics=diagnostics or [],
        meta={"runtime": PINE_COMPAT_RUNTIME_ID, **(meta or {})},
    )


def _span_location(item: dict[str, Any]) -> tuple[int | None, int | None]:
    span = item.get("span") if isinstance(item.get("span"), dict) else {}
    line = span.get("line")
    column = span.get("column")
    return (
        int(line) if isinstance(line, int) else None,
        int(column) if isinstance(column, int) else None,
    )


def _feature_is_host_blocked(feature: str) -> bool:
    normalized = feature.strip().lower()
    return normalized in _HOST_BLOCKED_EXACT or any(
        normalized == prefix.rstrip(".") or normalized.startswith(prefix)
        for prefix in _HOST_BLOCKED_PREFIXES
    )


def _validate_analysis(analysis: dict[str, Any]) -> ScriptRuntimeResult | None:
    if analysis.get("schemaVersion") != PINE_ANALYSIS_SCHEMA_VERSION:
        return _failure(
            "PINE_SCHEMA_MISMATCH",
            "pine_compat analysis schema is incompatible with this CandleScope adapter",
            hint=(
                f"Expected analysis schema {PINE_ANALYSIS_SCHEMA_VERSION}; "
                f"received {analysis.get('schemaVersion')!r}."
            ),
        )

    diagnostics = [item for item in analysis.get("diagnostics") or [] if isinstance(item, dict)]
    errors = [item for item in diagnostics if str(item.get("severity", "")).lower() == "error"]
    if errors:
        first = errors[0]
        line, column = _span_location(first)
        return _failure(
            str(first.get("code") or "PINE_ANALYSIS_ERROR"),
            str(first.get("message") or "Pine analysis failed"),
            line=line,
            column=column,
            hint="请检查 Pine 语法、版本声明和报错位置。",
            diagnostics=diagnostics,
        )

    compatibility = analysis.get("compatibility")
    compatibility = compatibility if isinstance(compatibility, dict) else {}
    unsupported = [item for item in compatibility.get("unsupported") or [] if isinstance(item, dict)]
    if unsupported:
        first = unsupported[0]
        line, column = _span_location(first)
        features = [str(item.get("feature") or "unknown") for item in unsupported]
        return _failure(
            "PINE_UNSUPPORTED_FEATURE",
            f"pine_compat does not support: {', '.join(features)}",
            line=line,
            column=column,
            hint=str(first.get("reason") or "请改写脚本或等待解释器补齐该 Pine 能力。"),
            diagnostics=diagnostics,
            meta={"unsupportedFeatures": features},
        )

    supported = [item for item in compatibility.get("supported") or [] if isinstance(item, dict)]
    blocked = [item for item in supported if _feature_is_host_blocked(str(item.get("feature") or ""))]
    if blocked:
        first = blocked[0]
        line, column = _span_location(first)
        features = sorted({str(item.get("feature") or "unknown") for item in blocked})
        return _failure(
            "PINE_HOST_CAPABILITY_UNSUPPORTED",
            f"CandleScope Pine v1 does not host: {', '.join(features)}",
            line=line,
            column=column,
            hint="首版仅支持闭合 K 线上的指标计算；上下文请求、策略、imports 和原生绘图对象尚未接入。",
            diagnostics=diagnostics,
            meta={"blockedFeatures": features},
        )

    if not bool(analysis.get("executable")):
        return _failure(
            "PINE_NOT_EXECUTABLE",
            "Pine analysis did not produce an executable program",
            diagnostics=diagnostics,
        )
    return None


def analyze_pine_script_for_host(script: str) -> dict[str, Any]:
    """Return native analysis plus CandleScope's explicit v1 host boundary."""
    module = _load_module()
    analysis = dict(module.analyze_script(script))
    failure = _validate_analysis(analysis)
    analysis["runtime"] = PINE_COMPAT_RUNTIME_ID
    analysis["hostCompatibility"] = {
        "executable": failure is None,
        "closedBarsOnly": True,
        "error": failure.to_dict() if failure else None,
    }
    return analysis


def _normalize_bars(
    ohlcv: list[dict[str, Any]],
    *,
    max_bars: int,
) -> tuple[list[dict[str, Any]], list[int]] | ScriptRuntimeResult:
    if not isinstance(ohlcv, list):
        return _failure("PINE_INVALID_INPUT", "OHLCV input must be a list of bars")
    if len(ohlcv) > max_bars:
        return _failure(
            "PINE_INPUT_LIMIT_EXCEEDED",
            f"Too many Pine bars: {len(ohlcv)} > {max_bars}",
        )

    runtime_bars: list[dict[str, Any]] = []
    host_times: list[int] = []
    previous_runtime_time: int | None = None
    for index, bar in enumerate(ohlcv):
        if not isinstance(bar, dict):
            return _failure("PINE_INVALID_INPUT", f"OHLCV bar {index} must be an object")
        try:
            raw_time = bar["time"]
            if isinstance(raw_time, bool):
                raise TypeError("boolean time")
            numeric_time = float(raw_time)
            if not math.isfinite(numeric_time) or not numeric_time.is_integer():
                raise ValueError("non-integral time")
            timestamp = int(numeric_time)
            if abs(timestamp) < 100_000_000_000:
                host_time = timestamp
                runtime_time = timestamp * 1000
            else:
                runtime_time = timestamp
                host_time = timestamp // 1000
            values = {}
            for name in ("open", "high", "low", "close", "volume"):
                value = float(bar[name])
                if not math.isfinite(value):
                    raise ValueError(f"non-finite {name}")
                values[name] = value
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            return _failure(
                "PINE_INVALID_INPUT",
                f"Invalid OHLCV bar {index}: {exc}",
            )
        if previous_runtime_time is not None and runtime_time <= previous_runtime_time:
            relation = "duplicate" if runtime_time == previous_runtime_time else "unsorted"
            return _failure(
                "PINE_INVALID_INPUT",
                f"OHLCV bar times must be strictly increasing ({relation} time at index {index})",
            )
        previous_runtime_time = runtime_time
        runtime_bars.append({"time": runtime_time, **values})
        host_times.append(host_time)
    return runtime_bars, host_times


def _normalize_overrides(params: dict[str, Any] | None) -> dict[int, Any] | ScriptRuntimeResult:
    if params is None:
        return {}
    if not isinstance(params, dict):
        return _failure("PINE_INVALID_PARAMS", "Pine params must be an object")
    overrides: dict[int, Any] = {}
    for raw_key, value in params.items():
        if isinstance(raw_key, bool):
            return _failure("PINE_INVALID_PARAMS", "Pine parameter keys must be input callSiteId integers")
        try:
            key = int(raw_key)
        except (TypeError, ValueError):
            return _failure(
                "PINE_INVALID_PARAMS",
                f"Pine parameter key {raw_key!r} is not an input callSiteId integer",
            )
        if key < 0 or str(raw_key).strip() != str(key):
            return _failure(
                "PINE_INVALID_PARAMS",
                f"Pine parameter key {raw_key!r} is not a canonical input callSiteId",
            )
        if isinstance(value, float) and not math.isfinite(value):
            return _failure("PINE_INVALID_PARAMS", f"Pine parameter {key} must be finite")
        if not isinstance(value, (str, int, float, bool)):
            return _failure(
                "PINE_INVALID_PARAMS",
                f"Pine parameter {key} must be a string, number, or boolean",
            )
        overrides[key] = value
    return overrides


def _infer_pane(script: str, render_hints: dict[str, Any] | None) -> str:
    target = str((render_hints or {}).get("paneTarget") or "").strip().lower()
    if target in {"main", "overlay"}:
        return "main"
    if target in {"separate", "pane", "indicator"}:
        return "separate"
    declaration = re.search(r"\bindicator\s*\((.*?)\)", script, flags=re.IGNORECASE | re.DOTALL)
    if declaration and re.search(r"\boverlay\s*=\s*true\b", declaration.group(1), flags=re.IGNORECASE):
        return "main"
    return "separate"


def _css_color(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value:
        return value
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return fallback
    value &= 0xFFFFFFFF
    if value <= 0xFFFFFF:
        return f"#{value:06x}"
    red = (value >> 24) & 0xFF
    green = (value >> 16) & 0xFF
    blue = (value >> 8) & 0xFF
    alpha = (value & 0xFF) / 255
    return f"rgba({red},{green},{blue},{alpha:.3f})"


def _value_at(values: Any, index: int) -> Any:
    return values[index] if isinstance(values, list) and index < len(values) else None


def _is_active(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return math.isfinite(float(value)) and float(value) != 0.0
    return bool(value)


def _marker_position(value: Any) -> str:
    normalized = str(value or "abovebar").lower().removeprefix("location.")
    if normalized in {"belowbar", "bottom"}:
        return "below"
    if normalized in {"abovebar", "top"}:
        return "above"
    return "inBar"


def _input_type(name: str) -> str:
    return {
        "input.int": "int",
        "input.float": "float",
        "input.bool": "bool",
        "input.string": "string",
        "input.color": "color",
        "input.source": "source",
        "input.timeframe": "timeframe",
        "input.symbol": "symbol",
        "input.session": "session",
        "input.time": "time",
        "input.price": "float",
        "input.text_area": "string",
    }.get(name, "string")


def _param_schema(analysis: dict[str, Any], overrides: dict[int, Any]) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = []
    for raw in analysis.get("inputs") or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("callSiteId"), int):
            continue
        call_site_id = int(raw["callSiteId"])
        name = str(raw.get("name") or "input")
        title = str(raw.get("title") or f"Input {call_site_id}")
        item: dict[str, Any] = {
            "id": str(call_site_id),
            "key": str(call_site_id),
            "callSiteId": call_site_id,
            "type": _input_type(name),
            "title": title,
            "label": title,
            "pineInput": name,
        }
        if call_site_id in overrides:
            item["current"] = overrides[call_site_id]
        schema.append(item)
    return schema


def _normalize_output(
    raw: dict[str, Any],
    *,
    script: str,
    host_times: list[int],
    analysis: dict[str, Any],
    overrides: dict[int, Any],
    render_hints: dict[str, Any] | None,
    max_output_series: int,
    max_output_points: int,
) -> ScriptRuntimeResult:
    if raw.get("schemaVersion") != PINE_RUNTIME_SCHEMA_VERSION:
        return _failure(
            "PINE_SCHEMA_MISMATCH",
            "pine_compat runtime schema is incompatible with this CandleScope adapter",
            hint=f"Expected runtime schema {PINE_RUNTIME_SCHEMA_VERSION}; received {raw.get('schemaVersion')!r}.",
        )
    unsupported_outputs = [key for key in _UNMAPPABLE_OUTPUT_KEYS if raw.get(key)]
    if unsupported_outputs:
        return _failure(
            "PINE_HOST_OUTPUT_UNSUPPORTED",
            f"CandleScope Pine v1 cannot render output collections: {', '.join(unsupported_outputs)}",
            hint="请暂时改用 plot/plotshape/plotchar/plotarrow、hline、fill、bgcolor、barcolor 或 alert。",
            meta={"unsupportedOutputCollections": unsupported_outputs},
        )
    runtime_diagnostics = [item for item in raw.get("diagnostics") or [] if isinstance(item, dict)]
    if runtime_diagnostics:
        first = runtime_diagnostics[0]
        return _failure(
            str(first.get("code") or "PINE_RUNTIME_DIAGNOSTIC"),
            str(first.get("message") or "Pine runtime reported a diagnostic"),
            diagnostics=runtime_diagnostics,
        )

    pane = _infer_pane(script, render_hints)
    lines: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    bgcolors: list[dict[str, Any]] = []
    barcolors: list[dict[str, Any]] = []
    hlines: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    for plot_index, plot in enumerate(raw.get("plots") or []):
        if not isinstance(plot, dict):
            continue
        plot_id = plot.get("id", plot_index)
        color = _PALETTE[plot_index % len(_PALETTE)]
        data = [
            {"time": host_times[index], "value": value}
            for index, value in enumerate(plot.get("values") or [])
            if index < len(host_times)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ]
        lines.append({
            "id": f"pine-plot-{plot_id}",
            "title": f"Plot {plot_id}",
            "type": "line",
            "color": color,
            "lineWidth": 2,
            "pane": pane,
            "data": data,
        })

    def add_marker_series(item: dict[str, Any], kind: str, series_index: int) -> None:
        values = item.get("values") or []
        points: list[dict[str, Any]] = []
        default_color = _PALETTE[(len(lines) + series_index) % len(_PALETTE)]
        for index, value in enumerate(values):
            location_value = _value_at(item.get("locations"), index) if kind == "plotshape" else None
            absolute_location = str(location_value or "").lower().endswith("absolute")
            active = (
                value is not None
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ) if absolute_location else _is_active(value)
            if index >= len(host_times) or not active:
                continue
            if kind == "plotchar":
                shape = "text"
                text = str(_value_at(item.get("chars"), index) or "•")
                position = "above"
                color_value = _value_at(item.get("colors"), index)
                size = "normal"
            elif kind == "plotshape":
                shape = str(_value_at(item.get("styles"), index) or "circle").removeprefix("shape.")
                text = str(_value_at(item.get("texts"), index) or "")
                position = _marker_position(location_value)
                color_value = _value_at(item.get("colors"), index)
                size = str(_value_at(item.get("sizes"), index) or "normal").removeprefix("size.")
            else:
                up = float(value) > 0 if isinstance(value, (int, float)) else True
                shape = "arrowUp" if up else "arrowDown"
                text = ""
                position = "below" if up else "above"
                color_value = _value_at(item.get("colorUps" if up else "colorDowns"), index)
                size = "normal"
            point = {
                "time": host_times[index],
                "shape": shape,
                "color": _css_color(color_value, default_color),
                "text": text,
                "position": position,
                "size": size,
                "pane": pane,
            }
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                point["value"] = value
            points.append(point)
        if points:
            first = points[0]
            markers.append({
                "id": f"pine-{kind}-{item.get('id', series_index)}",
                "title": f"{kind} {item.get('id', series_index)}",
                "shape": first["shape"],
                "color": first["color"],
                "text": first["text"],
                "position": first["position"],
                "size": first["size"],
                "pane": pane,
                "data": points,
            })

    for index, item in enumerate(raw.get("plotChars") or []):
        if isinstance(item, dict):
            add_marker_series(item, "plotchar", index)
    for index, item in enumerate(raw.get("plotShapes") or []):
        if isinstance(item, dict):
            add_marker_series(item, "plotshape", index)
    for index, item in enumerate(raw.get("plotArrows") or []):
        if isinstance(item, dict):
            add_marker_series(item, "plotarrow", index)

    for index, item in enumerate(raw.get("bgColors") or []):
        if not isinstance(item, dict):
            continue
        regions = [
            {"time": host_times[i], "color": _css_color(value, "rgba(59,130,246,0.1)")}
            for i, value in enumerate(item.get("values") or [])
            if i < len(host_times) and value is not None
        ]
        if regions:
            bgcolors.append({
                "id": f"pine-bgcolor-{item.get('id', index)}",
                "title": f"Background {item.get('id', index)}",
                "color": regions[0]["color"],
                "pane": pane,
                "regions": regions,
            })
    for index, item in enumerate(raw.get("barColors") or []):
        if not isinstance(item, dict):
            continue
        data = [
            {"time": host_times[i], "color": _css_color(value, "#787b86")}
            for i, value in enumerate(item.get("values") or [])
            if i < len(host_times) and value is not None
        ]
        if data:
            barcolors.append({"id": f"pine-barcolor-{item.get('id', index)}", "data": data})
    for index, item in enumerate(raw.get("hlines") or []):
        if not isinstance(item, dict) or not isinstance(item.get("price"), (int, float)):
            continue
        hlines.append({
            "id": f"pine-hline-{item.get('id', index)}",
            "price": item["price"],
            "title": f"HLine {item.get('id', index)}",
            "color": "#787b86",
            "linestyle": "dashed",
            "linewidth": 1,
            "pane": pane,
        })
    for index, item in enumerate(raw.get("fills") or []):
        if not isinstance(item, dict):
            continue
        fills.append({
            "id": f"pine-fill-{item.get('id', index)}",
            "plot1_id": f"pine-plot-{item.get('firstId')}",
            "plot2_id": f"pine-plot-{item.get('secondId')}",
            "title": f"Fill {item.get('id', index)}",
            "color": "rgba(59,130,246,0.12)",
            "pane": pane,
        })
    for index, alert in enumerate(raw.get("alerts") or []):
        if not isinstance(alert, dict):
            continue
        bar_index = alert.get("barIndex")
        event_time = (
            host_times[bar_index]
            if isinstance(bar_index, int) and 0 <= bar_index < len(host_times)
            else int(alert.get("time") or 0) // 1000
        )
        message = str(alert.get("message") or "Pine alert")
        signals.append({
            "id": f"pine-alert-{alert.get('id', index)}-{index}",
            "name": str(alert.get("source") or "alert"),
            "side": "alert",
            "message": message,
            "pane": pane,
            "data": [{"time": event_time, "side": "alert", "name": "alert", "message": message}],
        })

    series_count = sum(map(len, (lines, markers, bgcolors, barcolors, hlines, fills, signals)))
    point_count = (
        sum(len(item.get("data") or []) for item in lines)
        + sum(len(item.get("data") or []) for item in markers)
        + sum(len(item.get("regions") or []) for item in bgcolors)
        + sum(len(item.get("data") or []) for item in barcolors)
        + len(hlines)
        + len(fills)
        + sum(len(item.get("data") or []) for item in signals)
    )
    if series_count > max_output_series or point_count > max_output_points:
        return _failure(
            "PINE_OUTPUT_LIMIT_EXCEEDED",
            (
                f"Pine output exceeds limits: series={series_count}/{max_output_series}, "
                f"points={point_count}/{max_output_points}"
            ),
        )

    output: dict[str, Any] = {}
    for key, value in (
        ("markers", markers),
        ("hlines", hlines),
        ("fills", fills),
        ("bgcolors", bgcolors),
        ("barcolors", barcolors),
        ("signals", signals),
    ):
        if value:
            output[key] = value
    supported = [
        str(item.get("feature"))
        for item in (analysis.get("compatibility") or {}).get("supported", [])
        if isinstance(item, dict) and item.get("feature")
    ]
    return ScriptRuntimeResult(
        ok=True,
        lines=lines,
        output=output,
        param_schema=_param_schema(analysis, overrides),
        diagnostics=[item for item in analysis.get("diagnostics") or [] if isinstance(item, dict)],
        meta={
            "runtime": PINE_COMPAT_RUNTIME_ID,
            "runtimeSchemaVersion": PINE_RUNTIME_SCHEMA_VERSION,
            "analysisSchemaVersion": PINE_ANALYSIS_SCHEMA_VERSION,
            "languageVersion": analysis.get("languageVersion"),
            "closedBarsOnly": True,
            "pane": pane,
            "renderMetadata": "host-defaults",
            "supportedFeatures": supported,
            "outputSeries": series_count,
            "outputPoints": point_count,
        },
    )


def _execute_payload(payload: dict[str, Any]) -> ScriptRuntimeResult:
    try:
        module = _load_module()
    except Exception as exc:
        return _failure(
            "PINE_RUNTIME_UNAVAILABLE",
            f"Pine runtime is not installed for this backend: {exc}",
            hint="请为后端 Python 构建并安装 packages/pine-compat-runtime 的本机 wheel。",
            meta={"vendorSourcePath": str(_VENDOR_ROOT)},
        )
    try:
        script = str(payload.get("script") or "")
        if not script.strip():
            return _failure("PINE_SCRIPT_REQUIRED", "Pine script is required")
        analysis = dict(module.analyze_script(script))
        failure = _validate_analysis(analysis)
        if failure:
            return failure
        bars = _normalize_bars(payload.get("ohlcv"), max_bars=max(int(payload["max_bars"]), 1))
        if isinstance(bars, ScriptRuntimeResult):
            return bars
        runtime_bars, host_times = bars
        overrides = _normalize_overrides(payload.get("params"))
        if isinstance(overrides, ScriptRuntimeResult):
            return overrides
        raw = dict(module.run_script(script, runtime_bars, input_overrides=overrides))
        return _normalize_output(
            raw,
            script=script,
            host_times=host_times,
            analysis=analysis,
            overrides=overrides,
            render_hints=payload.get("render_hints"),
            max_output_series=max(int(payload["max_output_series"]), 1),
            max_output_points=max(int(payload["max_output_points"]), 1),
        )
    except Exception as exc:
        return _failure(
            "PINE_RUNTIME_ERROR",
            str(exc) or exc.__class__.__name__,
            hint="Pine 执行失败；请先查看分析诊断，再缩小脚本定位运行期错误。",
        )


def _process_worker(sender: Any, payload: dict[str, Any]) -> None:
    try:
        sender.send(_execute_payload(payload).to_dict())
    except BaseException as exc:  # pragma: no cover - final child-process guard
        sender.send(_failure("PINE_PROCESS_FAILED", str(exc) or exc.__class__.__name__).to_dict())
    finally:
        sender.close()


def _terminate_process(process: multiprocessing.Process, grace_seconds: float) -> None:
    if not process.is_alive():
        return
    process.terminate()
    process.join(max(grace_seconds, 0.0))
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(max(grace_seconds, 0.0))


def execute_pine_script(
    *,
    script: str,
    ohlcv: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
    render_hints: dict[str, Any] | None = None,
    executor_mode: str | None = None,
    timeout_seconds: float | None = None,
) -> ScriptRuntimeResult:
    payload = {
        "script": script,
        "ohlcv": ohlcv,
        "params": params or {},
        "render_hints": render_hints or {},
        "max_bars": max(int(config.PINE_MAX_BARS), 1),
        "max_output_series": max(int(config.PINE_MAX_OUTPUT_SERIES), 1),
        "max_output_points": max(int(config.PINE_MAX_OUTPUT_POINTS), 1),
    }
    mode = str(executor_mode or config.PINE_EXECUTOR_MODE).strip().lower()
    if mode == "inline":
        return _execute_payload(payload)
    if mode != "process":
        return _failure("PINE_EXECUTOR_INVALID", f"Unknown Pine executor mode: {mode}")

    timeout = max(
        float(config.PINE_EXEC_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds),
        0.0,
    )
    grace = max(float(config.PINE_PROCESS_GRACE_SECONDS), 0.0)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_process_worker, args=(sender, payload), daemon=True)
    try:
        process.start()
        sender.close()
        if not receiver.poll(timeout):
            _terminate_process(process, grace)
            return _failure(
                "PINE_TIMEOUT",
                f"Pine execution exceeded {timeout:g} seconds",
                hint="请减少循环、缩小窗口，或调整 PINE_EXEC_TIMEOUT_SECONDS。",
            )
        try:
            value = receiver.recv()
        except EOFError:
            value = None
        process.join(grace)
        if process.is_alive():
            _terminate_process(process, grace)
        if not isinstance(value, dict):
            return _failure("PINE_PROCESS_FAILED", "Pine worker exited without a result")
        return ScriptRuntimeResult.from_dict(value)
    except Exception as exc:
        _terminate_process(process, grace)
        return _failure("PINE_PROCESS_FAILED", str(exc) or exc.__class__.__name__)
    finally:
        receiver.close()
        if not sender.closed:
            sender.close()


class PineCompatRuntimeAdapter:
    runtime_id = PINE_COMPAT_RUNTIME_ID

    def execute(
        self,
        *,
        script: str,
        ohlcv: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
        security_mode: str | None = None,
        render_hints: dict[str, Any] | None = None,
    ) -> ScriptRuntimeResult:
        del security_mode
        return execute_pine_script(
            script=script,
            ohlcv=ohlcv,
            params=params,
            render_hints=render_hints,
        )

    def analyze(self, script: str) -> dict[str, Any]:
        return analyze_pine_script_for_host(script)

    def descriptor(self) -> ScriptRuntimeDescriptor:
        try:
            module = _load_module()
            source_path = str(getattr(module, "__file__", "") or "") or None
            try:
                version = importlib_metadata.version(_PACKAGE_NAME)
            except importlib_metadata.PackageNotFoundError:
                version = getattr(module, "__version__", None)
            available = True
            reason = None
        except Exception as exc:
            source_path = str(_VENDOR_ROOT)
            version = None
            available = False
            reason = str(exc)
        return ScriptRuntimeDescriptor(
            id=self.runtime_id,
            label="Pine-compatible",
            language="pine",
            package=_PACKAGE_NAME,
            available=available,
            version=version,
            source_path=source_path,
            reason=reason,
            capabilities={
                "historical": True,
                "closedBarsOnly": True,
                "formingBar": False,
                "incremental": False,
                "analysisSchemaVersion": PINE_ANALYSIS_SCHEMA_VERSION,
                "runtimeSchemaVersion": PINE_RUNTIME_SCHEMA_VERSION,
                "hostedOutputs": [
                    "plot",
                    "plotchar",
                    "plotshape",
                    "plotarrow",
                    "hline",
                    "fill",
                    "bgcolor",
                    "barcolor",
                    "alert",
                ],
                "blockedFamilies": [
                    "request",
                    "strategy",
                    "chart-context",
                    "imports",
                    "drawing-objects",
                    "plotbar",
                    "plotcandle",
                ],
            },
        )
