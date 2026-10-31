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


def fixed_history(events, *, max_bars, max_bytes):
    from .service import _event_wire_bytes
    rows,plan=[],[]
    size=0
    for event in events:
        size+=_event_wire_bytes((event,))
        if size>max_bytes:
            raise BacktestError("BUDGET_EXCEEDED","historical Pine input exceeds worker memory ceiling")
        rows.append(event)
        if event.role=="BARS":
            if len(plan)>=max_bars:
                raise BacktestError("BUDGET_EXCEEDED","historical Pine input exceeds frozen bar ceiling")
            plan.append(dict(time=int(event.payload["open_time_ms"])//1000,
                **{name:float(event.payload[name]) for name in ("open","high","low","close","volume")}))
    return tuple(rows),plan


class ChartHistoricalTicks(ChartHistoricalBarCallbacks):
    def on_vertex(self,bar,point,ordinal):
        from .service import _pine_account_view,_planning_context
        if time.monotonic()>=self.deadline:
            raise BacktestError("PROVIDER_TIMEOUT","historical Pine tick deadline exceeded")
        self.control()
        if ordinal==0:
            self.visible={**bar.payload,"high":bar.payload["open"],"low":bar.payload["open"],
                          "close":bar.payload["open"],"volume":"0"}
        price=float(point.payload["price"])
        self.visible.update(high=str(max(float(self.visible["high"]),price)),
            low=str(min(float(self.visible["low"]),price)),close=str(price),volume=str(float(bar.payload["volume"])*(ordinal+1)/4))
        index=self.kernel.chart_bar_count
        output=self.adapter.observe(sequence=self.session.last_sequence+1,event_time_ms=point.event_time_ms,
            watermark_ms=int(bar.payload["close_time_ms"]),phase="WARMUP" if index<self.warmup else "EVALUATION",
            market=dict(self.market),bar=dict(self.visible),features={**self.features(dict(self.visible)),
                "pineExecutionPass":dict(barIndex=index,confirmed=ordinal==3),
                "pineExecutionContext":dict(bar_state="historical",trigger="historical_tick",is_new=True)},
            account_view=_pine_account_view(self.kernel))
        plan=self.planner.plan(output,context=_planning_context(self.kernel,point))
        self.kernel._record_decision(plan,point)
        self.kernel._enqueue_many(plan,current_sequence=point.sequence)
        if ordinal<3: self.kernel.match_observation_markets(point)

    def observe(self,bar,point=None,trigger="bar_close"):
        # The fourth vertex already evaluated the confirmed observation. The
        # close callback only advances application bookkeeping and closing fills.
        return []
