"""Retrying execution of one BackfillCoordinator request and its delivery to the cache.

Split out of ``backfill_coordinator.py`` without changes (ADR-DATA-001 §8,
S4). ``BackfillCoordinator`` inherits this mixin; the state it reads and
writes is created in ``BackfillCoordinator.__init__``.
"""
from __future__ import annotations

import asyncio
import logging
from itertools import islice
from typing import Any

from app.core.executors import run_storage
from app.data_engine.backfill.fetch_stream import StreamBackfillDeferred
from app.data_engine.backfill.native_progress import NativeBackfillDeferred
from app.data_engine.interval_policy import parse_interval_ms
from app.data_engine.kline_quality import repair_requires_trusted_finality, source_is_trusted_final
from app.data_engine.series_identity import identity_from_metadata
from app.exchanges.rate_limits import RateLimitDeferred

from .backfill_contracts import RepairOutcome, RepairRetryDeferred, _merge_derived_repair_targets
from .models import BarData, DataEvent, DataEventType, SeriesKey, audience_for_backfill_reason

# The coordinator's logger: log filters and captures keep working on the moved code.
logger = logging.getLogger("data_manager.backfill_coordinator")


class BackfillExecution:
    """Run one request with retries, verify it and hand its bars to the cache."""

    async def _run_with_retries(self, request: RepairRequest) -> RepairOutcome:
        next_attempt = request._retry_attempt
        scheduled_request = request
        prepared = self._history_planner.prepare(request)
        close_delay = self._history_planner.source_second_close_delay(request, prepared.plan)
        if close_delay is not None:
            # No physical attempt occurred. Preserve the retry budget while
            # yielding this slot until the host can fetch the closed second.
            raise RepairRetryDeferred(close_delay, max(0, next_attempt - 1))
        if prepared.request is None:
            return self._history_planner.no_fetch_outcome(request, prepared.plan)
        request = prepared.request
        history_context = prepared.context

        if self._engine is None:
            return RepairOutcome(
                request=request,
                status="failed",
                error="BackfillEngine is not configured",
            )

        last_error: str | None = None
        report: Any | None = None

        for attempt in range(next_attempt, self._max_retries + 1):
            try:
                await self._ledger_mark_started(request, attempt=attempt)
                run_engine = (self._engine.run_receipt
                    if callable(getattr(type(self._engine),'run_receipt',None)) else self._engine.run)
                report = await run_engine(
                    symbol=request.symbol,
                    intervals=[request.interval],
                    range_start_ms=request.start_ms,
                    range_end_ms=request.end_ms,
                    exchange=request.exchange,
                    market_type=request.market_type,
                    metadata={
                        **request.metadata,
                        "reason": request.reason,
                        "priority": request.priority,
                        "requester": request.requester,
                        "request_id": request.request_id,
                    },
                    **({"native_progress": scheduled_request._native_progress}
                       if scheduled_request._native_progress is not None else {}),
                )
                await self._notify_source_storage(request, report)
                if self._is_failed(report.status) and attempt < self._max_retries:
                    delay = self._backoff(attempt)
                    await self._ledger_mark_retry_wait(
                        request,
                        attempt=attempt,
                        error="; ".join(report.errors) if report.errors else None,
                        delay_seconds=delay,
                    )
                    raise RepairRetryDeferred(delay, attempt)

                bars_loaded = 0
                verification: dict[str, Any] = {
                    "verified_contiguous": None,
                    "remaining_missing_bars": None,
                }
                verification_incomplete = False
                terminal_reason: str | None = None
                exhausted_before_ms: int | None = None
                boundary_checked = False
                requires_trusted_finality = repair_requires_trusted_finality(
                    request.metadata,
                    reason=request.reason,
                )
                if not self._is_failed(report.status):
                    await self._ledger_mark_verifying(request)
                    verification = await self._verify_request_range(
                        request,
                        context=history_context,
                        include_rows=True,
                    )
                    verification_incomplete = bool(
                        verification.get("verified_contiguous") is False
                    )
                    if verification_incomplete and not requires_trusted_finality:
                        terminal_reason, exhausted_before_ms = (
                            await self._record_confirmed_left_boundary(
                                request,
                                report,
                                context=history_context,
                            )
                        )
                        boundary_checked = True
                    confirmed_terminal = terminal_reason is not None
                    if (
                        verification_incomplete
                        and not confirmed_terminal
                        and attempt < self._max_retries
                    ):
                        delay = self._backoff(attempt)
                        remaining = verification.get("remaining_missing_bars")
                        await self._ledger_mark_retry_wait(
                            request,
                            attempt=attempt,
                            error=(
                                "backfill verification incomplete"
                                f" ({remaining} rows remain)"
                            ),
                            delay_seconds=delay,
                        )
                        raise RepairRetryDeferred(delay, attempt)
                    bars_loaded = await self._load_backfilled_to_cache(
                        request,
                        report,
                        verification,
                    )
                    await self._emit_completion_if_needed(
                        request,
                        report,
                        bars_loaded,
                        verification,
                    )

                if self._is_failed(report.status):
                    await self._emit_failed(request, report)

                if (
                    not self._is_failed(report.status)
                    and not boundary_checked
                    and not (
                        verification_incomplete
                        and requires_trusted_finality
                    )
                ):
                    terminal_reason, exhausted_before_ms = (
                        await self._record_confirmed_left_boundary(
                            request,
                            report,
                            context=history_context,
                        )
                    )

                if verification.get("verified_contiguous") is True:
                    await self._ledger_record_verified_native_chunk(request, verification.get("_rows", []))
                return RepairOutcome(
                    request=request,
                    status=report.status,
                    report=self._summarize_report(report),
                    attempts=attempt,
                    bars_loaded=bars_loaded,
                    verified_contiguous=verification.get("verified_contiguous"),
                    remaining_missing_bars=verification.get("remaining_missing_bars"),
                    error="; ".join(report.errors) if report.errors else None,
                    terminal_reason=terminal_reason,
                    exhausted_before_ms=exhausted_before_ms,
                    retryable=(
                        (
                            verification_incomplete
                            and terminal_reason is None
                        )
                        or self._report_retryable(report)
                    ),
                )
            except RepairRetryDeferred:
                raise
            except RateLimitDeferred as exc:
                progress = exc.progress if isinstance(exc, NativeBackfillDeferred) else None
                if progress is not None:
                    scheduled_request._native_progress = progress
                await self._ledger_mark_retry_wait(
                    request,
                    attempt=attempt,
                    error=(
                        f"rate_limit_deferred:{exc.bucket_key}:{exc.reason}"
                    ),
                    delay_seconds=exc.retry_after_seconds,
                    retry_at_ms=exc.retry_at_ms,
                    native_progress=progress,
                )
                if progress is not None or isinstance(exc,StreamBackfillDeferred):
                    await self._notify_source_storage(request, exc)
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = str(exc)
                logger.error(
                    "Backfill task error for %s@%s attempt %d/%d: %s",
                    request.symbol,
                    request.interval,
                    attempt,
                    self._max_retries,
                    exc,
                    exc_info=True,
                )
                if attempt < self._max_retries:
                    delay = self._backoff(attempt)
                    await self._ledger_mark_retry_wait(
                        request,
                        attempt=attempt,
                        error=last_error,
                        delay_seconds=delay,
                    )
                    raise RepairRetryDeferred(delay, attempt)

        await self._emit_failed(request, report, last_error)
        return RepairOutcome(
            request=request,
            status="failed",
            report=self._summarize_report(report),
            attempts=self._max_retries,
            error=last_error,
        )

    async def _notify_source_storage(self, request: RepairRequest, report: Any) -> None:
        """Wake exact source proofs before whole-request verification/retry.

        This private notification does not publish a completion or admit rows.
        Native absence can commit without any candle/write count, and an
        otherwise partial run can have durable inputs for another interval.
        DataManager must independently re-read canonical data and D126 tokens.
        """
        if self._source_available is None:
            return
        identity = identity_from_metadata(request.exchange, request.metadata)
        identity_kwargs = identity.to_dict() if identity is not None else {}
        intervals = {request.interval}
        ranges = getattr(getattr(report, 'reconcile_result', None), 'written_ranges', ()) or ()
        for item in islice(ranges, 4096):
            read = item.get if isinstance(item, dict) else lambda name: getattr(item, name, None)
            if (read('exchange'), read('market_type'), read('symbol')) != (
                    request.exchange, request.market_type, request.symbol):
                continue
            interval = read('interval')
            if isinstance(interval, str) and interval:
                intervals.add(interval)
            if len(intervals) >= 32:
                break
        for interval in sorted(intervals):
            key = SeriesKey(request.symbol, interval, exchange=request.exchange,
                            market_type=request.market_type, **identity_kwargs)
            try:
                await self._source_available(key)
            except Exception:
                logger.exception('Canonical source availability refresh failed for %s', key)

    async def _load_backfilled_to_cache(
        self,
        request: RepairRequest,
        report: Any,
        verification: dict[str, Any] | None = None,
    ) -> int:
        if self._total_bars_written(report) <= 0:
            return 0

        total_loaded = 0
        series_identity = identity_from_metadata(request.exchange, request.metadata)
        identity_kwargs = (
            {"series_identity": series_identity}
            if series_identity is not None
            else {}
        )
        derived_targets = _merge_derived_repair_targets(
            request.metadata.get("derived_repair_targets"),
        )
        verified_rows = (
            (verification or {}).get("_rows")
            if isinstance(verification, dict)
            else None
        )
        for written_range in self._written_ranges_for_request(request, report):
            if isinstance(verified_rows, list):
                range_start = int(written_range["start_ms"])
                range_end = int(written_range["end_ms"])
                rows = [
                    row
                    for row in verified_rows
                    if range_start <= int(row["open_time"]) <= range_end
                ]
            else:
                rows = await run_storage(
                    self._storage.query_bars,
                    symbol=written_range["symbol"],
                    interval=written_range["interval"],
                    start_ms=written_range["start_ms"],
                    end_ms=written_range["end_ms"],
                    order="ASC",
                    exchange=written_range["exchange"],
                    market_type=written_range["market_type"],
                    **identity_kwargs,
                )
            bars = [
                BarData.from_storage_row(
                    row,
                    exchange=written_range["exchange"],
                    market_type=written_range["market_type"],
                )
                for row in rows
            ]

            if not bars:
                continue

            await self._bars_backfilled(
                written_range["symbol"],
                written_range["interval"],
                bars,
                exchange=written_range["exchange"],
                market_type=written_range["market_type"],
                **(
                    {"series_identity": series_identity}
                    if series_identity is not None
                    else {}
                ),
                event_detail={
                    "request_id": request.request_id,
                    "status": self._status_value(report.status),
                    "reason": request.reason,
                    "priority": request.priority,
                    "requester": request.requester,
                    "range_start_ms": written_range["start_ms"],
                    "range_end_ms": written_range["end_ms"],
                    "request_start_ms": request.start_ms,
                    "request_end_ms": request.end_ms,
                    "verified_contiguous": (
                        verification or {}
                    ).get("verified_contiguous"),
                    "remaining_missing_bars": (
                        verification or {}
                    ).get("remaining_missing_bars"),
                    **(
                        {"derived_repair_targets": derived_targets}
                        if derived_targets else {}
                    ),
                },
            )
            total_loaded += len(bars)

        return total_loaded

    async def _emit_completion_if_needed(
        self,
        request: RepairRequest,
        report: Any,
        bars_loaded: int,
        verification: dict[str, Any] | None = None,
    ) -> None:
        if bars_loaded > 0:
            return
        derived_targets = _merge_derived_repair_targets(
            request.metadata.get("derived_repair_targets"),
        )
        series_identity = identity_from_metadata(request.exchange, request.metadata)
        await self._emit_event(DataEvent(
            event_type=DataEventType.BACKFILL_COMPLETED,
            key=SeriesKey(
                request.symbol,
                request.interval,
                exchange=request.exchange,
                market_type=request.market_type,
                **(series_identity.to_dict() if series_identity is not None else {}),
            ),
            audience=audience_for_backfill_reason(request.reason),
            detail={
                "request_id": request.request_id,
                "status": self._status_value(report.status),
                "reason": request.reason,
                "priority": request.priority,
                "requester": request.requester,
                "bars_count": 0,
                "range_start_ms": request.start_ms,
                "range_end_ms": request.end_ms,
                "request_start_ms": request.start_ms,
                "request_end_ms": request.end_ms,
                "verified_contiguous": (
                    verification or {}
                ).get("verified_contiguous"),
                "remaining_missing_bars": (
                    verification or {}
                ).get("remaining_missing_bars"),
                **(
                    {"derived_repair_targets": derived_targets}
                    if derived_targets else {}
                ),
            },
        ))

    async def _emit_failed(
        self,
        request: RepairRequest,
        report: Any | None = None,
        error: str | None = None,
    ) -> None:
        series_identity = identity_from_metadata(request.exchange, request.metadata)
        await self._emit_event(DataEvent(
            event_type=DataEventType.BACKFILL_FAILED,
            key=SeriesKey(
                request.symbol,
                request.interval,
                exchange=request.exchange,
                market_type=request.market_type,
                **(series_identity.to_dict() if series_identity is not None else {}),
            ),
            detail={
                "request_id": request.request_id,
                "status": self._status_value(report.status) if report is not None else "failed",
                "reason": request.reason,
                "priority": request.priority,
                "requester": request.requester,
                "source_gap_id": request.metadata.get("source_gap_id"),
                "range_start_ms": request.start_ms,
                "range_end_ms": request.end_ms,
                "errors": report.errors if report is not None else ([error] if error else []),
            },
        ))

    async def _verify_request_range(
        self,
        request: RepairRequest,
        *,
        context: Any | None = None,
        include_rows: bool = False,
    ) -> dict[str, Any]:
        query_bars = getattr(self._storage, "query_bars", None)
        if not callable(query_bars):
            return {
                "verified_contiguous": None,
                "remaining_missing_bars": None,
            }

        interval_ms = parse_interval_ms(request.interval)
        if interval_ms is None or interval_ms <= 0 or request.start_ms > request.end_ms:
            return {
                "verified_contiguous": None,
                "remaining_missing_bars": None,
            }

        series_identity = identity_from_metadata(request.exchange, request.metadata)
        identity_kwargs = (
            {"series_identity": series_identity}
            if series_identity is not None
            else {}
        )
        try:
            rows = await run_storage(
                query_bars,
                symbol=request.symbol,
                interval=request.interval,
                start_ms=request.start_ms,
                end_ms=request.end_ms,
                order="ASC",
                exchange=request.exchange,
                market_type=request.market_type,
                **identity_kwargs,
            )
        except Exception as exc:
            logger.warning(
                "Backfill verification query failed for %s:%s:%s@%s %d-%d: %s",
                request.exchange,
                request.market_type,
                request.symbol,
                request.interval,
                request.start_ms,
                request.end_ms,
                exc,
            )
            return {
                "verified_contiguous": None,
                "remaining_missing_bars": None,
            }

        physical_actual = {int(row["open_time"]) for row in rows}
        requires_trusted_finality = repair_requires_trusted_finality(
            request.metadata,
            reason=request.reason,
        )
        trusted_rows = [
            row for row in rows
            if source_is_trusted_final(row.get("source"))
        ]
        actual = (
            {int(row["open_time"]) for row in trusted_rows}
            if requires_trusted_finality
            else physical_actual
        )
        if request.metadata.get("history_verification") == "provider_authoritative_sparse":
            result = {
                "verified_contiguous": True,
                "remaining_missing_bars": 0,
                "expected_bars": None,
                "actual_bars": len(physical_actual),
                "verified_bars": len(actual),
                "verification_mode": "provider_authoritative_sparse",
            }
            if include_rows:
                result["_rows"] = (
                    trusted_rows if requires_trusted_finality else rows
                )
            return result
        calendar = self._history_planner.calendar(
            context,
            self._history_planner.availability(context),
        )
        if calendar is None and self._history_service is not None:
            calendar = self._history_service.calendars.get(
                request.metadata.get("history_calendar_id")
            )
        if calendar is not None:
            try:
                expected_opens = set(calendar.expected_opens(
                    request.start_ms,
                    request.end_ms,
                    request.interval,
                ))
            except Exception as exc:
                logger.warning(
                    "Calendar verification failed for %s:%s:%s@%s: %s",
                    request.exchange,
                    request.market_type,
                    request.symbol,
                    request.interval,
                    exc,
                )
                return {
                    "verified_contiguous": None,
                    "remaining_missing_bars": None,
                }
        else:
            expected_opens: set[int] = set()
            current = int(request.start_ms)
            while current <= request.end_ms:
                expected_opens.add(current)
                current += interval_ms

        missing = len(expected_opens - actual)

        result = {
            "verified_contiguous": missing == 0,
            "remaining_missing_bars": missing,
            "expected_bars": len(expected_opens),
            "actual_bars": len(physical_actual),
        }
        if requires_trusted_finality:
            result.update({
                "verified_bars": len(actual),
                "requires_trusted_finality": True,
                "untrusted_final_bars": len(
                    expected_opens & (physical_actual - actual)
                ),
            })
        if include_rows:
            # Private handoff to cache reload: verification already paid for
            # this exact storage range, so do not immediately query it again.
            result["_rows"] = trusted_rows if requires_trusted_finality else rows
        return result
