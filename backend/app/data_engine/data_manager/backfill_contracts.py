"""Backfill demand and outcome contracts shared by callers and executors.

These values carry no scheduler, persistence, or cache ownership. Callers that
only create demands or select priority do not need to import the coordinator.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.data_engine.kline_quality import repair_requires_trusted_finality
from app.data_engine.series_identity import identity_from_metadata

BACKFILL_REASON_PRIORITIES: dict[str, int] = {
    "initial_history": 10,
    "visible_load_more": 20,
    "visible_range_gap": 20,
    "visible_seed_gap": 25,
    "tail_gap": 25,
    "latest_refresh": 30,
    "query_gap": 35,
    "query_empty": 35,
    "query_tail_gap": 35,
    "query_left_gap": 35,
    "query_shortfall": 35,
    "query_interior_gap": 35,
    "price_daily_open": 70,
    "active_history_hydration": 90,
    "related_interval_warmup": 100,
    "full_subscription_warmup": 110,
    "startup_gap_scan": 140,
    "background_gap_audit": 160,
}

_MAX_MERGED_REQUEST_IDS = 32
_MAX_MERGED_REASON_PARTS = 8
_MAX_DERIVED_REPAIR_TARGETS = 32


def priority_for_reason(reason: str | None, default: int = 100) -> int:
    """Return the scheduler priority for a demand reason."""
    return BACKFILL_REASON_PRIORITIES.get(str(reason or "").strip(), default)


def _merge_derived_repair_targets(*values: Any) -> list[dict[str, Any]]:
    """Normalize and stably dedupe derived-series completion targets."""
    merged: dict[tuple[str, int, int], dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, (list, tuple)):
            continue
        for raw in value:
            if not isinstance(raw, dict):
                continue
            interval = str(raw.get("interval") or "").strip()
            try:
                start_ms = int(raw["start_ms"])
                end_ms = int(raw["end_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            if not interval or start_ms > end_ms:
                continue
            identity = (interval, start_ms, end_ms)
            merged.setdefault(identity, {
                "interval": interval,
                "start_ms": start_ms,
                "end_ms": end_ms,
            })
    return list(merged.values())[-_MAX_DERIVED_REPAIR_TARGETS:]


class RepairRetryDeferred(Exception):
    """Retryable work yields its worker without settling the caller's future."""

    def __init__(self, delay: float, attempt: int) -> None:
        super().__init__("repair_retry")
        self.retry_after_seconds = delay
        self.attempt = attempt
        self.retry_at_monotonic = None
        self.retry_at_ms = None
        self.reason = "repair_retry"
        self.bucket_key = None


@dataclass(slots=True)
class RepairRequest:
    """A single requested historical repair range."""

    symbol: str
    interval: str
    start_ms: int
    end_ms: int
    exchange: str = "binance"
    market_type: str = "spot"
    reason: str = "query_gap"
    priority: int | None = None
    requester: str = "query"
    wait_policy: str = "async"
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    _retry_attempt: int = field(default=1, repr=False)

    def __post_init__(self) -> None:
        if self.priority is None:
            self.priority = priority_for_reason(self.reason)
        self.metadata.setdefault("requested_range", {
            "start_ms": int(self.start_ms),
            "end_ms": int(self.end_ms),
        })

    @property
    def series_key(self) -> tuple[str, ...]:
        identity = identity_from_metadata(self.exchange, self.metadata)
        base = (
            self.exchange.lower().strip(),
            self.market_type.lower().strip(),
            self.symbol.upper().strip(),
            self.interval,
        )
        return base + (identity.storage_values if identity is not None else ())

    def merged_with(self, other: RepairRequest) -> RepairRequest:
        """Return a range that covers both requests for the same series."""
        metadata = {**self.metadata, **other.metadata}
        if (
            repair_requires_trusted_finality(self.metadata, reason=self.reason)
            or repair_requires_trusted_finality(other.metadata, reason=other.reason)
        ):
            metadata["requires_trusted_finality"] = True
        derived_targets = _merge_derived_repair_targets(
            self.metadata.get("derived_repair_targets"),
            other.metadata.get("derived_repair_targets"),
        )
        if derived_targets:
            metadata["derived_repair_targets"] = derived_targets
        else:
            metadata.pop("derived_repair_targets", None)
        planned_ranges = self._merged_history_fetch_ranges(other)
        if planned_ranges:
            metadata["history_fetch_ranges"] = planned_ranges
        raw_merged_ids = metadata.get("merged_request_ids")
        merged_ids = list(raw_merged_ids) if isinstance(raw_merged_ids, list) else []
        merged_ids.extend((self.request_id, other.request_id))
        metadata["merged_request_ids"] = list(dict.fromkeys(
            str(item) for item in merged_ids if item
        ))[-_MAX_MERGED_REQUEST_IDS:]
        reason_parts: list[str] = []
        for raw_reason in (self.reason, other.reason):
            for part in str(raw_reason or "").split("+"):
                normalized = part.strip()
                if normalized and normalized not in reason_parts:
                    reason_parts.append(normalized)
                if len(reason_parts) >= _MAX_MERGED_REASON_PARTS:
                    break
            if len(reason_parts) >= _MAX_MERGED_REASON_PARTS:
                break
        merged_reason = "+".join(reason_parts) or "query_gap"
        return RepairRequest(
            symbol=self.symbol,
            interval=self.interval,
            start_ms=min(self.start_ms, other.start_ms),
            end_ms=max(self.end_ms, other.end_ms),
            exchange=self.exchange,
            market_type=self.market_type,
            reason=merged_reason,
            priority=min(int(self.priority or 100), int(other.priority or 100)),
            requester=self.requester if self.requester == other.requester else "mixed",
            wait_policy=self.wait_policy,
            metadata=metadata,
            request_id=self.request_id,
        )

    def _merged_history_fetch_ranges(
        self,
        other: RepairRequest,
    ) -> list[dict[str, int]]:
        ranges: list[tuple[int, int]] = []
        for request in (self, other):
            raw_ranges = request.metadata.get("history_fetch_ranges")
            if not isinstance(raw_ranges, list):
                raw_ranges = [{"start_ms": request.start_ms, "end_ms": request.end_ms}]
            for raw in raw_ranges:
                if not isinstance(raw, dict):
                    continue
                try:
                    start_ms = int(raw["start_ms"])
                    end_ms = int(raw["end_ms"])
                except (KeyError, TypeError, ValueError):
                    continue
                if start_ms <= end_ms:
                    ranges.append((start_ms, end_ms))
        if not ranges:
            return []
        ranges.sort()
        merged: list[tuple[int, int]] = [ranges[0]]
        for start_ms, end_ms in ranges[1:]:
            previous_start, previous_end = merged[-1]
            if start_ms <= previous_end:
                merged[-1] = (previous_start, max(previous_end, end_ms))
            else:
                merged.append((start_ms, end_ms))
        return [
            {"start_ms": start_ms, "end_ms": end_ms}
            for start_ms, end_ms in merged
        ]


