"""How a practice market holds positions (ADR-DATA-002 §4.1, D5b).

The symbol's catalog row declares its ``accountModel``; practice accounts read
that instead of asking whether the market type is ``futures``:

- ``cash``: fully paid and long only (spot crypto, stocks, ETFs);
- ``crypto_linear``: margin on notional at the account's leverage, profit in
  the quote, long and short, one-way or hedge;
- ``crypto_inverse``: contracts settled in the base coin, which a ledger kept
  in the quote currency cannot value, so it opens no positions;
- ``futures_margin``: a fixed margin per contract (D5d), long and short, from
  the catalog row or, when the source publishes none, the figure the user
  entered for the account; without either it opens no positions.

A symbol without a declaration, or one the catalog has not loaded, keeps the
rules practice used before: ``futures`` is linear, anything else is cash.

Practice quantities are base units: shares, coins, or the underlying's units
for a futures contract, so profit is the price move times the quantity. A
contract row counts in contracts of ``contractMultiplier`` base units each;
its grid and its margin are converted at that size. The quantity grid (D5c,
D5d) has a step, an origin and a minimum. Coin-settled contracts have no grid
here, since their size is a quote amount. ``currency`` is what the market's
prices are quoted in; practice books them in the account's currency one for
one.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
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
# Contract rows whose quantity grid counts contracts of a declared size.
_SIZED = frozenset({CRYPTO_LINEAR, FUTURES_MARGIN})


@dataclass(frozen=True, slots=True)
class MarketRules:
    account_model: str
    declared: bool
    currency: str = ""
    quantity_step: Decimal | None = None
    quantity_origin: Decimal = Decimal(0)
    min_quantity: Decimal | None = None
    # Base units in one contract, for contract rows that declare it.
    contract_size: Decimal | None = None
    margin_per_contract: Decimal | None = None
    # Where the margin came from: "catalog" or "account" (the user's figure).
    margin_source: str = ""
    # What a quantity counts: the catalog's base asset (BTC for BTC-USDT-SWAP).
    base_asset: str = ""

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
        if self.account_model == FUTURES_MARGIN:
            return self.contract_size is not None and self.margin_per_contract is not None
        return self.account_model in _SIMULATED

    @property
    def takes_account_margin(self) -> bool:
        """A per-contract market whose source publishes no margin: the user enters it."""
        return (self.account_model == FUTURES_MARGIN and self.contract_size is not None
                and self.margin_source != "catalog")

    @property
    def margin_per_unit(self) -> Decimal | None:
        """A per-contract market's margin for one base unit, whatever the price."""
        if self.account_model == FUTURES_MARGIN and self.contract_size and self.margin_per_contract is not None:
            return self.margin_per_contract / self.contract_size
        return None

    def margin(self, qty: Decimal, price: Decimal, leverage: Decimal) -> Decimal:
        """Margin held for ``qty`` base units at ``price``.

        Linear contracts hold notional over the account's leverage; per-contract
        markets hold their margin per contract whatever the price; cash, and a
        per-contract market whose margin is no longer known, is fully paid.
        """
        if (per_unit := self.margin_per_unit) is not None:
            return qty * per_unit
        return qty * price / (leverage if self.leveraged else Decimal(1))

    def quantity_error(self, qty: Decimal) -> str | None:
        """Why ``qty`` is off the market's grid, or None when it is on it."""
        if self.min_quantity is not None and qty < self.min_quantity:
            return f"Quantity must be at least {_text(self.min_quantity)}"
        # Exact rational remainder: Decimal's % fails once the quotient outgrows its precision.
        if self.quantity_step is not None and (Fraction(qty) - Fraction(self.quantity_origin)) % Fraction(self.quantity_step):
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
        if self.base_asset:
            data["baseAsset"] = self.base_asset
        if self.quantity_step is not None:
            data["quantityStep"] = _text(self.quantity_step)
        if self.min_quantity is not None:
            data["minQuantity"] = _text(self.min_quantity)
        if self.contract_size is not None:
            data["contractSize"] = _text(self.contract_size)
        if self.margin_per_contract is not None:
            data["marginPerContract"] = _text(self.margin_per_contract)
            data["marginSource"] = self.margin_source
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


def _quantity_grid(info: dict[str, Any], size: Decimal = Decimal(1)) -> dict[str, Any]:
    """The row's grid in base units; a contract row's counts contracts of ``size``.

    Significant-digit rows have no fixed step.
    """
    step = None if info.get("quantityRuleModel") == "significant_digits" else _positive(info.get("quantityStep"))
    origin = (_positive(info.get("quantityOrigin")) or Decimal(0)) if step is not None else Decimal(0)
    minimum = _positive(info.get("minQuantity"))
    if step is not None:
        # The smallest quantity on the grid, when the row names no larger minimum.
        first = origin if origin > 0 else step
        minimum = max(minimum or first, first)
    return {"quantity_step": None if step is None else step * size,
            "quantity_origin": origin * size,
            "min_quantity": None if minimum is None else minimum * size}


def _contract_terms(model: str, info: dict[str, Any], account_margin: Decimal | None) -> dict[str, Any]:
    """Quantity grid, contract size and margin of one declared row."""
    if model == CASH:
        return _quantity_grid(info)
    size = _positive(info.get("contractMultiplier")) if model in _SIZED else None
    if size is None:
        # Coin-settled contracts, and contract rows without a size.
        return {}
    terms: dict[str, Any] = {**_quantity_grid(info, size), "contract_size": size}
    if model == FUTURES_MARGIN:
        catalog = _positive(info.get("marginPerContract"))
        if catalog is not None:
            terms.update(margin_per_contract=catalog, margin_source="catalog")
        elif account_margin is not None:
            terms.update(margin_per_contract=account_margin, margin_source="account")
    return terms


def market_rules(
    market: Any, instrument: tuple[str, str, str], *, account_margin: Decimal | None = None,
) -> MarketRules:
    """The rules ``instrument`` follows, from the catalog row ``market`` knows.

    ``account_margin`` is the margin per contract the user entered for this
    market on the account; a margin the catalog publishes comes first.
    """
    lookup = getattr(market, "symbol_info", None)
    info = None
    if callable(lookup):
        try:
            info = lookup(*instrument)
        except Exception:
            logger.debug("Practice symbol metadata unavailable for %s", instrument, exc_info=True)
    info = info if isinstance(info, dict) else {}
    currency = str(info.get("currency") or info.get("quoteAsset") or "").strip().upper()
    base = str(info.get("baseAsset") or "").strip().upper()
    model = str(info.get("accountModel") or "").strip().lower()
    if model and model in ACCOUNT_MODELS:
        return MarketRules(model, True, currency, base_asset=base, **_contract_terms(model, info, account_margin))
    return MarketRules(CRYPTO_LINEAR if instrument[1] == "futures" else CASH, False, currency, base_asset=base)


__all__ = ["CASH", "CRYPTO_INVERSE", "CRYPTO_LINEAR", "FUTURES_MARGIN", "MarketRules", "market_rules"]
