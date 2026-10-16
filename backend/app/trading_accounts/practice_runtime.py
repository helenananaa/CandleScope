"""Background loop that drives local practice accounts from live 1m candles.

Every tick replays the 1m candles of each instrument with working orders from
its cursor up to the present. Live matching and catch-up after downtime are
the same operation; a history gap pauses the instrument (status
``catching_up``) instead of guessing what happened inside it.
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

from app.core.executors import run_storage

from .service import Instrument, TradingAccountService

logger = logging.getLogger("trading_accounts.practice")

INTERVAL = "1m"
BAR_SECONDS = 60
MAX_BARS_PER_TICK = 1_000


def _bar_dict(bar: Any) -> dict[str, Any]:
    return {
        "time": int(bar.time),
        "open": Decimal(repr(float(bar.open))),
        "high": Decimal(repr(float(bar.high))),
        "low": Decimal(repr(float(bar.low))),
        "close": Decimal(repr(float(bar.close))),
        "is_closed": bool(getattr(bar, "is_closed", True)),
    }


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
    ) -> None:
        self.service = service
        self.data_manager = data_manager
        self.market = DataManagerMarket(data_manager)
        self.tick_seconds = max(0.2, float(tick_seconds))
        self._task: asyncio.Task[None] | None = None
        self._streams: set[Instrument] = set()
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="trading-practice-runtime")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for instrument in list(self._streams):
            await self._release(instrument)

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Practice runtime tick failed")
            await asyncio.sleep(self.tick_seconds)

    async def tick(self) -> None:
        instruments = set(await run_storage(self.service.working_instruments))
        for instrument in instruments - self._streams:
            await self._ensure(instrument)
        for instrument in self._streams - instruments:
            await self._release(instrument)
        for instrument in instruments:
            await self._advance(instrument)

    @staticmethod
    def _consumer(instrument: Instrument) -> str:
        return "practice:" + ":".join(instrument)

    async def _ensure(self, instrument: Instrument) -> None:
        exchange, market_type, symbol = instrument
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

    async def _release(self, instrument: Instrument) -> None:
        self._streams.discard(instrument)
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

    async def _advance(self, instrument: Instrument) -> None:
        start_ms = await run_storage(self.service.cursor_start_ms, instrument)
        if start_ms is None:
            return
        now = int(time.time() * 1000)
        end_ms = min(now, start_ms + (MAX_BARS_PER_TICK - 1) * BAR_SECONDS * 1000)
        try:
            bars, complete = await run_storage(
                self.market.bars, *instrument, INTERVAL, start_ms, end_ms, MAX_BARS_PER_TICK,
            )
        except Exception as exc:
            await run_storage(self.service.set_feed_status, instrument, "unavailable", str(exc))
            return
        usable, gap = contiguous_bars(bars, start_ms // 1000, complete=complete)
        if usable:
            await run_storage(self.service.apply_market_bars, instrument, usable, observed_ms=now)
        behind = now - start_ms > 3 * BAR_SECONDS * 1000
        if gap or (not usable and behind):
            await run_storage(
                self.service.set_feed_status,
                instrument,
                "catching_up",
                "Waiting for 1m history before matching further",
            )
