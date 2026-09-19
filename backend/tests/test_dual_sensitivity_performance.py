from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pytest

from app.simulation.cost_sensitivity import build_cost_sensitivity_matrix
from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from scripts.benchmark_trade_strategy import events
from tests.test_trade_strategy_performance import mixed_orders


@pytest.mark.parametrize("funding", ["0", "0.001"])
@pytest.mark.parametrize("end", ["CANCEL_AT_END", "KEEP_OPEN"])
@pytest.mark.parametrize("gap", ["REJECT", "SKIP_WITH_WARNING"])
def test_shared_clock_preserves_entire_matrix(monkeypatch, funding, end, gap):
    tape = events(500, 2)
    if gap == "SKIP_WITH_WARNING":
        tape = tuple(
            replace(
                e, event_time_ms=e.event_time_ms + (120000 if e.sequence >= 200 else 0)
            )
            for e in tape
        )
    kernel = DualClockSimulationKernel(
        "1m",
        execution_model_revision="EXECUTION_REALISM_V2",
        participation_rate=Decimal("0.03"),
        taker_fee_bps=Decimal("4"),
        maker_fee_bps=Decimal("2"),
        slippage_bps=Decimal("3"),
        latency_events=1,
        latency_ms=5,
        funding_rate=Decimal(funding),
        funding_interval_ms=60000,
        order_end_policy=end,
        gap_policy=gap,
    )
    primary = kernel.run(tape, mixed_orders, finalize=True)
    before = deepcopy(kernel.snapshot())
    monkeypatch.setenv("BACKTEST_FUSED_DUAL_SENSITIVITY_ENABLED", "0")
    reference = build_cost_sensitivity_matrix(kernel, tape, primary)
    monkeypatch.setenv("BACKTEST_FUSED_DUAL_SENSITIVITY_ENABLED", "1")
    assert build_cost_sensitivity_matrix(kernel, tape, primary) == reference
    assert kernel.snapshot() == before


@pytest.mark.parametrize("empty", [False, True])
def test_contract_auxiliary_events_and_empty_tape(monkeypatch, empty):
    from tests.test_backtest_account_v2_m4 import rules, event

    tape = events(100, 2)
    tape = (
        rules(-2),
        event("MARK_INDEX", -1, mark_price="100", index_price="100"),
        *tape,
    )
    if empty:
        tape = ()
    kernel = DualClockSimulationKernel(
        "1m",
        account_model="LINEAR_PERP_ONE_WAY_V2",
        execution_model_revision="EXECUTION_REALISM_V2",
        participation_rate=Decimal("0.03"),
        leverage=Decimal("10"),
        funding_mode="FIXED_SCENARIO",
        funding_rate=Decimal("0.001"),
        funding_interval_ms=60000,
    )
    primary = kernel.run(tape, mixed_orders, finalize=True)
    monkeypatch.setenv("BACKTEST_FUSED_DUAL_SENSITIVITY_ENABLED", "0")
    reference = build_cost_sensitivity_matrix(kernel, tape, primary)
    monkeypatch.setenv("BACKTEST_FUSED_DUAL_SENSITIVITY_ENABLED", "1")
    assert build_cost_sensitivity_matrix(kernel, tape, primary) == reference


@pytest.mark.parametrize("bad", ["gap", "kind", "role", "budget"])
def test_shared_clock_rejects_invalid_inputs_like_reference(monkeypatch, bad):
    kernel = DualClockSimulationKernel(
        "1m",
        execution_model_revision="EXECUTION_REALISM_V2",
        participation_rate=Decimal("0.1"),
    )
    tape = events(20)
    primary = kernel.run(tape, mixed_orders, finalize=True)
    if bad == "gap":
        tape = tape[:5] + tape[6:]
    elif bad == "kind":
        tape = tuple(
            replace(e, payload={**e.payload, "source_event_kind": "RAW_TRADE"})
            for e in tape
        )
    elif bad == "role":
        tape += (MarketEvent(21, 200000, "INVALID", {}),)
    else:
        kernel.max_events = 1
    codes = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_FUSED_DUAL_SENSITIVITY_ENABLED", str(enabled))
        with pytest.raises(MarketDatasetError) as error:
            build_cost_sensitivity_matrix(kernel, tape, primary)
        codes.append(error.value.code)
    assert codes[0] == codes[1]


