"""Validated scalar instrument rules shared by admission and account recovery."""
from decimal import Decimal, InvalidOperation

from app.market_dataset.snapshot import MarketDatasetError


def positive_rule(value, name, *, required=False, code="DATA_QUALITY_FAILED"):
    if value is None and not required:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MarketDatasetError(f"invalid {name} rule", code=code) from exc
    if not number.is_finite() or number <= 0:
        raise MarketDatasetError(f"invalid {name} rule", code=code)
    return number


def quantity_bounds(payload, *, code="DATA_QUALITY_FAILED"):
    minimum = positive_rule(payload.get("min_quantity"), "minimum quantity", code=code)
    maximum = positive_rule(payload.get("max_quantity"), "maximum quantity", code=code)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise MarketDatasetError("minimum quantity exceeds maximum quantity", code=code)
    return minimum, maximum
