from __future__ import annotations

import asyncio
import base64
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.trading_accounts import router as trading_router
from app.trading_accounts.journal import locked_plan, phase_at, plan_direction, should_coalesce
from app.trading_accounts.models import TradingAccountError
from app.trading_accounts.practice import (
    Cursor,
    PathChunk,
    PracticeMatcher,
    PracticeSettings,
    WorkingOrder,
    advance_cursor,
)
from app.data_engine.data_manager.models import DataEvent, DataEventType, SeriesKey
from app.trading_accounts.practice_runtime import PracticeRuntime, contiguous_bars
from app.trading_accounts.service import CURSOR_FLUSH_MS, TradingAccountService
from app.trading_accounts.stats import LOW_SAMPLE_TRADES, TradeFacts, compute_stats, journal_tags
from app.trading_accounts.store import TradingStore
from app.trading_accounts.trades import build_trades

D = Decimal
T0 = 1_760_000_040_000  # a minute boundary in ms


def fill(fid: str, side: str, qty: str, price: str, ts: int, fee: str = "0") -> dict[str, Any]:
    return {
        "id": fid, "side": side, "qty": D(qty), "price": D(price), "fee": D(fee), "ts_ms": ts,
        "exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT",
        "liquidity": "taker", "order_id": None,
    }


# ── trades ──────────────────────────────────────────────────────

def test_trade_grouping_scale_in_partial_exit_and_close():
    trades = build_trades("acc", [
        fill("f1", "buy", "1", "100", 1, fee="0.1"),
        fill("f2", "buy", "1", "110", 2, fee="0.1"),
        fill("f3", "sell", "1", "120", 3, fee="0.1"),
        fill("f4", "sell", "1", "100", 4, fee="0.1"),
    ])
    assert len(trades) == 1
    trade = trades[0]
    assert trade.status == "closed"
    assert trade.avg_entry_price == D("105")
    assert trade.realized_pnl == D("15") + D("-5")
    assert trade.fees == D("0.4")
    assert trade.net_pnl == D("9.6")
    assert [leg.role for leg in trade.legs] == ["open", "add", "reduce", "close"]


def test_reversal_splits_fill_and_fee_into_two_trades():
    trades = build_trades("acc", [
        fill("f1", "buy", "1", "100", 1),
        fill("f2", "sell", "3", "90", 2, fee="0.3"),
    ])
    assert [trade.id for trade in trades] == ["f1", "f2~r"]
    first, second = trades
    assert first.status == "closed" and first.realized_pnl == D("-10") and first.fees == D("0.1")
    assert second.direction == "short" and second.open_qty == D("2") and second.fees == D("0.2")
    assert second.status == "open"


# ── practice matcher ───────────────────────────────────────────

SETTINGS = PracticeSettings(
    taker_fee_rate=D("0.001"), maker_fee_rate=D("0"), slippage_bps=D("0"), allow_short=True,
)


def matcher(orders: list[WorkingOrder], position: str = "0") -> PracticeMatcher:
    counter = iter(range(1000))
    return PracticeMatcher(orders, D(position), SETTINGS, new_order_id=lambda: f"child{next(counter)}")


def test_limit_needs_trade_through_and_stop_fills_at_level():
    limit = WorkingOrder(id="l", side="buy", type="limit", qty=D("1"), created_at_ms=0, limit_price=D("99"))
    m = matcher([limit])
    m.run(PathChunk([D("100"), D("99"), D("100")], 0, 10))
    assert not m.result.fills  # a touch is not a fill
    m.run(PathChunk([D("100"), D("98.5")], 10, 20))
    assert m.result.fills[0].price == D("99")
    assert m.result.fills[0].liquidity == "maker"

    stop = WorkingOrder(id="s", side="sell", type="stop", qty=D("1"), created_at_ms=0, stop_price=D("95"))
    m2 = matcher([stop], position="1")
    m2.run(PathChunk([D("100"), D("94")], 0, 10))
    assert m2.result.fills[0].price == D("95")
    assert m2.result.position == 0


