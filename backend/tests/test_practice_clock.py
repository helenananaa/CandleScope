"""ADR-BACKTEST-015 P6e3: the Host kernel's PRACTICE clock fills exactly like a practice account.

The same closed 1m candles and the same orders go through a practice account (the practice
service, the user's own account path) and through ``SimulationKernel(bar_clock="PRACTICE")``
(a strategy deciding at each close). Fills (time, side, quantity, price, fee), refusals and
the final equity must be identical: one account model, two ledgers.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from app.simulation.kernel import SimulationKernel
from app.trading_accounts.models import TradingAccountError
from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore
from tests.practice_baselines import candles
from tests.test_trading_accounts import Clock, FakeMarket

FEES = {"takerFeeRate": "0.0005", "makerFeeRate": "0.0002", "slippageBps": "1"}
KERNEL_FEES = {"taker_fee_bps": Decimal(5), "maker_fee_bps": Decimal(2), "slippage_bps": Decimal(1)}
REFUSALS = {"TRADING_INSUFFICIENT_BALANCE": "INSUFFICIENT_BALANCE", "TRADING_INSUFFICIENT_POSITION": "INSUFFICIENT_POSITION",
            "TRADING_NOTHING_TO_REDUCE": "NOTHING_TO_REDUCE", "TRADING_STOP_WOULD_TRIGGER": "STOP_WOULD_TRIGGER"}


def one_way(index, bar):
    close, low = bar["close"], bar["low"]
    return {
        2: [dict(side="buy", type="market", qty=2, bracketStop=close - 3, bracketTarget=close + 4)],
        9: [dict(side="buy", type="limit", qty=1, limitPrice=low - 1)],
        14: [dict(side="sell", type="stop", qty=1, stopPrice=close - 2)],
        20: [dict(side="sell", type="market", qty=3, bracketStop=close + 3, bracketTarget=close - 5)],
        27: [dict(side="buy", type="limit", qty=1, limitPrice=close - 2, reduceOnly=True)],
        33: [dict(side="buy", type="market", qty=120)],
        36: [dict(side="buy", type="stop", qty=1, stopPrice=close + 3)],
        40: [dict(side="sell", type="stop", qty=1, stopPrice=close + 1)],
        42: [dict(side="buy", type="limit", qty=1, limitPrice=close + 2)],  # marketable: fills at the close
    }.get(index, [])


def spot(index, bar):
    close, low = bar["close"], bar["low"]
    return {
        2: [dict(side="buy", type="market", qty=3, bracketStop=close - 3)],
        8: [dict(side="sell", type="market", qty=5)],
        11: [dict(side="buy", type="limit", qty=2, limitPrice=low - 1)],
        17: [dict(side="sell", type="limit", qty=1, limitPrice=close + 3)],
        24: [dict(side="sell", type="stop", qty=1, stopPrice=close - 2)],
        30: [dict(side="sell", type="limit", qty=1, limitPrice=close - 1, reduceOnly=True)],
    }.get(index, [])


def intents(request):
    """A practice order as a strategy's intents: a bracket becomes reduce-only OCO exits after the entry."""
    side = request["side"].upper()
    order = {"type": request["type"].upper(), "side": side, "qty": str(request["qty"]),
             **({"limit_price": str(request["limitPrice"])} if "limitPrice" in request else {}),
             **({"stop_price": str(request["stopPrice"])} if "stopPrice" in request else {}),
             **({"reduce_only": True} if request.get("reduceOnly") else {})}
    exits = []
    exit_side = "SELL" if side == "BUY" else "BUY"
    group = {"oco_group": "bracket"} if "bracketStop" in request and "bracketTarget" in request else {}
    if "bracketTarget" in request:
        exits.append({"type": "LIMIT", "side": exit_side, "qty": str(request["qty"]),
                      "limit_price": str(request["bracketTarget"]), "reduce_only": True, **group})
    if "bracketStop" in request:
        exits.append({"type": "STOP", "side": exit_side, "qty": str(request["qty"]),
                      "stop_price": str(request["bracketStop"]), "reduce_only": True, **group})
    return [[order], exits]


def bar_event(index, bar):
    start = bar["time"] * 1000
    return MarketEvent(index + 1, start + 59_999, "BARS", {
        "open_time_ms": start, "close_time_ms": start + 59_999, "volume": "12",
        **{key: str(bar[key]) for key in ("open", "high", "low", "close")}})


