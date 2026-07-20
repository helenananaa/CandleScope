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


PINE_ANALYSIS_SCHEMA_VERSION = 5
PINE_RUNTIME_SCHEMA_VERSION = 8
PINE_RENDER_METADATA_VERSION = 1
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
_HOST_BLOCKED_EXACT = {"plotbar", "plotcandle", "plotchar", "plotarrow"}
_UNMAPPABLE_OUTPUT_KEYS = (
    "plotChars",
    "plotArrows",
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
    previous_host_time: int | None = None
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
            if timestamp <= 0:
                raise ValueError("non-positive time")
            if timestamp < 100_000_000_000:
                host_time = timestamp
                runtime_time = timestamp * 1000
            else:
                if timestamp >= 10_000_000_000_000:
                    raise ValueError("unsupported timestamp unit; expected seconds or milliseconds")
                if timestamp % 1000 != 0:
                    raise ValueError("sub-second timestamps are not supported")
                runtime_time = timestamp
                host_time = timestamp // 1000
            values = {}
            for name in ("open", "high", "low", "close", "volume"):
                if isinstance(bar[name], bool):
                    raise TypeError(f"boolean {name}")
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
        if previous_host_time is not None and host_time <= previous_host_time:
            return _failure(
                "PINE_INVALID_INPUT",
                (
                    "OHLCV timestamps collapse to duplicate CandleScope seconds "
                    f"at index {index}; sub-second bars are not supported"
                ),
            )
        if values["high"] < max(values["open"], values["low"], values["close"]):
            return _failure("PINE_INVALID_INPUT", f"OHLCV bar {index} has an invalid high")
        if values["low"] > min(values["open"], values["high"], values["close"]):
            return _failure("PINE_INVALID_INPUT", f"OHLCV bar {index} has an invalid low")
        if values["volume"] < 0:
            return _failure("PINE_INVALID_INPUT", f"OHLCV bar {index} has negative volume")
        previous_runtime_time = runtime_time
        previous_host_time = host_time
        runtime_bars.append({"time": runtime_time, **values})
        host_times.append(host_time)
    return runtime_bars, host_times


def _normalize_overrides(
    params: dict[str, Any] | None,
    analysis: dict[str, Any],
) -> dict[int, Any] | ScriptRuntimeResult:
    if params is None:
        return {}
    if not isinstance(params, dict):
        return _failure("PINE_INVALID_PARAMS", "Pine params must be an object")
    inputs = {
        int(item["callSiteId"]): item
        for item in analysis.get("inputs") or []
        if isinstance(item, dict) and isinstance(item.get("callSiteId"), int)
    }
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
        if key not in inputs:
            return _failure(
                "PINE_INVALID_PARAMS",
                f"Pine parameter {key} does not match an input in this script",
            )
        if isinstance(value, float) and not math.isfinite(value):
            return _failure("PINE_INVALID_PARAMS", f"Pine parameter {key} must be finite")
        if not isinstance(value, (str, int, float, bool)):
            return _failure(
                "PINE_INVALID_PARAMS",
                f"Pine parameter {key} must be a string, number, or boolean",
            )
        input_spec = inputs[key]
        input_name = str(input_spec.get("name") or "input")
        if input_name in {"input.int", "input.time"} and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            return _failure("PINE_INVALID_PARAMS", f"Pine parameter {key} must be an integer")
        if input_name in {"input.float", "input.price"} and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            return _failure("PINE_INVALID_PARAMS", f"Pine parameter {key} must be numeric")
        if input_name == "input.bool" and not isinstance(value, bool):
            return _failure("PINE_INVALID_PARAMS", f"Pine parameter {key} must be boolean")
        if input_name == "input.color" and (
            isinstance(value, bool) or not isinstance(value, (int, str))
        ):
            return _failure(
                "PINE_INVALID_PARAMS",
                f"Pine parameter {key} must be a color integer or string",
            )
        if input_name == "input.color" and isinstance(value, int) and not 0 <= value <= 0xFFFFFFFF:
            return _failure(
                "PINE_INVALID_PARAMS",
                f"Pine parameter {key} color integer must fit in u32",
            )
        if input_name == "input.source":
            return _failure(
                "PINE_INVALID_PARAMS",
                f"Pine parameter {key} cannot override input.source in this host",
            )
        if input_name in {
            "input.string",
            "input.symbol",
            "input.timeframe",
            "input.session",
            "input.text_area",
            "input.source",
        } and not isinstance(value, str):
            return _failure("PINE_INVALID_PARAMS", f"Pine parameter {key} must be a string")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = input_spec.get("min")
            maximum = input_spec.get("max")
            if isinstance(minimum, (int, float)) and value < minimum:
                return _failure("PINE_INVALID_PARAMS", f"Pine parameter {key} is below its minimum")
            if isinstance(maximum, (int, float)) and value > maximum:
                return _failure("PINE_INVALID_PARAMS", f"Pine parameter {key} is above its maximum")
        options = input_spec.get("options")
        if isinstance(options, list) and options and value not in options:
            return _failure("PINE_INVALID_PARAMS", f"Pine parameter {key} is not one of its options")
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
    has_alpha_flag = bool(value & (1 << 32))
    payload = value & 0xFFFFFFFF
    if not has_alpha_flag and payload <= 0xFFFFFF:
        return f"#{payload:06x}"
    red = (payload >> 24) & 0xFF
    green = (payload >> 16) & 0xFF
    blue = (payload >> 8) & 0xFF
    alpha = (payload & 0xFF) / 255
    return f"rgba({red},{green},{blue},{alpha:.3f})"


def _value_at(values: Any, index: int) -> Any:
    return values[index] if isinstance(values, list) and index < len(values) else None


def _is_active(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return math.isfinite(float(value)) and float(value) != 0.0
    return bool(value)


def _marker_position(value: Any) -> str | None:
    normalized = str(value or "abovebar").lower().removeprefix("location.")
    if normalized in {"belowbar", "bottom"}:
        return "below"
    if normalized in {"abovebar", "top"}:
        return "above"
    return None


_PANE_DISPLAYS = {"display.all", "display.pane"}
_HIDDEN_DISPLAYS = {"display.none"}
_UNSUPPORTED_DISPLAYS = {
    "display.data_window",
    "display.price_scale",
    "display.status_line",
}


def _render_settings(
    item: dict[str, Any],
    *,
    base_pane: str,
    fallback_title: str,
) -> dict[str, Any] | ScriptRuntimeResult:
    raw_offset = item.get("offset", 0)
    raw_show_last = item.get("showLast")
    if isinstance(raw_offset, bool) or not isinstance(raw_offset, int):
        return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"{fallback_title} has an invalid offset")
    if raw_show_last is not None and (
        isinstance(raw_show_last, bool) or not isinstance(raw_show_last, int) or raw_show_last < 0
    ):
        return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"{fallback_title} has an invalid show_last")
    display = str(item.get("display") or "display.all").lower()
    if display in _UNSUPPORTED_DISPLAYS:
        return _failure(
            "PINE_HOST_DISPLAY_UNSUPPORTED",
            f"CandleScope cannot faithfully host Pine display mode {display!r}",
        )
    if display not in _PANE_DISPLAYS | _HIDDEN_DISPLAYS:
        return _failure(
            "PINE_HOST_DISPLAY_UNSUPPORTED",
            f"CandleScope cannot map Pine display mode {display!r}",
        )
    force_overlay = item.get("forceOverlay", False)
    if not isinstance(force_overlay, bool):
        return _failure(
            "PINE_RUNTIME_OUTPUT_INVALID",
            f"{fallback_title} has an invalid force_overlay value",
        )
    title = item.get("title")
    if title is None or title == "":
        title = fallback_title
    elif not isinstance(title, str):
        return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"{fallback_title} has an invalid title")
    return {
        "offset": raw_offset,
        "showLast": raw_show_last,
        "paneVisible": display in _PANE_DISPLAYS,
        "pane": "main" if force_overlay else base_pane,
        "title": title,
    }


