"""Shared special-chart observation clock; real kernels retain order admission."""

from copy import deepcopy
from app.data_engine.synthetic_series.events import ChartEventSeries, CONTRACT
from app.simulation.chart_decisions import ChartDecisionBatch
from .errors import BacktestError
from .strategy.host_planner import HostPlan


def observed_tick(kernel, metadata=None):
    from fractions import Fraction

    value = (
        getattr(kernel.account, "tick", None)
        or getattr(kernel, "price_tick", None)
        or (metadata or {}).get("priceTickSize")
    )
    return float(Fraction(str(value))) if value is not None else None


class ChartEventCallbacks:
    def __init__(
        self, definition, evaluate, *, every_tick, fills, control, bar_state="realtime", tick=None
    ):
        self.series = ChartEventSeries(definition)
        self.evaluate = evaluate
        self.every_tick, self.fills, self.control, self.bar_state = (
            every_tick,
            fills,
            control,
            bar_state,
        )
        self.raw = None
        self.pass_event = None
        self.pass_count = 0
        self.fill_count = 0
        self.observed_ordinal = None
        self.last_closed = None
        self.tick_supplier = tick

    def _bind_tick(self):
        if self.series.tick is None and self.tick_supplier is not None:
            value = self.tick_supplier()
            if value is not None:
                self.series.tick = value

    def prepare(self, event, forming):
        if event.role != "TRADES":
            return
        self._bind_tick()
        self.series.update(
            dict(forming.payload),
            event.event_time_ms,
            event.sequence,
            quantity=event.payload.get("qty", 0),
        )

    def prepare_path(self, bar, point):
        if (
            bar is None
            or point.role != "BARS"
            or "price" not in point.payload
            or point.payload.get("execution_phase") == "PINE_BAR_CLOSE"
        ):
            return
        self._bind_tick()
        opened = int(bar.payload["open_time_ms"])
        price = float(point.payload["price"])
        if self.raw is None or self.raw["open_time_ms"] != opened:
            self.raw = dict(
                open_time_ms=opened,
                close_time_ms=bar.payload["close_time_ms"],
                open=price,
                high=price,
                low=price,
                close=price,
                volume=0,
            )
        else:
            self.raw.update(
                high=max(self.raw["high"], price), low=min(self.raw["low"], price), close=price
            )
        previous = float(self.raw["volume"])
        span = int(bar.payload["close_time_ms"]) - opened
        progress = 1 if span == 0 else min(1, max(0, (point.event_time_ms - opened) / span))
        self.raw["volume"] = float(bar.payload.get("volume", 0)) * progress
        self.series.update(
            self.raw,
            point.event_time_ms,
            point.sequence,
            quantity=max(0, self.raw["volume"] - previous),
        )

    def _plans(self, event, trigger, preview):
        def plans():
            for row in self.series.observations(event.event_time_ms, preview=preview):
                self.control()
                self._budget(event, "bar_close" if row["confirmed"] else trigger)
                if row["confirmed"]:
                    self.last_closed = deepcopy(row)
                yield self.evaluate(
                    row, event, "bar_close" if row["confirmed"] else trigger, self.bar_state
                )

        return ChartDecisionBatch(plans())

    def _budget(self, event, trigger):
        key = (event.sequence, event.event_time_ms)
        if self.pass_event != key:
            self.pass_event, self.pass_count, self.fill_count = key, 0, 0
        self.pass_count += 1
        if trigger in {"order_fill", "closing_fill"}:
            self.fill_count += 1
            if self.fill_count > 64:
                raise BacktestError(
                    "BUDGET_EXCEEDED", "at most 64 chart fill callbacks per market event"
                )
        if self.pass_count > 10064:
            raise BacktestError("BUDGET_EXCEEDED", "chart event observation budget exceeded")

    def on_tick(self, event, forming):
        self.prepare(event, forming)
        return self._plans(event, "realtime_tick", self.every_tick)

    def on_fill(self, event, forming):
        self.prepare(event, forming)
        return self._plans(event, "order_fill", self.fills)

    def after_path(self, bar, point):
        self.prepare_path(bar, point)
        return self._plans(point, "historical_tick", False)

    def on_path_fill(self, bar, point, trigger):
        if trigger == "closing_fill":
            return self.closing_fill(point)
        self.prepare_path(bar, point)
        return self._plans(point, "order_fill", self.fills)

    def observe(self, bar, **_):
        self.series.close_source(dict(bar.payload), bar.event_time_ms)
        self.raw = None
        return self._plans(bar, "bar_close", False)

    def closing_fill(self, event):
        if self.series.active is not None:
            return self._plans(event, "order_fill", self.fills)

        def plans():
            if self.last_closed is not None and self.fills:
                self.control()
                self._budget(event, "closing_fill")
                yield self.evaluate(self.last_closed, event, "closing_fill", self.bar_state)

        return ChartDecisionBatch(plans())

    def observe_closing_fill(self, bar):
        return self.closing_fill(bar)

    def snapshot(self):
        return dict(
            contract=CONTRACT,
            series=self.series.snapshot(),
            raw=deepcopy(self.raw),
            pass_event=self.pass_event,
            pass_count=self.pass_count,
            fill_count=self.fill_count,
            observed_ordinal=self.observed_ordinal,
            last_closed=deepcopy(self.last_closed),
        )

    def restore(self, value):
        if not isinstance(value, dict) or value.get("contract") != CONTRACT:
            raise BacktestError("CHECKPOINT_CORRUPT", "chart event checkpoint is missing")
        self.series.restore(value["series"])
        self.raw = deepcopy(value["raw"])
        self.pass_event = tuple(value["pass_event"]) if value["pass_event"] else None
        self.pass_count = value["pass_count"]
        self.fill_count = value["fill_count"]
        self.observed_ordinal = value["observed_ordinal"]
        self.last_closed = deepcopy(value["last_closed"])


