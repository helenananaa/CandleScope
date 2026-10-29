"""Causal FIFO repricing of working V2 exposure; never books a trading fill."""

from decimal import Decimal

from .linear_perp_account_v2 import LinearPerpetualAccountV2

ZERO = Decimal(0)
REASON = "ACCOUNT_MARGIN_REPRICE_REJECTED"


def _working(kernel):
    getter = getattr(kernel, "_live_orders", None) or kernel._working_orders
    return tuple(getter())


def opening_quantity(kernel, target):
    position = kernel.account.position_qty
    closing = {"BUY": max(-position, ZERO), "SELL": max(position, ZERO)}
    for order in _working(kernel):
        closed = min(order.qty, closing[order.side])
        if order.order_id == target.order_id:
            return ZERO if order.reduce_only else order.qty - closed
        closing[order.side] -= closed
    return ZERO


def reprice(kernel, event=None, *, execution_price=None):
    account = kernel.account
    if (
        not isinstance(account, LinearPerpetualAccountV2)
        or account.liquidation_state != "ACTIVE"
    ):
        return
    orders = _working(kernel)
    if not orders or account.mark is None or account.multiplier is None:
        return
    event = event or kernel._last_event
    stamp = 0 if event is None else event.event_time_ms
    payload = {} if event is None else event.payload
    quote = (
        execution_price
        if execution_price is not None
        else payload.get(
            "price", payload.get("open", payload.get("close", account.mark))
        )
    )
    reference = max(account.mark, Decimal(str(quote)))
    budget = max(ZERO, account.equity() - account.initial_margin())
    closing = {
        "BUY": max(-account.position_qty, ZERO),
        "SELL": max(account.position_qty, ZERO),
    }
    fee_bps = max(abs(kernel.maker_fee_bps), abs(kernel.taker_fee_bps))
    for order in orders:
        closed = min(order.qty, closing[order.side])
        opened = ZERO if order.reduce_only else order.qty - closed
        book_quote = getattr(
            kernel, "last_ask" if order.side == "BUY" else "last_bid", None
        )
        depth = getattr(kernel, "depth", {}).get(
            "SELL" if order.side == "BUY" else "BUY", {}
        )
        if depth:
            book_quote = min(depth) if order.side == "BUY" else max(depth)
        price = max(
            reference,
            book_quote or ZERO,
            order.limit_price or ZERO,
            order.stop_price or ZERO,
        )
        margin = opened * price * account.multiplier / account.leverage
        fee = kernel._execution_fee(price, order.qty, fee_bps) if opened else ZERO
        if opened and margin + fee > budget:
            order.status = "CANCELLED"
            kernel._active_orders.pop(order.order_id, None)
            kernel._lifecycle(order, "CANCELLED", reason=REASON)
            account.reject_repriced_margin(
                order.order_id,
                amount=margin + fee,
                budget=budget,
                event_time_ms=stamp,
                reference_price=price,
            )
            continue
        closing[order.side] -= closed
        budget -= margin + fee
        account.reprice_order_margin(
            order.order_id, margin, event_time_ms=stamp, reference_price=price
        )
