from decimal import Decimal as D

import pytest

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from app.simulation.execution_realism import BAR_PATH_SCENARIO, EXECUTION_REALISM_V2
from app.simulation.kernel import SimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from app.simulation.spot_cash_account import ACCOUNT_MODEL, SpotCashAccount
from tests.test_trade_tape import _trade


def kernel(kind, **kwargs):
    cls = SimulationKernel if kind == "bar" else TradeSimulationKernel
    args = dict(account_model=ACCOUNT_MODEL, initial_balance=D("1000"), slippage_bps=D("0"),
                taker_fee_bps=D("10"), maker_fee_bps=D("10"),
                execution_model_revision=EXECUTION_REALISM_V2, participation_rate=D("1"))
    if kind == "bar":
        args["bar_path_scenario"] = BAR_PATH_SCENARIO
    return cls(**{**args, **kwargs})


def event(kind, sequence, price="100", volume="10", close=None):
    if kind == "trade":
        return _trade(sequence, price=price, qty=volume)
    return MarketEvent(sequence=sequence, event_time_ms=sequence * 60_000, role="BARS", payload={
        "open": price, "close": close or price, "high": str(max(D(price), D(close or price))),
        "low": str(min(D(price), D(close or price))), "volume": volume,
    })


def order(qty="1", side="BUY", **kwargs):
    return {"side": side, "type": "MARKET", "qty": qty, **kwargs}


def test_cash_asset_equity_and_realized_journal_are_distinct_and_recoverable():
    account = SpotCashAccount(quote_balance=D("1000"), mark=D("100"), taker_fee_bps=D("10"))
    account.apply_fill(side="BUY", price=D("100"), qty=D("2"))
    assert account.quote_balance == D("799.8")
    account.mark = D("110")
    account.apply_fill(side="SELL", price=D("110"), qty=D("1"))
    assert account.quote_balance == D("909.69")
    assert account.equity() == D("1019.69")
    assert account.unrealized() == D("10")
    restored = SpotCashAccount(taker_fee_bps=D("10"))
    restored.restore(account.snapshot())
    assert restored.snapshot() == account.snapshot()
    restored.mark = D("90")
    restored.apply_fill(side="SELL", price=D("90"), qty=D("1"))
    assert restored.position_qty == 0
    assert restored.entry_price is None
    assert restored.quote_balance == restored.equity() == D("999.6")
    assert restored.fees_paid == D("0.4")


def test_book_assisted_spot_uses_real_print_valuation_and_preserves_rejected_capacity():
    from app.simulation.book_kernel import BookAssistedKernel
    from tests.test_book_assisted import _book, _trade as book_trade
    engine = BookAssistedKernel(account_model=ACCOUNT_MODEL, initial_balance=D("100"),
                                slippage_bps=D("0"), taker_fee_bps=D("0"))
    engine.run((_book(1, 1, snapshot=True), book_trade(2, 2), book_trade(3, 3)),
               lambda _, e: [order("1"), order("0.5")] if e.sequence == 2 else [])
    # Second order is refused at admission because the first reserves all cash.
    assert engine.rejected[0]["reason"] == "SPOT_INSUFFICIENT_CASH"
    # The first would cost 101 at the real ask and must also be refused.
    assert engine.rejected[-1]["reason"] == "SPOT_INSUFFICIENT_CASH"
    assert not engine.fills and engine.account.quote_balance == 100
    engine.run((book_trade(4, 4), book_trade(5, 5)),
               lambda _, e: [order("0.5")] if e.sequence == 4 else [])
    assert engine.fills[-1].price == 101
    assert engine.account.quote_balance == D("49.5")
    assert engine.account.mark == 100 and engine.account.equity() == D("99.5")


