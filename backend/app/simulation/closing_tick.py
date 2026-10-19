"""Explicit simulated closing ticks over revealed bars, never raw trade events."""
from decimal import Decimal

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from .kernel import SimulationKernel
from .linear_perp_account_v2 import LinearPerpetualAccountV2

CONTRACT = "candlescope.pine-closing-tick/1"
REASON = "PINE_BAR_CLOSE"


def closing_event(bar, sequence):
    price = str(bar.payload["close"])
    return MarketEvent(sequence, bar.event_time_ms, "BARS", {**bar.payload,
        **{key: price for key in ("open", "high", "low", "close", "price")},
        "execution_phase": REASON,
        "revealed_bar": {key: bar.payload[key] for key in ("open", "high", "low", "close", "volume")}})


def match_closing_tick(kernel, bar, sequence, *, on_fill=None):
    event = closing_event(bar, sequence)
    previous_event, previous_reporter = kernel._last_event, kernel.execution_reporter
    price = Decimal(str(bar.payload["close"]))
    remaining = None
    if kernel.execution_model_revision is not None:
        used = Decimal(0)
        for fill in reversed(kernel.fills):
            if fill.event_time_ms < int(bar.payload["open_time_ms"]):
                break
            used += fill.qty
        remaining = max(Decimal(0), Decimal(str(bar.payload["volume"])) * kernel.participation_rate - used)

    def report(value):
        if not isinstance(kernel.account, LinearPerpetualAccountV2):
            kernel.account.mark = price
        if previous_reporter is not None:
            previous_reporter(value)
        if value.get("fill") and on_fill is not None:
            on_fill(bar, event)

    kernel._last_event, kernel.execution_reporter = event, report
    try:
        if not isinstance(kernel.account, LinearPerpetualAccountV2):
            kernel.account.mark = price
        if kernel.market_observer is not None:
            kernel.market_observer(event)
        for _ in range(65):
            progress = False
            working = kernel._live_orders() if isinstance(kernel, SimulationKernel) else kernel._working_orders()
            for order in tuple(working):
                if remaining is not None and remaining <= 0:
                    return
                # The simulated close is a later tick than the last tape print,
                # even though it does not consume another source-event ordinal.
                # Explicit event latency still counts physical source events.
                pending_next_tick = (not isinstance(kernel, SimulationKernel)
                    and (kernel.execution_model_revision is None or kernel.latency_events == 0))
                if order.status not in {"OPEN", "PARTIAL"} or order.eligible_after_sequence > sequence + int(pending_next_tick):
                    continue
                if getattr(kernel, "_order_eligible_time_ms", {}).get(order.order_id, 0) > event.event_time_ms:
                    continue
                if kernel.order_policy is not None and not kernel.order_policy(order, event):
                    continue
                if order.type == "STOP_LIMIT" and not order.activated and triggers_stop(order, price):
                    order.activated = True
                eligible = (order.type == "MARKET"
                    or (order.type == "LIMIT" and crosses_limit(order, price))
                    or (order.type == "STOP" and triggers_stop(order, price))
                    or (order.type == "STOP_LIMIT" and order.activated and crosses_limit(order, price)))
                if not eligible:
                    continue
                fill_price = price
                if order.type in {"MARKET", "STOP"}:
                    fill_price += price * kernel.slippage_bps / 10000 * (1 if order.side == "BUY" else -1)
                if isinstance(kernel, SimulationKernel):
                    used = kernel._fill(order, sequence, fill_price, REASON, remaining)
                else:
                    used = kernel._fill(order, sequence, fill_price, order.qty if remaining is None else min(order.qty, remaining), REASON)
                progress |= used > 0
                if remaining is not None:
                    remaining -= used
            if not progress or on_fill is None:
                return
        raise MarketDatasetError("closing-tick recalculation budget exceeded", code="BUDGET_EXCEEDED")
    finally:
        kernel._last_event, kernel.execution_reporter = previous_event, previous_reporter
        if not isinstance(kernel.account, LinearPerpetualAccountV2):
            kernel.account.mark = price


def crosses_limit(order, price):
    return price <= order.limit_price if order.side == "BUY" else price >= order.limit_price


def triggers_stop(order, price):
    return price >= order.stop_price if order.side == "BUY" else price <= order.stop_price
