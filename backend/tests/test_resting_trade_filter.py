from decimal import Decimal

import pytest

from app.simulation.trade_kernel import TradeSimulationKernel
from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from scripts.benchmark_trade_strategy import events
from tests.test_trade_strategy_performance import mixed_orders


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("indexed", [False, True])
@pytest.mark.parametrize("account_v2", [False, True])
def test_resting_filter_mixed_orders_and_resume(monkeypatch, dual, v2, indexed, account_v2):
    monkeypatch.setenv("BACKTEST_TRADE_ACTIVE_INDEX_ENABLED", str(int(indexed)))
    outcomes = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_TRADE_RESTING_FILTER_ENABLED", str(enabled))
        options = dict(checkpoint_event_interval=0, funding_rate=Decimal("0.001"), funding_interval_ms=60000)
        if v2:
            options.update(execution_model_revision="EXECUTION_REALISM_V2", participation_rate=Decimal("0.03"),
                           latency_events=1, latency_ms=5)
        if account_v2:
            options.update(account_model="LINEAR_PERP_ONE_WAY_V2", funding_mode="FIXED_SCENARIO")

        def factory():
            return DualClockSimulationKernel("1m", **options) if dual else TradeSimulationKernel(**options)

        kernel = factory()
        tape = events(1000, 2)
        if account_v2:
            from tests.test_backtest_account_v2_m4 import rules, event
            tape = (rules(-2), event("MARK_INDEX", -1, mark_price="100", index_price="100"), *tape)
        kernel.run(tape[:501], mixed_orders)
        state = kernel.snapshot()
        restored = factory()
        restored.restore(state)
        result = restored.run(tape[501:], mixed_orders, finalize=True)
        assert result == kernel.run(tape[501:], mixed_orders, finalize=True)
        outcomes.append((result, restored.snapshot()))
    assert outcomes[0] == outcomes[1]


def test_unfilled_ioc_expires_but_stop_limit_still_activates(monkeypatch):
    outcomes = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_TRADE_RESTING_FILTER_ENABLED", str(enabled))
        kernel = TradeSimulationKernel(execution_model_revision="EXECUTION_REALISM_V2",
                                       participation_rate=Decimal("0.1"), checkpoint_event_interval=0)

        def strategy(visible, event):
            if event.sequence != 1:
                return []
            return [dict(side="BUY", type="LIMIT", qty="1", limit_price="50", tif="IOC"),
                    dict(side="BUY", type="STOP_LIMIT", qty="1", stop_price="99", limit_price="50")]

        result = kernel.run(events(5), strategy)
        assert kernel.orders[0].status == "EXPIRED"
        assert kernel.orders[1].activated
        assert not kernel.fills
        outcomes.append((result, kernel.snapshot()))
    assert outcomes[0] == outcomes[1]


def test_fill_callback_can_amend_later_limit_in_same_print(monkeypatch):
    outcomes = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_TRADE_RESTING_FILTER_ENABLED", str(enabled))
        kernel = TradeSimulationKernel(checkpoint_event_interval=0)

        def report(value):
            if "fill" in value:
                kernel.orders[1].limit_price = Decimal("101")

        kernel.execution_reporter = report
        result = kernel.run(events(2), lambda _, event: [
            dict(side="BUY", type="MARKET", qty="1"),
            dict(side="BUY", type="LIMIT", qty="1", limit_price="50"),
        ] if event.sequence == 1 else [])
        assert len(kernel.fills) == 2
        outcomes.append((result, kernel.snapshot()))
    assert outcomes[0] == outcomes[1]
