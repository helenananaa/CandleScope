"""Pure boundary adapters for existing chart rows and accepted live snapshots.

These do not select sources or revisions. Timestamp units and field masks are
converted here, before calling K130. Native snapshots and trade ticks keep
their existing admission/execution paths.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.data_engine.market_data.kline_metrics import (
    KLINE_ENHANCED_FIELDS, normalize_kline_aggregation_fields,
    serialize_kline_enhancements,
)

from .semantics import ClosePolicy, Coverage, CoverageStatus, FieldSummary, summarize_fields


def chart_field_summary(rows: Sequence[Mapping]) -> FieldSummary:
    values = []
    for row in rows:
        enhanced = serialize_kline_enhancements(
            volume=row.get("volume"), quote_volume=row.get("quote_volume"),
            trades=row.get("trades"), taker_buy_base=row.get("taker_buy_base"),
            taker_buy_quote=row.get("taker_buy_quote"),
        )
        values.append((
            *(float(row[name]) for name in ("open", "high", "low", "close", "volume")),
            *(enhanced[name] for name in KLINE_ENHANCED_FIELDS),
        ))
    return summarize_fields(values)


def snapshot_aggregation_values(row: Mapping) -> tuple:
    """Normalize once when the immutable snapshot is created, not per target scan."""
    mask = row["enhanced_fields"]
    enhanced = normalize_kline_aggregation_fields(
        volume=row["volume"],
        **{name: row[name] if name in mask else None for name in KLINE_ENHANCED_FIELDS},
    )
    values = (
        *(round(float(row[name]), 8) for name in ("open", "high", "low", "close", "volume")),
        *enhanced,
    )
    # Normalized input generally already has <=8 decimal places. Reuse its
    # immutable scalars instead of retaining a second set per component.
    names = ("open", "high", "low", "close", "volume", *KLINE_ENHANCED_FIELDS)
    return tuple(row[name] if row[name] == value else value
                 for name, value in zip(names, values))


def snapshot_field_summary(ordered: Sequence[Mapping]) -> FieldSummary:
    return summarize_fields([
        row["aggregation_values"] if "aggregation_values" in row else snapshot_aggregation_values(row)
        for row in ordered
    ])


def snapshot_coverage(ordered: Sequence[Mapping], start_ms: int, end_ms: int) -> CoverageStatus:
    try:
        coverage = Coverage.from_ranges(
            (int(row["open_time_ms"]), int(row["close_time_ms"]) + 1, bool(row.get("is_closed")))
            for row in ordered
        )
    except ValueError:
        return CoverageStatus()
    return coverage.evaluate(start_ms, end_ms, close_policy=ClosePolicy.EXPLICIT)
