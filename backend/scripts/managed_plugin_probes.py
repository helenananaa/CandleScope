"""Host-owned health probes for managed CandleScope plugins.

The installer always performs the generic distribution-version and import checks.
This module contains only the optional semantic checks that are specific to a
plugin's host contract.
"""
from __future__ import annotations

from typing import Any, Mapping


class ProbeError(RuntimeError):
    """A managed plugin imported successfully but failed its host contract."""


def _positive_int(config: Mapping[str, Any], key: str) -> int:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProbeError(f"verification.{key} must be a positive integer")
    return value


def _probe_pine_runtime(module: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    expected_analysis_schema = _positive_int(config, "analysisSchemaVersion")
    expected_runtime_schema = _positive_int(config, "runtimeSchemaVersion")
    source = (
        '//@version=5\nindicator("CandleScope install probe", overlay=true)\n'
        'plot(ta.sma(close, 2), "SMA")\n'
    )
    analysis = dict(module.analyze_script(source))
    if analysis.get("schemaVersion") != expected_analysis_schema:
        raise ProbeError(
            "analysis schema mismatch: "
            f"expected {expected_analysis_schema}, "
            f"got {analysis.get('schemaVersion')!r}"
        )
    bars = [
        {
            "time": 1_700_000_000_000,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 100.0,
        },
        {
            "time": 1_700_000_060_000,
            "open": 10.0,
            "high": 12.0,
            "low": 9.5,
            "close": 11.0,
            "volume": 110.0,
        },
        {
            "time": 1_700_000_120_000,
            "open": 11.0,
            "high": 13.0,
            "low": 10.5,
            "close": 12.0,
            "volume": 120.0,
        },
    ]
    runtime = dict(module.run_script(source, bars))
    if runtime.get("schemaVersion") != expected_runtime_schema:
        raise ProbeError(
            "runtime schema mismatch: "
            f"expected {expected_runtime_schema}, "
            f"got {runtime.get('schemaVersion')!r}"
        )
    if "renderMetadataVersion" in config:
        expected_render_metadata = _positive_int(config, "renderMetadataVersion")
        if runtime.get("renderMetadataVersion") != expected_render_metadata:
            raise ProbeError(
                "runtime render metadata mismatch: "
                f"expected {expected_render_metadata}, "
                f"got {runtime.get('renderMetadataVersion')!r}"
            )
    plots = runtime.get("plots")
    if not isinstance(plots, list) or not plots:
        raise ProbeError("runtime smoke did not produce the expected plot output")
    return {
        "analysisSchemaVersion": analysis.get("schemaVersion"),
        "runtimeSchemaVersion": runtime.get("schemaVersion"),
    }


def _last_plot_value(result: Any, index: int) -> float:
    if not isinstance(result, Mapping):
        raise ProbeError("realtime smoke returned a non-object result")
    plots = result.get("plots")
    if not isinstance(plots, list) or index >= len(plots):
        raise ProbeError("realtime smoke did not produce the expected plot output")
    plot = plots[index]
    values = plot.get("values") if isinstance(plot, Mapping) else None
    if not isinstance(values, list) or not values:
        raise ProbeError("realtime smoke plot did not contain values")
    value = values[-1]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeError("realtime smoke plot contained a non-numeric value")
    return float(value)


def _probe_pine_realtime_runtime(
    module: Any,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    result = _probe_pine_runtime(module, config)
    expected_render_metadata = _positive_int(config, "renderMetadataVersion")
    expected_realtime_schema = _positive_int(
        config,
        "realtimeSessionSchemaVersion",
    )
    installed_render_metadata = getattr(module, "RENDER_METADATA_VERSION", None)
    if installed_render_metadata != expected_render_metadata:
        raise ProbeError(
            "render metadata version mismatch: "
            f"expected {expected_render_metadata}, got {installed_render_metadata!r}"
        )
    installed_realtime_schema = getattr(
        module,
        "REALTIME_SESSION_SCHEMA_VERSION",
        None,
    )
    if installed_realtime_schema != expected_realtime_schema:
        raise ProbeError(
            "realtime session schema mismatch: "
            f"expected {expected_realtime_schema}, got {installed_realtime_schema!r}"
        )
    create_session = getattr(module, "create_realtime_session", None)
    if not callable(create_session):
        raise ProbeError("runtime does not expose create_realtime_session")

    source = (
        '//@version=6\nindicator("CandleScope realtime install probe")\n'
        "var float regular = 0.0\n"
        "varip float intrabar = 0.0\n"
        "regular += 1.0\n"
        "intrabar += 1.0\n"
        "plot(regular)\n"
        "plot(intrabar)\n"
    )
    first_time = 1_700_000_000_000
    second_time = 1_700_000_060_000

    def bar(timestamp: int, close: float) -> dict[str, float | int]:
        return {
            "time": timestamp,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1.0,
        }

    session = create_session(source)
    if getattr(session, "schema_version", None) != expected_realtime_schema:
        raise ProbeError("realtime session instance has an incompatible schema version")
    session.seed([bar(first_time, 1.0)])
    first = session.update_forming(bar(second_time, 2.0))
    replacement = session.update_forming(bar(second_time, 3.0))
    confirmed = session.update_confirmed(bar(second_time, 4.0))
    observed = (
        _last_plot_value(first, 0),
        _last_plot_value(first, 1),
        _last_plot_value(replacement, 0),
        _last_plot_value(replacement, 1),
        _last_plot_value(confirmed, 0),
        _last_plot_value(confirmed, 1),
    )
    if observed != (2.0, 2.0, 2.0, 3.0, 2.0, 4.0):
        raise ProbeError(
            "realtime rollback/varip smoke mismatch: "
            f"expected (2, 2, 2, 3, 2, 4), got {observed!r}"
        )
    if (
        getattr(session, "confirmed_bars", None) != 2
        or getattr(session, "last_confirmed_time", None) != second_time
        or getattr(session, "forming_time", object()) is not None
    ):
        raise ProbeError("realtime session lifecycle state did not confirm cleanly")
    return {
        **result,
        "renderMetadataVersion": installed_render_metadata,
        "realtimeSessionSchemaVersion": installed_realtime_schema,
    }


def validate_probe_config(kind: str, config: Mapping[str, Any]) -> None:
    """Validate probe configuration while loading locks, before any mutation."""

    if kind == "python-import":
        return
    if kind == "pine-runtime-v1":
        _positive_int(config, "analysisSchemaVersion")
        _positive_int(config, "runtimeSchemaVersion")
        return
    if kind == "pine-runtime-v2":
        _positive_int(config, "analysisSchemaVersion")
        _positive_int(config, "runtimeSchemaVersion")
        _positive_int(config, "renderMetadataVersion")
        _positive_int(config, "realtimeSessionSchemaVersion")
        return
    raise ProbeError(f"unsupported managed plugin probe {kind!r}")


def run_probe(kind: str, module: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    """Run a named semantic probe after the generic import/version checks."""

    if kind == "python-import":
        return {}
    if kind == "pine-runtime-v1":
        return _probe_pine_runtime(module, config)
    if kind == "pine-runtime-v2":
        return _probe_pine_realtime_runtime(module, config)
    raise ProbeError(f"unsupported managed plugin probe {kind!r}")
