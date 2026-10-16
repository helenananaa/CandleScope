from __future__ import annotations

import base64
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.trading_accounts import router as trading_router
from app.trading_accounts.journal import locked_plan, phase_at, should_coalesce
from app.trading_accounts.models import TradingAccountError
from app.trading_accounts.practice import (
    Cursor,
    PathChunk,
    PracticeMatcher,
    PracticeSettings,
    WorkingOrder,
    advance_cursor,
)
from app.trading_accounts.practice_runtime import contiguous_bars
from app.trading_accounts.service import TradingAccountService
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

    def latest_bar(self, exchange, market_type, symbol):
        return self.bar

    def bars(self, exchange, market_type, symbol, interval, start_ms, end_ms, limit):
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
