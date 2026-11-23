"""Special-chart observations over existing real BAR/tape/book matchers."""

from copy import deepcopy
from decimal import Decimal

from app.market_dataset.snapshot import MarketEvent
from app.data_engine.interval_policy import parse_interval_spec
from app.simulation.chart_decisions import decision_plans
from .errors import BacktestError
from .pine_chart_events import ChartEventCallbacks, CONTRACT, observed_tick
from .pine_stream import PineStream, observations_match
from .pine_request_updates import from_wire, pass_observations, validate_replay
from .pine_workbench import bar_event, check_risk_response
from .pine_print_account import (
    events as physical_events,
    apply_account,
    observe_market,
    record_decision,
    AUXILIARY,
)
from .strategy.host_planner import HostPlan
from .workbench_sensitivity import check_control


def opening(wire):
    names = {
        "source",
        "parameters",
        "libraries",
        "context",
        "contexts",
        "host_settings",
        "risk_contract",
        "closing_ticks",
        "order_metadata_contract",
        "currency_rates",
        "request_update_contract",
        "signal_chart",
        "chart_signal_contract",
        "chart_event_contract",
    }
    result = {k: deepcopy(v) for k, v in wire.items() if k in names}
    if result.get("contexts"):
        if not wire.get("request_update_contract"):
            raise BacktestError(
                "EXTERNAL_UNSUPPORTED", "chart events require observed requested-data updates"
            )
        result["contexts"] = [{**item, "bars": []} for item in result["contexts"]]
    return result


