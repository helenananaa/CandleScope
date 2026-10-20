"""Historical BAR fill callbacks over the actual Host account and order book."""
from copy import deepcopy
from decimal import Decimal
import time

from .errors import BacktestError
from .pine_workbench import bar_event, check_risk_response
from .strategy.pine_schedule import CONTRACT as SCHEDULE_CONTRACT
from app.simulation.pine_bar_kernel import CONTRACT


def run_bar_clock(kernel, orders, wire, plugin, runner, cancelled, deadline, *, state=None, target=None):
    from .external import account_feedback_profit, visible_contexts
    state = deepcopy(state or {})
    cursor = state.get("bar_cursor", 0)
    groups, accounts, history, latest = (state.get(name, default) for name, default in
        (("groups", []), ("accounts", []), ("history", []), ("latest", {})))
    if (wire.get("pine_bar_path_contract") != CONTRACT
            or wire.get("execution_schedule_contract") != SCHEDULE_CONTRACT
            or len(groups) != cursor or len(accounts) != cursor
            or (state and state.get("contract") != CONTRACT)
            or state.get("last_sequence", 0) != kernel.path_sequence):
        raise BacktestError("NATIVE_IDENTITY_MISMATCH", "Pine BAR clock identity differs")
    target = len(wire["bars"]) if target is None else target

    def evaluate(event, trigger):
        nonlocal latest
        if cancelled.is_set():
            raise BacktestError("NATIVE_CANCELLED", "Pine BAR execution cancelled")
        if time.monotonic() >= deadline:
            raise BacktestError("NATIVE_TIMEOUT", "Pine BAR execution deadline exceeded")
        orders.feedback()
        account = kernel.account
        bar = wire["bars"][cursor]
        frame = {"time": bar["time"], "position_size": float(account.position_qty),
            "position_avg_price": None if account.entry_price is None else float(account.entry_price),
            "equity": float(account.equity()), "initial_capital": float(kernel.initial_balance),
            "netprofit": float(account_feedback_profit(account, kernel.initial_balance)),
            "openprofit": float(account.unrealized())}
        if len(groups) == cursor:
            groups.append([])
            accounts.append(frame)
        if len(groups[cursor]) >= 65:
            raise BacktestError("BUDGET_EXCEEDED", "at most 65 Pine evaluations per chart bar")
        accounts[cursor] = frame
        index = len(groups[cursor])
        evaluation = {"bar": deepcopy(bar), "account": frame, "event_time_ms": event.event_time_ms,
                      "confirmed": trigger != "order_fill"}
        # Historical fill recalculations see the completed canonical OHLCV.
        # Requested streams use that same chart-close cutoff, independently of
        # the artificial interpolation used to timestamp intrabar fills.
        if wire.get("contexts"):
            evaluation["request_data"] = visible_contexts(wire, bar_event(wire, cursor, 0).event_time_ms + 1)
        groups[cursor].append({"evaluation": evaluation,
            "context": {"bar_state": "historical", "trigger": trigger, "is_new": True}})
        request = {key: value for key, value in wire.items() if key not in {"execution_events", "execution_passes"}}
        request.update(bars=wire["bars"][:cursor + 1], accounts=accounts,
            execution_schedule=groups, contexts=[{**row, "bars": []} for row in wire.get("contexts", [])])
        if "execution_times" in wire:
            request["execution_times"] = wire["execution_times"][:cursor + 1]
        latest = runner(plugin, request, cancelled=cancelled, timeout=max(.1, deadline - time.monotonic()))
        if (latest.get("contract") != "external-broker/1" or latest.get("identity") != wire["identity"]
                or latest.get("execution_mode") != "CANDLESCOPE" or latest.get("account_authority") != "candlescope"
                or latest.get("execution_schedule_contract") != SCHEDULE_CONTRACT
                or latest.get("raw_output", {}).get("strategy")):
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine BAR callback authority")
        emitted = latest["intents"]
        current = [row for row in emitted if (row.get("bar_index"), row.get("pass_index")) == (cursor, index)]
        previous = [row for row in emitted if (row.get("bar_index", -1), row.get("pass_index", -1)) < (cursor, index)]
        if previous != history or len(previous) + len(current) != len(emitted):
            raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX", "Pine BAR callback changed earlier decisions")
        if sum(row["bar_index"] == cursor for row in emitted) > 64:
            raise BacktestError("BUDGET_EXCEEDED", "at most 64 intents per chart bar")
        history.extend(current)
        orders.configure(latest.get("pyramiding", 1))
        check_risk_response(orders, wire, latest)
        intents = orders.translate(current, event.sequence)
        kernel.decisions.append({"sequence": event.sequence, "watermark_ms": event.event_time_ms,
            "intents": intents, "signal_bar": cursor, "pass_index": index, "trigger": trigger.upper()})
        kernel._enqueue_many(intents, current_sequence=event.sequence)

    prior_reporter = kernel.execution_reporter

    def report(event):
        # Common ledger bookkeeping may mark the account at the slipped fill;
        # script/risk feedback observes the path's current market price.
        kernel.account.mark = Decimal(kernel._last_event.payload["price"])
        prior_reporter(event)
        if event.get("fill"):
            trigger = "closing_fill" if kernel._last_event.payload["execution_phase"] == "PINE_BAR_CLOSE" else "order_fill"
            evaluate(kernel._last_event, trigger)

    def close(event):
        evaluate(event, "bar_close")
        if wire.get("closing_ticks"):
            kernel.closing_tick()

    kernel.execution_reporter = report
    try:
        while cursor < target:
            kernel.walk_bar(bar_event(wire, cursor, cursor + 1), close)
            cursor += 1
        if target == len(wire["bars"]):
            kernel.finalize_orders()
    finally:
        kernel.execution_reporter = prior_reporter
    passes = [[row["evaluation"] for row in group] for group in groups]
    clock = {"contract": CONTRACT, "bar_cursor": cursor, "last_sequence": kernel.path_sequence,
             "groups": groups, "accounts": accounts, "history": history, "latest": latest}
    return latest, history, accounts, passes, clock
