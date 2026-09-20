"""Full L2 depth with a disclosed pessimistic FIFO queue model, never exact MBO.

Takers walk visible depth. Passive orders join behind displayed size and earlier
own orders; only same-price aggressor prints advance them. Cancellations never
advance an assumed queue. Consumed depth is not replenished by repeated snapshots.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from app.market_dataset.snapshot import MarketDatasetError
from .trade_kernel import TradeSimulationKernel, _print_triggers_stop

ZERO = Decimal(0)
LIVE = {"OPEN", "PARTIAL"}


def depth_error(message):
    raise MarketDatasetError(message, code="DATA_QUALITY_FAILED")


def levels(rows):
    if not isinstance(rows, list):
        depth_error("depth levels must be [price, quantity] arrays")
    result = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            depth_error("invalid depth level")
        try:
            price, qty = map(lambda value: Decimal(str(value)), row)
        except (InvalidOperation, ValueError):
            depth_error("invalid depth number")
        if not price.is_finite() or not qty.is_finite() or price <= 0 or qty < 0 or price in result:
            depth_error("depth prices must be unique and positive; quantity must be nonnegative")
        result[price] = qty
    return result


@dataclass(slots=True)
class DepthQueueKernel(TradeSimulationKernel):
    fill_policy: str = "FULL_L2_PESSIMISTIC_FIFO_V1"
    depth: dict = field(default_factory=lambda: {"BUY": {}, "SELL": {}})
    available: dict = field(default_factory=lambda: {"BUY": {}, "SELL": {}})
    book_sequence: int | None = None
    queues: dict = field(default_factory=dict)
    admission_depth: dict = field(default_factory=dict)

    def _validate_book(self, event):
        data = event.payload
        seq = data.get("book_sequence")
        if type(seq) is not int or seq < 0:
            depth_error("depth requires an integer book_sequence")
        if self.book_sequence is None:
            if data.get("snapshot") is not True or data.get("depth_complete") is not True:
                depth_error("depth mode requires an explicitly complete initial snapshot")
        elif seq != self.book_sequence + 1 or data.get("reset"):
            depth_error("depth sequence gap/reset would invalidate resting queues")
        if data.get("snapshot") and data.get("depth_complete") is not True:
            depth_error("truncated depth snapshot is not admissible")
        return seq

    def _passive_allowed(self):
        return True

    def _apply_book(self, event):
        seq = self._validate_book(event)
        data = event.payload
        updated, liquidity = {}, {}
        for side, key in (("BUY", "bids"), ("SELL", "asks")):
            delta = levels(data.get(key))
            book = {} if data.get("snapshot") else dict(self.depth[side])
            for price, qty in delta.items():
                if qty: book[price] = qty
                else: book.pop(price, None)
            updated[side] = book
            # Apply observed size changes; identical snapshots cannot recreate
            # liquidity already consumed by our hypothetical orders.
            liquidity[side] = {price: min(qty, max(ZERO,
                self.available[side].get(price, ZERO) + qty - self.depth[side].get(price, ZERO)))
                for price, qty in book.items()}
        if not updated["BUY"] or not updated["SELL"] or max(updated["BUY"]) >= min(updated["SELL"]):
            depth_error("depth must remain two-sided and uncrossed")
        self.depth, self.available, self.book_sequence = updated, liquidity, seq

    def _enqueue(self, intent, *, current_sequence):
        before = len(self.orders)
        TradeSimulationKernel._enqueue(self, intent, current_sequence=current_sequence)
        if len(self.orders) > before:
            # Book dictionaries are replaced, not mutated, by _apply_book.
            self.admission_depth[self.orders[-1].order_id] = self.depth

    def _match(self, event):
        if event.role == "ORDER_BOOK":
            self._apply_book(event)
            return
        if self.book_sequence is None:
            depth_error("trade precedes full depth snapshot")
        aggressor = event.payload.get("aggressor_side")
        if aggressor not in {"BUY", "SELL"}:
            depth_error("depth queues require explicit trade aggressor_side BUY/SELL")
        price, volume = Decimal(str(event.payload["price"])), Decimal(str(event.payload["qty"]))
        active = [o for o in self.orders if o.status in LIVE and o.eligible_after_sequence <= event.sequence]
        if self.order_policy is not None:
            for order in active: self.order_policy(order, event)
        preceding = []
        initial_ahead = {}
        for order in active:
            initial_ahead[order.order_id] = sum((qty for side,limit,qty in preceding
                if side == order.side and limit == order.limit_price), ZERO)
            if order.status in LIVE:
                preceding.append((order.side,order.limit_price,order.qty))
        remaining = volume
        for order in active:
            if order.status not in LIVE or (self.order_policy and not self.order_policy(order, event)):
                continue
            if order.type in {"STOP", "STOP_LIMIT"}:
                if _print_triggers_stop(order, price): order.activated = True
                if not order.activated: continue
            opposite = "SELL" if order.side == "BUY" else "BUY"
            market = order.type in {"MARKET", "STOP"}
            best = min(self.depth[opposite]) if order.side == "BUY" else max(self.depth[opposite])
            crosses = order.limit_price is not None and (best <= order.limit_price if order.side == "BUY" else best >= order.limit_price)
            if market or crosses:
                for level in sorted(self.depth[opposite], reverse=order.side == "SELL"):
                    if order.status not in LIVE or (self.order_policy and not self.order_policy(order, event)): break
                    if not market and (level > order.limit_price if order.side == "BUY" else level < order.limit_price): break
                    qty = min(order.qty, self.available[opposite].get(level, ZERO))
                    if qty <= 0: continue
                    execution = level
                    if market:
                        execution *= 1 + self.slippage_bps / 10000 * (1 if order.side == "BUY" else -1)
                    before = len(self.fills)
                    self._fill(order,event.sequence,execution,qty,"DEPTH_WALK",maker=False)
                    self.available[opposite][level] -= sum((fill.qty for fill in self.fills[before:]), ZERO)
            elif order.limit_price is not None and self._passive_allowed():
                key = (order.side, order.limit_price)
                previous = self.queues.get(order.order_id)
                if previous is None or previous[0] != key:
                    admitted = self.admission_depth.get(order.order_id, self.depth)[order.side].get(order.limit_price, ZERO)
                    ahead = max(admitted, self.depth[order.side].get(order.limit_price, ZERO))
                    ahead += initial_ahead[order.order_id]
                    previous = (key, ahead)
                ahead = previous[1]
                if aggressor != order.side and price == order.limit_price:
                    executable = max(ZERO, volume - ahead)
                    self.queues[order.order_id] = (key, max(ZERO, ahead-volume))
                    qty = min(order.qty, remaining, executable)
                    if qty > 0:
                        before = len(self.fills)
                        self._fill(order,event.sequence,order.limit_price,qty,"DEPTH_PASSIVE_FIFO_ASSUMED",maker=True)
                        remaining -= sum((fill.qty for fill in self.fills[before:]), ZERO)
                else:
                    self.queues[order.order_id] = previous
