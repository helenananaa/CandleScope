"""Own retries and restart recovery for final bars, outside ingestion callbacks."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app.core.executors import run_storage
from app.data_engine.bar_delivery_errors import BarDeliveryUnavailable
from app.data_engine.interval_policy import is_ephemeral_interval, parse_interval_spec
from .models import BarData, DataEvent, DataEventType, SeriesKey

logger = logging.getLogger("data_manager.bar_delivery")


class DurableBarDelivery:
    def __init__(self, storage_provider, publish, *, retry_delay=0.1, max_submissions=64,
                 recovery_lookback_bars=500):
        self._storage_provider, self._publish = storage_provider, publish
        self.retry_delay = retry_delay
        self.owner = uuid.uuid4().hex
        self.recover_source = None
        self._dispatcher = asyncio.Lock()
        self._wake = asyncio.Event()
        self._worker = self._recovery = None
        self._closing = False
        self._submissions = set()
        self.max_submissions = max(1, max_submissions)
        self._admission_rejected = 0
        self._receipt_failed = False
        self.recovery_lookback_bars = max(1, recovery_lookback_bars)
        self._watched = {}
        self._pending = 0
        self._recovery_pending = 0
        self._recovery_cursor = None
        self._failures = 0
        self._last_error = None
        self._recovery_error = None
        self._published = self._rejected = 0

    @property
    def journal(self):
        return getattr(self._storage_provider(), "bar_delivery", None)

    def snapshot(self):
        return dict(mode="durable" if self.journal is not None else "legacy",
                    degraded=bool(self._last_error or self._recovery_error or self._receipt_failed),
                    pending=self._pending, recovery_pending=self._recovery_pending,
                    failures=self._failures, last_error=self._last_error,
                    recovery_error=self._recovery_error, unconfirmed_receipt=self._receipt_failed,
                    active_submissions=len(self._submissions), admission_rejected=self._admission_rejected,
                    published=self._published, rejected=self._rejected)

    async def start(self):
        self._closing = False
        if self.journal is not None and self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="bar-delivery")
            self._recovery = asyncio.create_task(self._recover(), name="bar-source-recovery")

    async def stop(self):
        self._closing = True
        tasks = {task for task in (self._worker, self._recovery, *self._submissions)
                 if task is not None and task is not asyncio.current_task()}
        for task in tasks:
            task.cancel()
        # A cancelled storage await drains its physical transaction. Even a
        # cancelled shutdown must wait for those writes before releasing watches.
        drain = asyncio.gather(*tasks, return_exceptions=True)
        cancelled = False
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                cancelled = True
        self._worker = self._recovery = None
        # Journaled receipts are independently recoverable. If even receipt
        # admission failed, retain the watch for authoritative source repair.
        if self.journal is not None and not self._receipt_failed:
            try:
                await run_storage(self.journal.release_watches, self.owner)
            except Exception:
                logger.exception("Bar recovery watches retained after shutdown write failure")
        self._watched.clear()
        if cancelled:
            raise asyncio.CancelledError

    async def prepare_series(self, key, *, from_ms=None):
        if self._closing:
            raise BarDeliveryUnavailable("Bar delivery is shutting down")
        if self.journal is None or is_ephemeral_interval(key.interval):
            return
        protected_from = self._watched.get(key)
        if protected_from is not None and (from_ms is None or from_ms >= protected_from):
            return
        spec = parse_interval_spec(key.interval)
        if spec is None:
            raise BarDeliveryUnavailable(f"Cannot protect recovery range for {key}")
        start = spec.floor_ms(int(time.time() * 1000))
        for _ in range(self.recovery_lookback_bars):
            start = max(0, spec.previous_ms(start))
            if start == 0:
                break
        if from_ms is not None:
            start = min(start, from_ms)
        series = dict(symbol=key.symbol, interval=key.interval, exchange=key.exchange,
                      market_type=key.market_type, **key.identity.to_dict())
        await self._retry(self.journal.watch, self.owner, series, start)
        self._watched[key] = min(start, self._watched.get(key, start))

    async def _retry(self, function, *args):
        for attempt in range(3):
            try:
                return await run_storage(function, *args)
            except Exception as exc:
                self._failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                if attempt == 2:
                    raise BarDeliveryUnavailable(self._last_error) from exc
                await asyncio.sleep(self.retry_delay * 2**attempt)

    async def submit(self, event_id, payload, key):
        if self._closing or len(self._submissions) >= self.max_submissions:
            self._receipt_failed = True
            self._admission_rejected += 1
            raise BarDeliveryUnavailable("Bar delivery is shutting down or at admission capacity")
        task = asyncio.current_task()
        self._submissions.add(task)
        try:
            return await self._submit(event_id, payload, key)
        finally:
            self._submissions.discard(task)

    async def _submit(self, event_id, payload, key):
        try:
            await self.prepare_series(key, from_ms=payload["storage_row"]["open_time"])
            record = await self._retry(self.journal.enqueue, event_id, payload)
        except BaseException:
            # Includes cancellation in the interval where commit outcome is
            # unknown to this observer. Retaining a source watch is conservative.
            self._receipt_failed = True
            raise
        self._wake.set()
        if record["phase"] in {"published", "rejected"}:
            return record["phase"]
        # Never accumulate ingestion callbacks waiting for a dispatcher lock.
        # Admission is already durable; the one dispatcher owns its completion.
        if not self._dispatcher.locked():
            await self.flush()
        return "accepted"

    async def flush(self):
        journal = self.journal
        if journal is None:
            return
        async with self._dispatcher:
            try:
                records = await self._retry(journal.pending)
                self._pending = await self._retry(journal.pending_count)
                for pending in records:
                    record = await self._retry(journal.commit, pending["event_id"])
                    if record["phase"] == "rejected":
                        self._rejected += 1
                    elif record["phase"] == "committed":
                        # A later authoritative repair may already have replaced
                        # this row while publication was interrupted. Publish a
                        # current correction, never roll a cold cache backward.
                        if record["canonical_row"] is not None:
                            await self._publish(self._event(record))
                        await self._retry(journal.acknowledge, record["event_id"])
                        self._published += 1
                    self._pending -= 1
                self._last_error = None
                if len(records) == 64:
                    self._wake.set()
            except Exception as exc:
                self._failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Final bar delivery deferred; durable receipt retained: %s", exc)

    @staticmethod
    def _event(record):
        value = record["payload"]
        identity_names = ("provider_id", "venue", "asset_class", "series_variant", "price_adjustment", "session_variant", "volume_semantics")
        key = SeriesKey(value["symbol"], value["interval"], exchange=value["exchange"],
                        market_type=value["market_type"], **{k: value[k] for k in identity_names if k in value})
        current = record["canonical_row"]
        superseded = any(current.get(k) != v for k, v in value["storage_row"].items()) or current["source"] != value["bar"]["source"]
        return DataEvent(DataEventType.BAR_AMENDED if superseded else DataEventType(value["event_type"]), key,
                         BarData.from_storage_row(current) if superseded else BarData.from_dict(value["bar"]),
                         BarData.from_dict(value["previous_bar"]) if value.get("previous_bar") and not superseded else None,
                         detail={**value.get("detail", {}), "delivery_id": record["event_id"],
                                 "delivery_sequence": record["sequence"], "canonical_reconciled": superseded},
                         timestamp_ms=value["timestamp_ms"])

    async def _run(self):
        while True:
            self._wake.clear()
            await self.flush()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except TimeoutError:
                pass

    async def recover_once(self):
        if self._receipt_failed:
            self._receipt_failed = False
            try:
                await self._retry(self.journal.capture_failed_watches, self.owner)
            except BaseException:
                self._receipt_failed = True
                raise
        through_ms = int(time.time() * 1000)
        watches = await self._retry(self.journal.recovery_watches, self.owner, through_ms,
                                    32, self._recovery_cursor)
        if not watches and self._recovery_cursor is not None:
            self._recovery_cursor = None
            watches = await self._retry(self.journal.recovery_watches, self.owner, through_ms)
        self._recovery_pending = await self._retry(self.journal.recovery_pending_count, self.owner)
        if watches and self.recover_source is None:
            self._recovery_error = "Authoritative source recovery is not configured"
            return
        for watch in watches:
            try:
                if await self.recover_source(watch):
                    await self._retry(self.journal.finish_recovery, watch["watch_id"])
                    self._recovery_pending -= 1
                else:
                    self._recovery_error = f"Source recovery incomplete: {watch['watch_id']}"
            except Exception as exc:
                self._recovery_error = f"Source recovery failed: {watch['watch_id']}: {type(exc).__name__}: {exc}"
                logger.warning("Bar source recovery deferred: %s", self._recovery_error)
            # Advance after failures too, so an unavailable batch cannot starve
            # later watches. Cancellation still propagates without advancing.
            self._recovery_cursor = (watch["from_ms"], watch["watch_id"])
        # A successful page does not mean earlier failed watches have recovered.
        if self._recovery_pending == 0:
            self._recovery_error = None
            self._recovery_cursor = None

    async def _recover(self):
        while True:
            try:
                await self.recover_once()
            except Exception as exc:
                self._recovery_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Bar source recovery deferred: %s", exc)
            await asyncio.sleep(5)


def source_recovery_handler(coordinator):
    """Reuse the existing paged, provider-aware authoritative repair path."""
    async def recover(watch):
        from .backfill_contracts import RepairRequest
        series = watch["series"]
        spec = parse_interval_spec(series["interval"])
        if spec is None:
            return False
        end = spec.previous_ms(spec.floor_ms(watch["through_ms"]))
        from app.data_engine.history.exchange_policy import native_kline_calendar
        from app.data_engine.history.calendar import latest_closed_expected_open_ms
        calendar = native_kline_calendar(series["exchange"], series["market_type"], series["interval"])
        if calendar is not None:
            end = latest_closed_expected_open_ms(calendar, watch["through_ms"], series["interval"])
            if end is None:
                return False
        if end < watch["from_ms"]:
            return True
        key = SeriesKey(**series)
        outcome = await coordinator.request_and_wait(RepairRequest(
            symbol=key.symbol, interval=key.interval, exchange=key.exchange, market_type=key.market_type,
            start_ms=watch["from_ms"], end_ms=end, reason="bar_delivery_recovery", priority=50,
            requester="bar_delivery", metadata={"requires_trusted_finality": True,
                "series_identity": key.identity.to_dict(), "recovery_watch_id": watch["watch_id"]}))
        status = getattr(outcome.status, "value", outcome.status)
        return status == "completed" and outcome.verified_contiguous is True and not outcome.error
    return recover