@pytest.mark.parametrize("kind", ["bar", "trade"])
@pytest.mark.parametrize("intent,reason", [
    (order("10"), "SPOT_INSUFFICIENT_CASH"),  # cash covers notional but not fees
    (order("1", "SELL"), "SPOT_INSUFFICIENT_BASE"),
])
def test_cash_and_no_short_constraints_reject_before_fill(kind, intent, reason):
    engine = kernel(kind)
    engine.run(tuple(event(kind, n) for n in range(1, 4)), lambda _, e: [intent] if e.sequence == 1 else [])
    assert not engine.fills
    assert engine.rejected[0]["reason"] == reason
    assert engine.account.quote_balance == 1000
    assert engine.account.position_qty == engine.fee_total == 0


@pytest.mark.parametrize("kind", ["bar", "trade"])
def test_pending_orders_share_cash_and_oco_siblings_do_not_double_reserve(kind):
    engine = kernel(kind)
    engine.run((event(kind, 1),), lambda _, e: [order("6", type="LIMIT", limit_price="99"),
                                                   order("5", type="LIMIT", limit_price="99")])
    assert len(engine.orders) == 1
    assert engine.rejected[0]["reason"] == "SPOT_INSUFFICIENT_CASH"
    engine.orders[0].status = "CANCELLED"
    engine.run((event(kind, 2),), lambda _, e: [order("5", type="LIMIT", limit_price="99")])
    assert len(engine.orders) == 2
    held = kernel(kind)
    held.account.mark = D("100")
    held.account.apply_fill(side="BUY", price=D("100"), qty=D("2"), fee=D("0"))
    held.run((event(kind, 1),), lambda _, e: [
        order("2", "SELL", type="LIMIT", limit_price="110", oco_group="exit"),
        order("2", "SELL", type="STOP", stop_price="90", oco_group="exit")])
    assert len(held.orders) == 2
    assert not held.rejected


@pytest.mark.parametrize("kind", ["bar", "trade"])
def test_price_gap_rejection_does_not_spend_cash_fees_or_market_capacity(kind):
    engine = kernel(kind)
    engine.run((event(kind, 1), event(kind, 2, "150")),
               lambda _, e: [order("8"), order("1")] if e.sequence == 1 else [])
    assert engine.rejected[0]["reason"] == "SPOT_INSUFFICIENT_CASH"
    assert len(engine.fills) == 1
    assert engine.fills[0].qty == 1
    assert engine.account.quote_balance == D("849.85")
    assert engine.fee_total == D("0.15")
    assert engine.orders[0].status == "REJECTED"


@pytest.mark.parametrize("kind", ["bar", "trade"])
def test_partial_fill_restore_then_gap_refuses_unaffordable_remainder(kind):
    engine = kernel(kind)
    def strategy(_, e):
        return [order("3")] if e.sequence == 1 else []
    engine.run((event(kind, 1), event(kind, 2, volume="1")), strategy)
    assert engine.account.position_qty == 1
    assert engine.orders[0].status == "PARTIAL"
    restored = kernel(kind)
    restored.restore(engine.snapshot())
    assert restored.account.snapshot() == engine.account.snapshot()
    for instance in (engine, restored):
        instance.run((event(kind, 3, "500"),), strategy)
        assert instance.account.position_qty == 1
        assert instance.account.quote_balance == D("899.9")
        assert instance.account.equity() == D("1399.9")
        assert instance.rejected[-1]["reason"] == "SPOT_INSUFFICIENT_CASH"
    assert restored.account.snapshot() == engine.account.snapshot()
    assert restored.result().fill_hash == engine.result().fill_hash


def test_spot_equity_uses_source_close_and_not_slipped_open_fill():
    engine = kernel("bar", slippage_bps=D("10"))
    engine.run((event("bar", 1), event("bar", 2, close="120")),
               lambda _, e: [order()] if e.sequence == 1 else [])
    assert engine.account.mark == 120
    assert engine.account.quote_balance == D("899.7999")
    assert engine.account.equity() == D("1019.7999")


