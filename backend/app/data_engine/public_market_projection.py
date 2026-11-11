"""Shared public market-data serialization used by HTTP and plugin consumers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from app.data_engine.market_data.trade_flow import (
    BUCKET_INTERVAL_MS, MAX_TRADE_HISTORY_PROOF_MINUTES, TradeHistoryRead,
)


def serialize_public_value(value: Any) -> dict[str, Any]:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(f"unsupported public market value: {type(value).__name__}")


def public_bar_rows(bars: list[Any]) -> list[dict[str, Any]]:
    return [
        item.to_kline_dict()
        if hasattr(item, "to_kline_dict")
        else item.to_dict()
        if hasattr(item, "to_dict")
        else item
        for item in bars
    ]


def project_trade_recent_payload(key: Any, records: list[Any]) -> dict[str, Any]:
    data = [serialize_public_value(item) for item in records]
    ids = [int(item["agg_trade_id"]) for item in data]
    missing = [
        {"start_agg_trade_id": left + 1, "end_agg_trade_id": right - 1}
        for left, right in zip(ids, ids[1:])
        if right > left + 1
    ]
    continuity = bool(data) and all(
        right == left + 1 for left, right in zip(ids, ids[1:])
    )
    return {
        "type": "trade_flow.recent",
        "protocol": "tradeflow.v1",
        "key": key.to_dict(),
        "count": len(data),
        "data": data,
        "cursor": {
            "earliest_agg_trade_id": min(ids, default=None),
            "latest_agg_trade_id": max(ids, default=None),
        },
        "continuity": continuity,
        "resync_required": not continuity,
        "missing_agg_trade_id_ranges": missing,
        "bounded": True,
    }


def project_local_rollup_status(
    *, start_ms: int | None, end_ms: int | None, reason: str,
) -> dict[str, Any]:
    """Report source coverage separately from a completed local page read."""
    return {
        "mode": "local_only",
        "requested_range": {"start_ms": start_ms, "end_ms": end_ms},
        "complete": False,
        "retryable": False,
        "terminal_reason": reason,
    }


def project_trade_history_payload(
    key: Any, history: TradeHistoryRead, *, limit: int,
    start_ms: int | None = None, end_ms: int | None = None,
) -> dict[str, Any]:
    records = history.rows
    data = [serialize_public_value(item) for item in records[:limit]]
    following = serialize_public_value(records[limit]) if len(records) > limit else None
    next_cursor = None
    if following is not None:
        next_cursor = {"start_ms": int(following.get("bucket_start_ms", following.get("bucket_open_ms")))}
    times = [
        int(item.get("bucket_start_ms", item.get("bucket_open_ms"))) for item in data
    ]
    # Quiet minutes carry coverage without a synthetic zero-volume row.
    # A row wins over any overlapping absence assertion.
    empty_opens = sorted(history.verified_empty_opens.difference(times))
    empty_ranges: list[dict[str, int]] = []
    for opened in empty_opens:
        if empty_ranges and opened == empty_ranges[-1]["end_ms"] + BUCKET_INTERVAL_MS:
            empty_ranges[-1]["end_ms"] = opened
        else:
            empty_ranges.append({"start_ms": opened, "end_ms": opened})
    complete = False
    if start_ms is not None and end_ms is not None and next_cursor is None:
        first = (start_ms + BUCKET_INTERVAL_MS - 1) // BUCKET_INTERVAL_MS * BUCKET_INTERVAL_MS
        if first <= end_ms and (end_ms - first) // BUCKET_INTERVAL_MS < MAX_TRADE_HISTORY_PROOF_MINUTES:
            covered = set(empty_opens)
            covered.update(
                opened for opened, row in zip(times, data)
                if row.get("is_complete") is True and row.get("is_final") is True
            )
            complete = all(opened in covered for opened in range(first, end_ms + 1, BUCKET_INTERVAL_MS))
    return {
        "type": "trade_flow.history",
        "protocol": "tradeflow.v1",
        "key": {**key.to_dict(), "params": {"period": "1m"}},
        "count": len(data),
        "data": data,
        "has_more": next_cursor is not None,
        "next_cursor": next_cursor,
        **project_local_rollup_status(
            start_ms=start_ms, end_ms=end_ms, reason="unverified_continuity",
        ),
        "complete": complete,
        "terminal_reason": None if complete else "unverified_continuity",
        "coverage": {
            "earliest_ms": min(times, default=None),
            "latest_ms": max(times, default=None),
            "observed_only": not complete,
            "verified_empty_minutes": len(empty_opens),
            "verified_empty_ranges": empty_ranges,
            "all_rows_complete": bool(data)
            and all(bool(item.get("is_complete", False)) for item in data),
        },
    }


__all__ = [
    "project_local_rollup_status",
    "project_trade_history_payload",
    "project_trade_recent_payload",
    "public_bar_rows",
    "serialize_public_value",
]
