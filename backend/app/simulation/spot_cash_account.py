"""Unleveraged spot cash accounting; quantity is always an absolute base amount."""
from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from app.market_dataset.snapshot import MarketDatasetError
from .contract_accounting import ContractAccount

ACCOUNT_MODEL = "SPOT_CASH_V1"
ZERO = Decimal("0")


class SpotCashAccount(ContractAccount):
    def __init__(self, **kwargs):
        super().__init__(**kwargs, require_mark=False, require_funding=False, liquidation_enabled=False)

    def equity(self):
        return self.quote_balance + (self.position_qty * self._require_mark() if self.position_qty else ZERO)

    def fill_rejection(self, *, side, price, qty, fee):
        if side not in {"BUY", "SELL"} or any(not value.is_finite() for value in (price, qty, fee)) or price <= 0 or qty <= 0 or fee < 0:
            return "SPOT_INVALID_FILL"
        if side == "BUY" and price * qty + fee > self.quote_balance:
            return "SPOT_INSUFFICIENT_CASH"
        if side == "SELL" and qty > self.position_qty:
            return "SPOT_INSUFFICIENT_BASE"
        if side == "SELL" and fee > self.quote_balance + price * qty:
            return "SPOT_INSUFFICIENT_CASH"
        return None

    def apply_fill(self, *, side, price, qty, fee=None):
        charged = price * qty * self.taker_fee_bps / Decimal("10000") if fee is None else fee
        reason = self.fill_rejection(side=side, price=price, qty=qty, fee=charged)
        if reason:
            raise MarketDatasetError("Spot cash or base balance does not cover the fill", code=reason)
        if side == "BUY":
            cost = (self.entry_price or ZERO) * self.position_qty + price * qty
            self.position_qty += qty
            self.entry_price = cost / self.position_qty
            self.quote_balance -= price * qty + charged
        else:
            realized = (price - self.entry_price) * qty
            self.journal.append({"kind": "REALIZED", "amount": str(realized)})
            self.position_qty -= qty
            self.quote_balance += price * qty - charged
            if not self.position_qty:
                self.entry_price = None
        if charged:
            self.fees_paid += charged
            self.journal.append({"kind": "FEE", "amount": str(charged)})

    def apply(self, event):
        if event.role == "FUNDING":
            raise MarketDatasetError("Spot cash accounts do not settle funding", code="SPOT_FUNDING_UNSUPPORTED")
        if event.role == "INSTRUMENT_RULES" and Decimal(str(event.payload.get("multiplier", "1"))) != 1:
            raise MarketDatasetError("Spot cash accounts require unit multiplier", code="SPOT_CONTRACT_UNSUPPORTED")
        super().apply(event)

    def snapshot(self):
        return {**super().snapshot(), "account_model": ACCOUNT_MODEL}

    def restore(self, payload: Mapping):
        if payload.get("account_model") != ACCOUNT_MODEL:
            raise MarketDatasetError("Spot checkpoint account identity changed", code="IDENTITY_MUTATION")
        super().restore(payload)
        if self.quote_balance < 0 or self.position_qty < 0 or self.liquidation_enabled or self.funding_paid or self.multiplier != 1:
            raise MarketDatasetError("Invalid spot cash checkpoint", code="DATA_QUALITY_FAILED")


def reserved_spot_order_reason(account, intent, pending, reference, fee_bps):
    """OCO siblings reserve their maximum, independent orders reserve their sum.

    Reservations derive from the authoritative active orders, so cancellation,
    partial fills, and restored checkpoints cannot leave a stale second ledger.
    Actual fill prices and fees are checked again before any account mutation.
    """
    if not isinstance(account, SpotCashAccount):
        return None
    if reference is None or not reference.is_finite() or reference <= 0:
        return "SPOT_REFERENCE_PRICE_UNAVAILABLE"
    groups = {}
    values = [(order.side, order.type, order.qty, order.limit_price, order.stop_price, order.oco_group)
              for order in pending if order.status in {"OPEN", "PARTIAL"}]
    values.append((intent["side"], intent["type"], Decimal(str(intent["qty"])),
                   intent.get("limit_price"), intent.get("stop_price"), intent.get("oco_group")))
    for index, (side, kind, qty, limit, stop, oco) in enumerate(values):
        price = Decimal(str(limit)) if kind in {"LIMIT", "STOP_LIMIT"} and limit is not None else reference
        if kind == "STOP" and stop is not None:
            price = max(price, Decimal(str(stop)))
        reserve = qty * price * (1 + fee_bps / Decimal("10000")) if side == "BUY" else qty
        key = (side, str(oco)) if oco else (side, index)
        groups[key] = max(groups.get(key, ZERO), reserve)
    cash = sum((value for (side, _), value in groups.items() if side == "BUY"), ZERO)
    base = sum((value for (side, _), value in groups.items() if side == "SELL"), ZERO)
    if cash > account.quote_balance:
        return "SPOT_INSUFFICIENT_CASH"
    if base > account.position_qty:
        return "SPOT_INSUFFICIENT_BASE"
    return None


def reject_spot_fill(kernel, order, sequence, reason):
    order.status = "REJECTED"
    kernel._active_orders.pop(order.order_id, None)
    rejected = {"accepted": False, "reason": reason, "sequence": sequence,
                "order_id": order.order_id, "intent": {"side": order.side, "type": order.type, "qty": str(order.qty)}}
    kernel.rejected.append(rejected)
    kernel._lifecycle(order, "REJECTED", reason=reason)
    if kernel.execution_reporter is not None:
        kernel.execution_reporter(rejected)
