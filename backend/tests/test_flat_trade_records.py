from dataclasses import asdict, dataclass, replace
from decimal import Decimal

import pytest

from app.backtest.checkpoint_history import trade_history_encoder
from app.simulation.kernel import SimulatedFill
from app.simulation.trade_kernel import TradeSimulationKernel
from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from scripts.benchmark_trade_strategy import events
from tests.test_trade_strategy_performance import mixed_orders


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize("v2", [False, True])
def test_flat_records_preserve_result_snapshot_feedback_and_resume(monkeypatch, dual, v2):
    options = {"checkpoint_event_interval": 0}
    if v2:
        options.update(execution_model_revision="EXECUTION_REALISM_V2", participation_rate=Decimal("0.03"))
    outcomes = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_FLAT_TRADE_RECORDS_ENABLED", str(enabled))
        def factory():
            return DualClockSimulationKernel("1m", **options) if dual else TradeSimulationKernel(**options)
        kernel = factory()
        feedback = []
        execution = kernel.execution if dual else kernel
        execution.execution_reporter = feedback.append
        kernel.run(events(501, 2)[:251], mixed_orders)
        snapshot = kernel.snapshot()
        restored = factory()
        restored.restore(snapshot)
        execution = restored.execution if dual else restored
        execution.execution_reporter = feedback.append
        result = restored.run(events(501, 2)[251:], mixed_orders, finalize=True)
        history = trade_history_encoder()
        chunked = restored.snapshot(history_encoder=history)
        outcomes.append((result, snapshot, restored.snapshot(), feedback, chunked, history.pending, history.logical_extra))
    assert outcomes[0] == outcomes[1]


def test_flat_record_fallback_detaches_mutable_fields_and_subclasses(monkeypatch):
    monkeypatch.setenv("BACKTEST_FLAT_TRADE_RECORDS_ENABLED", "1")
    kernel = TradeSimulationKernel()
    base = SimulatedFill("o", 1, 1, "BUY", Decimal("1.2300"), Decimal("2"), Decimal("0"), "test")
    assert kernel._record_encoder(base) == asdict(base)
    mutable = replace(base, reason={"nested": [1]})
    encoded = kernel._record_encoder(mutable)
    assert encoded == asdict(mutable)
    encoded["reason"]["nested"].append(2)
    assert mutable.reason == {"nested": [1]}

    @dataclass(frozen=True)
    class Extended(SimulatedFill):
        extra: str = "subclass"

    child = Extended(**asdict(base))
    assert kernel._record_encoder(child) == asdict(child)
