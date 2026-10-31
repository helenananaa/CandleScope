"""Validate evaluated Pine annotations and select actual Host fill-leg values."""
from copy import deepcopy

from app.backtest.errors import BacktestError

CONTRACT = "candlescope.pine-order-metadata/1"
COMMON = {"comment", "alert_message", "disable_alert"}
EXIT = COMMON | {f"{prefix}_{leg}" for prefix in ("comment", "alert") for leg in ("profit", "loss", "trailing")}
ROLES = {"entry", "order", "close", "profit", "loss", "trailing"}


def declaration(intent, contract=None):
    if "metadata" not in intent:
        return None
    if contract != CONTRACT:
        raise BacktestError("EXTERNAL_UNSUPPORTED", "Pine order metadata requires a negotiated Host contract")
    value = intent["metadata"]
    allowed = EXIT if intent.get("action") == "exit" else COMMON
    if (intent.get("action") not in {"entry", "order", "close", "close_all", "exit"}
        or not isinstance(value, dict) or not set(value) <= allowed
        or type(value.get("disable_alert")) is not bool
        or any(not isinstance(text, str) for key, text in value.items() if key != "disable_alert")
    ):
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine order metadata")
    return deepcopy(value)


def fill_annotation(value, role):
    if value is None:
        return {}
    if role not in ROLES:
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine fill annotation role")
    comment = value.get(f"comment_{role}", value.get("comment")) if role in {"profit", "loss", "trailing"} else value.get("comment")
    message = value.get(f"alert_{role}", value.get("alert_message", "")) if role in {"profit", "loss", "trailing"} else value.get("alert_message", "")
    return {"pine_metadata": {"contract": CONTRACT, "fill_role": role,
        **({"comment": comment} if comment is not None else {}),
        "alert_message": message, "alert_enabled": not value["disable_alert"]}}


def report_fields(annotation):
    value = annotation.get("pine_metadata")
    if value is None:
        return {}
    return {"pine_fill_role": value["fill_role"],
        **({"pine_comment": value["comment"]} if "comment" in value else {}),
        "pine_alert_message": value["alert_message"], "pine_alert_enabled": value["alert_enabled"]}


def enrich_fills(fills, allocations):
    if not any(row.get("annotation") for row in allocations):
        return fills
    result = []
    for fill, allocation in zip(fills, allocations, strict=True):
        if (fill["order_id"], fill["sequence"]) != (allocation["order_id"], allocation["sequence"]):
            raise BacktestError("EXTERNAL_ACCOUNT_MISMATCH", "Pine annotation allocation differs from financial fill")
        result.append({**fill, **report_fields(allocation.get("annotation", {}))})
    return result


def enrich_orders(orders, annotations):
    if not annotations:
        return orders
    result = []
    for order in orders:
        value = annotations.get(order["order_id"])
        fields = report_fields(fill_annotation(value["metadata"], value["role"])) if value else {}
        fields.pop("pine_fill_role", None)  # A pending/cancelled order is not a fill.
        result.append({**order, **fields})
    return result