@pytest.mark.parametrize("kind", ["bar", "trade"])
@pytest.mark.parametrize("invalid", [{"leverage": D("2")}, {"funding_rate": D("0.01")}, {"funding_mode": "FIXED_SCENARIO"}])
def test_cash_account_rejects_leverage_and_funding(kind, invalid):
    with pytest.raises(MarketDatasetError, match="SPOT_ACCOUNT_CONFIG_INVALID"):
        kernel(kind, **invalid)


def test_service_freezes_cash_model_and_signal_sizes_against_equity(tmp_path):
    import json
    from app.backtest.service import BacktestService
    from app.backtest.errors import BacktestError
    from app.backtest.strategy.protocol import DeterministicFakeProvider
    from tests.test_backtest_host_policy_m5 import settings
    service = BacktestService.start(settings(tmp_path), now_ms=1)
    payload = {"strategy_revision_id": "fake-signal-v1", "dataset_id": "spot-signal",
               "data_epoch": "sha256:" + "33" * 32, "snapshot_hash": "sha256:" + "44" * 32,
               "fidelity_mode": "BAR_APPROX", "source_event_kind": "BAR", "start_time_ms": 0,
               "end_time_ms": 180_000, "interval": "1m", "output_mode": "SIGNAL",
               "account_model": ACCOUNT_MODEL, "market_type": "spot", "leverage": "1", "funding_mode": "OFF",
               "initial_balance": "1000", "sizing_policy": "EQUITY_PERCENT_V1", "equity_percent": "10",
               "qty_step": "0.001", "taker_fee_bps": "10", "maker_fee_bps": "10", "slippage_bps": "0"}
    try:
        for values in ({"leverage": "2"}, {"market_type": "futures"}, {"funding_mode": "FIXED_SCENARIO"}):
            with pytest.raises(BacktestError, match="SPOT_ACCOUNT_CONFIG_INVALID"):
                service.validate_run({**payload, **values})
        run = service.create_run(payload, idempotency_key="spot-actual-signal", now_ms=2)
        assert json.loads(run["config_json"])["account_model"] == ACCOUNT_MODEL
        done = service.execute_bar_run(run["run_id"], events=tuple(event("bar", n) for n in range(1, 4)),
                                       provider=DeterministicFakeProvider(), now_ms=3)
        assert done["state"] == "COMPLETED"
        report = service.get_report(run["run_id"])
        assert report["account_model"] == report["identity"]["account_model"] == ACCOUNT_MODEL
        assert D(report["fills"][0]["qty"]) == 1
        account = report["account"]
        assert D(account["quote_balance"]) >= 0 and D(account["position_qty"]) >= 0
        assert D(account["equity"]) == D(account["quote_balance"]) + D(account["position_qty"]) * 100
        assert "funding" not in report["unmodeled"] and "liquidation" not in report["unmodeled"]
    finally:
        service.shutdown()


def test_builtin_python_template_emits_sizing_signals_and_preserves_absolute_api():
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from candlescope_backtest_sdk import Signal, TargetPosition
    text = (Path(__file__).parents[2] / "frontend/src/features/backtest/chart-tester/chartStrategyTesterUiModel.ts").read_text()
    source = json.JSONDecoder().raw_decode(text.split("export const PYTHON_SMA_SOURCE = ", 1)[1])[0]
    namespace = {}
    exec(compile(source, "builtin-python-sma", "exec"), namespace)
    strategy = namespace["Strategy"]()
    strategy.prepare({})
    outputs = [strategy.step(SimpleNamespace(bar=SimpleNamespace(close=str(price))))
               for price in [100, 101, 102, 103, 104, 90, 80]]
    assert all(isinstance(item, Signal) for item in outputs)
    assert outputs[0].direction == "FLAT"
    assert outputs[4].direction == "LONG"
    assert outputs[-1].direction == "FLAT"
    assert TargetPosition(quantity="1").to_payload() == {"quantity": "1"}