class NativeChartEvents:
    def __init__(self, kernel, orders, wire, plugin, cancelled, deadline, state=None):
        from .external import account_feedback_profit

        self.kernel, self.orders, self.wire = kernel, orders, wire
        self.cancelled, self.deadline = cancelled, deadline
        state = deepcopy(state or {})
        self.cursor = state.get("bar_cursor", 0)
        self.event_cursor = state.get("event_cursor", 0)
        self.last_sequence = state.get("last_sequence", 0)
        self.groups, self.accounts, self.history = (
            state.get(k, []) for k in ("groups", "accounts", "history")
        )
        self.feed = from_wire(wire)
        if self.feed is not None and state:
            validate_replay(
                self.feed, state.get("request_feed"), pass_observations(self.groups, scheduled=True)
            )
        transport = {k: wire[k] for k in ("protocol", "identity")}
        restored_intents = []

        def verify(command, result):
            if command["operation"] == "stream_observe":
                restored_intents.extend(result["intents"])

        self.stream = (
            PineStream.restore(plugin, state["stream"], cancelled, deadline=deadline, verify=verify)
            if state
            else PineStream(plugin, transport, opening(wire), cancelled, deadline=deadline)
        )
        if state and restored_intents != self.history:
            self.stream.close()
            raise BacktestError(
                "EXTERNAL_NONCAUSAL_PREFIX", "chart event restore changed decisions"
            )
        if self.stream.opening != opening(wire):
            self.stream.close()
            raise BacktestError(
                "NATIVE_IDENTITY_MISMATCH", "chart event stream environment changed"
            )
        try:
            self.raw = state.get("raw")

            def evaluate(row, event, trigger, bar_state):
                self.orders.feedback()
                from app.simulation.linear_perp_account_v2 import LinearPerpetualAccountV2

                if (
                    not isinstance(kernel.account, LinearPerpetualAccountV2)
                    and "price" in event.payload
                ):
                    kernel.account.mark = Decimal(str(event.payload["price"]))
                index = row["ordinal"]
                if self.stream.bar_open and self.stream.cursor != index:
                    if not self.groups or not self.groups[-1][-1]["evaluation"]["confirmed"]:
                        raise BacktestError(
                            "EXTERNAL_PROTOCOL_ERROR", "chart observation skipped an open row"
                        )
                    self.stream.commit()
                first = len(self.groups) == index
                if self.stream.cursor != index:
                    raise BacktestError(
                        "EXTERNAL_PROTOCOL_ERROR", "chart and evaluator ordinals differ"
                    )
                bar = dict(
                    time=row["bar"]["open_time_ms"] // 1000,
                    chart_time_ms=row["bar"]["open_time_ms"],
                    **{k: float(row["bar"][k]) for k in ("open", "high", "low", "close", "volume")}
                )
                account = kernel.account
                feedback = dict(
                    time=bar["time"],
                    position_size=float(account.position_qty),
                    position_avg_price=(
                        None if account.entry_price is None else float(account.entry_price)
                    ),
                    equity=float(account.equity()),
                    initial_capital=float(kernel.initial_balance),
                    netprofit=float(account_feedback_profit(account, kernel.initial_balance)),
                    openprofit=float(account.unrealized()),
                )
                evaluation = dict(
                    bar=bar,
                    account=feedback,
                    event_time_ms=event.event_time_ms,
                    confirmed=row["confirmed"],
                )
                if self.feed is not None:
                    evaluation.update(
                        request_observed_at_ms=event.event_time_ms,
                        request_updates=self.feed.advance(event.event_time_ms),
                    )
                observation = dict(
                    evaluation=evaluation,
                    context=dict(
                        bar_state=bar_state,
                        trigger=trigger,
                        is_new=bar_state == "historical" or first,
                    ),
                )
                if not self.stream.bar_open:
                    self.stream.begin(bar, bar_state=bar_state)
                result = self.stream.observe(observation)
                current = result["intents"]
                if len(current) > 64:
                    raise BacktestError(
                        "BUDGET_EXCEEDED", "at most 64 intents per chart observation"
                    )
                if first:
                    self.groups.append([])
                    self.accounts.append(None)
                self.groups[index].append(observation)
                self.accounts[index] = feedback
                self.history.extend(current)
                self.orders.configure(result.get("pyramiding", 1))
                check_risk_response(self.orders, wire, result)
                plan = self.orders.translate(current, event.sequence)
                metadata = dict(
                    ordinal=index,
                    available_time_ms=event.event_time_ms,
                    source_time_ms=row["bar"]["open_time_ms"],
                    source_count=self.driver.series.source_count,
                    confirmed=row["confirmed"],
                    contract=CONTRACT,
                    trigger=trigger,
                )
                return HostPlan(
                    plan,
                    decision=dict(
                        kind="ORDER_INTENT", payload={"intents": plan}, chart_signal=metadata
                    ),
                )

            control = lambda: check_control(cancelled, deadline)
            self.driver = ChartEventCallbacks(
                wire["signal_chart"],
                evaluate,
                every_tick=wire.get("chart_every_tick", False),
                fills=wire.get("fill_recalculation", False),
                control=control,
                bar_state=(
                    "historical" if wire["execution_fidelity"] == "BAR_APPROX" else "realtime"
                ),
                tick=lambda: observed_tick(kernel, wire.get("context", {}).get("metadata")),
            )
            if state:
                self.driver.restore(state["driver"])
        except BaseException:
            self.stream.close()
            if hasattr(self, "driver"):
                self.driver.evaluate = None
            raise

    def admit(self, plans, event):
        for plan in decision_plans(plans):
            record_decision(
                self.kernel,
                dict(
                    sequence=event.sequence,
                    watermark_ms=event.event_time_ms,
                    intents=list(plan),
                    provider_decision=plan.decision,
                    trigger=(plan.decision["chart_signal"]["trigger"]).upper(),
                ),
            )
            self.kernel._enqueue_many(plan, current_sequence=event.sequence)

    def close_source(self):
        if self.raw is None:
            raise BacktestError("DATA_GAP_REJECTED", "chart source bar has no observed prices")
        raw = deepcopy(self.raw)
        source = MarketEvent(self.last_sequence, int(raw["close_time_ms"]), "BARS", raw)
        closing = MarketEvent(
            self.last_sequence,
            source.event_time_ms,
            "TRADES",
            dict(price=str(raw["close"]), qty="0"),
        )
        self.kernel._last_event = closing
        observe_market(self.kernel, closing)
        self.admit(self.driver.observe(source), closing)
        if self.wire.get("closing_ticks"):
            from app.simulation.closing_tick import match_closing_tick

            match_closing_tick(
                self.kernel,
                source,
                self.last_sequence,
                on_fill=(
                    (lambda _bar, event: self.admit(self.driver.closing_fill(event), event))
                    if self.driver.fills
                    else None
                ),
            )
        self.cursor += 1
        self.raw = None

    def snapshot(self):
        value = dict(
            contract=CONTRACT,
            bar_cursor=self.cursor,
            event_cursor=self.event_cursor,
            last_sequence=self.last_sequence,
            driver=self.driver.snapshot(),
            raw=self.raw,
            groups=self.groups,
            accounts=self.accounts,
            history=self.history,
            stream=self.stream.checkpoint(compact=True),
        )
        if self.feed is not None:
            value["request_feed"] = self.feed.snapshot()
        return value