def test_shared_sensitivity_builds_each_trade_once_and_retains_all_scenarios(
    monkeypatch,
):
    from app.simulation.trade_bar_builder import TradeBarBuilder

    tape = events(100, 2)
    kernel = DualClockSimulationKernel(
        "1m",
        execution_model_revision="EXECUTION_REALISM_V2",
        participation_rate=Decimal("0.1"),
    )
    primary = kernel.run(tape, mixed_orders, finalize=True)
    original = TradeBarBuilder.push
    reads = []

    def push(self, trade):
        reads.append(trade.sequence)
        return original(self, trade)

    monkeypatch.setattr(TradeBarBuilder, "push", push)
    monkeypatch.setenv("BACKTEST_FUSED_DUAL_SENSITIVITY_ENABLED", "1")
    matrix = build_cost_sensitivity_matrix(kernel, tape, primary)
    assert reads == [e.sequence for e in tape]
    assert len(matrix["scenarios"]) == 5


@pytest.mark.parametrize("interval", [1, 7, 1000])
@pytest.mark.parametrize("daily", [False, True])
@pytest.mark.parametrize("account_v2", [False, True])
def test_lazy_curve_preserves_every_point_and_resume(
    monkeypatch, interval, daily, account_v2
):
    from tests.test_backtest_account_v2_m4 import rules, event

    tape = events(301, 2)
    options = dict(
        execution_model_revision="EXECUTION_REALISM_V2",
        participation_rate=Decimal("0.1"),
        equity_curve_event_interval=interval,
        equity_curve_mode="UTC_DAILY_CLOSE_V1" if daily else None,
    )
    if account_v2:
        options["account_model"] = "LINEAR_PERP_ONE_WAY_V2"
        tape = (
            rules(-2),
            event("MARK_INDEX", -1, mark_price="100", index_price="100"),
            *tape,
        )
    outputs = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_LAZY_DUAL_CURVE_ENABLED", str(enabled))
        kernel = DualClockSimulationKernel("1m", **options)
        kernel.run(tape[:111], mixed_orders)
        state = kernel.snapshot()
        resumed = DualClockSimulationKernel("1m", **options)
        resumed.restore(state)
        result = resumed.run(tape[111:], mixed_orders, finalize=True)
        outputs.append((result, resumed.snapshot()))
    assert outputs[0] == outputs[1]


def test_fused_historical_funding_and_mark_events_match_reference(monkeypatch):
    from tests.test_backtest_account_v2_m4 import rules, event

    tape = [rules(-2), event("MARK_INDEX", -1, mark_price="100", index_price="100")]
    for trade in events(30, 2):
        tape.append(trade)
        if trade.sequence % 5 == 0:
            tape.extend(
                [
                    event(
                        "FUNDING",
                        trade.event_time_ms + 1,
                        period_id=str(trade.sequence),
                        funding_rate="0.001",
                    ),
                    event(
                        "MARK_INDEX",
                        trade.event_time_ms + 2,
                        mark_price="102",
                        index_price="102",
                    ),
                ]
            )
    tape = tuple(replace(e, sequence=i) for i, e in enumerate(tape, 1))
    kernel = DualClockSimulationKernel(
        "1m",
        account_model="LINEAR_PERP_ONE_WAY_V2",
        funding_mode="HISTORICAL_REQUIRED",
        leverage=Decimal("5"),
        execution_model_revision="EXECUTION_REALISM_V2",
        participation_rate=Decimal("0.1"),
    )
    primary = kernel.run(tape, mixed_orders, finalize=True)
    matrices = []
    for enabled in (0, 1):
        monkeypatch.setenv("BACKTEST_FUSED_DUAL_SENSITIVITY_ENABLED", str(enabled))
        matrices.append(build_cost_sensitivity_matrix(kernel, tape, primary))
    assert matrices[0] == matrices[1]
