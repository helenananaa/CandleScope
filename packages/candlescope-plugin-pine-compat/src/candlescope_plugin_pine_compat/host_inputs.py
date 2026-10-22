"""Explicit host clocks and price grids, shared by Pine execution paths."""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Any
import re
import math

from .currency_inputs import currency_rates
from .contract_metadata import quantity_decimal, require_contract_capability


def chart_metadata(value: Any) -> dict[str, int | float | str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("PINE_HOST_METADATA_INVALID: chart metadata must be an object")
    unknown = set(value) - {"priceTickSize", "quantityPrecision", "pointValue", "currency", "quantityStep", "minContract"}
    if unknown:
        raise ValueError(
            "PINE_HOST_METADATA_INVALID: unknown fields: " + ", ".join(sorted(unknown))
        )
    tick = value.get("priceTickSize")
    if tick is None:
        raise ValueError("PINE_HOST_METADATA_INVALID: priceTickSize is required")
    if isinstance(tick, bool):
        raise TypeError("PINE_HOST_METADATA_INVALID: priceTickSize must be positive")
    try:
        grid = Fraction(str(tick))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("PINE_HOST_METADATA_INVALID: priceTickSize must be positive") from exc
    if grid <= 0 or max(grid.numerator, grid.denominator) > 4_294_967_295:
        raise ValueError("PINE_HOST_METADATA_INVALID: priceTickSize exceeds the runtime grid")
    result = {"minMove": grid.numerator, "priceScale": grid.denominator}
    if value.get("currency") is not None:
        currency = value["currency"]
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{1,20}", currency):
            raise ValueError("PINE_HOST_METADATA_INVALID: currency must be an uppercase code")
        result["currency"] = currency
    if value.get("quantityPrecision") is not None:
        precision = value["quantityPrecision"]
        if type(precision) is not int or not 0 <= precision <= 9:
            raise ValueError(
                "PINE_HOST_METADATA_INVALID: quantityPrecision must be an integer in 0..9"
            )
        result["quantityPrecision"] = precision
    if value.get("pointValue") is not None:
        point = value["pointValue"]
        try:
            valid = type(point) in (int, float) and math.isfinite(point) and point > 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("PINE_HOST_METADATA_INVALID: pointValue must be positive and finite")
        result["pointValue"] = point
    for key in ("quantityStep", "minContract"):
        if value.get(key) is not None:
            places = quantity_decimal(value[key], key)
            if key == "quantityStep" and value.get("quantityPrecision") is not None and places > value["quantityPrecision"]:
                raise ValueError("PINE_HOST_METADATA_INVALID: quantityStep exceeds quantityPrecision")
            result[key] = value[key]
    return result


def execution_times(bars, value=None, *, default=None):
    """Milliseconds, with one explicit timestamp per evaluated chart bar."""
    times = value if value is not None else default
    if times is None:
        return None
    if type(times) is int:
        times = [times] * len(bars)
    if not isinstance(times, (list, tuple)) or len(times) != len(bars):
        raise ValueError("PINE_HOST_CLOCK_INVALID: one execution timestamp is required per bar")
    if any(type(item) is not int or item < 0 or item > 9_007_199_254_740_991 for item in times):
        raise ValueError(
            "PINE_HOST_CLOCK_INVALID: execution timestamps must be nonnegative integer milliseconds"
        )
    return list(times)


def native_request_bars(request, supplied):
    """Keep the exact supplied grid in native/replay run identities."""
    grid = chart_metadata(request.get("context", {}).get("metadata"))
    if grid is not None:
        supplied["$chart"] = grid
    symbols = requested_metadata(request)
    require_contract_capability(grid, *symbols.values())
    if symbols:
        import pine_compat
        if getattr(pine_compat, "SYMBOL_METADATA_SCHEMA_VERSION", 0) != 1:
            raise ValueError("PINE_HOST_METADATA_UNAVAILABLE: install the runtime with requested-symbol metadata support")
        supplied["$symbolMetadata"] = symbols
    rates = currency_rates(request.get("currency_rates"))
    if rates is not None:
        supplied["$currencyRates"] = rates
    return supplied


def requested_metadata(request):
    symbols = {}
    for context in request.get("contexts", []):
        metadata = chart_metadata(context.get("metadata"))
        if metadata is None:
            continue
        symbol = context["symbol"]
        if symbol in symbols and symbols[symbol] != metadata:
            raise ValueError("PINE_HOST_METADATA_INVALID: conflicting metadata for requested symbol " + symbol)
        symbols[symbol] = metadata
    return symbols


def indicator_request_bars(analysis, options, chart_symbol, supplied):
    metadata = options.get("pineRequestSymbolMetadata", {})
    if not isinstance(metadata, Mapping) or len(metadata) > 16:
        raise ValueError("PINE_HOST_METADATA_INVALID: requested metadata must map at most 16 symbols")
    contexts = [{"symbol": key.rsplit(":", 1)[0], "metadata": metadata.get(key.rsplit(":", 1)[0]), "contract_profile": options.get("pineRequestSymbolProfiles", {}).get(key.rsplit(":", 1)[0])}
        for key in supplied]
    request = {"context": {"symbol": chart_symbol, "metadata": options.get("pineChartMetadata"), "contract_profile": options.get("pineContractProfile")}, "contexts": contexts}
    require_price_grid(analysis, request)
    require_quote_currency(analysis, {}, request)
    return native_request_bars(request, supplied)


def require_price_grid(analysis, request):
    profile = request.get("context", {}).get("contract_profile") or {}
    if analysis.get("scriptMode") == "strategy":
        if profile.get("model") in {"inverse", "unknown"}:
            raise ValueError("PINE_HOST_METADATA_UNSUPPORTED: this strategy requires a known linear contract")
        if profile.get("quantityModel") in {"significant_digits", "offset_step", "unknown"}:
            raise ValueError("PINE_HOST_METADATA_UNSUPPORTED: this strategy requires a fixed quantity grid with zero-aligned steps")
        if profile.get("model") == "linear" and (request.get("context", {}).get("metadata") or {}).get("pointValue") is None:
            raise ValueError("PINE_HOST_METADATA_REQUIRED: the catalog's actual linear multiplier is missing")
        if profile.get("model") == "linear" and not any((request.get("context", {}).get("metadata") or {}).get(key) is not None for key in ("quantityStep", "quantityPrecision")):
            raise ValueError("PINE_HOST_METADATA_REQUIRED: the catalog's actual quantity grid is missing")
    features = {
        item.get("feature") for item in analysis.get("compatibility", {}).get("supported", [])
    }
    if (
        features & {"syminfo.mintick", "syminfo.minmove", "syminfo.pricescale", "math.round_to_mintick", "format.mintick"}
        and not request.get("context", {}).get("metadata")
        and request.get("host_settings", {}).get("price_tick") is None
    ):
        raise ValueError(
            "PINE_HOST_METADATA_REQUIRED: freeze the chart's actual priceTickSize before using syminfo price-grid values"
        )
    needs_grid = features & {"syminfo.mintick", "syminfo.minmove", "syminfo.pricescale", "math.round_to_mintick", "format.mintick"}
    needs_quantity = "syminfo.mincontract" in features
    needs_point = "syminfo.pointvalue" in features
    if needs_point and profile and (request.get("context", {}).get("metadata") or {}).get("pointValue") is None:
        raise ValueError("PINE_HOST_METADATA_REQUIRED: the chart's actual point value and price grid are missing")
    def has_quantity(metadata):
        return any(metadata.get(key) is not None for key in ("minContract", "quantityStep", "quantityPrecision"))

    if needs_quantity and not has_quantity(request.get("context", {}).get("metadata") or {}):
        raise ValueError("PINE_HOST_METADATA_REQUIRED: freeze the chart's actual minimum contract, quantity step or legacy precision before using syminfo.mincontract")
    for context in request.get("contexts", []):
        if context["symbol"] == request.get("context", {}).get("symbol"):
            continue
        metadata = context.get("metadata") or {}
        if needs_point and context.get("contract_profile") and metadata.get("pointValue") is None:
            raise ValueError("PINE_HOST_METADATA_REQUIRED: requested point value and price grid are missing for " + context["symbol"])
        if (needs_grid and not metadata.get("priceTickSize")) or (needs_quantity and not has_quantity(metadata)):
            raise ValueError("PINE_HOST_METADATA_REQUIRED: freeze requested symbol metadata for " + context["symbol"])


def require_quote_currency(analysis, requirements, request, *, external=False):
    features = {
        item.get("feature") for item in analysis.get("compatibility", {}).get("supported", [])
    }
    declared = (requirements.get("account") or {}).get("declaredCurrency")
    quote = (request.get("context", {}).get("metadata") or {}).get("currency")
    if (declared or features & {"syminfo.currency", "strategy.account_currency"}) and not quote:
        raise ValueError("PINE_HOST_METADATA_REQUIRED: supply the chart's actual quote currency before using currency-dependent accounting")
    if "syminfo.currency" in features:
        for context in request.get("contexts", []):
            if context["symbol"] != request.get("context", {}).get("symbol") and not (context.get("metadata") or {}).get("currency"):
                raise ValueError("PINE_HOST_METADATA_REQUIRED: supply requested quote currency for " + context["symbol"])
    if external and declared and declared != quote:
        raise ValueError("EXTERNAL_UNSUPPORTED: the CandleScope ledger does not convert account currencies; use native execution with explicit effective rates")
