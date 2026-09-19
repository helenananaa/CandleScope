from dataclasses import replace
from decimal import Decimal

import pytest

from app.market_dataset.snapshot import MarketDatasetError
from app.simulation.cost_sensitivity import build_cost_sensitivity_matrix
from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from app.simulation.trade_kernel import TradeSimulationKernel
from scripts.benchmark_trade_strategy import events
from tests.test_trade_strategy_performance import mixed_orders


@pytest.mark.parametrize("indexed", [False, True])
@pytest.mark.parametrize("funding", ["0", "0.001"])
@pytest.mark.parametrize("account_v2", [False, True])
def test_pruning_matches_full_matrix_with_orders_and_positions(monkeypatch, indexed, funding, account_v2):
    from tests.test_backtest_account_v2_m4 import rules, event

    monkeypatch.setenv("BACKTEST_TRADE_ACTIVE_INDEX_ENABLED", str(int(indexed)))
    tape = events(301, 2)
    options = dict(execution_model_revision="EXECUTION_REALISM_V2",
                   participation_rate=Decimal("0.03"), funding_rate=Decimal(funding),
                   funding_interval_ms=60000)
    if account_v2:
        options.update(account_model="LINEAR_PERP_ONE_WAY_V2", funding_mode="FIXED_SCENARIO")
        tape = (rules(-2), event("MARK_INDEX", -1, mark_price="100", index_price="100"), *tape)
    kernel = DualClockSimulationKernel("1m", **options)
    primary = kernel.run(tape, mixed_orders, finalize=True)
    matrices = []
    for prune in (0, 1):
        monkeypatch.setenv("BACKTEST_PRUNED_DUAL_SENSITIVITY_ENABLED", str(prune))
        matrices.append(build_cost_sensitivity_matrix(kernel, tape, primary))
    assert matrices[0] == matrices[1]


def test_idle_clones_skip_work_but_still_validate_prices(monkeypatch):
    kernel = DualClockSimulationKernel("1m", execution_model_revision="EXECUTION_REALISM_V2",
                                       participation_rate=Decimal("0.1"))
    tape = events(100)
    primary = kernel.run(tape, lambda *_: [], finalize=True)
    calls = {"match": 0, "funding": 0}
    match = TradeSimulationKernel._match
    funding = TradeSimulationKernel._apply_funding

    def counted_match(self, event):
        calls["match"] += 1
        return match(self, event)

    def counted_funding(self, event):
        calls["funding"] += 1
        return funding(self, event)

    monkeypatch.setattr(TradeSimulationKernel, "_match", counted_match)
    monkeypatch.setattr(TradeSimulationKernel, "_apply_funding", counted_funding)
    monkeypatch.setenv("BACKTEST_PRUNED_DUAL_SENSITIVITY_ENABLED", "0")
    reference = build_cost_sensitivity_matrix(kernel, tape, primary)
    assert calls == {"match": 400, "funding": 400}
    calls.update(match=0, funding=0)
    monkeypatch.setenv("BACKTEST_PRUNED_DUAL_SENSITIVITY_ENABLED", "1")
    assert build_cost_sensitivity_matrix(kernel, tape, primary) == reference
    assert calls == {"match": 0, "funding": 0}
    for field in ("price", "qty"):
        bad = (replace(tape[0], payload={**tape[0].payload, field: "-1"}), *tape[1:])
        with pytest.raises(MarketDatasetError, match="DATA_QUALITY_FAILED"):
            build_cost_sensitivity_matrix(kernel, bad, primary)
