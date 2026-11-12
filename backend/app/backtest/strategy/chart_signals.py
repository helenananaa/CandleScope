"""Causal chart signal clock for existing BAR-close provider contracts."""
from app.data_engine.synthetic_series.signals import ChartSignalSeries
from app.simulation.chart_decisions import ChartDecisionBatch
from .host_planner import HostPlan


class ChartSignalClock:
    def __init__(self, definition, adapter, planner, *, market, warmup, features, context, account=None, control=None):
        self.series = ChartSignalSeries(definition)
        self.adapter, self.planner = adapter, planner
        self.market, self.warmup = market, warmup
        self.features, self.context, self.account = features, context, account
        self.control = control
        planner.signal_input = self.series

    def observe(self, event):
        rows = self.series.observe(dict(event.payload), event.event_time_ms)
        def plans():
            for row in rows:
                number = row['ordinal'] + 1
                if self.control is not None and (row is rows[0] or number % 256 == 1):
                    self.control()
                bar = row['bar']
                metadata = {key: row[key] for key in ('ordinal', 'source_time_ms', 'available_time_ms', 'source_count')}
                features = {**self.features(bar), 'chart_signal': metadata}
                output = self.adapter.observe(sequence=number, event_time_ms=event.event_time_ms,
                    watermark_ms=event.event_time_ms, phase='WARMUP' if number <= self.warmup else 'EVALUATION',
                    market=dict(self.market), bar=bar, features=features,
                    account_view=self.account() if self.account else None)
                plan = self.planner.plan(output, context=self.context(event))
                decision = getattr(plan, 'decision', None)
                # Retain the provider contract, alongside explicit real clock and
                # ordinal metadata. Warmup runs providers without admitting orders.
                if decision is None and output is not None:
                    decision = output.to_wire() if hasattr(output, 'to_wire') else dict(output)
                yield HostPlan([] if number <= self.warmup else list(plan),
                    decision={**(decision or {}), 'chart_signal': metadata})
        return ChartDecisionBatch(plans())
