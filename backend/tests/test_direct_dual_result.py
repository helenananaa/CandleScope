from decimal import Decimal

import pytest

from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from scripts.benchmark_trade_strategy import events
from tests.test_trade_strategy_performance import mixed_orders


@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("count", [0, 501])
def test_direct_result_is_exact_and_does_not_mutate_state(monkeypatch, v2, stream, count):
    options = {"scale_stream_decisions": stream}
    if v2:
        options.update(execution_model_revision="EXECUTION_REALISM_V2", participation_rate=Decimal("0.03"))
    kernel = DualClockSimulationKernel("1m", **options)
    tape = events(count, 2)
    kernel.run(tape[:201], mixed_orders)
    restored = DualClockSimulationKernel("1m", **options)
    restored.restore(kernel.snapshot())
    restored.run(tape[201:], mixed_orders, finalize=True)
    before = restored.snapshot()
    monkeypatch.setenv("BACKTEST_DIRECT_DUAL_RESULT_ENABLED", "0")
    reference = restored.result()
    monkeypatch.setenv("BACKTEST_DIRECT_DUAL_RESULT_ENABLED", "1")
    assert restored.result() == reference
    assert restored.snapshot() == before


def test_direct_result_avoids_discarded_hashes(monkeypatch):
    import app.simulation.trade_kernel as trade
    import app.simulation.dual_clock_kernel as dual

    kernel = DualClockSimulationKernel("1m")
    kernel.run(events(51, 2), mixed_orders, finalize=True)
    original = trade.sha256_hex
    calls = []

    def hashed(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(trade, "sha256_hex", hashed)
    monkeypatch.setattr(dual, "sha256_hex", hashed)
    monkeypatch.setenv("BACKTEST_DIRECT_DUAL_RESULT_ENABLED", "0")
    reference = kernel.result()
    assert len(calls) == 7
    calls.clear()
    monkeypatch.setenv("BACKTEST_DIRECT_DUAL_RESULT_ENABLED", "1")
    assert kernel.result() == reference
    assert len(calls) == 4


def test_custom_execution_result_is_preserved(monkeypatch):
    calls = []

    class Custom(TradeSimulationKernel):
        def result(self):
            calls.append(True)
            return super().result()

    kernel = DualClockSimulationKernel("1m")
    kernel.execution = Custom()
    monkeypatch.setenv("BACKTEST_DIRECT_DUAL_RESULT_ENABLED", "1")
    kernel.result()
    assert calls == [True]
