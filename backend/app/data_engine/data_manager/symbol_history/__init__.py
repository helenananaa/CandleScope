"""Per-symbol history backfill planner (ADR-DATA-001).

One ``SymbolHistoryPlanner`` per symbol owns fetching its history source
data: demands from every chart and stream of the symbol are merged on source
slots and fetched once, most urgent first. Behind
``HISTORY_SYMBOL_PLANNER_ENABLED`` (off by default) until it is measured; the
existing per-request path stays unchanged while the flag is off.

- ``demands``: demand kinds, urgency and owners
- ``slots``: interval sets and the per-source slot map
- ``pieces``: cutting missing slots into pieces, piece results
- ``planner``: the planner and the per-symbol registry
- ``coordinator_executor``: pieces as source-interval coordinator repairs
- ``router``: which chart reads, seeds and tails go to the planner, thread handoff, serving them
"""
from __future__ import annotations

from .demands import REQUEST_FIELDS, URGENCY, Demand, DemandKind, DemandOwner, kind_for_reason
from .pieces import MAX_PIECE_BARS, Piece, PieceResult, cut_pieces, piece_block_ms
from .planner import PlannerRegistry, SymbolHistoryPlanner, SymbolKey
from .slots import IntervalSet, Segment, SlotMap


def planner_enabled() -> bool:
    """Whether producers register demand with the planner instead of the per-request path."""
    from app.core import config

    return bool(getattr(config, "HISTORY_SYMBOL_PLANNER_ENABLED", False))


__all__ = [
    "Demand", "DemandKind", "DemandOwner", "IntervalSet", "MAX_PIECE_BARS", "Piece", "PieceResult",
    "PlannerRegistry", "REQUEST_FIELDS", "Segment", "SlotMap", "SymbolHistoryPlanner", "SymbolKey",
    "URGENCY", "cut_pieces", "kind_for_reason", "piece_block_ms", "planner_enabled",
]
