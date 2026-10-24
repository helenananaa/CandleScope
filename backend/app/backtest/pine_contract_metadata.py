"""Admission bounds of the Pine runtime's decimal contract metadata transport."""
from decimal import Decimal, localcontext, InvalidOperation
from fractions import Fraction
import re

from .errors import BacktestError


def quantity_decimal(value: str, field: str) -> int:
    error = f"{field} must preserve a positive decimal with at most 18 fractional places and a u64 coefficient"
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


def bind_account_metadata(account, supplied):
    """Bind only rules visible at the initial chart observation."""
    actual = {
        "priceTickSize": account.tick,
        "pointValue": account.multiplier,
        "quantityStep": account.step,
        "minContract": account.min_quantity,
    }
    if actual["priceTickSize"] is None or actual["pointValue"] is None:
        raise BacktestError("DATA_ROLE_COVERAGE_MISSING", "initial Pine contract rules lack tick or multiplier")
    for key, value in actual.items():
        if supplied.get(key) is not None:
            if value is None:
                raise BacktestError("DATA_ROLE_COVERAGE_MISSING", f"initial account rules lack {key}")
            differs = (Fraction(str(supplied[key])) != Fraction(value) if key == "priceTickSize"
                       else Decimal(str(supplied[key])) != value)
            if differs:
                raise BacktestError("DATA_SNAPSHOT_MISMATCH", f"historical {key} differs from explicit Pine metadata")
    multiplier = float(account.multiplier)
    if Decimal(str(multiplier)) != account.multiplier:
        raise BacktestError("FIDELITY_UNSUPPORTED", "Pine pointValue cannot represent the historical multiplier")
    metadata = {**supplied, "priceTickSize": str(account.tick), "pointValue": multiplier}
    for key in ("quantityStep", "minContract"):
        if actual[key] is not None:
            metadata[key] = str(actual[key])
    # The core's transport is intentionally bounded even when the Host's
    # Decimal account can represent a more detailed exchange rule.
    try:
        from .native_contracts import PineChartMetadata
        return PineChartMetadata.model_validate(metadata).model_dump(exclude_none=True)
    except ValueError as exc:
        raise BacktestError("FIDELITY_UNSUPPORTED", "historical contract rules exceed the Pine metadata transport") from exc


def configure_legacy_account(kernel, wire):
    """Use the frozen chart's rules for the synthetic V1 account as well."""
    if wire.get("account_model") == "LINEAR_PERP_ONE_WAY_V2":
        return  # Historical events own V2 rules and their effective times.
    metadata = wire.get("context", {}).get("metadata") or {}
    multiplier = Decimal(str(metadata.get("pointValue", 1)))
    if wire.get("account_model") == "SPOT_CASH_V1" and multiplier != 1:
        raise BacktestError("FIDELITY_UNSUPPORTED", "spot cash accounting requires unit pointValue")
    kernel.account.multiplier = multiplier
    if metadata.get("quantityStep") is not None:
        kernel.account.step = Decimal(metadata["quantityStep"])
    elif metadata.get("quantityPrecision") is not None:
        kernel.account.step = Decimal(1).scaleb(-metadata["quantityPrecision"])
    if metadata.get("minContract") is not None:
        kernel.account.min_quantity = Decimal(metadata["minContract"])


def observed_contract_metadata(kernel):
    """Only account rules already applied to this observation may be exposed."""
    account = kernel.account
    tick = getattr(account, "tick", None) or getattr(kernel, "price_tick", None)
    if tick is None:
        return None
    multiplier = getattr(account, "multiplier", None) or Decimal(1)
    if Decimal(str(float(multiplier))) != multiplier:
        raise BacktestError("FIDELITY_UNSUPPORTED", "Pine cannot represent the account multiplier")
    step = getattr(account, "step", None) or getattr(kernel, "qty_step", None)
    minimum = getattr(account, "min_quantity", None)
    return {"priceTickSize": str(tick), "pointValue": float(multiplier),
            **({"quantityStep": str(step)} if step is not None else {}),
            **({"minContract": str(minimum)} if minimum is not None else {})}


