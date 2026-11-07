"""Transport-independent projection of confirmed indicator ranges.

HTTP, WebSocket and isolated history workers share these computations; this
module owns no request, application composition or market-data lookup.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from functools import partial
from operator import itemgetter
from typing import Any

from app.indicator import create_engine
from app.indicator.errors import IndicatorRangeNotReadyError
from app.indicator.serialization import build_indicator_snapshot_payload
from app.indicator.series_reference import identity_kwargs
from app.indicator.warmup import indicator_warmup_bars as _indicator_warmup_bars


def _filter_points_to_range(
    points: list[dict[str, Any]], start_s: int, end_s: int, *, ordered_times: bool
) -> list[dict[str, Any]]:
    if ordered_times:
        timestamp = itemgetter("time")
        try:
            first = bisect_left(points, start_s, key=timestamp)
            last = bisect_right(points, end_s, lo=first, key=timestamp)
            return points[first:last]
        except (KeyError, TypeError):
            # Malformed producer records retain the generic filter.
            pass
    filtered: list[dict[str, Any]] = []
    for point in points or []:
        try:
            ts = int(point.get("time"))
        except (TypeError, ValueError):
            continue
        if start_s <= ts <= end_s:
            filtered.append(point)
    return filtered


def filter_payload_to_range(
    payload: dict[str, Any], start_s: int, end_s: int, *, ordered_times: bool = False
) -> dict[str, Any]:
    """Trim a snapshot-like indicator payload down to a range patch."""
    slice_points = partial(
        _filter_points_to_range, start_s=start_s, end_s=end_s, ordered_times=ordered_times,
    )
    next_payload = dict(payload)

    if isinstance(next_payload.get("lines"), list):
        next_payload["lines"] = [
            {
                **line,
                "data": slice_points(line.get("data") or []),
                **(
                    {
                        "colorData": slice_points(line.get("colorData") or [])
                    }
                    if line.get("colorData")
                    else {}
                ),
            }
            for line in next_payload["lines"]
        ]

    if isinstance(next_payload.get("series"), list):
        series = []
        for item in next_payload["series"]:
            style = dict(item.get("style") or {})
            if style.get("colorData"):
                style["colorData"] = slice_points(style.get("colorData") or [])
            series.append(
                {
                    **item,
                    "data": slice_points(item.get("data") or []),
                    "style": style,
                }
            )
        next_payload["series"] = series

    # Builtin snapshots also carry the legacy ``result.outputs`` envelope.
    # Leaving it unsliced would make a tiny cache hit serialize the complete
    # WS seed history even though ``lines``/``series`` were correctly trimmed.
    nested_result = next_payload.get("result")
    if isinstance(nested_result, dict) and isinstance(
        nested_result.get("outputs"), dict
    ):
        filtered_result = dict(nested_result)
        filtered_outputs: dict[str, Any] = {}
        for name, output in nested_result["outputs"].items():
            if not isinstance(output, dict):
                filtered_outputs[name] = output
                continue
            filtered_outputs[name] = {
                **output,
                "data": slice_points(output.get("data") or []),
                **(
                    {
                        "colorData": slice_points(output.get("colorData") or [])
                    }
                    if output.get("colorData")
                    else {}
                ),
            }
        filtered_result["outputs"] = filtered_outputs
        next_payload["result"] = filtered_result

    if isinstance(next_payload.get("annotations"), list):
        annotations = []
        for item in next_payload["annotations"]:
            data = item.get("data") or []
            if data and isinstance(data[0], dict) and "time" in data[0]:
                data = slice_points(data)
            annotations.append({**item, "data": data})
        next_payload["annotations"] = annotations

    for key in ("markers", "bgcolors", "barcolors", "signals"):
        if isinstance(next_payload.get(key), list):
            next_payload[key] = [
                {
                    **group,
                    "data": slice_points(group.get("data") or []),
                    # Script bgcolors keep their per-bar runs in ``regions``.
                    **(
                        {
                            "regions": slice_points(group["regions"])
                        }
                        if isinstance(group.get("regions"), list)
                        else {}
                    ),
                }
                for group in next_payload[key]
            ]

    # Script fills carry per-bar colors beside their endpoints. ``fills`` is
    # the untimed v2 projection and needs no slicing.
    if isinstance(next_payload.get("legacyFills"), list):
        next_payload["legacyFills"] = [
            {
                **fill,
                **{
                    field: slice_points(fill[field])
                    for field in ("data", "colorData")
                    if isinstance(fill.get(field), list)
                },
            }
            for fill in next_payload["legacyFills"]
        ]

    return next_payload


def replace_range_from_snapshot(
    payload: dict[str, Any],
    *,
    reason: str,
    start_s: int,
    end_s: int,
) -> dict[str, Any]:
    replacement = filter_payload_to_range(payload, start_s, end_s)
    replacement.update(
        {
            "type": "indicator.replace_range",
            "reason": reason,
            "range": {"start": start_s, "end": end_s},
        }
    )
    return replacement


def confirmed_target_range(
    bars: list[Any], start_s: int, end_s: int
) -> tuple[int, int]:
    target_times = [int(bar.time) for bar in bars if start_s <= int(bar.time) <= end_s]
    if not target_times:
        raise IndicatorRangeNotReadyError("target K-line range is not available yet")
    return min(target_times), max(target_times)


def compute_builtin_range_patch_from_bars(
    client_id: str,
    meta: dict[str, Any],
    start_s: int,
    end_s: int,
    bars: list[Any],
    reason: str,
    target_bars: int,
) -> dict[str, Any]:
    name = str(meta.get("name") or "").upper()
    params = meta.get("params") if isinstance(meta.get("params"), dict) else {}
    warmup = _indicator_warmup_bars(name, params)
    engine = create_engine()
    try:
        result = engine.compute(
            symbol=meta["symbol"],
            interval=meta["interval"],
            market_type=meta["market_type"],
            indicator_name=name,
            params=params,
            bars=bars,
            exchange=meta["exchange"],
            **identity_kwargs(meta),
        )
    finally:
        engine.stop()
    payload = build_indicator_snapshot_payload(
        client_id=client_id,
        indicator_id=meta.get("indicatorId")
        or f"{meta['exchange']}:{meta['market_type']}:{meta['symbol']}:{meta['interval']}:{name}",
        exchange=meta["exchange"],
        symbol=meta["symbol"],
        interval=meta["interval"],
        market_type=meta["market_type"],
        name=name,
        params=params,
        result=result,
    )
    range_start_s, range_end_s = confirmed_target_range(bars, start_s, end_s)
    patch = replace_range_from_snapshot(
        payload,
        reason=reason,
        start_s=range_start_s,
        end_s=range_end_s,
    )
    patch["warmupBars"] = warmup
    patch["targetBars"] = target_bars
    return patch
