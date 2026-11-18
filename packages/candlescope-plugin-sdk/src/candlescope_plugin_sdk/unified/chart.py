"""Bounded chart computation on a host-provided, already revealed frame."""

from __future__ import annotations

import math

from .manifest import ManifestError

CHART_SCOPE_V1 = "candlescope.unified-chart/1"
MAX_CHART_BARS = 256
CHART_MODES = frozenset(
    {"live", "quick-replay", "history-study", "replay", "replay-review", "strategy-replay"}
)
_SCOPE_FIELDS = frozenset(
    {
        "schema",
        "documentId",
        "chartId",
        "instanceId",
        "mode",
        "runId",
        "trackId",
        "seriesId",
        "symbol",
        "interval",
        "dataRevision",
        "visibleThroughMs",
    }
)
_BAR_FIELDS = frozenset(
    {"openTimeMs", "observedThroughMs", "open", "high", "low", "close", "volume", "closed"}
)
_MAX_SAFE = 9_007_199_254_740_991


def _timestamp(value):
    return type(value) is int and 0 <= value <= _MAX_SAFE


def _identity(value):
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 1024
        and not any(ord(char) < 32 for char in value)
    )


def _finite(value):
    return (type(value) is int and abs(value) <= _MAX_SAFE) or (
        type(value) is float and math.isfinite(value)
    )


def validate_chart_frame(scope, bars):
    """Validate the wire bounds without opening any underlying data source."""
    if not isinstance(scope, dict) or set(scope) != _SCOPE_FIELDS:
        raise ManifestError("invalid chart scope fields")
    if (
        scope["schema"] != CHART_SCOPE_V1
        or not isinstance(scope["mode"], str)
        or scope["mode"] not in CHART_MODES
    ):
        raise ManifestError("invalid chart mode or scope version")
    if not all(
        _identity(scope[key])
        for key in (
            "documentId",
            "chartId",
            "instanceId",
            "seriesId",
            "symbol",
            "interval",
            "dataRevision",
        )
    ):
        raise ManifestError(
            "chart scope requires window, chart, instance, series and data revision"
        )
    if scope["mode"] == "live":
        if scope["runId"] is not None or scope["trackId"] is not None:
            raise ManifestError("live charts do not have replay identities")
    elif not _identity(scope["runId"]) or not _identity(scope["trackId"]):
        raise ManifestError("replay charts require a run and track")
    horizon = scope["visibleThroughMs"]
    if (
        not _timestamp(horizon)
        or not isinstance(bars, list)
        or not 1 <= len(bars) <= MAX_CHART_BARS
    ):
        raise ManifestError("chart frame has an invalid horizon or bar count")
    previous_end = -1
    for index, bar in enumerate(bars):
        if not isinstance(bar, dict) or set(bar) != _BAR_FIELDS:
            raise ManifestError("invalid chart frame bar")
        opened, observed = bar["openTimeMs"], bar["observedThroughMs"]
        if not (
            _timestamp(opened)
            and _timestamp(observed)
            and previous_end < opened <= observed <= horizon
        ):
            raise ManifestError("chart bar is outside the ordered revealed boundary")
        if type(bar["closed"]) is not bool or (not bar["closed"] and index != len(bars) - 1):
            raise ManifestError("only the revealed rightmost bar may be forming")
        if not all(_finite(bar[key]) for key in ("open", "high", "low", "close")):
            raise ManifestError("chart bar must contain finite OHLC")
        if bar["low"] > min(bar["open"], bar["close"]) or bar["high"] < max(
            bar["open"], bar["close"]
        ):
            raise ManifestError("chart bar has inconsistent OHLC")
        volume = bar["volume"]
        if volume is not None and (not _finite(volume) or volume < 0):
            raise ManifestError("invalid chart bar volume")
        previous_end = observed


def validate_chart_result(result, times):
    """Release only point results aligned to this call's supplied bar openings."""
    if not isinstance(result, dict) or set(result) != {"points"}:
        raise ManifestError("chart computation must return points")
    points = result["points"]
    if not isinstance(points, list) or len(points) > len(times):
        raise ManifestError("chart result exceeds the supplied chart frame")
    previous = -1
    for point in points:
        if not isinstance(point, dict) or set(point) != {"timeMs", "value"}:
            raise ManifestError("invalid chart result point")
        time = point["timeMs"]
        if (
            not _timestamp(time)
            or time not in times
            or time <= previous
            or not _finite(point["value"])
        ):
            raise ManifestError("chart result references a bar outside the supplied frame")
        previous = time
