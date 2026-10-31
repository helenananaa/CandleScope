"""Causal chart fill passes over the Host's observed aggregate-trade stream."""
from app.market_dataset.snapshot import MarketEvent
from .errors import BacktestError
import time


class ChartFillCallbacks:
    def __init__(self, session, adapter, planner, kernel, *, market, warmup, features, control, deadline):
        self.session, self.adapter, self.planner, self.kernel = session, adapter, planner, kernel
        self.market, self.warmup, self.features, self.control = market, warmup, features, control
        self.deadline = deadline

    def observe(self, bar, *, confirmed):
        from .service import _pine_account_view, _planning_context
        if time.monotonic() >= self.deadline:
            raise BacktestError("PROVIDER_TIMEOUT", "Pine callback run deadline exceeded")
        if self.session.last_sequence % 256 == 0:
            self.control()
        index = int(bar.payload["signal_sequence"]) - 1
        phase = "WARMUP" if index < self.warmup else "EVALUATION"
        if not confirmed and phase == "WARMUP":
            return []
        sequence = self.session.last_sequence + 1
        event = MarketEvent(sequence, bar.event_time_ms, bar.role, bar.payload)
        features = {**self.features(dict(bar.payload)),
            "pineExecutionPass": {"barIndex": index, "confirmed": confirmed}}
        output = self.adapter.observe(sequence=sequence, event_time_ms=bar.event_time_ms, watermark_ms=bar.event_time_ms,
            phase=phase, market=dict(self.market), bar=dict(bar.payload), features=features,
            account_view=_pine_account_view(self.kernel))
        plan = self.planner.plan(output, context=_planning_context(self.kernel.execution, event))
        if plan.decision is None:
            plan.decision = {"sequence": sequence, "kind": "NO_OUTPUT", "stateHash": self.session.provider.state_hash}
        return plan

    def on_fill(self, trade, forming):
        return self.observe(forming, confirmed=False)
