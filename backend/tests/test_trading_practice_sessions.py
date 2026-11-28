"""Practice markets on a trading calendar (ADR-DATA-002 D2c).

AAPL:NASDAQ on Twelve Data follows XNYS. Around Thanksgiving 2026: Tuesday
24 and Wednesday 25 November are full sessions (14:30-21:00 UTC), Thursday 26
is closed, Friday 27 closes early at 18:00 UTC, and Monday 30 opens at 14:30.
A night is about 17.5 hours, longer than one step's window of 1000 minutes.
"""
from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.data_engine.history.calendar import AlwaysOpenCalendar
from app.data_engine.history.expected_bars import calendar_by_id
from app.data_engine.series_identity import identity_from_mapping
from app.exchanges.plugins.twelvedata.adapter import EXCHANGE_DATE_CALENDAR_ID
from app.exchanges.plugins.twelvedata.plugin import _register_calendars
from app.trading_accounts import practice_runtime
from app.trading_accounts.practice_runtime import DataManagerMarket, PracticeRuntime, contiguous_bars, window_end_ms
from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore

D = Decimal
MINUTE = 60_000
DAY = 86_400_000
TUE_OPEN = 1_795_530_600_000  # 2026-11-24 14:30 UTC
TUE_CLOSE = TUE_OPEN + 390 * MINUTE  # 21:00 UTC
WED_OPEN = TUE_OPEN + DAY
THU = TUE_OPEN + 2 * DAY  # Thanksgiving, 14:30 UTC
FRI_OPEN = TUE_OPEN + 3 * DAY
FRI_CLOSE = FRI_OPEN + 210 * MINUTE  # 18:00 UTC, a half day
SAT = TUE_OPEN + 4 * DAY
MON_OPEN = TUE_OPEN + 6 * DAY
STOCK = {"provider_id": "twelvedata", "venue": "xngs", "asset_class": "stock", "series_variant": "ohlcv",
         "price_adjustment": "raw", "session_variant": "regular", "volume_semantics": "shares"}
STOCK_SERIES = identity_from_mapping("twelvedata", STOCK)
APPLE = {"exchange": "twelvedata", "marketType": "stock", "symbol": "AAPL:NASDAQ", "identity": STOCK}
INSTRUMENT = ("twelvedata", "stock", "AAPL:NASDAQ")


@pytest.fixture(scope="module")
def xnys():
    _register_calendars()
    return calendar_by_id(EXCHANGE_DATE_CALENDAR_ID)


