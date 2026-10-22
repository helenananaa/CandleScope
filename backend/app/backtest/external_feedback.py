"""Fill-by-fill callbacks driven by authoritative host executions and visible tape."""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal
import time
from app.market_dataset.snapshot import MarketEvent
from app.data_engine.interval_policy import parse_interval_spec
from app.market_dataset.trades import assert_trade_stream
from .errors import BacktestError


def run_feedback_clock(kernel, orders, wire, plugin, runner, cancelled, deadline, *, state=None, target=None):
    if wire["execution_fidelity"] == "BAR_APPROX":
        raise BacktestError("EXTERNAL_UNSUPPORTED", "fill callbacks require a frozen trade tape")
    interval = parse_interval_spec(wire["interval"])
    events = [MarketEvent(**item) for item in wire["execution_events"]]
    kernel.source_kind = assert_trade_stream(tuple(event for event in events if event.role == "TRADES"))
    state=state or {}
    target=len(wire["bars"]) if target is None else target
    groups,accounts,history,latest=(state.get(name,default) for name,default in
        (("groups",[]),("accounts",[]),("history",[]),("latest",{})))
    from .pine_request_updates import from_wire, pass_observations, validate_replay
    request_feed = from_wire(wire)
    if request_feed is not None and state:
        validate_replay(request_feed, state.get("request_feed"), pass_observations(groups, scheduled=False))
    cursor,visible,active_event=state.get("bar_cursor",0),None,None
    last_sequence,event_cursor=state.get("last_sequence",0),state.get("event_cursor",0)
    end=interval.next_ms(wire["bars"][target-1]["time"]*1000)

    def evaluate(event, confirmed):
        nonlocal latest
        if cancelled.is_set():
            raise BacktestError("NATIVE_CANCELLED", "fill callback cancelled")
        if time.monotonic() >= deadline:
            raise BacktestError("NATIVE_TIMEOUT", "fill callback deadline exceeded")
        orders.feedback()
        account = kernel.account
        from .external import account_feedback_profit
        frame = {"time": visible["time"], "position_size": float(account.position_qty),
            "position_avg_price": None if account.entry_price is None else float(account.entry_price),
            "equity": float(account.equity()), "initial_capital": float(kernel.initial_balance),
            "netprofit": float(account_feedback_profit(account, kernel.initial_balance)), "openprofit": float(account.unrealized())}
        if len(groups) == cursor:
            groups.append([])
            accounts.append(frame)
        if len(groups[cursor]) >= 65:
            raise BacktestError("BUDGET_EXCEEDED", "at most 64 fill callbacks and one close per bar")
        accounts[cursor] = frame
        pass_index = len(groups[cursor])
        groups[cursor].append({"bar": deepcopy(visible), "account": frame,
            "event_time_ms": event.event_time_ms, "confirmed": confirmed})
        if wire.get("contexts"):
            from .external import visible_contexts
            # A fill at boundary-1 may be followed by more prints with the same
            # millisecond. Only the confirmed close has consumed all of them.
            boundary = event.event_time_ms + (1 if confirmed else 0)
            if request_feed is not None:
                groups[cursor][-1].update(request_observed_at_ms=boundary-1, request_updates=request_feed.advance(boundary-1))
            else:
                groups[cursor][-1]["request_data"] = visible_contexts(wire, boundary)
        request = {key: value for key, value in wire.items() if key != "execution_events"}
        request.update(bars=[*wire["bars"][:cursor], deepcopy(visible)], accounts=accounts, execution_passes=groups,
            contexts=[{**context, "bars": []} for context in wire.get("contexts", [])])
        if "execution_times" in wire:
            request["execution_times"] = wire["execution_times"][:cursor + 1]
        latest = runner(plugin, request, cancelled=cancelled, timeout=max(.1, deadline-time.monotonic()))
        if (latest.get("contract") != "external-broker/1" or latest.get("identity") != wire["identity"]
                or latest.get("execution_mode") != "CANDLESCOPE" or latest.get("account_authority") != "candlescope"
                or latest.get("raw_output", {}).get("strategy")):
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid fill callback authority")
        emitted = latest["intents"]
        current = [item for item in emitted if item.get("bar_index") == cursor and item.get("pass_index") == pass_index]
        previous = [item for item in emitted if (item.get("bar_index", -1), item.get("pass_index", -1)) < (cursor, pass_index)]
        if previous != history or len(previous) + len(current) != len(emitted):
            raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX", "script changed a committed fill decision")
        if sum(item["bar_index"] == cursor for item in emitted) > 64:
            raise BacktestError("BUDGET_EXCEEDED", "at most 64 intents per chart bar")
        history.extend(current)
        orders.configure(latest.get("pyramiding", 1))
        from .pine_workbench import check_risk_response
        check_risk_response(orders, wire, latest)
        intents = orders.translate(current, event.sequence)
        kernel.decisions.append({"sequence": event.sequence, "watermark_ms": event.event_time_ms,
            "intents": intents, "signal_bar": cursor, "pass_index": pass_index,
            "trigger": "BAR_CLOSE" if confirmed else "ORDER_FILL"})
        # Newly emitted orders cannot consume the event that caused this callback.
        kernel._enqueue_many(intents, current_sequence=event.sequence)

    prior_reporter = kernel.execution_reporter
    def report(event):
        prior_reporter(event)
        if event.get("fill") and kernel._last_event.payload.get("execution_phase") != "PINE_BAR_CLOSE":
            evaluate(active_event, False)
    kernel.execution_reporter = report

    def close_bar():
        nonlocal cursor, visible
        if visible is None:
            raise BacktestError("DATA_GAP_REJECTED", "missing visible chart bar")
        visible = deepcopy(wire["bars"][cursor])  # All prints have arrived; use the frozen canonical bar.
        boundary = interval.next_ms(visible["time"] * 1000) - 1
        event = MarketEvent(last_sequence, boundary, "TRADES", {"price": str(visible["close"]), "qty": "0"})
        kernel._last_event = event
        if kernel.market_observer is not None:
            kernel.market_observer(event)
        evaluate(event, True)
        if wire.get("closing_ticks"):
            from .pine_workbench import bar_event
            from app.simulation.closing_tick import match_closing_tick
            match_closing_tick(kernel, bar_event(wire, cursor, last_sequence), last_sequence,
                on_fill=lambda _bar, tick: evaluate(tick, True))
            kernel._record_equity_point({"sequence": last_sequence, "event_time_ms": boundary,
                "equity": str(kernel.account.equity()), "position_qty": str(kernel.account.position_qty)})
        cursor += 1
        visible = None

    try:
        for event in events[event_cursor:]:
            if event.event_time_ms>=end:
                break
            if cancelled.is_set():
                raise BacktestError("NATIVE_CANCELLED", "execution cancelled")
            while cursor < len(wire["bars"]) and interval.next_ms(wire["bars"][cursor]["time"]*1000) <= event.event_time_ms:
                close_bar()
            active_event = event
            kernel._last_event = event
            if event.role == "ORDER_BOOK":
                kernel._apply_book(event)
                if kernel.market_observer is not None:
                    kernel.market_observer(event)
            else:
                price, qty = float(event.payload["price"]), float(event.payload["qty"])
                if visible is None:
                    visible = dict(time=wire["bars"][cursor]["time"], open=price, high=price, low=price, close=price, volume=qty)
                else:
                    visible.update(high=max(visible["high"], price), low=min(visible["low"], price), close=price, volume=visible["volume"]+qty)
                kernel.account.mark = Decimal(str(event.payload["price"]))
                if kernel.market_observer is not None:
                    kernel.market_observer(event)
                kernel._match(event)
                kernel.equity_curve.append({"sequence": event.sequence, "event_time_ms": event.event_time_ms,
                    "equity": str(kernel.account.equity()), "position_qty": str(kernel.account.position_qty)})
            last_sequence = event.sequence
            event_cursor+=1
        while cursor < target:
            close_bar()
        if target==len(wire["bars"]):
            kernel.finalize_orders()
    finally:
        kernel.execution_reporter = prior_reporter
    return latest,history,accounts,groups,{"bar_cursor":cursor,"last_sequence":last_sequence,
        "event_cursor":event_cursor,"groups":groups,"accounts":accounts,"history":history,"latest":latest,
        **({"request_feed":request_feed.snapshot()} if request_feed is not None else {})}
