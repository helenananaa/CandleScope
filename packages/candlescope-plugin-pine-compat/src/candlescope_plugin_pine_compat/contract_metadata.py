"""Pine contract transport checks, independent of a concrete Host account."""
from decimal import Decimal, localcontext
import re


def quantity_decimal(value, field):
    error = f"PINE_HOST_METADATA_INVALID: {field} must preserve a positive decimal with at most 18 fractional places and a u64 coefficient"
    if not isinstance(value, str) or len(value) > 80 or not re.fullmatch(
        r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value
    ):
        raise ValueError(error)
    exponent_text = re.split("[eE]", value)
    if len(exponent_text) == 2 and abs(int(exponent_text[1])) > 100:
        raise ValueError(error)
    number = Decimal(value)
    if not number.is_finite() or number <= 0:
        raise ValueError(error)
    with localcontext() as context:
        context.prec = 100
        normal = number.normalize()
    exponent = int(normal.as_tuple().exponent)
    if not -18 <= exponent <= 19:
        raise ValueError(error)
    coefficient = int("".join(map(str, normal.as_tuple().digits))) * 10 ** max(0, exponent)
    if coefficient > 18_446_744_073_709_551_615 or Decimal(str(float(number))) != number:
        raise ValueError(error)
    return max(0, -exponent)


def require_contract_capability(*metadata):
    if any(item and (item.get("pointValue", 1) != 1 or "quantityStep" in item or "minContract" in item)
           for item in metadata):
        import pine_compat
        if getattr(pine_compat, "CONTRACT_METADATA_SCHEMA_VERSION", 0) != 1:
            raise ValueError("PINE_HOST_CONTRACT_UNAVAILABLE: install a runtime with contract metadata schema 1")