class HostChartEventCallbacks(ChartEventCallbacks):
    def __init__(
        self,
        session,
        adapter,
        planner,
        kernel,
        *,
        definition,
        market,
        warmup,
        features,
        control,
        every_tick,
        fills,
        bar_state
    ):
        from .service import _pine_account_view, _planning_context

        self.session, self.adapter, self.planner, self.kernel = session, adapter, planner, kernel

        def evaluate(row, event, trigger, state):
            index = row["ordinal"]
            first = index != self.observed_ordinal
            metadata = dict(
                ordinal=index,
                source_time_ms=row["bar"]["open_time_ms"],
                available_time_ms=event.event_time_ms,
                source_count=self.series.source_count,
                confirmed=row["confirmed"],
                contract=CONTRACT,
                trigger=trigger,
            )
            account_kernel = getattr(kernel, "execution", kernel)
            from app.simulation.linear_perp_account_v2 import LinearPerpetualAccountV2

            if (
                not isinstance(account_kernel.account, LinearPerpetualAccountV2)
                and "price" in event.payload
            ):
                from decimal import Decimal

                account_kernel.account.mark = Decimal(str(event.payload["price"]))
            output = adapter.observe(
                sequence=session.last_sequence + 1,
                event_time_ms=event.event_time_ms,
                watermark_ms=event.event_time_ms,
                phase="WARMUP" if index < warmup else "EVALUATION",
                market=dict(market),
                bar=row["bar"],
                features={
                    **features(row["bar"]),
                    "chart_signal": metadata,
                    "pineExecutionPass": dict(barIndex=index, confirmed=row["confirmed"]),
                    "pineExecutionContext": dict(
                        bar_state=state, trigger=trigger, is_new=state == "historical" or first
                    ),
                },
                account_view=_pine_account_view(kernel),
            )
            self.observed_ordinal = index
            plan = planner.plan(
                output, context=_planning_context(getattr(kernel, "execution", kernel), event)
            )
            return HostPlan(
                [] if index < warmup else list(plan),
                decision={**(getattr(plan, "decision", None) or {}), "chart_signal": metadata},
            )

        super().__init__(
            definition,
            evaluate,
            every_tick=every_tick,
            fills=fills,
            control=control,
            bar_state=bar_state,
            tick=lambda: observed_tick(
                getattr(kernel, "execution", kernel), adapter.input_plan.get("pineChartMetadata")
            ),
        )
        planner.signal_input = self
