"""Real BAR/account continuation versus an uninterrupted historical reference."""
from dataclasses import asdict
from decimal import Decimal
import json

import pytest

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from app.simulation.kernel import SimulationKernel
from app.backtest.identity import canonical_json
from app.simulation.execution_realism import EXECUTION_REALISM_V2, BAR_PATH_SCENARIO
from app.simulation.pine_bar_kernel import PineBarKernel


def events():
    return tuple(MarketEvent(i, i * 60_000, "BARS", {
        "open_time_ms": (i - 1) * 60_000, "close_time_ms": i * 60_000,
        "open": str(100 + i % 7), "high": str(105 + i % 7),
        "low": str(95 + i % 7), "close": str(102 + i % 7), "volume": "10",
    }) for i in range(1, 26))


def make_kernel(*, sparse=False, closing=False):
    return SimulationKernel(execution_model_revision=EXECUTION_REALISM_V2,
        bar_path_scenario=BAR_PATH_SCENARIO, participation_rate=Decimal("0.1"),
        equity_curve_event_interval=100 if sparse else 1,
        process_orders_on_close=closing, taker_fee_bps=Decimal("3"),
        maker_fee_bps=Decimal("1"))


def strategy(calls):
    def observe(visible, event):
        assert visible == (event,)
        calls.append(event.sequence)
        if event.sequence in (1, 10, 20):
            return [{"side": "BUY", "type": "MARKET", "qty": "2"}]
        if event.sequence in (6, 16):
            return [{"side": "SELL", "type": "LIMIT", "qty": "1", "limit_price": "102"}]
        if event.sequence == 25:
            return [{"side": "BUY", "type": "LIMIT", "qty": "1", "limit_price": "1"}]
        return []
    return observe


@pytest.mark.parametrize("sparse", [False, True])
@pytest.mark.parametrize("fast", [False, True])
def test_batches_and_durable_account_restore_equal_one_continuous_reference(sparse, fast):
    reference, resumed = make_kernel(sparse=sparse), make_kernel(sparse=sparse)
    reference._specialized_bar = resumed._specialized_bar = fast
    reference_calls, calls, commits = [], [], []
    expected = reference.run(events(), strategy(reference_calls), finalize=True)
    resumed.advance(events()[:7], strategy(calls), checkpoint_callback=lambda event: commits.append(event.sequence))
    # Cross a JSON storage boundary; no sharing live lists/account state.
    saved = json.loads(canonical_json(resumed.snapshot()))
    restored = make_kernel(sparse=sparse)
    restored._specialized_bar = fast
    restored.restore(saved)
    restored.advance(events()[7:19], strategy(calls), checkpoint_callback=lambda event: commits.append(event.sequence))
    restored.advance(events()[19:], strategy(calls), checkpoint_callback=lambda event: commits.append(event.sequence))
    assert any(order.status == "OPEN" for order in restored.orders)
    actual = restored.run((), strategy(calls), finalize=True)
    assert calls == reference_calls == commits == list(range(1, 26))
    assert asdict(actual) == asdict(expected)
    assert restored.snapshot() == reference.snapshot()
    assert actual.fills and actual.ledger


def test_continuation_does_not_materialize_report_or_end_orders(monkeypatch):
    kernel = make_kernel(sparse=True)
    def unexpected(*args, **kwargs):
        raise AssertionError("Continuation must not build/finalize the complete history")
    monkeypatch.setattr(SimulationKernel, "result", unexpected)
    monkeypatch.setattr(SimulationKernel, "_append_terminal_curve_point", unexpected)
    monkeypatch.setattr(SimulationKernel, "finalize_orders", unexpected)
    calls = []
    assert kernel.advance(events()[:1], strategy(calls)) is None
    assert calls == [1] and kernel.orders[0].status == "OPEN"
    kernel.advance(events()[1:3], strategy(calls))
    assert calls == [1, 2, 3] and kernel.fills


def test_fast_loop_fallback_preserves_batch_boundary():
    reference, batched = make_kernel(sparse=True), make_kernel(sparse=True)
    reference._specialized_bar = batched._specialized_bar = True
    def callback(kernel, calls):
        observe = strategy(calls)
        def step(visible, event):
            if event.sequence == 2:
                # Exercise the real specialized->generic loop handoff.
                kernel.market_observer = lambda ignored: None
            return observe(visible, event)
        return step
    a, b = [], []
    expected = reference.run(events(), callback(reference, a), finalize=True)
    batched.advance(events()[:9], callback(batched, b))
    batched.advance(events()[9:], callback(batched, b))
    actual = batched.run((), callback(batched, b), finalize=True)
    assert a == b == list(range(1, 26))
    assert asdict(expected) == asdict(actual)


def test_warmup_pause_and_strategy_failure_keep_existing_execution_order():
    reference, batched = make_kernel(), make_kernel()
    a, b = [], []
    expected = reference.run(events(), strategy(a), warmup_events=5, finalize=True)
    batched.advance(events()[:3], strategy(b), warmup_events=5)
    batched.paused = True
    saved = batched.snapshot()
    batched.advance(events()[3:6], strategy(b), warmup_events=5)
    assert batched.snapshot() == saved and b == [1, 2, 3]
    batched.paused = False
    batched.advance(events()[3:], strategy(b), warmup_events=5)
    assert asdict(batched.run((), strategy(b), finalize=True)) == asdict(expected)
    assert a == b == list(range(1, 26))
    def failure(visible, event):
        if event.sequence == 4:
            raise RuntimeError("provider failed")
        return []
    one, split = make_kernel(), make_kernel()
    with pytest.raises(RuntimeError, match="provider failed"):
        one.run(events(), failure)
    split.advance(events()[:2], failure)
    with pytest.raises(RuntimeError, match="provider failed"):
        split.advance(events()[2:], failure)
    assert one.snapshot() == split.snapshot()


def test_other_execution_clocks_and_missing_closing_handler_fail_before_input():
    def unread():
        raise AssertionError("Unsupported execution must reject before consuming input")
        yield
    with pytest.raises(MarketDatasetError, match="FIDELITY_UNSUPPORTED"):
        PineBarKernel().advance(unread(), strategy([]))
    with pytest.raises(MarketDatasetError, match="closing-tick handler"):
        make_kernel(closing=True).advance(unread(), strategy([]))
