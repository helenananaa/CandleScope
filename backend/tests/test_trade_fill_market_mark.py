from decimal import Decimal

import pytest

from app.market_dataset.snapshot import MarketEvent
from app.simulation import DualClockSimulationKernel, TradeSimulationKernel


def trade(sequence, time_ms, price="100"):
    return MarketEvent(sequence=sequence, event_time_ms=time_ms, role="TRADES", payload={
        "source_event_kind": "AGG_TRADE", "source_sequence": sequence,
        "tie_break": f"AGG_TRADE:{sequence}", "price": price, "qty": "10",
    })


def kernel(kind):
    options = {"slippage_bps": Decimal(100), "taker_fee_bps": Decimal(10)}
    return TradeSimulationKernel(**options) if kind == "trade" else DualClockSimulationKernel("1m", **options)


@pytest.mark.parametrize("kind", ["trade", "dual"])
@pytest.mark.parametrize("side,price,equity", [("BUY", "101", "9998.899"), ("SELL", "99", "9998.901")])
def test_terminal_open_position_marks_to_market_and_charges_slippage_immediately(kind, side, price, equity):
    result = kernel(kind).run((trade(1, 1000), trade(2, 60000)),
                              lambda *_: [{"side": side, "type": "MARKET", "qty": "1"}], finalize=True)
    assert len(result.fills) == 1
    assert Decimal(result.fills[0]["price"]) == Decimal(price)
    assert Decimal(result.ledger["account"]["mark"]) == Decimal(100)
    assert Decimal(result.ledger["account"]["equity"]) == Decimal(equity)
    assert Decimal(result.equity_curve[-1]["equity"]) == Decimal(equity)


@pytest.mark.parametrize("kind", ["trade", "dual"])
def test_market_mark_survives_checkpoint_at_fill_and_resume(kind):
    events = (trade(1, 1000), trade(2, 60000), trade(3, 61000, "102"))
    def strategy(_visible, event):
        return [{"side": "BUY", "type": "MARKET", "qty": "1"}] if event.sequence == 1 else []
    full = kernel(kind).run(events, strategy, finalize=True)
    paused = kernel(kind)
    partial = paused.run(events[:2], strategy)
    assert Decimal(partial.equity_curve[-1]["equity"]) == Decimal("9998.899")
    restored = kernel(kind)
    restored.restore(paused.snapshot())
    resumed = restored.run(events[2:], strategy, finalize=True)
    for field in ("decision_hash", "fill_hash", "ledger_hash", "report_hash"):
        assert getattr(resumed, field) == getattr(full, field)


def test_reversal_and_multiple_fills_keep_the_same_print_as_market_mark():
    events = tuple(trade(i, i * 1000) for i in range(1, 4))
    def strategy(_visible, event):
        if event.sequence == 1:
            return [{"side": "BUY", "type": "MARKET", "qty": "1"}] * 2
        if event.sequence == 2:
            return [{"side": "SELL", "type": "MARKET", "qty": "3"}]
        return []
    result = kernel("trade").run(events, strategy, finalize=True)
    cash = Decimal(10000)
    qty = Decimal(0)
    for fill in result.fills:
        signed = Decimal(fill["qty"]) * (1 if fill["side"] == "BUY" else -1)
        cash -= signed * Decimal(fill["price"]) + Decimal(fill["fee"])
        qty += signed
    assert qty == -1
    assert Decimal(result.ledger["account"]["mark"]) == 100
    assert Decimal(result.equity_curve[-1]["equity"]) == cash + qty * 100