def practice_account(tmp_path, market_type, script):
    """Place each order just after a candle closes, then apply the next closed candle."""
    clock, market = Clock(0), FakeMarket()
    store = TradingStore(tmp_path / f"{market_type}.sqlite3")
    service = TradingAccountService(store, snapshot_dir=tmp_path / "snaps", market=market, clock=clock)
    try:
        account = service.create_account({"kind": "practice", "name": market_type, "settings": {
            "initialBalance": "1000", "leverage": "10", **FEES,
            **({"positionMode": "ONE_WAY"} if market_type == "futures" else {})}})["id"]
        refusals = []
        for index, bar in enumerate(candles()):
            close_ms = bar["time"] * 1000 + 59_999
            clock.now = close_ms
            market.bar = dict(bar)
            if index:
                service.apply_market_bars(("binance", market_type, "BTCUSDT"), [dict(bar)], observed_ms=close_ms)
            for request in script(index, bar):
                payload = {"exchange": "binance", "marketType": market_type, "symbol": "BTCUSDT",
                           **{key: str(value) if not isinstance(value, bool) else value for key, value in request.items()}}
                if request["type"] != "limit":
                    payload["referencePrice"] = str(bar["close"])
                try:
                    service.place_order(account, payload)
                except TradingAccountError as exc:
                    refusals.append((index, REFUSALS.get(exc.code, exc.code)))
        fills = [(int(row["tsMs"]), row["side"], Decimal(row["qty"]), Decimal(row["price"]), Decimal(row["fee"]))
                 for row in service.list_fills(account)["fills"]]
        equity = Decimal(service.account_summary(account)["equity"])
    finally:
        store.close()
    return sorted(fills), refusals, equity


def practice_clock(market_type, script, *, split_at=None):
    settings = dict(bar_clock="PRACTICE", leverage=Decimal(10) if market_type == "futures" else Decimal(1),
                    initial_balance=Decimal(1000), **KERNEL_FEES,
                    account_model="LINEAR_PERP_ONE_WAY_V1" if market_type == "futures" else "SPOT_CASH_V1")
    kernel = SimulationKernel(**settings)
    plans = {}

    def strategy(_visible, event):
        return plans.get(event.sequence, [])

    rows = list(enumerate(candles()))
    events = [bar_event(index, bar) for index, bar in rows]
    for index, bar in rows:
        plan = [item for request in script(index, bar) for group in intents(request) for item in group]
        if plan:
            plans[index + 1] = plan
    if split_at is None:
        kernel.run(events, strategy)
    else:
        kernel.advance(events[:split_at], strategy)
        restored = SimulationKernel(**settings)
        restored.restore(deepcopy(kernel.snapshot()))
        kernel = restored
        kernel.advance(events[split_at:], strategy)
        kernel.run((), strategy)
    refusals = sorted({(rejected["sequence"] - 1, rejected["reason"]) for rejected in kernel.rejected})
    fills = [(fill.event_time_ms, fill.side.lower(), fill.qty, fill.price, fill.fee) for fill in kernel.fills]
    return kernel, sorted(fills), refusals, kernel.account.equity()


@pytest.mark.parametrize("market_type,script", [("futures", one_way), ("spot", spot)], ids=["futures-one-way", "spot"])
def test_practice_clock_fills_exactly_like_a_practice_account(tmp_path, market_type, script):
    account_fills, account_refusals, account_equity = practice_account(tmp_path, market_type, script)
    kernel, fills, refusals, equity = practice_clock(market_type, script)
    assert len(fills) >= 5, "the script must exercise the model"
    assert fills == account_fills
    assert refusals == sorted(account_refusals)
    assert equity == account_equity
    assert kernel.fill_policy == "PRACTICE_CANDLE_PATH_V1"


@pytest.mark.parametrize("market_type,script", [("futures", one_way), ("spot", spot)], ids=["futures-one-way", "spot"])
def test_practice_clock_continues_from_a_checkpoint_like_one_run(market_type, script):
    _, whole, refusals, equity = practice_clock(market_type, script)
    whole_kernel = practice_clock(market_type, script)[0]
    for split in (5, 21, 37):
        resumed, fills, resumed_refusals, resumed_equity = practice_clock(market_type, script, split_at=split)
        assert (fills, resumed_refusals, resumed_equity) == (whole, refusals, equity)
        assert resumed.result().report_hash == whole_kernel.result().report_hash


def test_practice_clock_refuses_what_the_practice_model_does_not_have():
    for settings in (dict(account_model="LINEAR_PERP_ONE_WAY_V2"), dict(funding_mode="FIXED_SCENARIO"),
                     dict(execution_model_revision="EXECUTION_REALISM_V2", participation_rate=Decimal("0.5"),
                          bar_path_scenario="OHLC_WORST_CASE_STOP_FIRST_V1")):
        with pytest.raises(MarketDatasetError):
            SimulationKernel(bar_clock="PRACTICE", **settings)
    kernel = SimulationKernel(bar_clock="PRACTICE", leverage=Decimal(10))
    kernel.run([bar_event(0, candles()[0])], lambda *_: [{"type": "STOP_LIMIT", "side": "BUY", "qty": "1",
                                                           "stop_price": "200", "limit_price": "201"}])
    assert [row["reason"] for row in kernel.rejected] == ["ORDER_TYPE_UNSUPPORTED"]
    practice = SimulationKernel(bar_clock="PRACTICE", leverage=Decimal(10))
    practice.run([bar_event(0, candles()[0])], lambda *_: [])
    with pytest.raises(MarketDatasetError, match="practice clock"):
        SimulationKernel().restore(practice.snapshot())
    with pytest.raises(MarketDatasetError, match="practice path checkpoint"):
        SimulationKernel(bar_clock="PRACTICE").restore(SimulationKernel().snapshot())
