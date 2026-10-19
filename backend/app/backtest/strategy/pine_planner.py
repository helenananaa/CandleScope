"""Pine order ownership over the existing Host ledger and risk policies."""
from dataclasses import replace
from decimal import Decimal
import hashlib
from pathlib import Path

from app.backtest.external_orders import ExternalOrders
from .pine_engine import ORDER_CONTRACT
from .protocol import StrategyOutput, StrategyProviderError
from .pyne_adapter import HostPlan, PyneHostPlanner


def host_identity():
    from app.backtest.external import host_identity as execution_identity
    digest = hashlib.sha256()
    for name in ("pine_planner.py", "pine_engine.py", "pyne_adapter.py", "host_policy.py", "host_adapter.py"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    digest.update(Path(__file__).parent.parent.joinpath("pine_callbacks.py").read_bytes())
    digest.update(Path(__file__).parent.parent.joinpath("pine_sensitivity.py").read_bytes())
    digest.update(Path(__file__).parent.parent.joinpath("service.py").read_bytes())
    return {"contract": ORDER_CONTRACT, "execution": execution_identity(), "planner_sha256": digest.hexdigest()}


class PineHostPlanner(PyneHostPlanner):
    def __init__(self, config=None, **kwargs):
        super().__init__(config, **kwargs)
        self.price_tick = (config or {}).get("price_tick")

    def bind_kernel(self, kernel):
        from app.simulation.kernel import SimulationKernel
        self.kernel = getattr(kernel, "execution", kernel)
        self.orders = ExternalOrders(self.kernel, price_tick=self.price_tick,
            fidelity="BAR_APPROX" if isinstance(self.kernel, SimulationKernel) else "TRADE_TAPE")
        self.kernel.order_policy = self._before_match

    def _before_match(self, order, event):
        if not self.orders.prepare_order(order, event):
            return False
        if self.config is None:
            return True
        from app.backtest.service import _planning_context
        context = _planning_context(self.kernel, event)
        context = replace(context, projected_position=context.actual_position,
            active_order_count=max(0, context.active_order_count - 1))
        intent = {"side": order.side, "type": order.type, "qty": str(order.qty), "reduce_only": order.reduce_only}
        accepted = self._validate_intents([intent], decision={"kind": "PINE_MATCH_ADMISSION"}, context=context)
        if not accepted:
            self.orders.cancel_order(order, "PINE_MATCH_RISK_REJECTED")
        return bool(accepted)

    def plan(self, output, *, current_position=None, context=None):
        if output is None:
            if self.risk is not None and context is not None:
                self.risk.observe(context)
            return HostPlan([])
        wire = output.to_wire() if isinstance(output, StrategyOutput) else dict(output)
        payload = wire.get("payload") or {}
        if wire.get("kind") != "ORDER_INTENT" or payload.get("contract") != ORDER_CONTRACT:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "Pine order batch required")
        intents = payload.get("intents")
        if not isinstance(intents, list) or len(intents) > 64:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "at most 64 Pine order intents")
        self.orders.feedback()
        self.orders.configure(payload["pyramiding"])
        translated = self.orders.translate(intents, wire["sequence"])
        if self.config is None:
            return HostPlan(translated, decision=wire)
        if context is None:
            raise ValueError("Pine Host policy requires PlanningContext")
        self.risk.observe(context)
        working = self.kernel._live_orders() if hasattr(self.kernel, "_live_orders") else self.kernel._working_orders()
        accepted, projected, active = [], self.kernel.projected_position_qty, sum(order.status in {"OPEN", "PARTIAL"} for order in working)
        for intent in translated:
            # OCO protective legs each reduce the same potential entry. They
            # reserve order capacity separately, but never consume that position
            # twice during policy admission. Actual fills recheck the live ledger.
            admission = replace(context, projected_position=projected, active_order_count=active)
            values = self._validate_intents([intent], decision=wire, context=admission)
            if values:
                accepted.extend(values)
                active += 1
                if not intent.get("reduce_only"):
                    projected += Decimal(intent["qty"]) * (1 if intent["side"] == "BUY" else -1)
            else:
                self.orders.staged_bindings.pop(intent["client_tag"], None)
        return HostPlan(accepted, decision=wire)

    def snapshot(self):
        return {**super().snapshot(), "pine_orders": self.orders.snapshot()}

    def restore(self, payload):
        super().restore(payload)
        self.orders.restore(payload.get("pine_orders") or {})

    def report(self):
        return {**super().report(), "pine_orders": self.orders.report()}
