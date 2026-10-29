"""Validate the core's default-quantity declaration without evaluating Pine."""
from decimal import Decimal, InvalidOperation


def supported(identity):
    value = identity.get("external_sizing")
    return type(value) is int and value == 1


def declaration(value):
    if (not isinstance(value, dict) or set(value) != {"kind", "value"}
        or not isinstance(value["kind"], str) or value["kind"] not in {"fixed", "cash", "percent_of_equity"}
        or not isinstance(value["value"], str) or not 1 <= len(value["value"]) <= 1024):
        raise ValueError("invalid Pine default quantity declaration")
    try:
        amount = Decimal(value["value"])
    except InvalidOperation as exc:
        raise ValueError("invalid Pine default quantity value") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("Pine default quantity must be finite and nonnegative")
    return dict(value)