def candle(open_ms: int, price: str, low: str | None = None) -> dict[str, Any]:
    value = D(price)
    return {"time": open_ms // 1000, "open": value, "high": value, "low": D(low) if low else value, "close": value}


class Clock:
    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


class SessionMarket:
    """Twelve Data as the matcher sees it: candles only while XNYS trades."""

    def __init__(self, calendar, clock: Clock, *, complete: bool = False) -> None:
        self._calendar = calendar
        self.clock = clock
        # The DataManager may not explain a closure itself; the calendar does.
        self.complete = complete
        self.history: dict[int, dict[str, Any]] = {}
        self.windows: list[tuple[int, int]] = []

    def session(self, start_ms: int, end_ms: int, price: str = "350") -> None:
        for open_ms in self._calendar.expected_opens(start_ms, end_ms - 1, "1m"):
            self.history[open_ms // 1000] = candle(open_ms, price)

    def calendar(self, exchange, market_type, symbol, *, series_identity=None):
        assert series_identity == STOCK_SERIES
        return self._calendar

    def _visible(self):
        return [bar for time_s, bar in sorted(self.history.items()) if time_s * 1000 <= self.clock.now]

    def latest_bar(self, exchange, market_type, symbol, **kwargs):
        visible = self._visible()
        return visible[-1] if visible else None

    def bars(self, exchange, market_type, symbol, interval, start_ms, end_ms, limit, **kwargs):
        self.windows.append((start_ms, end_ms))
        rows = [bar for bar in self._visible() if start_ms <= bar["time"] * 1000 <= end_ms]
        return rows[:limit], self.complete


class QuietDataManager:
    async def ensure_stream(self, *args, **kwargs):
        raise RuntimeError("history only")


@pytest.fixture()
def practice(tmp_path: Path, xnys, monkeypatch):
    clock = Clock(TUE_OPEN)
    market = SessionMarket(xnys, clock)
    monkeypatch.setattr(practice_runtime, "_wall_ms", clock)
    store = TradingStore(tmp_path / "trading.sqlite3")
    service = TradingAccountService(store, snapshot_dir=tmp_path / "snaps", market=market, clock=clock)
    runtime = PracticeRuntime(service, QuietDataManager(), market=market)
    account = service.create_account({"kind": "practice", "name": "Stocks", "settings": {"slippageBps": "0"}})
    yield service, runtime, market, clock, account["id"]
    store.close()


def step(runtime, clock: Clock, at_ms: int) -> str:
    clock.now = at_ms
    runtime._step(INSTRUMENT, at_ms, time.perf_counter(), None)
    return runtime.service._feed(INSTRUMENT).status


def test_a_resting_order_matches_after_the_night(practice):
    service, runtime, market, clock, account_id = practice
    market.session(TUE_OPEN, TUE_CLOSE)
    market.history[WED_OPEN // 1000] = candle(WED_OPEN, "345", low="338")
    market.session(WED_OPEN + MINUTE, WED_OPEN + 10 * MINUTE)
    clock.now = TUE_CLOSE - 90_000
    order = service.place_order(account_id, {**APPLE, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "340"})["order"]

    # Overnight the market owes no candles, so the feed is not catching up ...
    assert step(runtime, clock, TUE_CLOSE + 2 * 60 * MINUTE) == "live"
    assert service.store.order(order["id"])["status"] == "working"
    # ... and one step reaches past the night to Wednesday's opening gap.
    assert step(runtime, clock, WED_OPEN + 5 * MINUTE) == "live"
    assert service.store.order(order["id"])["status"] == "filled"
    assert service.store.order(order["id"])["fill_price"] == D("340")
    assert market.windows[-1][1] == WED_OPEN + 5 * MINUTE


def test_an_order_placed_on_a_holiday_waits_through_the_half_day_and_the_weekend(practice):
    service, runtime, market, clock, account_id = practice
    market.session(WED_OPEN, WED_OPEN + 390 * MINUTE)
    market.session(FRI_OPEN, FRI_CLOSE, "352")
    market.history[MON_OPEN // 1000] = candle(MON_OPEN, "331", low="325")
    market.session(MON_OPEN + MINUTE, MON_OPEN + 10 * MINUTE, "331")
    clock.now = THU + 3 * 60 * MINUTE + 30_000  # Thanksgiving, 17:30 UTC
    order = service.place_order(account_id, {**APPLE, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "330"})["order"]

    assert step(runtime, clock, THU + 4 * 60 * MINUTE) == "live"
    assert step(runtime, clock, FRI_OPEN + 60 * MINUTE) == "live"
    assert service._feed(INSTRUMENT).cursor.last_close == D("352")
    # After Friday's early close, through Saturday and into Monday.
    assert step(runtime, clock, FRI_CLOSE + 30 * MINUTE) == "live"
    assert service._feed(INSTRUMENT).cursor.bar_time * 1000 == FRI_CLOSE - MINUTE
    assert step(runtime, clock, SAT + 6 * 60 * MINUTE) == "live"
    assert service.store.order(order["id"])["status"] == "working"
    assert step(runtime, clock, MON_OPEN + 5 * MINUTE) == "live"
    assert service.store.order(order["id"])["status"] == "filled"
    assert service._feed(INSTRUMENT).cursor.bar_time * 1000 == MON_OPEN + 5 * MINUTE


def test_a_closed_history_only_market_is_not_reported_unavailable(practice):
    service, runtime, market, clock, account_id = practice
    market.session(WED_OPEN, WED_OPEN + 390 * MINUTE)
    clock.now = THU + 30_000
    service.place_order(account_id, {**APPLE, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "300"})

    async def sweep():
        # Twelve Data has no 1m stream; the sweep that tried to open one still matches from history.
        await runtime.tick()
        return service.account_summary(account_id)["feeds"][0]["status"]

    clock.now = THU + 10 * MINUTE
    assert asyncio.run(sweep()) == "live"
    assert INSTRUMENT in runtime._stream_retry and INSTRUMENT not in runtime._streams


def test_missing_candles_while_the_market_trades_still_pause_matching(practice):
    service, runtime, market, clock, account_id = practice
    market.session(WED_OPEN, WED_OPEN + 390 * MINUTE)
    clock.now = THU + 30_000
    service.place_order(account_id, {**APPLE, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "300"})

    # Friday has opened but its candles have not arrived.
    assert step(runtime, clock, FRI_OPEN + 2 * MINUTE) == "live"
    assert step(runtime, clock, FRI_OPEN + 10 * MINUTE) == "catching_up"
    # A hole inside a session is a gap, not a closure.
    market.session(FRI_OPEN, FRI_OPEN + 5 * MINUTE)
    market.session(FRI_OPEN + 8 * MINUTE, FRI_OPEN + 12 * MINUTE)
    assert step(runtime, clock, FRI_OPEN + 12 * MINUTE) == "catching_up"
    assert service._feed(INSTRUMENT).cursor.bar_time * 1000 == FRI_OPEN + 4 * MINUTE


def test_a_closed_market_values_positions_at_its_last_close(practice):
    service, runtime, market, clock, account_id = practice
    market.session(TUE_OPEN, TUE_CLOSE, "350")
    clock.now = TUE_CLOSE - 30_000
    service.place_order(account_id, {**APPLE, "side": "buy", "type": "market", "qty": "2"})

    def valuation(at_ms):
        clock.now = at_ms
        summary = service.account_summary(account_id)
        [position] = summary["positions"]
        return summary["valuationStatus"], position["markSource"], position["markPrice"]

    # Nothing has traded since Tuesday's close: that close is the market price.
    assert valuation(WED_OPEN - 10 * 60 * MINUTE) == ("current", "market", "350")
    # Once Wednesday trades, Tuesday's close is an estimate until its candles load.
    assert valuation(WED_OPEN + 30 * MINUTE)[0] == "stale"
    market.session(WED_OPEN, WED_OPEN + 390 * MINUTE, "356")
    assert valuation(THU + 2 * 60 * MINUTE) == ("current", "market", "356")


def test_the_minute_grid_is_unchanged_without_a_session_calendar():
    start = 1_700_000_000_000 // MINUTE * MINUTE
    assert window_end_ms(None, start, start + 5 * DAY) == start + 999 * MINUTE
    bars = [candle(start, "1"), candle(start + 3 * MINUTE, "1")]
    assert contiguous_bars(bars, start // 1000, complete=False) == ([bars[0]], True)
    assert contiguous_bars(bars, start // 1000, complete=True) == (bars, False)


def test_window_counts_trading_minutes(xnys):
    end = window_end_ms(xnys, TUE_CLOSE - MINUTE, MON_OPEN + 2 * DAY)
    # 999 trading minutes after Tuesday's last candle: Wednesday's 390, Friday's 210, Monday's 390
    # and Tuesday 1 December's first 9.
    assert end == MON_OPEN + DAY + 8 * MINUTE
    assert window_end_ms(xnys, TUE_CLOSE - MINUTE, WED_OPEN + 5 * MINUTE) == WED_OPEN + 5 * MINUTE


def test_data_manager_market_asks_the_series_calendar_once(xnys):
    class Manager:
        def __init__(self):
            self.calls = []
            self.known = False

        def series_calendar(self, symbol, interval, *, exchange, market_type, series_identity=None):
            self.calls.append((exchange, interval))
            if exchange == "binance":
                return AlwaysOpenCalendar()
            return xnys if self.known else None

    manager = Manager()
    market = DataManagerMarket(manager)
    assert market.calendar("binance", "spot", "BTCUSDT") is None
    assert market.calendar("binance", "spot", "BTCUSDT") is None
    # A provider still loading has no calendar yet; it is asked again.
    assert market.calendar(*INSTRUMENT, series_identity=STOCK_SERIES) is None
    manager.known = True
    assert market.calendar(*INSTRUMENT, series_identity=STOCK_SERIES) is xnys
    assert market.calendar(*INSTRUMENT, series_identity=STOCK_SERIES) is xnys
    assert manager.calls == [("binance", "1m"), ("twelvedata", "1m"), ("twelvedata", "1m")]


# ADR-DATA-002 D5a: nothing trades while the market is closed.


def bar(open_ms: int, open_: str, high: str, low: str, close: str) -> dict[str, Any]:
    return {"time": open_ms // 1000, "open": D(open_), "high": D(high), "low": D(low), "close": D(close)}


def fill_of(service, order_id: str) -> tuple[str, Decimal, int, str]:
    order = service.store.order(order_id)
    [fill] = [row for row in service.store.fills(order["account_id"]) if row["order_id"] == order_id]
    return order["status"], order["fill_price"], fill["ts_ms"], fill["liquidity"]


def test_orders_the_open_gaps_through_fill_at_the_open(practice):
    service, runtime, market, clock, account_id = practice
    market.session(TUE_OPEN, TUE_CLOSE, "350")
    clock.now = TUE_CLOSE - 90_000
    service.place_order(account_id, {**APPLE, "side": "buy", "type": "market", "qty": "3"})
    stop = service.place_order(account_id, {**APPLE, "side": "sell", "type": "stop", "qty": "1", "stopPrice": "340"})
    limit = service.place_order(account_id, {**APPLE, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "336"})
    near = service.place_order(account_id, {**APPLE, "side": "sell", "type": "stop", "qty": "1", "stopPrice": "320"})
    # Wednesday opens at 330: the stop at 340 and the limit at 336 were gapped
    # through overnight and fill at the open, not at prices that never traded.
    market.history[WED_OPEN // 1000] = bar(WED_OPEN, "330", "331", "325", "329")
    market.session(WED_OPEN + MINUTE, WED_OPEN + 10 * MINUTE, "329")
    step(runtime, clock, WED_OPEN + 5 * MINUTE)

    assert fill_of(service, stop["order"]["id"]) == ("filled", D("330"), WED_OPEN, "taker")
    assert fill_of(service, limit["order"]["id"]) == ("filled", D("330"), WED_OPEN, "maker")
    # The open did not reach 320; the candle's low of 325 did not either.
    assert service.store.order(near["order"]["id"])["status"] == "working"


def test_a_market_order_placed_while_closed_fills_at_the_next_open(practice):
    service, runtime, market, clock, account_id = practice
    market.session(WED_OPEN, WED_OPEN + 390 * MINUTE, "350")
    clock.now = THU + 3 * 60 * MINUTE  # Thanksgiving
    placed = service.place_order(account_id, {
        **APPLE, "side": "buy", "type": "market", "qty": "2", "bracketStop": "330", "bracketTarget": "370",
    })
    assert placed["waitsForOpen"] is True and placed["order"]["status"] == "working"
    marketable = service.place_order(account_id, {**APPLE, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "360"})
    assert marketable["waitsForOpen"] is True and marketable["order"]["status"] == "working"
    assert service.account_summary(account_id)["positions"] == []

    assert step(runtime, clock, FRI_OPEN - 30 * MINUTE) == "live"
    assert service.store.order(placed["order"]["id"])["status"] == "working"
    market.history[FRI_OPEN // 1000] = bar(FRI_OPEN, "355", "357", "354", "356")
    market.session(FRI_OPEN + MINUTE, FRI_OPEN + 10 * MINUTE, "356")
    step(runtime, clock, FRI_OPEN + 5 * MINUTE)

    assert fill_of(service, placed["order"]["id"]) == ("filled", D("355"), FRI_OPEN, "taker")
    assert fill_of(service, marketable["order"]["id"]) == ("filled", D("355"), FRI_OPEN, "maker")
    [position] = service.account_summary(account_id)["positions"]
    assert position["openQty"] == "3"
    exits = {row["tag"] for row in service.store.working_orders_for(*INSTRUMENT)}
    assert exits == {"stop_loss", "take_profit"}


def test_an_open_market_still_fills_market_orders_now(practice):
    service, runtime, market, clock, account_id = practice
    market.session(TUE_OPEN, TUE_CLOSE, "350")
    clock.now = TUE_OPEN + 30 * MINUTE + 10_000
    placed = service.place_order(account_id, {**APPLE, "side": "buy", "type": "market", "qty": "1"})
    assert placed["waitsForOpen"] is False and placed["order"]["status"] == "filled"


def test_without_a_session_calendar_the_path_still_moves_from_the_last_close():
    from app.simulation.practice_account import (
        Cursor, PracticeMatcher, PracticeSettings, WorkingOrder, advance_cursor,
    )

    cursor = Cursor(bar_time=0, seen_high=D("350"), seen_low=D("350"), last_close=D("350"), observed_ms=59_000)
    settings = PracticeSettings(D("0"), D("0"), D("0"), allow_short=True)

    def stop_fill(after_closure):
        _, chunk = advance_cursor(cursor, 600, D("330"), D("331"), D("325"), D("329"),
                                  observed_ms=659_000, after_closure=after_closure)
        stop = WorkingOrder(id="o1", side="sell", type="stop", qty=D("1"), created_at_ms=0, stop_price=D("340"))
        matcher = PracticeMatcher([stop], D("1"), settings, new_order_id=lambda: "x")
        matcher.run(chunk)
        return chunk.points[0], matcher.result.fills[0].price

    # An always-open market's hole is a move from the last close (unchanged) ...
    assert stop_fill(False) == (D("350"), D("340"))
    # ... a closure is a gap to the open.
    assert stop_fill(True) == (D("330"), D("330"))
