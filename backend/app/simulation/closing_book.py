"""Synthetic closing ticks consume visible quotes/depth, never passive prints."""
from decimal import Decimal

from .book_kernel import BookAssistedKernel
from .depth_kernel import DepthQueueKernel, LIVE
from .sampled_book_kernel import SampledBookKernel

ZERO = Decimal(0)


def is_book_kernel(kernel):
    return isinstance(kernel, (BookAssistedKernel, DepthQueueKernel))


def match_book_close(kernel, order, event, capacity):
    from .closing_tick import REASON, triggers_stop
    price = Decimal(str(event.payload["close"]))
    if order.type in {"STOP", "STOP_LIMIT"}:
        if triggers_stop(order, price):
            order.activated = True
        if not order.activated:
            return ZERO
    if isinstance(kernel, SampledBookKernel):
        stamp = kernel.sample_time_ms
        if stamp is None or not 0 < event.event_time_ms - stamp <= kernel.max_age_ms:
            return ZERO
    market = order.type in {"MARKET", "STOP"}
    if isinstance(kernel, BookAssistedKernel):
        level = kernel.last_ask if order.side == "BUY" else kernel.last_bid
        if level is None or (not market and (level > order.limit_price if order.side == "BUY" else level < order.limit_price)):
            return ZERO
        qty = order.qty if capacity is None else min(order.qty, capacity)
        execution = level * (1 + kernel.slippage_bps / 10000 * (1 if order.side == "BUY" else -1)) if market else level
        return kernel._fill(order, event.sequence, execution, qty, REASON)
    opposite = "SELL" if order.side == "BUY" else "BUY"
    used = ZERO
    # No queue movement or aggressor volume is invented by this observation.
    for level in sorted(kernel.depth[opposite], reverse=order.side == "SELL"):
        if order.status not in LIVE or capacity is not None and used >= capacity:
            break
        if kernel.order_policy is not None and not kernel.order_policy(order, event):
            break
        if not market and (level > order.limit_price if order.side == "BUY" else level < order.limit_price):
            break
        qty = min(order.qty, kernel.available[opposite].get(level, ZERO))
        if capacity is not None:
            qty = min(qty, capacity - used)
        if qty <= 0:
            continue
        execution = level * (1 + kernel.slippage_bps / 10000 * (1 if order.side == "BUY" else -1)) if market else level
        actual = kernel._fill(order, event.sequence, execution, qty, REASON)
        kernel.available[opposite][level] -= actual
        used += actual
    return used
