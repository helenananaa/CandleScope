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


def _trade_kernel(*, account_v2=False, funding="0", end="CANCEL_AT_END", latency=(0, 0)):
    from app.simulation.trade_kernel import TradeSimulationKernel
    from scripts.benchmark_trade_strategy import events
    from tests.test_backtest_account_v2_m4 import rules, event

    options = dict(execution_model_revision=EXECUTION_REALISM_V2, participation_rate=Decimal("0.03"),
                   taker_fee_bps=Decimal("4"), maker_fee_bps=Decimal("2"), slippage_bps=Decimal("1"),
                   funding_rate=Decimal(funding), funding_interval_ms=60000, order_end_policy=end,
                   latency_ms=latency[0], latency_events=latency[1], checkpoint_event_interval=0)
    tape = events(301, 3)
    if account_v2:
        options.update(account_model="LINEAR_PERP_ONE_WAY_V2", funding_mode="FIXED_SCENARIO")
        tape = (rules(-2), event("MARK_INDEX", -1, mark_price="100", index_price="100"), *tape)
    return TradeSimulationKernel(**options), tape


@pytest.mark.parametrize("indexed", [False, True])
@pytest.mark.parametrize("account_v2", [False, True])
@pytest.mark.parametrize("funding", ["0", "0.001"])
@pytest.mark.parametrize("end", ["CANCEL_AT_END", "KEEP_OPEN"])
@pytest.mark.parametrize("latency", [(0, 0), (5, 1)])
def test_fused_trade_scenarios_preserve_full_reference_matrix(monkeypatch, indexed, account_v2, funding, end, latency):
    from tests.test_trade_strategy_performance import mixed_orders

    monkeypatch.setenv("BACKTEST_TRADE_ACTIVE_INDEX_ENABLED", str(int(indexed)))
    kernel, tape = _trade_kernel(account_v2=account_v2, funding=funding, end=end, latency=latency)
    primary = kernel.run(tape, mixed_orders, finalize=True)
    before = deepcopy(kernel.snapshot())
    monkeypatch.setenv("BACKTEST_FUSED_TRADE_SENSITIVITY_ENABLED", "0")
    expected = build_cost_sensitivity_matrix(kernel, tape, primary)
    assert [s["status"] for s in expected["scenarios"]] == ["COMPLETED"] * 5
    assert len({s["hashes"]["ledger"] for s in expected["scenarios"]}) > 1
    monkeypatch.setenv("BACKTEST_FUSED_TRADE_SENSITIVITY_ENABLED", "1")
    assert build_cost_sensitivity_matrix(kernel, tape, primary) == expected
    assert kernel.snapshot() == before


def test_fused_trade_scenarios_replace_four_kernel_runs(monkeypatch):
    from app.simulation.trade_kernel import TradeSimulationKernel

    kernel, tape = _trade_kernel()
    primary = kernel.run(tape, lambda *_: [], finalize=True)
    calls = {"run": 0, "match": 0}
    run, match = TradeSimulationKernel.run, TradeSimulationKernel._match

    def counted_run(self, *args, **kwargs):
        calls["run"] += 1
        return run(self, *args, **kwargs)

    def counted_match(self, event):
        calls["match"] += 1
        return match(self, event)

    monkeypatch.setattr(TradeSimulationKernel, "run", counted_run)
    monkeypatch.setattr(TradeSimulationKernel, "_match", counted_match)
    monkeypatch.setenv("BACKTEST_FUSED_TRADE_SENSITIVITY_ENABLED", "0")
    reference = build_cost_sensitivity_matrix(kernel, tape, primary)
    assert calls == {"run": 4, "match": 4 * 301}
    calls.update(run=0, match=0)
    monkeypatch.setenv("BACKTEST_FUSED_TRADE_SENSITIVITY_ENABLED", "1")
    assert build_cost_sensitivity_matrix(kernel, tape, primary) == reference
    # Idle clones skip matching; nothing can fill without a working order.
    assert calls == {"run": 0, "match": 0}


@pytest.mark.parametrize("field", ["price", "qty"])
def test_fused_trade_scenarios_still_reject_malformed_prints(monkeypatch, field):
    import decimal

    kernel, tape = _trade_kernel()
    primary = kernel.run(tape, lambda *_: [], finalize=True)
    bad = (*tape[:10], replace(tape[10], payload={**tape[10].payload, field: "x"}), *tape[11:])
    for fused in ("0", "1"):
        monkeypatch.setenv("BACKTEST_FUSED_TRADE_SENSITIVITY_ENABLED", fused)
        with pytest.raises(decimal.InvalidOperation):
            build_cost_sensitivity_matrix(kernel, bad, primary)
