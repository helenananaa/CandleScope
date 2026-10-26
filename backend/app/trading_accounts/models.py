"""Shared contracts and validation for trading accounts.

Money, prices and quantities are ``Decimal`` in memory and canonical decimal
strings at rest and on the wire. Floats never enter the ledger.
"""
from __future__ import annotations

import re
import secrets
import time
from decimal import Decimal, InvalidOperation
from typing import Any

ACCOUNT_KINDS = ("practice", "manual")
# Presented in the add-account dialog but not creatable until a verified
# exchange connector exists. Kept here so the UI and API agree on names.
PLANNED_ACCOUNT_KINDS = ("exchange_readonly", "exchange_trading")
MARKET_TYPES = ("spot", "futures")
SIDES = ("buy", "sell")
ORDER_TYPES = ("market", "limit", "stop")
ORDER_STATUSES = ("working", "filled", "cancelled", "rejected")
FILL_SOURCES = ("practice", "manual")
LIQUIDITY = ("maker", "taker", "manual")
ENTRY_KINDS = ("note", "quick")

DEFAULT_PRACTICE_SETTINGS: dict[str, str] = {
    "initialBalance": "10000",
    "takerFeeRate": "0.0005",
    "makerFeeRate": "0.0002",
    "slippageBps": "1",
    "leverage": "10",
}

MAX_NAME_LENGTH = 80
MAX_TEXT_LENGTH = 20_000
MAX_FIELD_COUNT = 64
MAX_FIELD_KEY_LENGTH = 64
MAX_TAGS = 32

_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._:/-]{0,39}$")
_EXCHANGE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_FIELD_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_ID = re.compile(r"^[a-z]{2,4}_[0-9a-f]{20}(~r)?$")


class TradingAccountError(Exception):
    """Domain error with a stable code; HTTP adapters map ``status``."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self)}


def not_found(what: str) -> TradingAccountError:
    return TradingAccountError("TRADING_NOT_FOUND", f"{what} was not found", status=404)


def invalid(message: str, code: str = "TRADING_INVALID") -> TradingAccountError:
    return TradingAccountError(code, message, status=422)


def conflict(message: str, code: str = "TRADING_CONFLICT") -> TradingAccountError:
    return TradingAccountError(code, message, status=409)


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def to_decimal(value: Any, field: str, *, positive: bool = False, allow_zero: bool = True) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise invalid(f"{field} is required")
    if isinstance(value, float):
        # JSON numbers arrive as floats; repr keeps the shortest round trip.
        value = repr(value)
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise invalid(f"{field} must be a decimal number") from exc
    if not number.is_finite():
        raise invalid(f"{field} must be finite")
    if positive and number <= 0:
        raise invalid(f"{field} must be greater than zero")
    if not allow_zero and number == 0:
        raise invalid(f"{field} must not be zero")
    if abs(number) >= Decimal("1e18"):
        raise invalid(f"{field} is out of range")
    return number


def optional_decimal(value: Any, field: str, *, positive: bool = False) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return to_decimal(value, field, positive=positive)


def dec_str(value: Decimal | None) -> str | None:
    """Canonical decimal text without exponent noise or trailing zeros."""
    if value is None:
        return None
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def normalize_instrument(exchange: Any, market_type: Any, symbol: Any) -> tuple[str, str, str]:
    exchange_text = str(exchange or "").strip().lower()
    market_text = str(market_type or "").strip().lower()
    symbol_text = str(symbol or "").strip().upper()
    if _EXCHANGE.fullmatch(exchange_text) is None:
        raise invalid("exchange is invalid")
    if market_text not in MARKET_TYPES:
        raise invalid("marketType must be spot or futures")
    if _SYMBOL.fullmatch(symbol_text) is None:
        raise invalid("symbol is invalid")
    return exchange_text, market_text, symbol_text


def bounded_text(value: Any, field: str, *, maximum: int = MAX_TEXT_LENGTH, required: bool = False) -> str:
    text = "" if value is None else str(value)
    if required and not text.strip():
        raise invalid(f"{field} is required")
    if len(text) > maximum:
        raise invalid(f"{field} is too long")
    return text


def normalize_fields(value: Any) -> dict[str, str]:
    """Journal template fields: flat string map with bounded keys and values."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise invalid("fields must be an object")
    if len(value) > MAX_FIELD_COUNT:
        raise invalid("too many fields")
    fields: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or _FIELD_KEY.fullmatch(key) is None:
            raise invalid("field key is invalid")
        if item is None:
            continue
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise invalid(f"field {key} must be text")
        text = bounded_text(item if isinstance(item, str) else repr(item), f"field {key}")
        if text.strip():
            fields[key] = text
    return fields


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_TAGS:
        raise invalid("tags must be a short list")
    tags: list[str] = []
    for item in value:
        tag = bounded_text(item, "tag", maximum=40).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags
