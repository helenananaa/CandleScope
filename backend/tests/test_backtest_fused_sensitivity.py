from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import random

import pytest

from app.market_dataset.snapshot import MarketEvent
from app.simulation.cost_sensitivity import build_cost_sensitivity_matrix
from app.simulation.execution_realism import EXECUTION_REALISM_V2, BAR_PATH_SCENARIO
from app.simulation.kernel import SimulationKernel


def data(count=150):
    rng = random.Random(987)
    return tuple(MarketEvent(i, i*60000, "BARS", {
        "open": str(rng.randrange(96, 105)), "high": "110", "low": "90",
        "close": str(rng.randrange(96, 105)), "volume": str(rng.randrange(1, 8)),
    }) for i in range(1, count+1))


def intents(_, event):
    side = "BUY" if event.sequence % 2 else "SELL"
    mode = event.sequence % 17
    if mode == 1:
        return [{"type": "MARKET", "side": side, "qty": "2", "tif": "IOC"}]
    if mode == 2:
        return [{"type": "LIMIT", "side": side, "qty": "2", "limit_price": "100"},
                {"type": "STOP", "side": side, "qty": "2", "stop_price": "102"}]
    if mode == 3:
        return [{"type": "STOP_LIMIT", "side": side, "qty": "1", "stop_price": "99", "limit_price": "101"}]
    if mode == 4:
        return [{"type": "MARKET", "side": "SELL", "qty": "0.5", "reduce_only": True}]
    return []


@pytest.mark.parametrize("gap", ["REJECT", "PAUSE", "SKIP_WITH_WARNING"])
@pytest.mark.parametrize("end", ["CANCEL_AT_END", "KEEP_OPEN"])
@pytest.mark.parametrize("funding", ["0", "0.001"])
def test_fused_scenarios_preserve_full_reference_matrix_and_inputs(monkeypatch, gap, end, funding):
    events = data()
    if gap != "REJECT":
        events = tuple(replace(e, sequence=e.sequence + (2 if e.sequence >= 80 else 0)) for e in events)
    kernel = SimulationKernel(execution_model_revision=EXECUTION_REALISM_V2,
        bar_path_scenario=BAR_PATH_SCENARIO, participation_rate=Decimal("0.1"),
        taker_fee_bps=Decimal("4"), maker_fee_bps=Decimal("2"),
        funding_rate=Decimal(funding), funding_interval_ms=120000,
        gap_policy=gap, order_end_policy=end)
    primary = kernel.run(events, intents, finalize=True)
    before = deepcopy(kernel.snapshot())
    expected = build_cost_sensitivity_matrix(kernel, events, primary, fast_bar=False)
    monkeypatch.setenv("BACKTEST_FUSED_BAR_SENSITIVITY_ENABLED", "0")
    assert build_cost_sensitivity_matrix(kernel, events, primary) == expected
    monkeypatch.setenv("BACKTEST_FUSED_BAR_SENSITIVITY_ENABLED", "1")
    assert build_cost_sensitivity_matrix(kernel, events, primary) == expected
    assert kernel.snapshot() == before


def test_fused_reads_close_once_per_bar_and_keeps_scenario_capacity_separate(monkeypatch):
    import app.simulation.cost_sensitivity as module
    events = data(30)
    kernel = SimulationKernel(execution_model_revision=EXECUTION_REALISM_V2,
        bar_path_scenario=BAR_PATH_SCENARIO, participation_rate=Decimal("0.1"))
    primary = kernel.run(events, intents, finalize=True)
    expected = build_cost_sensitivity_matrix(kernel, events, primary, fast_bar=False)
    original, reads = module._bar_decimal, []
    def read(event, name):
        reads.append((event.sequence, name))
        return original(event, name)
    monkeypatch.setattr(module, "_bar_decimal", read)
    assert build_cost_sensitivity_matrix(kernel, events, primary) == expected
    assert reads == [(e.sequence, "close") for e in events]
    assert expected["scenarios"][-1]["hashes"] != expected["scenarios"][1]["hashes"]


def test_empty_fused_matrix_matches_reference():
    kernel = SimulationKernel(execution_model_revision=EXECUTION_REALISM_V2,
        bar_path_scenario=BAR_PATH_SCENARIO, participation_rate=Decimal("0.1"))
    primary = kernel.run((), lambda *_: [], finalize=True)
    assert build_cost_sensitivity_matrix(kernel, (), primary) == build_cost_sensitivity_matrix(kernel, (), primary, fast_bar=False)
