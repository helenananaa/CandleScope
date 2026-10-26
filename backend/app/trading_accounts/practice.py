"""Pure order matching for local practice accounts.

The practice simulator is a lightweight real-time candle replay: it walks the
live 1m candles of an instrument, in order, from its cursor to the present and
matches working orders against the price path each candle implies. The same
walk catches up after the app was closed, so live matching and recovery share
one code path.

Path model (labelled in the UI): a new candle moves open -> low -> high ->
close when it closes up, otherwise open -> high -> low -> close. Updates to a
forming candle only add the extremes that were not seen before. Limit orders
fill only when price trades through the limit (a touch is not a fill); stop
orders fill at the stop or the first price beyond it, plus slippage. There is
no funding, liquidation or order-book depth.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Iterable

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
# Orders placed while the cursor is behind (catch-up) never match candles
# that started before them. A small tolerance absorbs poll timing.
ELIGIBILITY_TOLERANCE_MS = 2_000
BAR_MS = 60_000


@dataclass(slots=True)
class PracticeSettings:
    taker_fee_rate: Decimal
    maker_fee_rate: Decimal
    slippage_bps: Decimal
    allow_short: bool


@dataclass(slots=True)
class WorkingOrder:
    id: str
    side: str
    type: str
    qty: Decimal
    created_at_ms: int
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    reduce_only: bool = False
    oco_group: str | None = None
    tag: str | None = None
    bracket_stop: Decimal | None = None
    bracket_target: Decimal | None = None
    parent_id: str | None = None


@dataclass(slots=True)
class MatchFill:
    order_id: str
    side: str
    qty: Decimal
    price: Decimal
    fee: Decimal
    liquidity: str
    ts_ms: int


@dataclass(slots=True)
class MatchResult:
    fills: list[MatchFill] = field(default_factory=list)
    filled: dict[str, tuple[Decimal, int, Decimal]] = field(default_factory=dict)
    cancelled: dict[str, str] = field(default_factory=dict)
    created: list[WorkingOrder] = field(default_factory=list)
    position: Decimal = ZERO


@dataclass(slots=True)
class PathChunk:
    """Ordered price points observed between ``start_ms`` and ``ts_ms``."""

    points: list[Decimal]
    start_ms: int
    ts_ms: int


@dataclass(slots=True)
class Cursor:
    bar_time: int  # epoch seconds of the candle being observed
    seen_high: Decimal
    seen_low: Decimal
    last_close: Decimal
    observed_ms: int
    closes_only: bool = False


def _dedupe(points: Iterable[Decimal]) -> list[Decimal]:
    out: list[Decimal] = []
    for point in points:
        if not out or out[-1] != point:
            out.append(point)
    return out


def new_bar_path(open_: Decimal, high: Decimal, low: Decimal, close: Decimal) -> list[Decimal]:
    if close >= open_:
        return [open_, low, high, close]
    return [open_, high, low, close]


def advance_cursor(
    cursor: Cursor,
    bar_time: int,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    *,
    observed_ms: int,
) -> tuple[Cursor, PathChunk | None]:
    """Return the path implied by one candle observation and the next cursor."""
    if bar_time < cursor.bar_time:
        return cursor, None
    if bar_time == cursor.bar_time:
        if cursor.closes_only:
            points = [cursor.last_close, close]
            nxt = replace(cursor, last_close=close, observed_ms=max(cursor.observed_ms, observed_ms))
        else:
            extremes: list[Decimal] = []
            if high > cursor.seen_high:
                extremes.append(high)
            if low < cursor.seen_low:
                extremes.append(low)
            if len(extremes) == 2:
                # Unknown order: visit the extreme farther from the close first.
                extremes.sort(key=lambda value: abs(value - close), reverse=True)
            points = [cursor.last_close, *extremes, close]
            nxt = replace(
                cursor,
                seen_high=max(cursor.seen_high, high),
                seen_low=min(cursor.seen_low, low),
                last_close=close,
                observed_ms=max(cursor.observed_ms, observed_ms),
            )
        chunk = PathChunk(_dedupe(points), cursor.observed_ms, max(cursor.observed_ms, observed_ms))
        return nxt, chunk
    points = [cursor.last_close, *new_bar_path(open_, high, low, close)]
    bar_start_ms = bar_time * 1000
    nxt = Cursor(
        bar_time=bar_time,
        seen_high=high,
        seen_low=low,
        last_close=close,
        observed_ms=max(observed_ms, bar_start_ms),
        closes_only=False,
    )
    return nxt, PathChunk(_dedupe(points), bar_start_ms, nxt.observed_ms)


def fee_for(qty: Decimal, price: Decimal, rate: Decimal) -> Decimal:
    return qty * price * rate


def slipped(price: Decimal, side: str, bps: Decimal) -> Decimal:
    factor = bps / BPS
    return price * (ONE + factor) if side == "buy" else price * (ONE - factor)


def _trigger(order: WorkingOrder, a: Decimal, b: Decimal) -> Decimal | None:
    """Level at which ``order`` triggers on a monotonic move a -> b."""
    lo, hi = (a, b) if a <= b else (b, a)
    if order.type == "limit" and order.limit_price is not None:
        limit = order.limit_price
        if order.side == "buy" and lo < limit:
            return a if a < limit else limit
        if order.side == "sell" and hi > limit:
            return a if a > limit else limit
        return None
    if order.type == "stop" and order.stop_price is not None:
        stop = order.stop_price
        if order.side == "buy" and hi >= stop:
            return a if a >= stop else stop
        if order.side == "sell" and lo <= stop:
            return a if a <= stop else stop
    return None


def reachable(order: WorkingOrder, low: Decimal, high: Decimal) -> bool:
    """Whether a path spanning ``low``..``high`` could trigger ``order`` at all."""
    return _trigger(order, low, high) is not None


class PracticeMatcher:
    """Mutable matching session for one instrument of one account."""

    def __init__(
        self,
        orders: Iterable[WorkingOrder],
        position: Decimal,
        settings: PracticeSettings,
        *,
        new_order_id,
    ) -> None:
        self.orders: dict[str, WorkingOrder] = {order.id: order for order in orders}
        self.settings = settings
        self.result = MatchResult(position=position)
        self._new_order_id = new_order_id
        # Bracket exits created by a fill inside this session follow the path
        # from that fill onward, so the creation-time filter does not apply.
        self._born_here: set[str] = set()

    @property
    def position(self) -> Decimal:
        return self.result.position

    def working(self) -> list[WorkingOrder]:
        return sorted(self.orders.values(), key=lambda order: (order.created_at_ms, order.id))

    def cancel(self, order_id: str, reason: str) -> None:
        if self.orders.pop(order_id, None) is not None:
            self.result.cancelled[order_id] = reason

    def execute(self, order: WorkingOrder, price: Decimal, ts_ms: int, *, liquidity: str) -> bool:
        """Fill ``order`` completely (reduce-only orders clamp to the position)."""
        qty = order.qty
        position = self.result.position
        direction = ONE if order.side == "buy" else -ONE
        if order.reduce_only:
            if position == 0 or (position > 0) == (direction > 0):
                self.cancel(order.id, "nothing_to_reduce")
                return False
            qty = min(qty, abs(position))
        elif not self.settings.allow_short and order.side == "sell" and position - qty < 0:
            self.cancel(order.id, "insufficient_position")
            return False
        if order.type in {"market", "stop"}:
            price = slipped(price, order.side, self.settings.slippage_bps)
        rate = self.settings.maker_fee_rate if liquidity == "maker" else self.settings.taker_fee_rate
        fee = fee_for(qty, price, rate)
        self.orders.pop(order.id, None)
        self.result.fills.append(MatchFill(order.id, order.side, qty, price, fee, liquidity, ts_ms))
        self.result.filled[order.id] = (price, ts_ms, qty)
        self.result.position = position + direction * qty

        if order.oco_group:
            for sibling in list(self.orders.values()):
                if sibling.oco_group == order.oco_group:
                    self.cancel(sibling.id, "oco_sibling_filled")
        if self.result.position == 0:
            for other in list(self.orders.values()):
                if other.reduce_only:
                    self.cancel(other.id, "position_closed")
        if not order.reduce_only and (order.bracket_stop is not None or order.bracket_target is not None):
            self._create_bracket(order, qty, ts_ms)
        return True

    def _create_bracket(self, entry: WorkingOrder, qty: Decimal, ts_ms: int) -> None:
        exit_side = "sell" if entry.side == "buy" else "buy"
        group = f"oco:{entry.id}"
        if entry.bracket_stop is not None:
            child = WorkingOrder(
                id=self._new_order_id(), side=exit_side, type="stop", qty=qty,
                created_at_ms=ts_ms, stop_price=entry.bracket_stop, reduce_only=True,
                oco_group=group, tag="stop_loss", parent_id=entry.id,
            )
            self.orders[child.id] = child
            self._born_here.add(child.id)
            self.result.created.append(child)
        if entry.bracket_target is not None:
            child = WorkingOrder(
                id=self._new_order_id(), side=exit_side, type="limit", qty=qty,
                created_at_ms=ts_ms, limit_price=entry.bracket_target, reduce_only=True,
                oco_group=group, tag="take_profit", parent_id=entry.id,
            )
            self.orders[child.id] = child
            self._born_here.add(child.id)
            self.result.created.append(child)

    def run(self, chunk: PathChunk) -> None:
        points = chunk.points
        if not points:
            return
        for index in range(1, len(points)):
            a, b = points[index - 1], points[index]
            if a == b:
                continue
            self._run_move(a, b, chunk)

    def _run_move(self, a: Decimal, b: Decimal, chunk: PathChunk) -> None:
        upward = b > a
        start = a
        # Each fill can create (bracket) or cancel (OCO) orders, so re-scan the
        # remaining part of the move after every fill.
        for _ in range(64):
            candidates: list[tuple[Decimal, int, str, WorkingOrder]] = []
            for order in self.working():
                if (
                    order.id not in self._born_here
                    and chunk.start_ms < order.created_at_ms - ELIGIBILITY_TOLERANCE_MS
                ):
                    continue
                level = _trigger(order, start, b)
                if level is not None:
                    candidates.append((level, order.created_at_ms, order.id, order))
            if not candidates:
                return
            candidates.sort(key=lambda item: (item[0] if upward else -item[0], item[1], item[2]))
            level, _, _, order = candidates[0]
            liquidity = "maker" if order.type == "limit" else "taker"
            ts_ms = max(chunk.ts_ms, order.created_at_ms)
            self.execute(order, level, ts_ms, liquidity=liquidity)
            start = level
