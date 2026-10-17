"""Background loop that drives local practice accounts from live 1m candles.

Each step replays the 1m candles of one instrument with working orders from
its cursor up to the present. Live matching and catch-up after downtime are
the same operation; a history gap pauses the instrument (status
``catching_up``) instead of guessing what happened inside it.

Steps are triggered two ways:

- a live 1m update (DataManager ``BAR_*`` event) for an instrument wakes the
  loop at once; bursts coalesce into one step per ``EVENT_MIN_GAP_SECONDS``;
- a sweep every ``tick_seconds`` syncs streams with the working orders and
  steps every instrument that had no event-driven step since the last sweep,
  which is the catch-up path when events stop or were dropped.

A step is one storage-executor job: query the candles, match, persist. Its
timing (event -> applied) is recorded on the feed and returned by
``account_summary``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

from app.core.executors import run_storage
from app.data_engine.data_manager.models import DataEvent, DataEventType

from .service import Instrument, TradingAccountService

logger = logging.getLogger("trading_accounts.practice")

INTERVAL = "1m"
BAR_SECONDS = 60
MAX_BARS_PER_TICK = 1_000
# Live updates arriving while a step runs are folded into the next step; this
# bounds steps per instrument without adding more than a blink of latency.
EVENT_MIN_GAP_SECONDS = 0.1
STEP_EVENTS = frozenset({DataEventType.BAR_CREATED, DataEventType.BAR_UPDATED, DataEventType.BAR_CLOSED})


def _bar_dict(bar: Any) -> dict[str, Any]:
    return {
        "time": int(bar.time),
        "open": Decimal(repr(float(bar.open))),
        "high": Decimal(repr(float(bar.high))),
        "low": Decimal(repr(float(bar.low))),
        "close": Decimal(repr(float(bar.close))),
        "is_closed": bool(getattr(bar, "is_closed", True)),
    }


def _wall_ms() -> int:
    return int(time.time() * 1000)


class DataManagerMarket:
    """``MarketPort`` over the live DataManager (call from worker threads)."""

    def __init__(self, data_manager: Any) -> None:
        self.data_manager = data_manager

    def latest_bar(self, exchange: str, market_type: str, symbol: str) -> dict[str, Any] | None:
        result = self.data_manager.query_latest(
            symbol,
            INTERVAL,
            limit=1,
            exchange=exchange,
            market_type=market_type,
            auto_backfill=False,
            backfill_reason=None,
            backfill_requester="trading_accounts",
        )
        bars = list(getattr(result, "bars", None) or [])
        return _bar_dict(bars[-1]) if bars else None

    def bars(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        result = self.data_manager.query(
            symbol,
            interval,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
            exchange=exchange,
            market_type=market_type,
            auto_backfill=True,
            backfill_reason="practice_replay",
            backfill_requester="trading_accounts",
        )
        bars = [_bar_dict(bar) for bar in (getattr(result, "bars", None) or [])]
        complete = not getattr(result, "missing_ranges", None)
        return bars, complete


def contiguous_bars(
    bars: list[dict[str, Any]],
    start_time: int,
    *,
    complete: bool,
) -> tuple[list[dict[str, Any]], bool]:
    """Bars from ``start_time`` without unexplained gaps; second value = gap hit."""
    out: list[dict[str, Any]] = []
    expected = start_time
    for bar in sorted(bars, key=lambda item: item["time"]):
        if bar["time"] < expected:
            continue
        if bar["time"] > expected and not complete:
            return out, True
        out.append(bar)
        expected = bar["time"] + BAR_SECONDS
    return out, False


class PracticeRuntime:
    def __init__(
        self,
        service: TradingAccountService,
        data_manager: Any,
        *,
        tick_seconds: float = 1.0,
        market: Any | None = None,
    ) -> None:
        self.service = service
        self.data_manager = data_manager
        self.market = market if market is not None else DataManagerMarket(data_manager)
        self.tick_seconds = max(0.2, float(tick_seconds))
        self._task: asyncio.Task[None] | None = None
        self._streams: set[Instrument] = set()
        self._handles: dict[Instrument, Any] = {}
        # Instrument -> wall time of its oldest live update not yet applied.
        self._pending: dict[Instrument, int] = {}
        self._stepped: set[Instrument] = set()
        self._wake = asyncio.Event()
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="trading-practice-runtime")

    async def stop(self) -> None:
        self._running = False
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for instrument in list(self._streams):
            await self._release(instrument)
        try:
            await run_storage(self.service.flush_feeds)
        except Exception:
            logger.warning("Failed to flush practice cursors", exc_info=True)

    async def _loop(self) -> None:
        next_sweep = 0.0
        while self._running:
            self._wake.clear()
            try:
                if time.monotonic() >= next_sweep:
                    next_sweep = time.monotonic() + self.tick_seconds
                    await self.tick()
                else:
                    await self.drain_events()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Practice runtime step failed")
            if self._pending:
                await asyncio.sleep(EVENT_MIN_GAP_SECONDS)
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), max(0.0, next_sweep - time.monotonic()))
            except TimeoutError:
                pass

    async def tick(self) -> None:
        """Sweep: sync streams, then step instruments that events did not."""
        instruments = set(await run_storage(self.service.working_instruments))
        for instrument in instruments - self._streams:
            await self._ensure(instrument)
        for instrument in self._streams - instruments:
            await self._release(instrument)
        stepped, self._stepped = self._stepped, set()
        for instrument in instruments:
            event_ms = self._pending.pop(instrument, None)
            if event_ms is not None or instrument not in stepped:
                await self._advance(instrument, event_ms=event_ms)

    async def drain_events(self) -> None:
        pending, self._pending = self._pending, {}
        for instrument, event_ms in pending.items():
            if instrument in self._streams:
                await self._advance(instrument, event_ms=event_ms)
                self._stepped.add(instrument)

    def notify(self, instrument: Instrument, event_ms: int) -> None:
        """Record a live update for ``instrument`` and wake the loop."""
        previous = self._pending.get(instrument)
        self._pending[instrument] = event_ms if previous is None else min(previous, event_ms)
        self._wake.set()

    @staticmethod
    def _consumer(instrument: Instrument) -> str:
        return "practice:" + ":".join(instrument)

    async def _ensure(self, instrument: Instrument) -> None:
        exchange, market_type, symbol = instrument

        async def _on_event(event: DataEvent) -> None:
            if event.bar is not None:
                self.notify(instrument, int(event.timestamp_ms))

        async def _on_recovery(_error: Any) -> None:
            # Events were dropped; the step re-reads candles from the cursor.
            self.notify(instrument, _wall_ms())

        try:
            # The alerts tier keeps a durable, background-priority 1m stream
            # without foreground chart work, which is what the matcher needs.
            await self.data_manager.ensure_stream(
                symbol,
                INTERVAL,
                exchange=exchange,
                market_type=market_type,
                focus_scope="background",
                subscription_tier="alerts",
                consumer_id=self._consumer(instrument),
            )
            self._streams.add(instrument)
        except Exception as exc:
            logger.warning("Practice stream unavailable for %s: %s", instrument, exc)
            await run_storage(self.service.set_feed_status, instrument, "unavailable", str(exc))
            return
        try:
            self._handles[instrument] = self.data_manager.subscribe(
                callback=_on_event,
                on_recovery=_on_recovery,
                symbol=symbol,
                interval=INTERVAL,
                exchange=exchange,
                market_type=market_type,
                event_types=set(STEP_EVENTS),
            )
        except Exception:
            # The sweep still matches this instrument, only less promptly.
            logger.warning("Practice event subscription failed for %s", instrument, exc_info=True)

    async def _release(self, instrument: Instrument) -> None:
        self._streams.discard(instrument)
        self._pending.pop(instrument, None)
        handle = self._handles.pop(instrument, None)
        if handle is not None:
            try:
                self.data_manager.unsubscribe(handle)
            except Exception:
                logger.debug("Failed to unsubscribe practice events %s", instrument, exc_info=True)
        exchange, market_type, symbol = instrument
        try:
            await self.data_manager.release_stream(
                symbol,
                INTERVAL,
                exchange=exchange,
                market_type=market_type,
                focus_scope="background",
                subscription_tier="alerts",
                consumer_id=self._consumer(instrument),
            )
        except Exception:
            logger.debug("Failed to release practice stream %s", instrument, exc_info=True)

    async def _advance(self, instrument: Instrument, *, event_ms: int | None = None) -> None:
        timing = await run_storage(self._step, instrument, _wall_ms(), time.perf_counter(), event_ms)
        if timing is not None:
            logger.debug("Practice step %s: %s", ":".join(instrument), timing)

    def _step(
        self,
        instrument: Instrument,
        submitted_ms: int,
        submitted: float,
        event_ms: int | None,
    ) -> dict[str, int] | None:
        """Query candles from the cursor and match them (storage worker)."""
        started = time.perf_counter()
        start_ms = self.service.cursor_start_ms(instrument)
        if start_ms is None:
            return None
        now = _wall_ms()
        end_ms = min(now, start_ms + (MAX_BARS_PER_TICK - 1) * BAR_SECONDS * 1000)
        try:
            bars, complete = self.market.bars(*instrument, INTERVAL, start_ms, end_ms, MAX_BARS_PER_TICK)
        except Exception as exc:
            self.service.set_feed_status(instrument, "unavailable", str(exc))
            return None
        queried = time.perf_counter()
        usable, gap = contiguous_bars(bars, start_ms // 1000, complete=complete)
        behind = now - start_ms > 3 * BAR_SECONDS * 1000
        fills = 0
        if gap or (not usable and behind):
            status, detail = "catching_up", "Waiting for 1m history before matching further"
        else:
            status, detail = "live", ""
        if usable:
            fills = self.service.apply_market_bars(
                instrument, usable, observed_ms=now, status=status, detail=detail,
            )
        elif status != "live":
            self.service.set_feed_status(instrument, status, detail)
        done = time.perf_counter()
        timing = {
            "queueMs": round((started - submitted) * 1000),
            "queryMs": round((queried - started) * 1000),
            "applyMs": round((done - queried) * 1000),
            "bars": len(usable),
            "fills": fills,
            "measuredAtMs": _wall_ms(),
        }
        if event_ms is not None:
            # Event creation -> step submitted: event-loop dispatch, the
            # coalescing gap and other instruments' steps.
            timing["wakeMs"] = max(0, submitted_ms - event_ms)
            timing["lagMs"] = max(0, timing["measuredAtMs"] - event_ms)
            self.service.record_feed_timing(instrument, timing)
        return timing