def test_bracket_children_and_oco_inside_one_candle():
    entry = WorkingOrder(
        id="e", side="buy", type="stop", qty=D("2"), created_at_ms=0, stop_price=D("101"),
        bracket_stop=D("99"), bracket_target=D("104"),
    )
    m = matcher([entry])
    # open 100 -> low 99.5 -> high 105 -> close 104.5 (close >= open path)
    m.run(PathChunk([D("100"), D("99.5"), D("105"), D("104.5")], 0, 60_000))
    tags = {fill.order_id: fill for fill in m.result.fills}
    assert "e" in tags
    target = next(child for child in m.result.created if child.tag == "take_profit")
    stop = next(child for child in m.result.created if child.tag == "stop_loss")
    assert target.id in tags and tags[target.id].price == D("104")
    assert m.result.cancelled[stop.id] == "oco_sibling_filled"
    assert m.result.position == 0


def test_orders_ignore_candles_from_before_they_existed():
    order = WorkingOrder(id="l", side="buy", type="limit", qty=D("1"), created_at_ms=600_000, limit_price=D("99"))
    m = matcher([order])
    m.run(PathChunk([D("100"), D("90"), D("100")], 0, 59_999))
    assert not m.result.fills


def test_cursor_only_counts_new_extremes_of_a_forming_candle():
    cursor = Cursor(bar_time=60, seen_high=D("101"), seen_low=D("99"), last_close=D("100"), observed_ms=60_500)
    nxt, chunk = advance_cursor(cursor, 60, D("100"), D("101"), D("98"), D("99.5"), observed_ms=61_000)
    assert chunk is not None and chunk.points == [D("100"), D("98"), D("99.5")]
    assert nxt.seen_low == D("98")
    _, new_bar = advance_cursor(nxt, 120, D("99.6"), D("100"), D("99"), D("99.2"), observed_ms=121_000)
    assert new_bar is not None and new_bar.points == [D("99.5"), D("99.6"), D("100"), D("99"), D("99.2")]


def test_contiguous_bars_stops_at_unexplained_gap():
    bars = [{"time": 60}, {"time": 120}, {"time": 240}]
    usable, gap = contiguous_bars(bars, 60, complete=False)
    assert [bar["time"] for bar in usable] == [60, 120] and gap
    usable, gap = contiguous_bars(bars, 60, complete=True)
    assert len(usable) == 3 and not gap


# ── journal rules ──────────────────────────────────────────────

def test_plan_locks_at_first_fill_and_phases_do_not_coalesce():
    trade = build_trades("acc", [fill("f1", "buy", "1", "100", 1_000), fill("f2", "sell", "1", "110", 5_000)])[0]
    revisions = [
        {"saved_at_ms": 500, "fields": {"stopPrice": "95", "riskUsdt": "5"}},
        {"saved_at_ms": 2_000, "fields": {"stopPrice": "90", "riskUsdt": "10"}},
    ]
    plan = locked_plan(revisions, trade)
    assert plan is not None and plan["stopPrice"] == "95" and plan["riskUsdt"] == "5"
    assert phase_at(500, trade) == "pre" and phase_at(2_000, trade) == "open" and phase_at(6_000, trade) == "post"
    assert not should_coalesce({"saved_at_ms": 900}, 1_100, trade)
    assert should_coalesce({"saved_at_ms": 1_100}, 1_200, trade)


# ── service ────────────────────────────────────────────────────