def run_clock(kernel, orders, wire, plugin, cancelled, deadline, *, state=None, target=None):
    clock = NativeChartEvents(kernel, orders, wire, plugin, cancelled, deadline, state)
    interval = parse_interval_spec(wire["interval"])
    target = len(wire["bars"]) if target is None else target
    prior_reporter, prior_observer = kernel.execution_reporter, kernel.market_observer

    def report(value):
        if prior_reporter is not None:
            prior_reporter(value)
        if value.get("fill") and clock.driver.fills:
            point = kernel._last_event
            if wire["execution_fidelity"] == "BAR_APPROX":
                source = bar_event(wire, clock.cursor, clock.cursor + 1)
                clock.admit(
                    clock.driver.on_path_fill(
                        source,
                        point,
                        (
                            "closing_fill"
                            if point.payload.get("execution_phase") == "PINE_BAR_CLOSE"
                            else "order_fill"
                        ),
                    ),
                    point,
                )
            elif point.payload.get("execution_phase") != "PINE_BAR_CLOSE":
                # Account-only events update feedback without inventing a print.
                plans = (
                    clock.driver.on_fill(
                        point, MarketEvent(0, point.event_time_ms, "BARS", clock.raw)
                    )
                    if point.role == "TRADES" and clock.raw is not None
                    else clock.driver._plans(point, "order_fill", True)
                )
                clock.admit(plans, point)

    kernel.execution_reporter = report
    try:
        if wire["execution_fidelity"] == "BAR_APPROX":

            def observed(point):
                if "price" in point.payload:
                    clock.driver.prepare_path(
                        bar_event(wire, clock.cursor, clock.cursor + 1), point
                    )
                if prior_observer is not None:
                    prior_observer(point)

            kernel.market_observer = observed
            if wire.get("pine_v2_bar_contract"):
                # V2 owns the full account/event order; the same callbacks bind
                # to its canonical source bar and observed price points.
                from .pine_workbench_v2 import events

                rows = [
                    row
                    for row in events(wire)
                    if row.sequence > kernel.source_sequence
                    and row.event_time_ms <= bar_event(wire, target - 1, 0).event_time_ms
                ]

                def close(visible, bar):
                    clock.driver.series.close_source(dict(bar.payload), bar.event_time_ms)
                    return clock.driver._plans(kernel._last_event, "bar_close", False)

                def commit(event):
                    if event.role == "BARS":
                        clock.cursor += 1

                kernel.execution_reporter = prior_reporter
                kernel.run(
                    rows,
                    close,
                    fill_callback=clock.driver.on_path_fill,
                    chart_event_callbacks=clock.driver,
                    checkpoint_callback=commit,
                    finalize=target == len(wire["bars"]),
                )
                clock.last_sequence = kernel.path_sequence
            else:
                while clock.cursor < target:
                    check_control(cancelled, deadline)
                    bar = bar_event(wire, clock.cursor, clock.cursor + 1)

                    def close(point):
                        clock.driver.series.close_source(dict(bar.payload), point.event_time_ms)
                        clock.admit(clock.driver._plans(point, "bar_close", False), point)
                        if wire.get("closing_ticks"):
                            kernel.closing_tick()

                    kernel.walk_bar(
                        bar,
                        close,
                        on_vertex=lambda point, index: clock.admit(
                            clock.driver.after_path(bar, point), point
                        ),
                    )
                    clock.last_sequence = kernel.path_sequence
                    clock.cursor += 1
                if target == len(wire["bars"]):
                    kernel.finalize_orders()
        else:
            events = physical_events(wire)
            from app.market_dataset.trades import assert_trade_stream

            kernel.source_kind = assert_trade_stream(
                tuple(row for row in events if row.role == "TRADES")
            )
            end = interval.next_ms(wire["bars"][target - 1]["time"] * 1000)
            for event in events[clock.event_cursor :]:
                if event.event_time_ms >= end:
                    break
                check_control(cancelled, deadline)
                while (
                    interval.next_ms(wire["bars"][clock.cursor]["time"] * 1000)
                    <= event.event_time_ms
                ):
                    clock.close_source()
                kernel._last_event = event
                if event.role in AUXILIARY:
                    apply_account(kernel, event, record_equity=kernel._market_event_count > 0)
                elif event.role == "ORDER_BOOK":
                    kernel._apply_book(event)
                    if kernel.market_observer is not None:
                        kernel.market_observer(event)
                else:
                    price = float(event.payload["price"])
                    qty = Decimal(str(event.payload["qty"]))
                    if clock.raw is None:
                        opened = wire["bars"][clock.cursor]["time"] * 1000
                        clock.raw = dict(
                            open_time_ms=opened,
                            close_time_ms=interval.next_ms(opened) - 1,
                            open=price,
                            high=price,
                            low=price,
                            close=price,
                            volume="0",
                        )
                    clock.raw.update(
                        high=max(clock.raw["high"], price),
                        low=min(clock.raw["low"], price),
                        close=price,
                        volume=str(Decimal(str(clock.raw["volume"])) + qty),
                    )
                    forming = MarketEvent(0, event.event_time_ms, "BARS", clock.raw)
                    clock.driver.prepare(event, forming)
                    if wire.get("pine_v2_print_contract"):
                        kernel._market_event_count += 1
                    observe_market(kernel, event)
                    kernel._match(event)
                    clock.admit(clock.driver.on_tick(event, forming), event)
                    kernel._record_equity_point(
                        dict(
                            sequence=event.sequence,
                            event_time_ms=event.event_time_ms,
                            equity=str(kernel.account.equity()),
                            position_qty=str(kernel.account.position_qty),
                        )
                    )
                clock.last_sequence = event.sequence
                clock.event_cursor += 1
            while clock.cursor < target:
                clock.close_source()
            if target == len(wire["bars"]):
                kernel.finalize_orders()
        output = clock.stream.output()
        latest = {
            **output,
            "evaluation_contract": CONTRACT,
            "raw_output": output["output"],
            "graphics": output["output"].get("plots", []),
            "intents": deepcopy(clock.history),
        }
        saved = clock.snapshot()
        passes = [[item["evaluation"] for item in group] for group in clock.groups]
        return (
            latest,
            clock.history,
            clock.accounts,
            passes,
            saved,
            dict(bars=wire["bars"][:target], execution_schedule=clock.groups),
        )
    finally:
        kernel.execution_reporter, kernel.market_observer = prior_reporter, prior_observer
        clock.stream.close()
        clock.driver.evaluate = None


