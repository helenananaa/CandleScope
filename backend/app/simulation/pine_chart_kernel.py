"""Chart BAR lifecycle over the shared Pine OHLC path matcher."""
from dataclasses import dataclass
from decimal import Decimal

from app.market_dataset.snapshot import MarketDatasetError
from .pine_bar_kernel import PineBarKernel

CONTRACT = "candlescope.pine-chart-bar/1"


@dataclass(slots=True)
class PineChartBarKernel(PineBarKernel):
    source_sequence: int = 0
    source_time_ms: int | None = None
    chart_bar_count: int = 0

    def snapshot(self, *, history_encoder=None):
        return {**super(PineChartBarKernel, self).snapshot(history_encoder=history_encoder),
            "pine_chart_bar": {"contract": CONTRACT, "sequence": self.source_sequence,
                "time_ms": self.source_time_ms, "bar_count": self.chart_bar_count}}

    def restore(self, payload):
        state = payload.get("pine_chart_bar") or {}
        if (state.get("contract") != CONTRACT or type(state.get("sequence")) is not int
                or type(state.get("bar_count")) is not int or state["sequence"] < 0
                or not 0 <= state["bar_count"] <= state["sequence"]
                or (state.get("time_ms") is not None and type(state["time_ms"]) is not int)
                or (state["bar_count"] == 0) != (state.get("time_ms") is None)):
            raise MarketDatasetError("chart BAR checkpoint differs", code="CHECKPOINT_CORRUPT")
        super(PineChartBarKernel, self).restore(payload)
        if (self.path_sequence < state["bar_count"] * 4
                or (state["bar_count"] and self._last_event.event_time_ms != state["time_ms"])):
            raise MarketDatasetError("chart BAR path/source clocks differ", code="CHECKPOINT_CORRUPT")
        self.source_sequence, self.source_time_ms, self.chart_bar_count = state["sequence"], state["time_ms"], state["bar_count"]

    def run(self, events, strategy, *, warmup_events=0, finalize=False,
            checkpoint_callback=None, fill_callback=None, vertex_callback=None, **options):
        if fill_callback is None or warmup_events or options:
            raise MarketDatasetError("chart BAR path requires its explicit callback clock", code="FIDELITY_UNSUPPORTED")
        active = None
        prior_reporter = self.execution_reporter

        def apply(plan, point):
            self._record_decision(plan, point)
            self._enqueue_many(plan, current_sequence=point.sequence)

        def report(value):
            self.account.mark = Decimal(self._last_event.payload["price"])
            if prior_reporter is not None:
                prior_reporter(value)
            if value.get("fill") and vertex_callback is None:
                trigger = "closing_fill" if self._last_event.payload["execution_phase"] == "PINE_BAR_CLOSE" else "order_fill"
                apply(fill_callback(active, self._last_event, trigger), self._last_event)

        def close(point):
            # The strategy receives canonical OHLCV, with the path close's
            # actual account; the provider observation clock is independent.
            apply(strategy((active,), active), point)
            if self.process_orders_on_close:
                self.closing_tick()

        self.execution_reporter = report
        try:
            for event in events:
                if self.paused:
                    break
                if event.role != "BARS":
                    raise MarketDatasetError("chart BAR path requires bars", code="FIDELITY_MISLABEL")
                if type(event.sequence) is not int or event.sequence <= self.source_sequence:
                    raise MarketDatasetError("chart BAR source sequence went backwards", code="DATA_GAP_REJECTED")
                if event.event_time_ms != int(event.payload["close_time_ms"]):
                    raise MarketDatasetError("chart BAR close timestamp differs", code="DATA_QUALITY_FAILED")
                if self.source_time_ms is not None and (event.event_time_ms < self.source_time_ms
                        or int(event.payload["open_time_ms"]) <= self.source_time_ms):
                    raise MarketDatasetError("chart BAR time went backwards", code="DATA_GAP_REJECTED")
                if self.source_sequence and event.sequence != self.source_sequence + 1:
                    if self.gap_policy == "PAUSE":
                        self.paused = True
                        break
                    if self.gap_policy != "SKIP_WITH_WARNING":
                        raise MarketDatasetError("chart BAR sequence gap", code="DATA_GAP_REJECTED")
                    self.ambiguity_count += 1
                active = event
                self.walk_bar(event, close, on_vertex=(
                    (lambda point, index: vertex_callback(active, point, index)) if vertex_callback is not None else None))
                self.source_sequence, self.source_time_ms = event.sequence, event.event_time_ms
                self.chart_bar_count += 1
                if checkpoint_callback is not None:
                    checkpoint_callback(event)
            if finalize:
                self.finalize_orders()
        finally:
            self.execution_reporter = prior_reporter
        return self.result()
