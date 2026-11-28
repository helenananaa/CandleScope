"""How a practice market holds positions (ADR-DATA-002 §4.1, D5b).

The symbol's catalog row declares its ``accountModel``; practice accounts read
that instead of asking whether the market type is ``futures``:

- ``cash``: fully paid and long only (spot crypto, stocks, ETFs);
- ``crypto_linear``: margin on notional at the account's leverage, profit in
  the quote, long and short, one-way or hedge;
- ``crypto_inverse``: contracts settled in the base coin, which a ledger kept
  in the quote currency cannot value, so it opens no positions;
- ``futures_margin``: a fixed margin per contract (D5d), not simulated yet.

A symbol without a declaration, or one the catalog has not loaded, keeps the
rules practice used before: ``futures`` is linear, anything else is cash.

Cash markets also follow the row's quantity grid (D5c): its step, the grid's
origin and its minimum, all in base units (shares for stocks). Contract rows
count quantity in contracts, which practice does not trade in yet, so their
grid waits for D5d. ``currency`` is what the market's prices are quoted in;
practice books them in the account's currency one for one.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.exchanges.models import ACCOUNT_MODELS

logger = logging.getLogger("trading_accounts.practice")

CASH = "cash"
CRYPTO_LINEAR = "crypto_linear"
CRYPTO_INVERSE = "crypto_inverse"
FUTURES_MARGIN = "futures_margin"

_CONTRACTS = frozenset({CRYPTO_LINEAR, CRYPTO_INVERSE, FUTURES_MARGIN})
# Models whose positions the practice ledger can open and value.
_SIMULATED = frozenset({CASH, CRYPTO_LINEAR})


@dataclass(frozen=True, slots=True)
class MarketRules:
    account_model: str
    declared: bool
    currency: str = ""
    quantity_step: Decimal | None = None
    quantity_origin: Decimal = Decimal(0)
    min_quantity: Decimal | None = None

    @property
    def contract(self) -> bool:
        """A derivative: long or short, one-way or hedge positions."""
        return self.account_model in _CONTRACTS

    @property
    def leveraged(self) -> bool:
        """Margin is notional over the account's leverage; cash is fully paid."""
        return self.account_model == CRYPTO_LINEAR

    @property
    def opens_positions(self) -> bool:
        return self.account_model in _SIMULATED

    def quantity_error(self, qty: Decimal) -> str | None:
        """Why ``qty`` is off the market's grid, or None when it is on it."""
        if self.min_quantity is not None and qty < self.min_quantity:
            return f"Quantity must be at least {_text(self.min_quantity)}"
        if self.quantity_step is not None and (qty - self.quantity_origin) % self.quantity_step:
            return f"Quantity must be a multiple of {_text(self.quantity_step)}"
        return None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "accountModel": self.account_model,
            "declared": self.declared,
            "leverage": self.leveraged,
            "shorting": self.contract,
            "hedge": self.contract,
            "opensPositions": self.opens_positions,
        }
        if self.currency:
            data["currency"] = self.currency
        if self.quantity_step is not None:
            data["quantityStep"] = _text(self.quantity_step)
        if self.min_quantity is not None:
            data["minQuantity"] = _text(self.min_quantity)
        return data


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _positive(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _quantity_grid(info: dict[str, Any]) -> dict[str, Any]:
    """The base-unit grid a cash row declares; significant-digit rows have no fixed step."""
    step = None if info.get("quantityRuleModel") == "significant_digits" else _positive(info.get("quantityStep"))
    origin = (_positive(info.get("quantityOrigin")) or Decimal(0)) if step is not None else Decimal(0)
    minimum = _positive(info.get("minQuantity"))
    if step is not None:
        # The smallest quantity on the grid, when the row names no larger minimum.
        first = origin if origin > 0 else step
        minimum = max(minimum or first, first)
    return {"quantity_step": step, "quantity_origin": origin, "min_quantity": minimum}


def market_rules(market: Any, instrument: tuple[str, str, str]) -> MarketRules:
    """The rules ``instrument`` follows, from the catalog row ``market`` knows."""
    lookup = getattr(market, "symbol_info", None)
    info = None
    if callable(lookup):
        try:
            info = lookup(*instrument)
        except Exception:
            logger.debug("Practice symbol metadata unavailable for %s", instrument, exc_info=True)
    info = info if isinstance(info, dict) else {}
    currency = str(info.get("currency") or info.get("quoteAsset") or "").strip().upper()
    model = str(info.get("accountModel") or "").strip().lower()
    if model and model in ACCOUNT_MODELS:
        grid = _quantity_grid(info) if model == CASH else {}
        return MarketRules(model, True, currency, **grid)
    return MarketRules(CRYPTO_LINEAR if instrument[1] == "futures" else CASH, False, currency)


__all__ = ["CASH", "CRYPTO_INVERSE", "CRYPTO_LINEAR", "FUTURES_MARGIN", "MarketRules", "market_rules"]