def validate_state(wire, state):
    from .native_replay_storage import same_json

    clock = state.get("clock") or {}
    groups = clock.get("groups") or []
    saved = clock.get("stream") or {}
    driver = clock.get("driver") or {}
    series = driver.get("series") or {}
    if (
        clock.get("contract") != CONTRACT
        or clock.get("bar_cursor") != state["cursor"]
        or series.get("source_count") != state["cursor"]
        or saved.get("intents") != len(state.get("history", []))
        or not same_json(clock.get("history"), state.get("history"))
        or not same_json(clock.get("accounts"), state.get("accounts"))
        or len(groups) != len(state.get("accounts", []))
        or not observations_match(saved, groups)
        or saved.get("cursor") != len(groups) - int(bool(saved.get("bar_open")))
        or sum(bool(group[-1]["evaluation"]["confirmed"]) for group in groups)
        != series.get("count")
        or saved.get("opening") != opening(wire)
    ):
        raise BacktestError(
            "NATIVE_IDENTITY_MISMATCH", "chart event checkpoint cursors/transcript differ"
        )
    candidate = ChartEventCallbacks(
        wire["signal_chart"],
        None,
        every_tick=wire.get("chart_every_tick", False),
        fills=wire.get("fill_recalculation", False),
        control=lambda: None,
    )
    candidate.restore(driver)

    if wire["execution_fidelity"] != "BAR_APPROX":
        from .pine_print_account import event_coordinates

        events = event_coordinates(wire)
        interval = parse_interval_spec(wire["interval"])
        end = interval.next_ms(wire["bars"][state["cursor"] - 1]["time"] * 1000)
        expected = sum(row["event_time_ms"] < end for row in events)
        if (
            clock.get("event_cursor") != expected
            or expected < 1
            or clock.get("last_sequence") != events[expected - 1]["sequence"]
        ):
            raise BacktestError("NATIVE_IDENTITY_MISMATCH", "chart event market cursor differs")
    elif clock.get("last_sequence") != (state.get("kernel", {}).get("pine_bar_path") or {}).get(
        "sequence"
    ):
        raise BacktestError("NATIVE_IDENTITY_MISMATCH", "chart event BAR path cursor differs")