def _visible_source_index(index: int, total: int, show_last: int | None) -> bool:
    return show_last is None or index >= max(total - show_last, 0)


def _target_time(host_times: list[int], index: int, offset: int) -> int | None:
    target = index + offset
    return host_times[target] if 0 <= target < len(host_times) else None


def _pine_line_style(value: Any) -> int | ScriptRuntimeResult:
    normalized = str(value or "hline.style_solid").lower()
    styles = {
        "hline.style_solid": 0,
        "hline.style_dotted": 1,
        "hline.style_dashed": 2,
    }
    if normalized not in styles:
        return _failure("PINE_HOST_RENDER_STYLE_UNSUPPORTED", f"Unsupported hline style: {normalized}")
    return styles[normalized]


def _marker_size(value: Any) -> int | None:
    normalized = str(value or "size.auto").lower().removeprefix("size.")
    return {
        "tiny": 1,
        "small": 2,
        "normal": 3,
        "large": 4,
        "huge": 5,
        "auto": 2,
    }.get(normalized)


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
        for source_key, target_key in (
            ("default", "default"),
            ("min", "min"),
            ("max", "max"),
            ("step", "step"),
            ("options", "options"),
        ):
            if raw.get(source_key) is not None:
                item[target_key] = raw[source_key]
        if call_site_id in overrides:
            item["current"] = overrides[call_site_id]
        elif raw.get("default") is not None:
            item["current"] = raw["default"]
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
    native_render_metadata = raw.get("renderMetadataVersion") == PINE_RENDER_METADATA_VERSION
    unsupported_outputs = [key for key in _UNMAPPABLE_OUTPUT_KEYS if raw.get(key)]
    if unsupported_outputs:
        return _failure(
            "PINE_HOST_OUTPUT_UNSUPPORTED",
            f"CandleScope Pine v1 cannot render output collections: {', '.join(unsupported_outputs)}",
            hint="请暂时改用 plot、受支持样式的 plotshape、hline、fill、bgcolor、barcolor 或 alert。",
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
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", "Pine plot output must be an object")
        plot_id = plot.get("id", plot_index)
        settings = _render_settings(
            plot,
            base_pane=pane,
            fallback_title=f"Plot {plot_id}",
        )
        if isinstance(settings, ScriptRuntimeResult):
            return settings
        style = str(plot.get("style") or "plot.style_line").lower()
        if style == "plot.style_line":
            series_type = "line"
        elif style in {"plot.style_histogram", "plot.style_columns"}:
            series_type = "histogram"
        else:
            return _failure(
                "PINE_HOST_RENDER_STYLE_UNSUPPORTED",
                f"CandleScope cannot faithfully render {style}",
                hint="目前 plot 仅托管 plot.style_line、plot.style_histogram 和 plot.style_columns。",
                meta={"plotId": plot_id, "plotStyle": style},
            )
        line_width = plot.get("lineWidth", 1)
        if isinstance(line_width, bool) or not isinstance(line_width, int) or line_width <= 0:
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Plot {plot_id} has an invalid linewidth")
        hist_base = plot.get("histBase", 0)
        if isinstance(hist_base, bool) or not isinstance(hist_base, (int, float)) or not math.isfinite(float(hist_base)):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Plot {plot_id} has an invalid histbase")
        track_price = plot.get("trackPrice", False)
        if not isinstance(track_price, bool):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Plot {plot_id} has invalid trackprice")
        precision = plot.get("precision")
        if precision is not None and (
            isinstance(precision, bool) or not isinstance(precision, int) or precision < 0 or precision > 16
        ):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Plot {plot_id} has invalid precision")
        values = plot.get("values") or []
        if not isinstance(values, list):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Plot {plot_id} values must be a list")
        colors = plot.get("colors") or []
        if not isinstance(colors, list):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Plot {plot_id} colors must be a list")
        default_color = _PALETTE[plot_index % len(_PALETTE)]
        has_default_color = False
        data: list[dict[str, Any]] = []
        color_data: list[dict[str, Any]] = []
        for index, value in enumerate(values):
            if index >= len(host_times) or not _visible_source_index(index, len(host_times), settings["showLast"]):
                continue
            target_time = _target_time(host_times, index, settings["offset"])
            if target_time is None:
                continue
            if not (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ):
                continue
            point: dict[str, Any] = {"time": target_time, "value": value}
            color_value = _value_at(colors, index)
            if color_value is not None:
                point_color = _css_color(color_value, default_color)
                point["color"] = point_color
                color_data.append({"time": target_time, "color": point_color})
                if not has_default_color:
                    default_color = point_color
                    has_default_color = True
            data.append(point)
        line: dict[str, Any] = {
            "id": f"pine-plot-{plot_id}",
            "title": settings["title"],
            "type": series_type,
            "color": default_color,
            "lineWidth": line_width,
            "pane": settings["pane"],
            "data": data,
            "base": float(hist_base),
            "trackPrice": track_price,
            "visible": settings["paneVisible"],
        }
        if color_data:
            line["colorData"] = color_data
        pine_format = str(plot.get("format") or "format.inherit").lower().removeprefix("format.")
        if pine_format not in {"inherit", "price", "volume", "percent"}:
            return _failure("PINE_HOST_FORMAT_UNSUPPORTED", f"Unsupported Pine plot format: {pine_format}")
        if pine_format != "inherit":
            line["priceFormat"] = pine_format
        if precision is not None:
            line["precision"] = precision
        lines.append(line)

    def add_marker_series(
        item: dict[str, Any],
        kind: str,
        series_index: int,
    ) -> ScriptRuntimeResult | None:
        marker_id = item.get("id", series_index)
        settings = _render_settings(
            item,
            base_pane=pane,
            fallback_title=f"{kind} {marker_id}",
        )
        if isinstance(settings, ScriptRuntimeResult):
            return settings
        if not settings["paneVisible"]:
            return None
        values = item.get("values") or []
        if not isinstance(values, list):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"{kind} {marker_id} values must be a list")
        points: list[dict[str, Any]] = []
        default_color = _PALETTE[(len(lines) + series_index) % len(_PALETTE)]
        for index, value in enumerate(values):
            if index >= len(host_times) or not _visible_source_index(index, len(host_times), settings["showLast"]):
                continue
            target_time = _target_time(host_times, index, settings["offset"])
            if target_time is None:
                continue
            location_value = _value_at(item.get("locations"), index)
            absolute_location = str(location_value or "").lower().endswith("absolute")
            active = (
                value is not None
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ) if absolute_location else _is_active(value)
            if not active:
                continue
            shape = str(_value_at(item.get("styles"), index) or "shape.xcross").lower().removeprefix("shape.")
            shape_map = {
                "circle": "circle",
                "square": "square",
                "triangleup": "arrowUp",
                "triangledown": "arrowDown",
                "arrowup": "arrowUp",
                "arrowdown": "arrowDown",
            }
            if shape not in shape_map:
                return _failure(
                    "PINE_HOST_RENDER_STYLE_UNSUPPORTED",
                    f"CandleScope cannot faithfully render plotshape style {shape!r}",
                    hint="目前 plotshape 仅托管 circle、square、triangleup/down 和 arrowup/down。",
                    meta={"markerId": marker_id, "markerStyle": shape},
                )
            text = str(_value_at(item.get("texts"), index) or "")
            position = "atPrice" if absolute_location else _marker_position(location_value)
            if position is None:
                return _failure(
                    "PINE_HOST_RENDER_STYLE_UNSUPPORTED",
                    f"CandleScope cannot faithfully render plotshape location {location_value!r}",
                    meta={"markerId": marker_id},
                )
            color_value = _value_at(item.get("colors"), index)
            point_color = _css_color(color_value, default_color)
            text_color_value = _value_at(item.get("textColors"), index)
            if text and text_color_value is not None:
                text_color = _css_color(text_color_value, point_color)
                if text_color != point_color:
                    return _failure(
                        "PINE_HOST_RENDER_STYLE_UNSUPPORTED",
                        "CandleScope markers cannot use a text color different from the shape color",
                        meta={"markerId": marker_id},
                    )
            size_value = _value_at(item.get("sizes"), index)
            size = _marker_size(size_value)
            if size is None:
                return _failure(
                    "PINE_HOST_RENDER_STYLE_UNSUPPORTED",
                    f"CandleScope cannot faithfully render plotshape size {size_value!r}",
                    meta={"markerId": marker_id},
                )
            point = {
                "time": target_time,
                "shape": shape_map[shape],
                "color": point_color,
                "text": text,
                "position": position,
                "size": size,
                "pane": settings["pane"],
            }
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                point["value"] = value
            points.append(point)
        if points:
            first = points[0]
            markers.append({
                "id": f"pine-{kind}-{item.get('id', series_index)}",
                "title": settings["title"],
                "shape": first["shape"],
                "color": first["color"],
                "text": first["text"],
                "position": first["position"],
                "size": first["size"],
                "pane": settings["pane"],
                "data": points,
            })
        return None

    for index, item in enumerate(raw.get("plotShapes") or []):
        if not isinstance(item, dict):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", "Pine plotshape output must be an object")
        marker_failure = add_marker_series(item, "plotshape", index)
        if marker_failure:
            return marker_failure

    for index, item in enumerate(raw.get("bgColors") or []):
        if not isinstance(item, dict):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", "Pine bgcolor output must be an object")
        color_id = item.get("id", index)
        settings = _render_settings(item, base_pane=pane, fallback_title=f"Background {color_id}")
        if isinstance(settings, ScriptRuntimeResult):
            return settings
        if not settings["paneVisible"]:
            continue
        values = item.get("values") or []
        if not isinstance(values, list):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Background {color_id} values must be a list")
        regions = []
        for i, value in enumerate(values):
            if i >= len(host_times) or value is None or not _visible_source_index(i, len(host_times), settings["showLast"]):
                continue
            target_time = _target_time(host_times, i, settings["offset"])
            if target_time is not None:
                regions.append({"time": target_time, "color": _css_color(value, "rgba(59,130,246,0.1)")})
        if regions:
            bgcolors.append({
                "id": f"pine-bgcolor-{color_id}",
                "title": settings["title"],
                "color": regions[0]["color"],
                "pane": settings["pane"],
                "regions": regions,
            })
    for index, item in enumerate(raw.get("barColors") or []):
        if not isinstance(item, dict):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", "Pine barcolor output must be an object")
        color_id = item.get("id", index)
        settings = _render_settings(item, base_pane="main", fallback_title=f"Bars {color_id}")
        if isinstance(settings, ScriptRuntimeResult):
            return settings
        if not settings["paneVisible"]:
            continue
        values = item.get("values") or []
        if not isinstance(values, list):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Bars {color_id} values must be a list")
        data = []
        for i, value in enumerate(values):
            if i >= len(host_times) or value is None or not _visible_source_index(i, len(host_times), settings["showLast"]):
                continue
            target_time = _target_time(host_times, i, settings["offset"])
            if target_time is not None:
                data.append({"time": target_time, "color": _css_color(value, "#787b86")})
        if data:
            barcolors.append({
                "id": f"pine-barcolor-{color_id}",
                "title": settings["title"],
                "data": data,
            })

    raw_hlines_by_id: dict[Any, dict[str, Any]] = {}
    for index, item in enumerate(raw.get("hlines") or []):
        if not isinstance(item, dict):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", "Pine hline output must be an object")
        hline_id = item.get("id", index)
        price = item.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(float(price)):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"HLine {hline_id} has an invalid price")
        settings = _render_settings(item, base_pane=pane, fallback_title=f"HLine {hline_id}")
        if isinstance(settings, ScriptRuntimeResult):
            return settings
        line_style = _pine_line_style(item.get("lineStyle"))
        if isinstance(line_style, ScriptRuntimeResult):
            return line_style
        line_width = item.get("lineWidth", 1)
        if isinstance(line_width, bool) or not isinstance(line_width, int) or line_width <= 0:
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"HLine {hline_id} has an invalid linewidth")
        raw_hlines_by_id[hline_id] = {**item, "_settings": settings}
        if settings["paneVisible"]:
            hlines.append({
                "id": f"pine-hline-{hline_id}",
                "price": price,
                "title": settings["title"],
                "color": _css_color(item.get("color"), "#787b86"),
                "linestyle": line_style,
                "linewidth": line_width,
                "pane": settings["pane"],
            })

    hidden_hline_ids: set[Any] = set()
    for index, item in enumerate(raw.get("fills") or []):
        if not isinstance(item, dict):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", "Pine fill output must be an object")
        fill_id = item.get("id", index)
        settings = _render_settings(item, base_pane=pane, fallback_title=f"Fill {fill_id}")
        if isinstance(settings, ScriptRuntimeResult):
            return settings
        if not settings["paneVisible"]:
            continue
        first_id = item.get("firstId")
        second_id = item.get("secondId")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (first_id, second_id)):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Fill {fill_id} has invalid endpoint ids")
        first_is_hline = bool(item.get("firstIsHLine", first_id in raw_hlines_by_id))
        second_is_hline = bool(item.get("secondIsHLine", second_id in raw_hlines_by_id))

        endpoint_ids: list[str] = []
        for endpoint_id, is_hline in ((first_id, first_is_hline), (second_id, second_is_hline)):
            if is_hline:
                source_hline = raw_hlines_by_id.get(endpoint_id)
                if source_hline is None:
                    return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Fill {fill_id} references a missing hline")
                local_id = f"pine-hline-fill-{endpoint_id}"
                endpoint_ids.append(local_id)
                if endpoint_id not in hidden_hline_ids:
                    lines.append({
                        "id": local_id,
                        "title": "",
                        "type": "line",
                        "color": "rgba(0,0,0,0)",
                        "lineWidth": 1,
                        "pane": settings["pane"],
                        "visible": False,
                        "data": [
                            {"time": timestamp, "value": source_hline["price"]}
                            for timestamp in host_times
                        ],
                    })
                    hidden_hline_ids.add(endpoint_id)
            else:
                local_id = f"pine-plot-{endpoint_id}"
                if not any(line.get("id") == local_id for line in lines):
                    return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Fill {fill_id} references a missing plot")
                endpoint_ids.append(local_id)

        fill_gaps = item.get("fillGaps", True)
        if not isinstance(fill_gaps, bool):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Fill {fill_id} has invalid fillgaps")
        color_values = item.get("colors") or []
        if not isinstance(color_values, list):
            return _failure("PINE_RUNTIME_OUTPUT_INVALID", f"Fill {fill_id} colors must be a list")
        fallback_color = "rgba(59,130,246,0.12)"
        color_data: list[dict[str, Any]] = []
        for i, value in enumerate(color_values):
            if i >= len(host_times) or value is None or not _visible_source_index(i, len(host_times), settings["showLast"]):
                continue
            color = _css_color(value, fallback_color)
            if not color_data:
                fallback_color = color
            color_data.append({"time": host_times[i], "color": color})
        if color_values and not color_data:
            continue
        distinct_colors = {point["color"] for point in color_data}
        fill: dict[str, Any] = {
            "id": f"pine-fill-{fill_id}",
            "plot1_id": endpoint_ids[0],
            "plot2_id": endpoint_ids[1],
            "title": settings["title"],
            "color": fallback_color,
            "fillGaps": fill_gaps,
            "pane": settings["pane"],
        }
        if color_data and (
            settings["showLast"] is not None
            or fill_gaps is False
            or len(distinct_colors) > 1
            or len(color_data) < min(len(color_values), len(host_times))
        ):
            fill["colorData"] = color_data
        fills.append(fill)
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
            "renderMetadata": "pine-native" if native_render_metadata else "host-defaults",
            "renderMetadataVersion": raw.get("renderMetadataVersion"),
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
        overrides = _normalize_overrides(payload.get("params"), analysis)
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
        installed_render_metadata_version: int | None = None
        try:
            module = _load_module()
            source_path = str(getattr(module, "__file__", "") or "") or None
            try:
                version = importlib_metadata.version(_PACKAGE_NAME)
            except importlib_metadata.PackageNotFoundError:
                version = getattr(module, "__version__", None)
            available = True
            reason = None
            raw_render_version = getattr(module, "RENDER_METADATA_VERSION", None)
            if isinstance(raw_render_version, int) and not isinstance(raw_render_version, bool):
                installed_render_metadata_version = raw_render_version
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
                "renderMetadataVersion": installed_render_metadata_version,
                "expectedRenderMetadataVersion": PINE_RENDER_METADATA_VERSION,
                "nativeRenderMetadata": (
                    installed_render_metadata_version == PINE_RENDER_METADATA_VERSION
                ),
                "hostedOutputs": [
                    "plot",
                    "plotshape",
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
                    "plotchar",
                    "plotarrow",
                    "plotbar",
                    "plotcandle",
                ],
                "plotStyles": [
                    "plot.style_line",
                    "plot.style_histogram",
                    "plot.style_columns",
                ],
                "plotshapeStyles": [
                    "shape.circle",
                    "shape.square",
                    "shape.triangleup",
                    "shape.triangledown",
                    "shape.arrowup",
                    "shape.arrowdown",
                ],
            },
        )
