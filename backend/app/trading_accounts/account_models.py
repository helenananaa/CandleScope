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
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "accountModel": self.account_model,
            "declared": self.declared,
            "leverage": self.leveraged,
            "shorting": self.contract,
            "hedge": self.contract,
            "opensPositions": self.opens_positions,
        }


def market_rules(market: Any, instrument: tuple[str, str, str]) -> MarketRules:
    """The rules ``instrument`` follows, from the catalog row ``market`` knows."""
    lookup = getattr(market, "symbol_info", None)
    info = None
    if callable(lookup):
        try:
            info = lookup(*instrument)
        except Exception:
            logger.debug("Practice symbol metadata unavailable for %s", instrument, exc_info=True)
    model = str((info or {}).get("accountModel") or "").strip().lower()
    if model and model in ACCOUNT_MODELS:
        return MarketRules(model, True)
    return MarketRules(CRYPTO_LINEAR if instrument[1] == "futures" else CASH, False)


__all__ = ["CASH", "CRYPTO_INVERSE", "CRYPTO_LINEAR", "FUTURES_MARGIN", "MarketRules", "market_rules"]
