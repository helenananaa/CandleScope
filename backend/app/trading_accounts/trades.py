"""Derive trades (flat-to-flat position lifecycles) from immutable fills.

Trades are a pure, rebuildable projection: fills are never modified, and a
change to the grouping rule only means recomputing. One trade covers one
account + instrument from the first fill that leaves a flat position until the
fill that returns it to flat. A fill that crosses through zero is split: the
closing part ends the old trade and the remainder opens a new trade whose id
carries a ``~r`` suffix so ids stay unique and stable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from .models import dec_str

ZERO = Decimal("0")


@dataclass(slots=True)
class FillLeg:
    fill_id: str
    side: str
    role: str  # open | add | reduce | close
    qty: Decimal
    price: Decimal
    fee: Decimal
    ts_ms: int
    liquidity: str
    order_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fillId": self.fill_id,
            "side": self.side,
            "role": self.role,
            "qty": dec_str(self.qty),
            "price": dec_str(self.price),
            "fee": dec_str(self.fee),
            "tsMs": self.ts_ms,
            "liquidity": self.liquidity,
            "orderId": self.order_id,
        }


@dataclass(slots=True)
class Trade:
    id: str
    account_id: str
    exchange: str
    market_type: str
    symbol: str
    direction: str  # long | short
    opened_at_ms: int
    closed_at_ms: int | None = None
    open_qty: Decimal = ZERO
    max_qty: Decimal = ZERO
    entry_qty: Decimal = ZERO
    entry_cost: Decimal = ZERO
    exit_qty: Decimal = ZERO
    exit_value: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    legs: list[FillLeg] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "open" if self.closed_at_ms is None else "closed"

    @property
    def sign(self) -> Decimal:
        return Decimal(1) if self.direction == "long" else Decimal(-1)

    @property
    def avg_entry_price(self) -> Decimal | None:
        return self.entry_cost / self.entry_qty if self.entry_qty > 0 else None

    @property
    def avg_exit_price(self) -> Decimal | None:
        return self.exit_value / self.exit_qty if self.exit_qty > 0 else None

    @property
    def net_pnl(self) -> Decimal:
        return self.realized_pnl - self.fees

    def unrealized_pnl(self, mark: Decimal | None) -> Decimal | None:
        avg = self.avg_entry_price
        if mark is None or avg is None or self.open_qty == 0:
            return None
        return (mark - avg) * self.open_qty * self.sign

    def to_dict(self, *, mark: Decimal | None = None) -> dict[str, Any]:
        unrealized = self.unrealized_pnl(mark)
        return {
            "id": self.id,
            "accountId": self.account_id,
            "exchange": self.exchange,
            "marketType": self.market_type,
            "symbol": self.symbol,
            "direction": self.direction,
            "status": self.status,
            "openedAtMs": self.opened_at_ms,
            "closedAtMs": self.closed_at_ms,
            "openQty": dec_str(self.open_qty),
            "maxQty": dec_str(self.max_qty),
            "entryQty": dec_str(self.entry_qty),
            "exitQty": dec_str(self.exit_qty),
            "avgEntryPrice": dec_str(self.avg_entry_price),
            "avgExitPrice": dec_str(self.avg_exit_price),
            "realizedPnl": dec_str(self.realized_pnl),
            "fees": dec_str(self.fees),
            "netPnl": dec_str(self.net_pnl),
            "markPrice": dec_str(mark),
            "unrealizedPnl": dec_str(unrealized),
            "legs": [leg.to_dict() for leg in self.legs],
        }


def _fill_sort_key(fill: dict[str, Any]) -> tuple[int, int, str]:
    return (int(fill["ts_ms"]), int(fill.get("seq") or 0), str(fill["id"]))


def build_trades(account_id: str, fills: Iterable[dict[str, Any]]) -> list[Trade]:
    """Group fills of one account into trades, oldest first.

    ``fills`` rows need: id, side, qty, price, fee (Decimal), ts_ms, exchange,
    market_type, symbol, liquidity, order_id.
    """
    by_instrument: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for fill in fills:
        key = (fill["exchange"], fill["market_type"], fill["symbol"])
        by_instrument.setdefault(key, []).append(fill)

    trades: list[Trade] = []
    for (exchange, market_type, symbol), rows in by_instrument.items():
        current: Trade | None = None
        for fill in sorted(rows, key=_fill_sort_key):
            qty: Decimal = fill["qty"]
            price: Decimal = fill["price"]
            fee: Decimal = fill["fee"]
            side: str = fill["side"]
            fill_sign = Decimal(1) if side == "buy" else Decimal(-1)
            remaining = qty

            if current is not None and current.sign != fill_sign:
                closing = min(remaining, current.open_qty)
                fee_part = fee * closing / qty
                avg = current.avg_entry_price or price
                current.realized_pnl += (price - avg) * closing * current.sign
                current.exit_qty += closing
                current.exit_value += price * closing
                current.fees += fee_part
                current.open_qty -= closing
                remaining -= closing
                role = "close" if current.open_qty == 0 else "reduce"
                current.legs.append(FillLeg(
                    fill["id"], side, role, closing, price, fee_part,
                    int(fill["ts_ms"]), fill["liquidity"], fill.get("order_id"),
                ))
                if current.open_qty == 0:
                    current.closed_at_ms = int(fill["ts_ms"])
                    trades.append(current)
                    current = None
                if remaining == 0:
                    continue
                fee = fee - fee_part
                reversed_open = True
            else:
                reversed_open = False

            if current is None:
                current = Trade(
                    id=f"{fill['id']}~r" if reversed_open else str(fill["id"]),
                    account_id=account_id,
                    exchange=exchange,
                    market_type=market_type,
                    symbol=symbol,
                    direction="long" if fill_sign > 0 else "short",
                    opened_at_ms=int(fill["ts_ms"]),
                )
                role = "open"
            else:
                role = "add"
            current.open_qty += remaining
            current.entry_qty += remaining
            current.entry_cost += price * remaining
            current.max_qty = max(current.max_qty, current.open_qty)
            current.fees += fee
            current.legs.append(FillLeg(
                fill["id"], side, role, remaining, price, fee,
                int(fill["ts_ms"]), fill["liquidity"], fill.get("order_id"),
            ))
        if current is not None:
            trades.append(current)
    trades.sort(key=lambda trade: (trade.opened_at_ms, trade.id))
    return trades


def signed_position(trades: Iterable[Trade], exchange: str, market_type: str, symbol: str) -> Decimal:
    for trade in trades:
        if (
            trade.status == "open"
            and trade.exchange == exchange
            and trade.market_type == market_type
            and trade.symbol == symbol
        ):
            return trade.open_qty * trade.sign
    return ZERO
