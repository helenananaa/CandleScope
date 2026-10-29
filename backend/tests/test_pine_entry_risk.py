from copy import deepcopy
from decimal import Decimal

import pytest

from app.backtest.errors import BacktestError
from app.backtest.external_orders import ExternalOrders
from app.market_dataset.snapshot import MarketEvent
from app.simulation.kernel import SimulationKernel


def configuration(*rules):
    return {"schemaVersion": 1, "unresolvedCallSiteIds": [], "rules": [
        {"callSiteId": i, "resolved": True, "function": "strategy.risk." + name, **value}
        for i, (name, value) in enumerate(rules)]}


def limit(value):
    return "max_position_size", {"value": value}


def direction(value):
    return "allow_entry_in", {"direction": "strategy.direction." + value}


def intent(name, side="long", qty=5, action="entry", **extra):
    return {"action": action, "id": name, "direction": side, "qty": qty, **extra}


def event(i, price=10):
    return MarketEvent(i, i*60000-1, "BARS", {"open_time_ms": (i-1)*60000,
        "close_time_ms": i*60000-1, **{k: str(price) for k in ("open", "high", "low", "close")}, "volume": "100"})


def make_kernel(config):
    kernel = SimulationKernel(slippage_bps=Decimal(0))
    orders = ExternalOrders(kernel)
    orders.configure(8)
    orders.entry_risk.configure(config)
    return kernel, orders


def test_same_bar_pending_entries_recheck_the_live_position_and_keep_strictest_limit():
    kernel, orders = make_kernel(configuration(limit(4), limit(2)))
    kernel.run([event(i) for i in range(1, 4)], lambda _, e: orders.translate(
        [intent("A"), intent("B")] if e.sequence == 1 else [], e.sequence))
    assert [fill.qty for fill in kernel.fills] == [Decimal(2)]
    assert kernel.account.position_qty == 2
    assert kernel.orders[1].status == "CANCELLED"
    assert orders.report()["risk_configuration"]["rules"][1]["value"] == 2


def test_direction_converts_a_prohibited_price_reversal_to_market_close():
    kernel, orders = make_kernel(configuration(direction("long")))
    batches = {1: [intent("L", qty=3)], 2: [intent("S", "short", limit=1)]}
    kernel.run([event(i) for i in range(1, 5)], lambda _, e: orders.translate(batches.get(e.sequence, []), e.sequence))
    assert [fill.qty for fill in kernel.fills] == [Decimal(3), Decimal(3)]
    assert kernel.orders[1].type == "MARKET"
    assert not orders.lots and kernel.account.position_qty == 0


def test_generic_order_bypasses_entry_constraints_but_entry_reversal_uses_limit():
    kernel, orders = make_kernel(configuration(direction("short"), limit(2)))
    batches = {1: [intent("generic", qty=8, action="order")], 2: [intent("S", "short")]}
    kernel.run([event(i) for i in range(1, 5)], lambda _, e: orders.translate(batches.get(e.sequence, []), e.sequence))
    assert [fill.qty for fill in kernel.fills] == [Decimal(8), Decimal(10)]
    assert kernel.account.position_qty == -2
    assert len(orders.lots) == 1 and orders.lots[0]["entry_id"] == "S"


def test_pending_reversal_and_rule_configuration_survive_checkpoint_restore():
    config = configuration(direction("short"), limit(2))
    kernel, orders = make_kernel(config)
    batches = {1: [intent("generic", qty=8, action="order")], 2: [intent("S", "short", limit=15)]}
    kernel.run([event(1), event(2)], lambda _, e: orders.translate(batches.get(e.sequence, []), e.sequence), finalize=False)
    saved_kernel, saved_orders = deepcopy(kernel.snapshot()), deepcopy(orders.snapshot())
    restored, allocation = make_kernel(config)
    restored.restore(saved_kernel)
    allocation.restore(saved_orders)
    kernel.run([event(3, 20)], lambda *_: [], finalize=False)
    restored.run([event(3, 20)], lambda *_: [], finalize=False)
    assert restored.result() == kernel.result()
    assert allocation.snapshot() == orders.snapshot()
    assert restored.account.position_qty == -2


def test_conflicting_direction_rules_prevent_new_entries_and_configuration_is_frozen():
    kernel, orders = make_kernel(configuration(direction("long"), direction("short")))
    assert orders.translate([intent("L"), intent("S", "short")], 1) == []
    with pytest.raises(BacktestError, match="EXTERNAL_NONCAUSAL_PREFIX"):
        orders.entry_risk.configure(configuration(direction("all")))


@pytest.mark.parametrize("rule", [
    ("max_drawdown", {"value": 5, "valueType": "strategy.cash"}),
    ("max_intraday_loss", {"value": 5, "valueType": "strategy.cash"}),
    ("max_intraday_filled_orders", {"value": 3}),
    ("max_cons_loss_days", {"value": 2}),
    limit("NaN"), limit(0),
])
def test_unconnected_or_invalid_risk_rules_fail_closed(rule):
    with pytest.raises(BacktestError):
        make_kernel(configuration(rule))
