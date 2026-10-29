"""One explicit realtime Pine observation per already matched source print."""
from decimal import Decimal

from .pine_callbacks import ChartFillCallbacks


class ChartRealtimeTicks(ChartFillCallbacks):
    def observe(self,bar,*,confirmed,is_new=False,trigger=None):
        from .service import _pine_account_view,_planning_context
        from .errors import BacktestError
        import time
        if time.monotonic()>=self.deadline:
            raise BacktestError("PROVIDER_TIMEOUT","Pine realtime tick deadline exceeded")
        self.control()
        index=int(bar.payload["signal_sequence"])-1
        output=self.adapter.observe(sequence=self.session.last_sequence+1,
            event_time_ms=bar.event_time_ms,watermark_ms=bar.event_time_ms,
            phase="WARMUP" if index<self.warmup else "EVALUATION",market=dict(self.market),bar=dict(bar.payload),
            features={**self.features(dict(bar.payload)),
                "pineExecutionPass":dict(barIndex=index,confirmed=confirmed),
                "pineExecutionContext":dict(bar_state="realtime",trigger=trigger or ("bar_close" if confirmed else "realtime_tick"),is_new=is_new)},
            account_view=_pine_account_view(self.kernel))
        return self.planner.plan(output,context=_planning_context(self.kernel.execution,bar))

    def on_tick(self,trade,forming):
        # The builder accumulates strictly positive exact-decimal quantities.
        # Equality identifies the first print even after durable continuation.
        first=Decimal(forming.payload["volume"])==Decimal(trade.payload["qty"])
        return self.observe(forming,confirmed=False,is_new=first)

    def observe_closing_fill(self,bar):
        return self.observe(bar,confirmed=True,trigger="closing_fill")
