from types import SimpleNamespace

from app.simulation.kernel import SimulationKernel
from app.simulation.execution_realism import EXECUTION_REALISM_V2, BAR_PATH_SCENARIO
from decimal import Decimal
from tests.test_backtest_colocated import bars


class FullScanKernel(SimulationKernel):
    def _live_orders(self):
        return [order for order in self.orders if order.status in {"OPEN", "PARTIAL"}]


def test_active_index_matches_full_scan_with_ioc_oco_partial_and_restore():
    def strategy(_, event):
        if event.sequence == 1:
            return [{"side":"BUY", "type":"MARKET", "qty":"3", "tif":"IOC"}]
        if event.sequence == 7:
            return [{"side":"SELL", "type":"STOP", "qty":"1", "stop_price":"104", "oco_group":"g"},
                    {"side":"SELL", "type":"LIMIT", "qty":"1", "limit_price":"108", "oco_group":"g"}]
        if event.sequence % 17 == 0:
            return [{"side":"BUY" if event.sequence % 2 else "SELL", "type":"MARKET", "qty":"1"}]
        return []
    options = dict(execution_model_revision=EXECUTION_REALISM_V2,
                   participation_rate=Decimal("0.001"), bar_path_scenario=BAR_PATH_SCENARIO)
    reference = FullScanKernel(**options)
    candidate = SimulationKernel(**options)
    events = bars(800)
    for kernel in (reference, candidate):
        kernel.run(events[:400], strategy)
    restored = SimulationKernel(**options)
    restored.restore(candidate.snapshot())
    expected = reference.run(events[400:], strategy, finalize=True)
    assert candidate.run(events[400:], strategy, finalize=True) == expected
    assert restored.run(events[400:], strategy, finalize=True) == expected
    assert not list(candidate._live_orders())


def test_warm_matching_and_position_queries_do_not_scan_closed_history():
    class CountedHistory(list):
        scans = 0
        def __iter__(self):
            self.scans += 1
            return super().__iter__()
    kernel = SimulationKernel()
    kernel.orders = CountedHistory(SimpleNamespace(order_id=str(i), status="FILLED") for i in range(10000))
    assert not list(kernel._live_orders())
    initial = kernel.orders.scans
    for event in bars(1000):
        kernel._match(event)
        assert kernel.projected_position_qty == 0
    assert kernel.orders.scans == initial
