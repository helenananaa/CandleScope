"""Neutral exchange-to-catalog contract rules. """
from decimal import Decimal, InvalidOperation


def decimal_rule(value, *, zero=False):
    if isinstance(value, bool) or value in (None, ""):
        return ""
    text = str(value).strip()
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return ""
    if not number.is_finite() or number < 0 or (number == 0 and not zero):
        return ""
    return text


def fixed_quantity_rules(step, minimum, *, origin="0"):
    step = decimal_rule(step)
    return dict(quantity_step=step, min_quantity=decimal_rule(minimum),
                quantity_origin=decimal_rule(origin, zero=True) if step else "",
                quantity_rule_model="fixed_step" if step else "unknown")


def binance_contract_rules(item):
    lot = next((row for row in item.get("filters", []) if row.get("filterType") == "LOT_SIZE"), {})
    # Both the native spot and USD-M endpoints quote quantity in base units.
    return dict(contract_multiplier="1", contract_value_model="linear",
                **fixed_quantity_rules(lot.get("stepSize"), lot.get("minQty"),
                                       origin=lot.get("minQty", "0")))


def okx_contract_rules(item, *, spot):
    model = "linear" if spot else str(item.get("ctType") or "unknown").lower()
    if model not in {"linear", "inverse"}:
        model = "unknown"
    return dict(contract_value_model=model,
                contract_multiplier="1" if spot else decimal_rule(item.get("ctVal")),
                price_tick_size=decimal_rule(item.get("tickSz")),
                **fixed_quantity_rules(item.get("lotSz"), item.get("minSz")))


def precision_increment(mode, value, *, tick_mode, decimal_mode):
    if mode == tick_mode:
        return decimal_rule(value)
    if mode != decimal_mode or isinstance(value, bool) or value is None:
        return ""
    try:
        places = int(value)
        if Decimal(str(value)) != places or abs(places) > 100:
            return ""
        return format(Decimal(1).scaleb(-places), "f")
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return ""


def ccxt_contract_rules(exchange, market, *, tick_mode, decimal_mode, significant_mode):
    mode = getattr(exchange, "precisionMode", None)
    step = precision_increment(mode, (market.get("precision") or {}).get("amount"),
                               tick_mode=tick_mode, decimal_mode=decimal_mode)
    quantity = fixed_quantity_rules(step, ((market.get("limits") or {}).get("amount") or {}).get("min"))
    if mode == significant_mode:
        quantity["quantity_rule_model"] = "significant_digits"
    spot = market.get("spot") is True
    model = "inverse" if market.get("inverse") is True else "linear" if spot or market.get("linear") is True else "unknown"
    return dict(contract_value_model=model,
                contract_multiplier="1" if spot else decimal_rule(market.get("contractSize")),
                **quantity)