def bind_observed_metadata(actual, supplied):
    """Reject conflicts instead of reinterpreting earlier bars with newer rules."""
    for key, value in actual.items():
        if key in supplied and Fraction(str(supplied[key])) != Fraction(str(value)):
            raise BacktestError("DATA_SNAPSHOT_MISMATCH", f"observed account {key} differs from frozen Pine metadata")
    from .native_contracts import PineChartMetadata
    try:
        return PineChartMetadata.model_validate({**supplied, **actual}).model_dump(exclude_none=True)
    except ValueError as exc:
        raise BacktestError("FIDELITY_UNSUPPORTED", "observed contract exceeds the Pine metadata transport") from exc


def catalog_chart_metadata(row, explicit=None):
    """Translate actual catalog units without inferring them from symbol names."""
    row = row or {}
    metadata = {}
    if row.get("priceTickSize"):
        metadata["priceTickSize"] = str(row["priceTickSize"])
    currency = row.get("quoteAsset") or row.get("currency")
    if isinstance(currency, str) and re.fullmatch(r"[A-Z]{1,20}", currency):
        metadata["currency"] = currency
    if row.get("contractMultiplier") not in (None, ""):
        try:
            if isinstance(row["contractMultiplier"], bool):
                raise ValueError("boolean multiplier")
            number = Decimal(str(row["contractMultiplier"]))
            multiplier = float(number)
        except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("PINE_HOST_METADATA_INVALID: invalid catalog multiplier") from exc
        if not number.is_finite() or number <= 0 or not multiplier > 0 or Decimal(str(multiplier)) != number:
            raise ValueError("PINE_HOST_METADATA_UNSUPPORTED: catalog multiplier cannot preserve its value")
        metadata["pointValue"] = multiplier
    for source, target in (("quantityStep", "quantityStep"), ("minQuantity", "minContract")):
        if row.get(source) not in (None, ""):
            metadata[target] = row[source]
    if explicit is not None:
        if not isinstance(explicit, dict):
            raise ValueError("PINE_HOST_METADATA_INVALID: chart metadata must be an object")
        metadata.update(explicit)
    if not metadata.get("priceTickSize"):
        return None
    from .native_contracts import PineChartMetadata
    return PineChartMetadata.model_validate(metadata).model_dump(exclude_none=True)


def catalog_contract_profile(row):
    row = row or {}
    profile = {}
    if row.get("contractValueModel"):
        if not isinstance(row["contractValueModel"], str) or row["contractValueModel"] not in {"linear", "inverse", "unknown"}:
            raise ValueError("PINE_HOST_METADATA_INVALID: invalid catalog contract model")
        profile["model"] = row["contractValueModel"]
    if row.get("quantityRuleModel"):
        if not isinstance(row["quantityRuleModel"], str) or row["quantityRuleModel"] not in {"fixed_step", "significant_digits", "unknown"}:
            raise ValueError("PINE_HOST_METADATA_INVALID: invalid catalog quantity model")
        profile["quantityModel"] = row["quantityRuleModel"]
    step, origin = row.get("quantityStep"), row.get("quantityOrigin")
    if step not in (None, "") and origin not in (None, ""):
        # Rational comparison avoids Decimal context rounding for tiny steps.
        try:
            quantity_decimal(str(step), "quantityStep")
            number = Decimal(str(origin))
            if not number.is_finite() or number < 0:
                raise ValueError("invalid quantity origin")
            if number:
                quantity_decimal(str(origin), "quantityOrigin")
            offset = (Fraction(str(origin)) if number else Fraction(0)) % Fraction(str(step))
        except (InvalidOperation, ValueError, ZeroDivisionError) as exc:
            raise ValueError("PINE_HOST_METADATA_INVALID: catalog quantity grid is invalid") from exc
        if offset:
            profile["quantityModel"] = "offset_step"
    return profile
