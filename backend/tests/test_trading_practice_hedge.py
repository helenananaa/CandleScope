"""Exact references for independent hedge legs in the real-time practice account."""
from decimal import Decimal as D

import pytest

from app.trading_accounts.models import TradingAccountError
from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore
from tests.test_trading_accounts import service, T0


def create(service, initial="1000"):
    return service.create_account({"kind": "practice", "name": "Hedge", "settings": {
        "positionMode": "HEDGE", "initialBalance": initial, "leverage": "10",
        "takerFeeRate": "0", "makerFeeRate": "0", "slippageBps": "0",
    }})["id"]


def order(service, account, leg, effect, qty, price, symbol="BTCUSDT", **options):
    return service.place_order(account, {"exchange": "binance", "marketType": "futures", "symbol": symbol,
        "positionSide": leg, "positionEffect": effect, "type": "market",
        "qty": str(qty), "referencePrice": str(price), **options})["order"]


def tick(service, symbol, price):
    service.test_clock.now += 60_000
    bar = {"time": service.test_clock.now // 60_000 * 60, **dict.fromkeys(("open", "high", "low", "close"), price)}
    return service.apply_market_bars(("binance", "futures", symbol), [bar], observed_ms=service.test_clock.now)


def test_exact_two_leg_balance_cost_basis_and_recovery(service, tmp_path):
    account = create(service)
    original = order(service, account, "LONG", "open", 2, 100, bracketStop="80", bracketTarget="140")
    tick(service, "BTCUSDT", 110)
    order(service, account, "SHORT", "open", 1, 110, bracketStop="130", bracketTarget="70")
    tick(service, "BTCUSDT", 105)
    def amounts():
        s = service.account_summary(account)
        return tuple(D(s[k]) for k in ("balance", "unrealizedPnl", "equity", "usedMargin", "available"))
    assert amounts() == (1000, 15, 1015, D("31.5"), D("983.5"))
    order(service, account, "LONG", "close", 1, 105)
    assert amounts() == (1005, 10, 1015, 21, 994)
    # Remaining cost after a partial close and a subsequent add.
    tick(service, "BTCUSDT", 120)
    order(service, account, "LONG", "open", 1, 120)
    both = service.account_summary(account)["positions"]
    long, short = (next(t for t in both if t["positionSide"] == leg) for leg in ("LONG", "SHORT"))
    assert D(long["avgEntryPrice"]) == 110 and D(short["avgEntryPrice"]) == 110
    order(service, account, "LONG", "close", 100, 120, tradeId=long["id"])
    summary = service.account_summary(account)
    assert [t["id"] for t in summary["positions"]] == [short["id"]]
    assert {o["positionSide"] for o in summary["workingOrders"]} == {"SHORT"}
    assert len(summary["workingOrders"]) == 2
    assert D(summary["balance"]) == 1025
    order(service, account, "LONG", "open", 1, 120)
    with pytest.raises(TradingAccountError, match="already closed"):
        order(service, account, "LONG", "close", 1, 120, tradeId=long["id"])
    assert len(service.trade_detail(account, long["id"])["protectionOrders"]) == 2
    assert original["positionEffect"] == "open"
    other = order(service, account, "LONG", "open", 1, 50, symbol="ETHUSDT")
    assert service.working_instruments() == [("binance", "futures", "BTCUSDT"), ("binance", "futures", "ETHUSDT")]
    tick(service, "ETHUSDT", 60)
    service.set_feed_status(("binance", "futures", "ETHUSDT"), "catching_up", "gap")
    summary = service.account_summary(account)
    assert summary["valuationStatus"] == "stale"
    assert {t["symbol"]: D(t["markPrice"]) for t in summary["positions"]} == {"BTCUSDT": 120, "ETHUSDT": 60}
    tick(service, "BTCUSDT", 119)
    summary = service.account_summary(account)
    assert next(f for f in summary["feeds"] if f["symbol"] == "ETHUSDT")["status"] == "catching_up"
    assert {t["symbol"]: D(t["markPrice"]) for t in summary["positions"]} == {"BTCUSDT": 119, "ETHUSDT": 60}
    service.flush_feeds()
    recovered = TradingStore(tmp_path / "trading.sqlite3")
    try:
        restored = TradingAccountService(recovered, snapshot_dir=tmp_path / "snaps", clock=service.test_clock)
        assert restored.account_state(account)["summary"] == summary
        assert restored.working_instruments() == service.working_instruments()
        assert restored.store.order(other["id"])["status"] == "filled"
    finally:
        recovered.close()


def test_working_open_rechecks_account_margin_and_reduce_only_clamps(service):
    account = create(service, "100")
    for leg, price in [("LONG", 90), ("SHORT", 110)]:
        order(service, account, leg, "open", 9, 100, type="limit", limitPrice=str(price))
    service.test_clock.now += 60_000
    bar = {"time": (T0 // 1000) + 60, "open": 100, "high": 112, "low": 88, "close": 100}
    service.apply_market_bars(("binance", "futures", "BTCUSDT"), [bar], observed_ms=service.test_clock.now)
    s = service.account_summary(account)
    # The rising mark of the long makes the short affordable at 110.
    assert len(s["positions"]) == 2
    assert D(s["usedMargin"]) == 180
    for trade in s["positions"]:
        assert D(trade["openQty"]) == 9
    order(service, account, "SHORT", "close", 30, 100)
    assert [t["positionSide"] for t in service.account_summary(account)["positions"]] == ["LONG"]


def test_colliding_orders_cannot_spend_same_collateral(service):
    account = create(service, "100")
    first = order(service, account, "LONG", "open", 8, 100, type="limit", limitPrice="95")
    second = order(service, account, "LONG", "open", 8, 100, type="limit", limitPrice="94")
    tick(service, "BTCUSDT", 93)
    rows = [service.store.order(o["id"]) for o in (first, second)]
    assert sorted(row["status"] for row in rows) == ["cancelled", "filled"]
    assert next(row["reason"] for row in rows if row["status"] == "cancelled") == "insufficient_balance"


def test_explicit_intent_mode_and_spot_contract(service):
    account = create(service)
    with pytest.raises(TradingAccountError):
        order(service, account, "LONG", "open", 1, 100, side="sell")
    with pytest.raises(TradingAccountError):
        order(service, account, "SHORT", "open", 1, 100, marketType="spot")
    with pytest.raises(TradingAccountError):
        service.update_account(account, {"settings": {"positionMode": "ONE_WAY"}})
    spot = service.place_order(account, {"exchange": "binance", "marketType": "spot", "symbol": "BTCUSDT",
        "type": "market", "side": "buy", "qty": "1", "referencePrice": "100"})
    assert "positionSide" not in spot["order"]


def test_equal_legs_keep_feed_without_orders_and_competing_markets_share_funds(service):
    account = create(service, "100")
    order(service, account, "LONG", "open", 1, 100)
    order(service, account, "SHORT", "open", 1, 100)
    order(service, account, "LONG", "open", 1, 200, symbol="ETHUSDT")
    assert not service.account_summary(account)["workingOrders"]
    assert len(service.working_instruments()) == 2
    tick(service, "BTCUSDT", 105)
    tick(service, "ETHUSDT", 210)
    s = service.account_summary(account)
    assert D(s["equity"]) == 110
    assert D(s["usedMargin"]) == 42
    assert {t["positionSide"]: D(t["unrealizedPnl"]) for t in s["positions"] if t["symbol"] == "BTCUSDT"} == {"LONG": 5, "SHORT": -5}
    # Each pending order fits alone; after BTC executes, ETH must recheck collateral.
    order(service, account, "LONG", "open", 5, 105, type="limit", limitPrice="101")
    eth = order(service, account, "LONG", "open", 3, 210, symbol="ETHUSDT", type="limit", limitPrice="201")
    tick(service, "BTCUSDT", 100)
    assert next(t for t in service.account_summary(account)["positions"]
                if t["symbol"] == "BTCUSDT" and t["positionSide"] == "LONG")["openQty"] == "6"
    tick(service, "ETHUSDT", 200)
    assert service.store.order(eth["id"])["reason"] == "insufficient_balance"


def test_legacy_order_fill_and_link_survive_v3_migration(service, tmp_path):
    import sqlite3

    account = service.create_account({"kind": "practice", "name": "Legacy"})["id"]
    instrument = {"exchange": "binance", "marketType": "futures", "symbol": "BTCUSDT"}
    service.place_order(account, {**instrument, "type": "market", "side": "buy", "qty": "1", "referencePrice": "100"})
    service.place_order(account, {**instrument, "type": "market", "side": "sell", "qty": "2", "referencePrice": "100"})
    before = service.list_trades(account)["trades"]
    reversed_trade = next(t for t in before if t["id"].endswith("~r"))
    note = service.create_entry(account, {**instrument, "kind": "note", "tradeId": reversed_trade["id"], "fields": {"entryBasis": "old reversal"}})
    original = service.account_state(account)
    # Clone the fixture and remove precisely the columns and setting introduced in v4.
    database = tmp_path / "v3.sqlite3"
    with sqlite3.connect(database) as old, sqlite3.connect(service.store.path) as source:
        source.backup(old)
        for table in ("orders", "fills"):
            old.execute(f"ALTER TABLE {table} DROP COLUMN position_side")
        old.execute("UPDATE accounts SET settings_json=json_remove(settings_json,'$.positionMode')")
        old.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
    store = TradingStore(database)
    try:
        migrated = TradingAccountService(store, snapshot_dir=tmp_path / "snaps", clock=service.test_clock)
        state = migrated.account_state(account)
        assert state["summary"] == original["summary"]
        assert state["trades"] == original["trades"]
        assert migrated.entry_detail(note["id"])["tradeId"] == reversed_trade["id"]
    finally:
        store.close()


def test_late_candle_cannot_change_the_id_of_an_already_open_hedge_leg(service):
    account = create(service)
    order(service, account, "LONG", "open", 1, 100, type="limit", limitPrice="95")
    service.test_clock.now += 180_000
    order(service, account, "LONG", "open", 1, 100, bracketStop="50")
    original = service.account_summary(account)["positions"][0]
    fill_time = original["openedAtMs"]
    service.apply_market_bars(("binance", "futures", "BTCUSDT"),
        [{"time": T0 // 1000 + 60, "open": 100, "high": 102, "low": 94, "close": 98}],
        observed_ms=service.test_clock.now)
    position = service.account_summary(account)["positions"][0]
    assert position["id"] == original["id"] and position["openQty"] == "2"
    assert [leg["tsMs"] for leg in position["legs"]] == [fill_time, fill_time]
    assert len(service.trade_detail(account, position["id"])["protectionOrders"]) == 1