class FakeMarket:
    def __init__(self) -> None:
        self.bar: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []
        self.calls: list[str] = []

    def latest_bar(self, exchange, market_type, symbol):
        return self.bar

    def bars(self, exchange, market_type, symbol, interval, start_ms, end_ms, limit):
        self.calls.append(symbol)
        return [bar for bar in self.history if start_ms // 1000 <= bar["time"]], True


class Clock:
    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


@pytest.fixture()
def service(tmp_path: Path):
    market = FakeMarket()
    clock = Clock(T0 + 30_000)
    store = TradingStore(tmp_path / "trading.sqlite3")
    svc = TradingAccountService(store, snapshot_dir=tmp_path / "snaps", market=market, clock=clock)
    svc.test_market = market  # type: ignore[attr-defined]
    svc.test_clock = clock  # type: ignore[attr-defined]
    yield svc
    store.close()


def bar(time_s: int, o: str, h: str, l: str, c: str) -> dict[str, Any]:
    return {"time": time_s, "open": D(o), "high": D(h), "low": D(l), "close": D(c)}


INSTRUMENT = {"exchange": "binance", "marketType": "futures", "symbol": "BTCUSDT"}


def test_practice_flow_market_entry_bracket_and_candle_replay(service):
    market, clock = service.test_market, service.test_clock
    minute = T0 // 1000
    market.bar = bar(minute, "100", "100.5", "99.8", "100")
    account = service.create_account({"kind": "practice", "name": "Practice", "settings": {"slippageBps": "0"}})
    placed = service.place_order(account["id"], {
        **INSTRUMENT, "side": "buy", "type": "market", "qty": "1",
        "bracketStop": "98", "bracketTarget": "103",
    })
    assert placed["order"]["status"] == "filled"
    summary = service.account_summary(account["id"])
    assert len(summary["positions"]) == 1
    assert {order["tag"] for order in summary["workingOrders"]} == {"stop_loss", "take_profit"}

    # Same candle: old high 100.5 must not count; next candle reaches 103.5.
    clock.now = T0 + 70_000
    fills = service.apply_market_bars(
        ("binance", "futures", "BTCUSDT"),
        [bar(minute, "100", "100.5", "99.8", "100.2"), bar(minute + 60, "100.2", "103.5", "100.1", "103.2")],
        observed_ms=clock.now,
    )
    assert fills == 1
    summary = service.account_summary(account["id"])
    assert summary["positions"] == [] and summary["workingOrders"] == []
    trades = service.list_trades(account["id"])["trades"]
    assert trades[0]["status"] == "closed" and trades[0]["avgExitPrice"] == "103"
    # 10000 + 3 profit - taker fee on entry - maker fee on target
    assert D(summary["balance"]) == D("10000") + D("3") - D("100") * D("0.0005") - D("103") * D("0.0002")


def test_practice_rejects_spot_short_and_wrong_side_stop(service):
    service.test_market.bar = bar(T0 // 1000, "100", "100", "100", "100")
    account = service.create_account({"kind": "practice", "name": "Spot"})
    with pytest.raises(TradingAccountError) as short:
        service.place_order(account["id"], {**INSTRUMENT, "marketType": "spot", "side": "sell", "type": "market", "qty": "1"})
    assert short.value.code == "TRADING_INSUFFICIENT_POSITION"
    with pytest.raises(TradingAccountError) as stop:
        service.place_order(account["id"], {**INSTRUMENT, "side": "buy", "type": "stop", "qty": "1", "stopPrice": "99"})
    assert stop.value.code == "TRADING_STOP_WOULD_TRIGGER"


def test_exchange_account_kinds_are_planned_not_creatable(service):
    with pytest.raises(TradingAccountError) as exc:
        service.create_account({"kind": "exchange_readonly", "name": "OKX"})
    assert exc.value.code == "TRADING_ACCOUNT_KIND_PLANNED"


def test_manual_journal_plan_link_and_hindsight_flags(service):
    clock = service.test_clock
    account = service.create_account({"kind": "manual", "name": "Manual"})
    note = service.create_entry(account["id"], {
        **INSTRUMENT, "kind": "note", "templateId": "full", "templateVersion": 1,
        "fields": {"entryPrice": "100", "stopPrice": "95", "riskUsdt": "50", "entryBasis": "breakout"},
    })
    clock.now += 60_000
    service.add_fill(account["id"], {**INSTRUMENT, "side": "buy", "qty": "10", "price": "100", "fee": "1"})
    clock.now += 60_000
    service.add_fill(account["id"], {**INSTRUMENT, "side": "sell", "qty": "10", "price": "110", "fee": "1"})
    trade = service.list_trades(account["id"])["trades"][0]
    detail = service.trade_detail(account["id"], trade["id"])
    assert [item["id"] for item in detail["linkSuggestions"]] == [note["id"]]

    service.link_entry(note["id"], trade["id"])
    clock.now += 10_000
    saved = service.save_entry(note["id"], {"fields": {
        "entryPrice": "100", "stopPrice": "90", "riskUsdt": "100",
        "entryBasis": "breakout", "errors": "moved stop",
    }})
    assert saved["revisionCount"] == 2
    assert saved["fieldTiming"]["errors"]["phase"] == "post"
    detail = service.trade_detail(account["id"], trade["id"])
    assert detail["plan"]["riskUsdt"] == "50"
    assert detail["metrics"]["netR"] == "1.96"  # (100 - 2) / 50


def test_link_suggestions_carry_plan_fields_so_same_minute_plans_differ(service):
    clock = service.test_clock
    account = service.create_account({"kind": "manual", "name": "Manual"})
    long_plan = service.create_entry(account["id"], {
        **INSTRUMENT, "kind": "note",
        "fields": {"entryPrice": "82100", "stopPrice": "81000", "targetPrice": "84000", "riskUsdt": "25"},
    })
    clock.now += 5_000
    short_plan = service.create_entry(account["id"], {
        **INSTRUMENT, "kind": "note", "fields": {"entryPrice": "82100.50", "stopPrice": "83000"},
    })
    clock.now += 5_000
    bare_plan = service.create_entry(account["id"], {
        **INSTRUMENT, "kind": "note", "fields": {"entryBasis": "range", "riskUsdt": "a lot"},
    })
    service.create_entry(account["id"], {**INSTRUMENT, "kind": "quick", "body": "watching"})
    clock.now += 150_000  # past the coalesce window: the next save is a new revision
    service.save_entry(long_plan["id"], {"fields": {
        "entryPrice": "82100", "stopPrice": "81000", "targetPrice": "84000", "riskUsdt": "30",
    }})
    clock.now += 60_000
    service.add_fill(account["id"], {**INSTRUMENT, "side": "buy", "qty": "0.01", "price": "82150", "fee": "0"})
    trade = service.list_trades(account["id"])["trades"][0]
    suggestions = service.trade_detail(account["id"], trade["id"])["linkSuggestions"]

    assert {item["createdAtMs"] // 60_000 for item in suggestions} == {T0 // 60_000}
    keys = ("entryPrice", "stopPrice", "targetPrice", "riskUsdt", "direction")
    by_id = {item["id"]: tuple(item[key] for key in keys) for item in suggestions}
    assert by_id == {
        long_plan["id"]: ("82100", "81000", "84000", "30", "long"),
        short_plan["id"]: ("82100.5", "83000", None, None, "short"),
        bare_plan["id"]: (None, None, None, None, None),
    }
    # Stop and target on the same side of entry imply no direction.
    assert plan_direction({"entryPrice": D("100"), "stopPrice": D("95"), "targetPrice": D("90")}) is None


def test_snapshot_requires_png(service):
    account = service.create_account({"kind": "manual", "name": "Manual"})
    note = service.create_entry(account["id"], {**INSTRUMENT, "kind": "quick", "body": "watching"})
    with pytest.raises(TradingAccountError):
        service.add_snapshot(note["id"], {"image": base64.b64encode(b"not a png").decode()})
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 16).decode()
    detail = service.add_snapshot(note["id"], {"image": f"data:image/png;base64,{png}", "state": {"interval": "1h"}})
    snap = detail["snapshots"][0]
    assert snap["hasImage"] and service.snapshot_image_path(snap["id"]).is_file()


def test_http_adapter_maps_domain_errors(service):
    app = FastAPI()
    app.include_router(trading_router, prefix="/api/v1")
    app.state.trading_accounts = service
    client = TestClient(app)
    created = client.post("/api/v1/trading/accounts", json={"kind": "manual", "name": "M"})
    assert created.status_code == 200
    account_id = created.json()["id"]
    assert client.get(f"/api/v1/trading/accounts/{account_id}/summary").status_code == 200
    rejected = client.post(f"/api/v1/trading/accounts/{account_id}/orders", json={**INSTRUMENT, "side": "buy", "type": "market", "qty": 1})
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "TRADING_ORDERS_UNSUPPORTED"
    assert client.get("/api/v1/trading/journal/je_00000000000000000000").status_code == 404


# ── practice feed and runtime ─────────────────────────────────

FUTURES = ("binance", "futures", "BTCUSDT")


def test_cursor_stays_in_memory_until_candle_extremes_change(service):
    market, clock = service.test_market, service.test_clock
    minute = T0 // 1000
    market.bar = bar(minute, "100", "101", "99", "100")
    account = service.create_account({"kind": "practice", "name": "P", "settings": {"slippageBps": "0"}})
    service.place_order(account["id"], {**INSTRUMENT, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "90"})
    seeded = service.store.cursor(*FUTURES)
    loads: list[str] = []
    load_trades = service._trades
    service._trades = lambda account_id: loads.append(account_id) or load_trades(account_id)

    # A new close inside the seen range: visible at once, not written, and
    # far from the order so no ledger is loaded.
    clock.now = T0 + 31_000
    service.apply_market_bars(FUTURES, [bar(minute, "100", "101", "99", "100.4")], observed_ms=clock.now)
    assert loads == []
    assert service.store.cursor(*FUTURES)["updated_at_ms"] == seeded["updated_at_ms"]
    feed = service.account_summary(account["id"])["feeds"][0]
    assert feed["lastPrice"] == "100.4" and feed["observedMs"] == clock.now

    # A new extreme is written immediately.
    clock.now += 1_000
    service.apply_market_bars(FUTURES, [bar(minute, "100", "101.5", "99", "101")], observed_ms=clock.now)
    assert service.store.cursor(*FUTURES)["seen_high"] == D("101.5")

    # Close-only drift is flushed after CURSOR_FLUSH_MS, and on shutdown.
    clock.now += CURSOR_FLUSH_MS
    service.apply_market_bars(FUTURES, [bar(minute, "100", "101.5", "99", "100.9")], observed_ms=clock.now)
    assert service.store.cursor(*FUTURES)["last_close"] == D("100.9")
    clock.now += 1_000
    service.apply_market_bars(FUTURES, [bar(minute, "100", "101.5", "99", "100.7")], observed_ms=clock.now)
    assert service.store.cursor(*FUTURES)["last_close"] == D("100.9")
    service.flush_feeds()
    assert service.store.cursor(*FUTURES)["last_close"] == D("100.7")

    # Reaching the order loads the ledger and writes the fill with the cursor.
    clock.now += 1_000
    loads.clear()
    fills = service.apply_market_bars(FUTURES, [bar(minute, "100", "101.5", "89.5", "89.8")], observed_ms=clock.now)
    assert fills == 1 and loads == [account["id"]]
    assert service.store.cursor(*FUTURES)["seen_low"] == D("89.5")
    assert service.account_summary(account["id"])["positions"][0]["avgEntryPrice"] == "90"


def test_status_change_is_written_but_repeats_are_not(service):
    service.test_market.bar = bar(T0 // 1000, "100", "100", "100", "100")
    account = service.create_account({"kind": "practice", "name": "P"})
    service.place_order(account["id"], {**INSTRUMENT, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "90"})
    service.test_clock.now += 5_000
    service.set_feed_status(FUTURES, "catching_up", "gap")
    written = service.store.cursor(*FUTURES)
    assert written["status"] == "catching_up"
    service.test_clock.now += 5_000
    service.set_feed_status(FUTURES, "catching_up", "gap")
    assert service.store.cursor(*FUTURES)["updated_at_ms"] == written["updated_at_ms"]


def test_account_summary_exposes_feed_lag(service):
    service.test_market.bar = bar(T0 // 1000, "100", "100", "100", "100")
    account = service.create_account({"kind": "practice", "name": "P"})
    service.place_order(account["id"], {**INSTRUMENT, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "90"})
    service.record_feed_timing(FUTURES, {"lagMs": 120, "queueMs": 3, "queryMs": 5, "applyMs": 2})
    feed = service.account_summary(account["id"])["feeds"][0]
    assert feed["lagMs"] == 120 and feed["timing"]["queueMs"] == 3


class FakeDataManager:
    def __init__(self) -> None:
        self.handles: dict[object, tuple[str, Any]] = {}
        self.ensured: list[str] = []
        self.released: list[str] = []

    async def ensure_stream(self, symbol, interval, **_kwargs):
        self.ensured.append(symbol)

    async def release_stream(self, symbol, interval, **_kwargs):
        self.released.append(symbol)

    def subscribe(self, callback, symbol=None, interval=None, exchange="binance", market_type="spot",
                  event_types=None, *, on_recovery=None):
        assert DataEventType.BAR_UPDATED in event_types
        handle = object()
        self.handles[handle] = (symbol, callback)
        return handle

    def unsubscribe(self, handle):
        self.handles.pop(handle, None)

    async def emit(self, symbol: str, bar_time: int) -> None:
        event = DataEvent(
            event_type=DataEventType.BAR_UPDATED,
            key=SeriesKey(symbol, "1m", market_type="futures"),
            bar=SimpleNamespace(time=bar_time),
        )
        for subscribed, callback in list(self.handles.values()):
            if subscribed == symbol:
                await callback(event)


def live_service(tmp_path: Path) -> tuple[TradingAccountService, FakeMarket]:
    market = FakeMarket()
    store = TradingStore(tmp_path / "live.sqlite3")
    return TradingAccountService(store, snapshot_dir=tmp_path / "snaps", market=market), market


def test_sweep_steps_only_instruments_without_live_updates(tmp_path):
    service, market = live_service(tmp_path)
    minute = int(time.time()) // 60 * 60
    market.bar = bar(minute, "100", "100", "100", "100")
    market.history = [market.bar]
    account = service.create_account({"kind": "practice", "name": "P"})
    for symbol in ("BTCUSDT", "ETHUSDT"):
        service.place_order(account["id"], {
            **INSTRUMENT, "symbol": symbol, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "50",
        })
    dm = FakeDataManager()
    runtime = PracticeRuntime(service, dm, tick_seconds=60, market=market)

    async def scenario() -> None:
        await runtime.tick()
        assert sorted(dm.ensured) == ["BTCUSDT", "ETHUSDT"] and len(dm.handles) == 2
        assert sorted(market.calls) == ["BTCUSDT", "ETHUSDT"]
        market.calls.clear()
        await dm.emit("BTCUSDT", minute)
        await runtime.drain_events()
        assert market.calls == ["BTCUSDT"]
        market.calls.clear()
        await runtime.tick()  # BTC was just stepped by its live update
        assert market.calls == ["ETHUSDT"]
        market.calls.clear()
        await runtime.tick()
        assert sorted(market.calls) == ["BTCUSDT", "ETHUSDT"]
        await runtime.stop()
        assert sorted(dm.released) == ["BTCUSDT", "ETHUSDT"] and dm.handles == {}

    try:
        asyncio.run(scenario())
    finally:
        service.store.close()


def test_live_update_fills_limit_within_a_second_and_reports_lag(tmp_path):
    service, market = live_service(tmp_path)
    minute = int(time.time()) // 60 * 60
    market.bar = bar(minute, "100", "100", "100", "100")
    market.history = [market.bar]
    account = service.create_account({"kind": "practice", "name": "P", "settings": {"slippageBps": "0"}})
    order = service.place_order(account["id"], {
        **INSTRUMENT, "side": "buy", "type": "limit", "qty": "1", "limitPrice": "99",
    })["order"]
    dm = FakeDataManager()
    # The sweep is a minute away: only the live update can fill the order.
    runtime = PracticeRuntime(service, dm, tick_seconds=60, market=market)

    async def wait_for(predicate, timeout: float) -> float:
        started = time.perf_counter()
        while not predicate():
            assert time.perf_counter() - started < timeout, "timed out"
            await asyncio.sleep(0.005)
        return time.perf_counter() - started

    async def scenario() -> float:
        await runtime.start()
        try:
            await wait_for(lambda: dm.handles and market.calls, 2.0)
            market.history = [bar(minute, "100", "100", "98.5", "98.7")]
            await dm.emit("BTCUSDT", minute)
            return await wait_for(lambda: service.store.order(order["id"])["status"] == "filled", 1.0)
        finally:
            await runtime.stop()

    try:
        elapsed = asyncio.run(scenario())
        assert elapsed < 1.0
        assert service.store.order(order["id"])["fill_price"] == D("99")
        # The order is done, so the feed is no longer listed; read it directly.
        timing = service._feed(FUTURES).timing
        assert timing["fills"] == 1 and 0 <= timing["lagMs"] < 1_000
        assert {"wakeMs", "queueMs", "queryMs", "applyMs"} <= timing.keys()
    finally:
        service.store.close()


# ── statistics ─────────────────────────────────────────────────

def closed_trade(tid: str, pnl: str, ts: int, *, direction: str = "long", fee: str = "0"):
    """A one-unit round trip at 100 whose gross P&L is ``pnl``; net is pnl - fee."""
    sides = ("buy", "sell") if direction == "long" else ("sell", "buy")
    exit_price = D(100) + D(pnl) if direction == "long" else D(100) - D(pnl)
    return build_trades("acc", [
        fill(f"{tid}a", sides[0], "1", "100", ts, fee=fee),
        fill(f"{tid}b", sides[1], "1", str(exit_price), ts + 1),
    ])[0]


def test_stats_wins_losses_profit_factor_and_drawdown():
    facts = [
        TradeFacts(closed_trade("t1", "11", 1_000, fee="1")),  # +10
        TradeFacts(closed_trade("t2", "-5", 2_000)),
        TradeFacts(closed_trade("t3", "-3", 3_000, direction="short")),
        TradeFacts(closed_trade("t4", "20", 4_000)),
        TradeFacts(closed_trade("t5", "0", 5_000)),
    ]
    stats = compute_stats(reversed(facts))  # order comes from close time, not input
    assert (stats["tradeCount"], stats["wins"], stats["losses"], stats["breakeven"]) == (5, 2, 2, 1)
    assert stats["winRate"] == "0.4"
    assert stats["avgWin"] == "15" and stats["avgLoss"] == "-4"
    assert stats["profitFactor"] == "3.75"  # 30 / 8
    assert stats["netPnl"] == "22" and stats["fees"] == "1" and stats["realizedPnl"] == "23"
    # Equity 10, 5, 2, 22, 22: the worst fall is 10 -> 2 after t1's close.
    assert stats["maxDrawdown"] == {"amount": "8", "peakAtMs": 1_001, "troughAtMs": 3_001}


def test_stats_profit_factor_without_losses_and_empty_account():
    stats = compute_stats([TradeFacts(closed_trade("t1", "5", 1_000)), TradeFacts(closed_trade("t2", "0", 2_000))])
    assert stats["profitFactor"] is None and stats["grossLoss"] == "0" and stats["grossProfit"] == "5"
    assert stats["maxDrawdown"]["amount"] == "0" and stats["maxDrawdown"]["troughAtMs"] is None
    empty = compute_stats([])
    assert empty["tradeCount"] == 0 and empty["winRate"] is None and empty["profitFactor"] is None
    assert empty["r"]["coverage"] is None and empty["r"]["expectancyR"] is None


def test_stats_r_only_over_locked_risk_with_coverage_and_buckets():
    facts = [
        TradeFacts(closed_trade("t1", "-10", 1_000), risk=D("10")),  # exactly -1R
        TradeFacts(closed_trade("t2", "20", 2_000), risk=D("10")),  # exactly +2R
        TradeFacts(closed_trade("t3", "5", 3_000), risk=D("10")),  # 0.5R
        TradeFacts(closed_trade("t4", "500", 4_000)),  # no locked plan: ignored by R
    ]
    r = compute_stats(facts)["r"]
    assert (r["count"], r["missing"], r["coverage"]) == (3, 1, "0.75")
    assert r["expectancyR"] == "0.5"  # (-1 + 2 + 0.5) / 3, not diluted or inflated by t4
    assert r["avgWinR"] == "1.25" and r["avgLossR"] == "-1" and r["totalR"] == "1.5"
    assert r["winRate"] == "0.6667"
    buckets = {(b["fromR"], b["toR"]): b["count"] for b in compute_stats(facts)["rDistribution"]}
    assert buckets[("-2", "-1")] == 1 and buckets[("-1", "0")] == 0
    assert buckets[("0", "1")] == 1 and buckets[("2", "3")] == 1
    assert sum(buckets.values()) == 3


def test_stats_breakdowns_by_tag_direction_and_plan_timing():
    facts = [
        TradeFacts(closed_trade("t1", "10", 1_000), tags=("breakout", "trend"), plan_timing="before"),
        TradeFacts(closed_trade("t2", "-4", 2_000, direction="short"), tags=("breakout",), plan_timing="after"),
        TradeFacts(closed_trade("t3", "6", 3_000), plan_timing="before"),
    ]
    breakdowns = compute_stats(facts)["breakdowns"]
    tags = {group["key"]: group for group in breakdowns["tag"]}
    assert [group["key"] for group in breakdowns["tag"]] == ["breakout", "trend", None]
    assert tags["breakout"]["tradeCount"] == 2 and tags["breakout"]["netPnl"] == "6"
    assert tags["trend"]["tradeCount"] == 1 and tags[None]["netPnl"] == "6"
    timing = {group["key"]: group for group in breakdowns["planTiming"]}
    assert list(timing) == ["before", "mixed", "after", "none"]
    assert timing["before"]["tradeCount"] == 2 and timing["before"]["winRate"] == "1"
    assert timing["after"]["netPnl"] == "-4" and timing["mixed"]["tradeCount"] == 0
    direction = {group["key"]: group["tradeCount"] for group in breakdowns["direction"]}
    assert direction == {"long": 2, "short": 1}


def test_stats_low_sample_flags():
    few = [TradeFacts(closed_trade(f"t{i}", "1", i * 10), risk=D("1")) for i in range(LOW_SAMPLE_TRADES - 1)]
    stats = compute_stats(few)
    assert stats["lowSample"] and stats["r"]["lowSample"]
    enough = [*few, TradeFacts(closed_trade("tx", "1", 10_000), tags=("a",))]
    stats = compute_stats(enough)
    assert not stats["lowSample"]
    assert stats["r"]["lowSample"]  # only 19 of the 20 have a locked risk
    assert all(group["lowSample"] for group in stats["breakdowns"]["tag"])
    assert not next(g for g in stats["breakdowns"]["direction"] if g["key"] == "long")["lowSample"]


def test_journal_tags_merge_entry_tags_and_strategy_tag():
    entries = [{"tags": ["fomo", "a"]}, {"tags": []}]
    assert journal_tags(entries, {"strategyTag": " breakout, a ，trend"}) == ("fomo", "a", "breakout", "trend")
    assert journal_tags([], {}) == ()


def manual_round_trip(service, account_id: str, *, buy: str, sell: str, fee: str = "0") -> dict[str, Any]:
    """A 10-unit long entered by hand one minute apart; returns the closed trade."""
    clock = service.test_clock
    clock.now += 60_000
    service.add_fill(account_id, {**INSTRUMENT, "side": "buy", "qty": "10", "price": buy, "fee": fee})
    clock.now += 60_000
    service.add_fill(account_id, {**INSTRUMENT, "side": "sell", "qty": "10", "price": sell, "fee": fee})
    return service.list_trades(account_id)["trades"][0]


def test_account_stats_use_locked_plan_timing_tags_and_filters(service):
    account = service.create_account({"kind": "manual", "name": "Real"})
    plan = service.create_entry(account["id"], {
        **INSTRUMENT, "kind": "note",
        "fields": {"entryPrice": "100", "stopPrice": "95", "riskUsdt": "50", "strategyTag": "breakout, trend"},
    })
    planned = manual_round_trip(service, account["id"], buy="100", sell="110", fee="1")  # net 98
    service.link_entry(plan["id"], planned["id"])
    chased = manual_round_trip(service, account["id"], buy="100", sell="97")  # net -30
    service.test_clock.now += 60_000
    service.create_entry(account["id"], {
        **INSTRUMENT, "kind": "note", "tradeId": chased["id"], "tags": ["fomo"],
        "fields": {"entryBasis": "chased the move", "riskUsdt": "20"},
    })
    manual_round_trip(service, account["id"], buy="100", sell="100.5")  # net 5, no note

    stats = service.account_stats(account["id"])
    assert stats["accountKind"] == "manual" and stats["openTrades"] == 0
    assert stats["tradeCount"] == 3 and stats["netPnl"] == "73"
    # Only the planned trade had risk locked at its first fill; risk typed afterwards is no denominator.
    assert (stats["r"]["count"], stats["r"]["coverage"], stats["r"]["expectancyR"]) == (1, "0.3333", "1.96")
    timing = {group["key"]: group for group in stats["breakdowns"]["planTiming"]}
    assert timing["before"]["netPnl"] == "98" and timing["after"]["netPnl"] == "-30"
    assert timing["none"]["tradeCount"] == 1 and timing["mixed"]["tradeCount"] == 0
    assert [group["key"] for group in stats["breakdowns"]["tag"]] == ["breakout", "fomo", "trend", None]

    tagged = service.account_stats(account["id"], tags=["breakout"])
    assert tagged["tradeCount"] == 1 and tagged["filters"]["tags"] == ["breakout"]
    assert service.account_stats(account["id"], from_ms=chased["closedAtMs"])["tradeCount"] == 2
    assert service.account_stats(account["id"], to_ms=chased["closedAtMs"])["tradeCount"] == 1
    with pytest.raises(TradingAccountError):
        service.account_stats(account["id"], from_ms=10, to_ms=5)


def test_http_account_stats_route(service):
    app = FastAPI()
    app.include_router(trading_router, prefix="/api/v1")
    app.state.trading_accounts = service
    client = TestClient(app)
    account = service.create_account({"kind": "manual", "name": "M"})
    manual_round_trip(service, account["id"], buy="100", sell="102")
    url = f"/api/v1/trading/accounts/{account['id']}/stats"
    body = client.get(url).json()
    assert body["tradeCount"] == 1 and body["netPnl"] == "20" and body["lowSampleThreshold"] == LOW_SAMPLE_TRADES
    filtered = client.get(url, params={"fromMs": 0, "tag": ["x", "y"]})
    assert filtered.status_code == 200
    assert filtered.json()["filters"] == {"fromMs": 0, "toMs": None, "tags": ["x", "y"]}
    assert filtered.json()["tradeCount"] == 0
    assert client.get(url, params={"fromMs": 10, "toMs": 5}).status_code == 422
    assert client.get(url, params={"fromMs": -1}).status_code == 422
    assert client.get("/api/v1/trading/accounts/acc_00000000000000000000/stats").status_code == 404
