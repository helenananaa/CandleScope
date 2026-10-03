"""Plan backfill demand against source availability and trading calendars.

Owns request clamping and no-fetch outcomes only. It has no scheduler, ledger,
cache or event callback, so availability rules can be exercised independently.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.data_engine.history.calendar import TradingCalendar
from app.data_engine.history.models import (
    BoundaryReason, HistoryAvailability, HistoryDisposition,
    HistoryPlan, HistoryRequest, HistorySeriesKey, TimeBound,
)
from app.data_engine.history.planner import HistoryRequestPlanner
from app.data_engine.history.service import HistoryAvailabilityService
from app.data_engine.interval_policy import last_closed_bar_open_ms
from app.data_engine.series_identity import identity_from_metadata
from app.exchanges.models import HistoryAvailabilityPolicy
from .backfill_contracts import HistoryPolicyResolver, RepairOutcome, RepairRequest

logger = logging.getLogger("data_manager.backfill_history")


@dataclass(slots=True)
class PreparedHistoryRequest:
    request: RepairRequest | None
    plan: HistoryPlan | None = None
    context: Any | None = None


class BackfillHistoryPlanner:
    """Availability and closed-bar admission policy for backfill requests."""

    def __init__(
        self,
        service: HistoryAvailabilityService | None = None,
        policy_resolver: HistoryPolicyResolver | None = None,
    ) -> None:
        self._history_service = service
        self._history_policy_resolver = policy_resolver

    @property
    def configured(self) -> bool:
        return self._history_service is not None or self._history_policy_resolver is not None

    def prepare(
        self,
        request: RepairRequest,
    ) -> PreparedHistoryRequest:
        plan, context = self.plan(request)
        if plan is None:
            # Alternate embeddings may omit the availability service.  Still
            # enforce the universal closed-bar edge before a request reaches
            # the fetch engine; otherwise a forming-only task is guaranteed to
            # normalize to zero historical bars and be retried as a failure.
            now_ms = int(time.time() * 1000)
            last_closed_ms = last_closed_bar_open_ms(now_ms, request.interval)
            if last_closed_ms is None or request.end_ms <= last_closed_ms:
                return PreparedHistoryRequest(request=request)
            history_request = HistoryRequest(
                series=self.series_key(request),
                interval=request.interval,
                start_ms=request.start_ms,
                end_ms=request.end_ms,
            )
            plan = HistoryRequestPlanner().plan(
                history_request,
                HistoryAvailability(calendar_id="crypto.24x7.utc"),
                now_ms=now_ms,
            )
        if not plan.has_fetch_work:
            return PreparedHistoryRequest(request=None, plan=plan, context=context)

        fetch_ranges = [
            {"start_ms": item.start_ms, "end_ms": item.end_ms}
            for item in plan.fetch_ranges
        ]
        prepared = RepairRequest(
            symbol=request.symbol,
            interval=request.interval,
            start_ms=plan.fetch_ranges[0].start_ms,
            end_ms=plan.fetch_ranges[-1].end_ms,
            exchange=request.exchange,
            market_type=request.market_type,
            reason=request.reason,
            priority=request.priority,
            requester=request.requester,
            wait_policy=request.wait_policy,
            metadata={
                **request.metadata,
                "history_fetch_ranges": fetch_ranges,
                "history_calendar_id": plan.calendar_id,
                "history_exclusions": [
                    {
                        "start_ms": item.time_range.start_ms,
                        "end_ms": item.time_range.end_ms,
                        "disposition": item.disposition.value,
                        "reason": item.reason.value,
                    }
                    for item in plan.exclusions
                ],
            },
            request_id=request.request_id,
        )
        return PreparedHistoryRequest(
            request=prepared,
            plan=plan,
            context=context,
        )

    def plan(
        self,
        request: RepairRequest,
    ) -> tuple[HistoryPlan | None, Any | None]:
        if self._history_service is None and self._history_policy_resolver is None:
            return None, None

        history_request = HistoryRequest(
            series=self.series_key(request),
            interval=request.interval,
            start_ms=request.start_ms,
            end_ms=request.end_ms,
        )
        context: Any | None = None
        if self._history_policy_resolver is not None:
            try:
                resolved = self._history_policy_resolver(request)
            except Exception as exc:
                logger.warning(
                    "History policy resolution failed for %s:%s:%s@%s: %s",
                    request.exchange,
                    request.market_type,
                    request.symbol,
                    request.interval,
                    exc,
                )
                return HistoryRequestPlanner.fail_closed(
                    history_request,
                    reason=BoundaryReason.AVAILABILITY_UNKNOWN,
                ), None
            if (
                isinstance(resolved, tuple)
                and len(resolved) == 2
                and isinstance(resolved[0], HistoryPlan)
            ):
                return resolved[0], resolved[1]
            context = resolved

        availability = self.availability(context)
        if availability is None:
            if self._history_policy_resolver is not None:
                return HistoryRequestPlanner.fail_closed(
                    history_request,
                    reason=BoundaryReason.AVAILABILITY_UNKNOWN,
                ), context
            availability = HistoryAvailability(calendar_id="crypto.24x7.utc")

        if self._history_service is not None:
            availability = self._history_service.resolve_availability(
                history_request.series,
                availability,
            )

        calendar = self.calendar(context, availability)
        if calendar is not None:
            return HistoryRequestPlanner(calendar).plan(
                history_request,
                availability,
            ), context
        if self._history_service is not None:
            return self._history_service.plan(
                history_request,
                availability,
                calendar_id=availability.calendar_id,
            ), context
        return HistoryRequestPlanner.fail_closed(
            history_request,
            reason=BoundaryReason.CALENDAR_UNKNOWN,
            calendar_id=availability.calendar_id,
        ), context

    @staticmethod
    def series_key(request: RepairRequest) -> HistorySeriesKey:
        identity = identity_from_metadata(request.exchange, request.metadata)
        return HistorySeriesKey.from_params(
            exchange=request.exchange,
            market_type=request.market_type,
            symbol=request.symbol,
            channel="kline",
            variant=request.interval,
            params=(identity.to_dict() if identity is not None else None),
        )

    @staticmethod
    def availability(context: Any | None) -> HistoryAvailability | None:
        if isinstance(context, HistoryAvailability):
            return context
        availability = getattr(context, "availability", None)
        if isinstance(availability, HistoryAvailability):
            return availability
        policy = (
            context
            if isinstance(context, HistoryAvailabilityPolicy)
            else getattr(context, "policy", None)
        )
        if not isinstance(policy, HistoryAvailabilityPolicy):
            return None
        return HistoryAvailability(
            upstream_start=(
                TimeBound(
                    policy.available_from_ms,
                    BoundaryReason.UPSTREAM_START,
                )
                if policy.available_from_ms is not None
                else None
            ),
            upstream_end=(
                TimeBound(
                    policy.available_to_ms,
                    BoundaryReason.UPSTREAM_END,
                )
                if policy.available_to_ms is not None
                else None
            ),
            rolling_retention_ms=policy.max_age_ms,
            calendar_id=policy.calendar_id,
        )

    def calendar(
        self,
        context: Any | None,
        availability: HistoryAvailability | None = None,
    ) -> TradingCalendar | None:
        calendar = getattr(context, "calendar", None)
        if isinstance(calendar, TradingCalendar):
            return calendar
        if self._history_service is None:
            return None
        calendar_id = (
            availability.calendar_id
            if availability is not None
            else None
        )
        return self._history_service.calendars.get(calendar_id)

    @staticmethod
    def no_fetch_outcome(
        request: RepairRequest,
        plan: HistoryPlan | None,
    ) -> RepairOutcome:
        if plan is None:
            return RepairOutcome(
                request=request,
                status="completed",
                retryable=True,
                error="history planning produced no request",
            )
        exclusion = next(
            (
                item
                for item in plan.exclusions
                if item.disposition is HistoryDisposition.TERMINAL
            ),
            plan.exclusions[0] if plan.exclusions else None,
        )
        reason = exclusion.reason.value if exclusion is not None else None
        lower_reasons = {
            BoundaryReason.DATA_START,
            BoundaryReason.LISTING,
            BoundaryReason.UPSTREAM_START,
            BoundaryReason.PROVIDER_RETENTION,
            BoundaryReason.SOURCE_EXHAUSTED,
        }
        exhausted_before_ms = (
            exclusion.bound.value_ms
            if exclusion is not None
            and exclusion.bound is not None
            and exclusion.reason in lower_reasons
            else None
        )
        retryable = plan.retryable or plan.unknown
        terminal_reason = (
            reason
            if plan.terminal or plan.disposition is HistoryDisposition.NOT_EXPECTED
            else None
        )
        return RepairOutcome(
            request=request,
            status="completed",
            verified_contiguous=(None if retryable else True),
            remaining_missing_bars=(None if retryable else 0),
            terminal_reason=terminal_reason,
            exhausted_before_ms=exhausted_before_ms,
            retryable=retryable,
            error=("history availability is unknown" if plan.unknown else None),
        )
