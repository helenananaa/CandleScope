"""Historical chart observations; path time and script bar state stay distinct."""
import time

from .errors import BacktestError


class ChartHistoricalBarCallbacks:
    def __init__(self, session, adapter, planner, kernel, *, market, warmup, features, control, deadline):
        self.session, self.adapter, self.planner, self.kernel = session, adapter, planner, kernel
        self.market, self.warmup, self.features, self.control = market, warmup, features, control
        self.deadline = deadline

    def observe(self, bar, point=None, trigger="bar_close"):
        from .service import _pine_account_view, _planning_context
        if time.monotonic() >= self.deadline:
            raise BacktestError("PROVIDER_TIMEOUT", "historical Pine BAR deadline exceeded")
        self.control()
        point = point or self.kernel._last_event
        index = self.kernel.chart_bar_count
        phase = "WARMUP" if index < self.warmup else "EVALUATION"
        output = self.adapter.observe(sequence=self.session.last_sequence + 1,
            event_time_ms=point.event_time_ms, watermark_ms=int(bar.payload["close_time_ms"]),
            phase=phase, market=dict(self.market), bar=dict(bar.payload),
            features={**self.features(dict(bar.payload)),
                "pineExecutionPass": {"barIndex": index, "confirmed": trigger != "order_fill"},
                "pineExecutionContext": {"bar_state": "historical", "trigger": trigger, "is_new": True}},
            account_view=_pine_account_view(self.kernel))
        return self.planner.plan(output, context=_planning_context(self.kernel, point))

    def on_fill(self, bar, point, trigger):
        return self.observe(bar, point, trigger)
