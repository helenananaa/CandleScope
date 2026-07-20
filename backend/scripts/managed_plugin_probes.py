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
    plots = runtime.get("plots")
    if not isinstance(plots, list) or not plots:
        raise ProbeError("runtime smoke did not produce the expected plot output")
    return {
        "analysisSchemaVersion": analysis.get("schemaVersion"),
        "runtimeSchemaVersion": runtime.get("schemaVersion"),
    }


def validate_probe_config(kind: str, config: Mapping[str, Any]) -> None:
    """Validate probe configuration while loading locks, before any mutation."""

    if kind == "python-import":
        return
    if kind == "pine-runtime-v1":
        _positive_int(config, "analysisSchemaVersion")
        _positive_int(config, "runtimeSchemaVersion")
        return
    raise ProbeError(f"unsupported managed plugin probe {kind!r}")


def run_probe(kind: str, module: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    """Run a named semantic probe after the generic import/version checks."""

    if kind == "python-import":
        return {}
    if kind == "pine-runtime-v1":
        return _probe_pine_runtime(module, config)
    raise ProbeError(f"unsupported managed plugin probe {kind!r}")
