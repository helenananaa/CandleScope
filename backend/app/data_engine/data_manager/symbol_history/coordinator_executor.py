"""Run planner pieces through the existing backfill coordinator (ADR-DATA-001 S5).

A piece becomes one ordinary source-interval ``RepairRequest``: the same
fetcher, router, native write and verification as any repair. Each request
carries the target windows it serves (``derived_repair_targets``), so studies
on those targets recompute as they do for any derived repair. The request id
is the piece's handle: the API waits on it and leases it as before.

Submission is synchronous (``BackfillCoordinator.trigger`` on the loop), the
wait is ``wait_for_request``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.data_engine.data_manager.backfill_contracts import repair_status_value

from .demands import REQUEST_FIELDS, URGENCY, DemandKind
from .pieces import Piece, PieceResult
from .planner import SymbolKey

# Every urgency maps to one (reason, priority); viewport and gap repair share both.
_FIELDS_BY_URGENCY: dict[int, tuple[str, int]] = {}
for _kind in sorted(DemandKind, key=lambda kind: URGENCY[kind]):
    _FIELDS_BY_URGENCY.setdefault(URGENCY[_kind], REQUEST_FIELDS[_kind])

REQUESTER = "symbol_history"


class _Coordinator(Protocol):
    def trigger(self, symbol: str, interval: str, start_ms: int, end_ms: int, exchange: str = ...,
                market_type: str = ..., **kwargs: Any) -> str: ...

    async def wait_for_request(self, request_id: str) -> Any: ...


def request_fields(urgency: int) -> tuple[str, int]:
    return _FIELDS_BY_URGENCY.get(urgency, REQUEST_FIELDS[DemandKind.GAP_REPAIR])


class CoordinatorPieceExecutor:
    """Submit each piece as a source-interval repair and map its outcome back."""

    def __init__(
        self,
        coordinator: _Coordinator,
        key: SymbolKey,
        *,
        targets_for: Callable[[Piece], list[dict[str, Any]]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._key = key
        self._targets_for = targets_for
        self._metadata = dict(metadata or {})

    def submit(self, piece: Piece) -> str:
        reason, priority = request_fields(piece.urgency)
        metadata: dict[str, Any] = {
            **self._metadata,
            "requires_trusted_finality": True,
            "symbol_history_piece": piece.piece_id,
            "requested_range": {"start_ms": piece.start_ms, "end_ms": piece.end_ms - piece.width_ms},
        }
        targets = self._targets_for(piece) if self._targets_for is not None else []
        if targets:
            metadata["derived_repair_targets"] = targets
        # RepairRequest ranges are inclusive opens; pieces are half-open.
        return self._coordinator.trigger(
            self._key.symbol, piece.source_interval, piece.start_ms, piece.end_ms - piece.width_ms,
            self._key.exchange, self._key.market_type,
            reason=reason, priority=priority, requester=REQUESTER, metadata=metadata,
        )

    async def wait(self, handle: str, piece: Piece, still_wanted: Callable[[], bool]) -> PieceResult:
        outcome = await self._coordinator.wait_for_request(handle)
        if outcome is None:  # the coordinator shut down
            return PieceResult("cancelled")
        status = repair_status_value(getattr(outcome, "status", None))
        if status == "completed" and not getattr(outcome, "retryable", False):
            return PieceResult("committed")
        if status == "cancelled":
            return PieceResult("cancelled", written=_written(outcome, piece))
        error = getattr(outcome, "error", None) or getattr(outcome, "terminal_reason", None) or status
        return PieceResult("failed", written=_written(outcome, piece), error=str(error)[:300])


def _written(outcome: Any, piece: Piece) -> tuple[tuple[int, int], ...]:
    """Half-open source ranges the request reports as written."""
    report = getattr(outcome, "report", None)
    ranges = []
    for item in getattr(report, "written_ranges", ()) or ():
        if getattr(item, "interval", None) != piece.source_interval:
            continue
        start, end = int(item.start_ms), int(item.end_ms) + piece.width_ms
        if start < end:
            ranges.append((start, end))
    return tuple(ranges)
