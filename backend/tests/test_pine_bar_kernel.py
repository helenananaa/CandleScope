from copy import deepcopy
from decimal import Decimal as D

import pytest

from app.market_dataset.snapshot import MarketEvent, MarketDatasetError
from app.simulation.kernel import SimulationKernel
from app.simulation.pine_bar_kernel import PineBarKernel, MODEL


def bar(open_=100, high=110, low=80, close=105, begin=0):
    return MarketEvent(1, begin + 59999, "BARS", {"open_time_ms": begin,
        "close_time_ms": begin + 59999, "open": str(open_), "high": str(high),
        "low": str(low), "close": str(close), "volume": "100"})


def enqueue(kernel, kind, side="BUY", **extra):
    kernel._enqueue({"type": kind, "side": side, "qty": "1", **extra}, current_sequence=kernel.path_sequence)


@pytest.mark.parametrize("open_,winner", [(100, "LIMIT_TOUCH"), (90, "STOP_TOUCH")])
def test_oco_follows_nearest_extreme_instead_of_worst_case(open_, winner):
    kernel = PineBarKernel(slippage_bps=D(0))
    enqueue(kernel, "MARKET")
    def reporter(event):
        if event.get("fill") and len(kernel.fills) == 1:
            enqueue(kernel, "LIMIT", "SELL", limit_price="108", reduce_only=True, oco_group="x")
            enqueue(kernel, "STOP", "SELL", stop_price="85", reduce_only=True, oco_group="x")
    kernel.execution_reporter = reporter
    kernel.walk_bar(bar(open_=open_), lambda _: None)
    assert len(kernel.fills) == 2
    assert kernel.fills[1].reason == winner
    assert kernel.account.position_qty == 0
    assert kernel.fill_policy == MODEL


@pytest.mark.parametrize("kind,side,fields,expected", [
    ("LIMIT", "BUY", {"limit_price": "110"}, 100),
    ("LIMIT", "SELL", {"limit_price": "90"}, 100),
    ("STOP", "BUY", {"stop_price": "90"}, 100),
    ("STOP", "SELL", {"stop_price": "110"}, 100),
])
def test_gapped_orders_fill_at_open(kind, side, fields, expected):
    kernel = PineBarKernel(slippage_bps=D(0))
    enqueue(kernel, kind, side, **fields)
    kernel.walk_bar(bar(), lambda _: None)
    assert kernel.fills[0].price == expected and kernel.fills[0].event_time_ms == 0


def test_stop_limit_activation_waits_for_later_limit_retrace():
    kernel = PineBarKernel(slippage_bps=D(0))
    enqueue(kernel, "STOP_LIMIT", stop_price="108", limit_price="103")
    kernel.walk_bar(bar(), lambda _: None)
    assert len(kernel.fills) == 1
    assert kernel.fills[0].price == 103
    assert kernel.fills[0].event_time_ms > 19999


def test_market_created_by_crossing_callback_waits_for_vertex():
    kernel = PineBarKernel(slippage_bps=D(0))
    enqueue(kernel, "LIMIT", limit_price="95")
    def report(event):
        if event.get("fill") and len(kernel.fills) == 1:
            enqueue(kernel, "MARKET", "SELL")
    kernel.execution_reporter = report
    kernel.walk_bar(bar(), lambda _: None)
    assert [row.price for row in kernel.fills] == [D(95), D(80)]
    assert kernel.fills[1].sequence > kernel.fills[0].sequence


def test_restore_continues_path_sequence_and_rejects_wrong_matcher():
    kernel = PineBarKernel(slippage_bps=D(0))
    kernel.walk_bar(bar(), lambda _: enqueue(kernel, "MARKET"))
    saved = deepcopy(kernel.snapshot())
    restored = PineBarKernel(slippage_bps=D(0))
    restored.restore(saved)
    for candidate in (kernel, restored):
        candidate.walk_bar(bar(begin=60000), lambda _: None)
    assert restored.result() == kernel.result()
    assert restored.snapshot() == kernel.snapshot()
    with pytest.raises(MarketDatasetError, match="own matcher"):
        SimulationKernel().restore(saved)
    with pytest.raises(MarketDatasetError, match="checkpoint differs"):
        PineBarKernel().restore({**saved, "pine_bar_path": {"contract": "wrong", "sequence": 4}})


def test_callback_order_cannot_fill_on_same_vertex():
    kernel = PineBarKernel(slippage_bps=D(0))
    enqueue(kernel, "MARKET")
    def report(event):
        if event.get("fill") and len(kernel.fills) == 1:
            enqueue(kernel, "MARKET", "SELL")
    kernel.execution_reporter = report
    kernel.walk_bar(bar(), lambda _: None)
    assert [row.price for row in kernel.fills] == [100, 110]
    assert [row.sequence for row in kernel.fills] == [1, 2]


def test_trailing_activation_and_favorable_watermark_precede_reverse_stop():
    from app.backtest.external_orders import ExternalOrders
    kernel = PineBarKernel(slippage_bps=D(0))
    orders = ExternalOrders(kernel, price_tick="1", fidelity="PINE_BAR_PATH")
    orders.configure(1)
    kernel._enqueue_many(orders.translate([{"action": "entry", "id": "L", "direction": "long", "qty": 1}], 0), current_sequence=0)
    prior = kernel.execution_reporter
    def report(event):
        prior(event)
        if event.get("fill") and len(kernel.fills) == 1:
            kernel._enqueue_many(orders.translate([{"action": "exit", "id": "X", "from_entry": "L",
                "trail_price": 110, "trail_offset": 5}], kernel.path_sequence), current_sequence=kernel.path_sequence)
    kernel.execution_reporter = report
    kernel.walk_bar(bar(high=120, low=70), lambda _: None)
    assert [row.price for row in kernel.fills] == [100, 115]
    assert orders.allocations[-1]["opened"] is None
    assert kernel.account.position_qty == 0
    orders.feedback()


def test_flat_vertices_are_next_ticks_and_stop_limit_cannot_fill_before_activation():
    kernel = PineBarKernel(slippage_bps=D(0))
    enqueue(kernel, "STOP_LIMIT", stop_price="108", limit_price="95")
    kernel.walk_bar(bar(high=110, low=90, close=105), lambda _: None)
    # Low is first on the equal-distance policy: 95 is crossed before the
    # stop activates, and no later price returns to 95.
    assert kernel.fills == [] and kernel.orders[0].activated
    kernel = PineBarKernel(slippage_bps=D(0))
    enqueue(kernel, "MARKET")
    def report(event):
        if event.get("fill") and len(kernel.fills) == 1:
            enqueue(kernel, "MARKET", "SELL")
    kernel.execution_reporter = report
    kernel.walk_bar(bar(100, 100, 100, 100), lambda _: None)
    assert [row.sequence for row in kernel.fills] == [1, 2]


def test_path_cannot_accidentally_run_the_legacy_whole_bar_matcher():
    with pytest.raises(MarketDatasetError, match="explicit execution clock"):
        PineBarKernel().run([bar()], lambda *_: [])