HistoryPolicyResolver = Callable[[RepairRequest], Any]


@dataclass(slots=True)
class RepairOutcome:
    request: RepairRequest
    status: Any
    report: Any | None = None
    attempts: int = 0
    bars_loaded: int = 0
    verified_contiguous: bool | None = None
    remaining_missing_bars: int | None = None
    error: str | None = None
    terminal_reason: str | None = None
    exhausted_before_ms: int | None = None
    retryable: bool = False
    retry_at_ms: int | None = None
    suppressed: bool = False
    ledger_status: str | None = None
    suppression: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RepairReconcileSummary:
    """Small reconciliation payload retained after a repair completes."""

    bars_received: int = 0
    bars_written: int = 0
    bars_skipped: int = 0
    bars_deduplicated: int = 0
    custom_bars_generated: int = 0
    custom_bars_written: int = 0
    bars_cached: int = 0
    write_errors: int = 0
    failed_batch_count: int = 0
    written_range_count: int = 0
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class RepairWrittenRangeSummary:
    exchange: str
    market_type: str
    symbol: str
    interval: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class RepairReportSummary:
    """Report statistics retained without FetchResult bar payloads."""

    status: Any
    errors: tuple[str, ...]
    error_count: int
    reconcile_result: RepairReconcileSummary | None
    fetch_result_count: int
    fetched_bar_count: int
    written_range_count: int
    written_ranges: tuple[RepairWrittenRangeSummary, ...]
    elapsed_ms: int


@dataclass(slots=True)
class ScanReport:
    scanned: int = 0
    repaired: int = 0
    queued: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    ledger_scanned: int = 0
    ledger_resolved: int = 0
    ledger_requeued: int = 0
    ledger_compacted: int = 0
    ledger_skipped: int = 0
    ledger_failed: int = 0

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "repaired": self.repaired,
            "queued": self.queued,
            "failed": self.failed,
            "errors": list(self.errors),
            "ledger_scanned": self.ledger_scanned,
            "ledger_resolved": self.ledger_resolved,
            "ledger_requeued": self.ledger_requeued,
            "ledger_compacted": self.ledger_compacted,
            "ledger_skipped": self.ledger_skipped,
            "ledger_failed": self.ledger_failed,
        }


@dataclass(slots=True)
class LedgerReconciliationReport:
    """Result of verifying stale ledger decisions against stored K-lines."""

    scanned: int = 0
    resolved: int = 0
    requeued: int = 0
    compacted: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def repair_status_value(status: Any) -> str:
    """Normalize native enum and adapter string statuses at the shared boundary."""
    return getattr(status, "value", str(status))
