"""Order rules shared by training coordinators."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import cast

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_sha256
from app.replay.models import (
    normalize_decimal_string,
)

from . import service_validation as service_validation_ops
from .account import isolated_margin_key, round_to_step
from .errors import TrainingRunError
from .models import (
    AccountDataMode,
)


def _position_is_open(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("position_mode") == "HEDGE":
        return any(
            isinstance(value.get(leg), Mapping)
            and value[leg].get("quantity") not in {None, "0", 0}
            for leg in ("long", "short")
        )
    return value.get("quantity") not in {None, "0", 0}


def _position_leg(
    value: object,
    *,
    position_side: object = None,
) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("position_mode") != "HEDGE":
        return cast(Mapping[str, object], value)
    if position_side not in {"LONG", "SHORT"}:
        return None
    leg = value.get(str(position_side).lower())
    return cast(Mapping[str, object], leg) if isinstance(leg, Mapping) else None


def _position_mark(value: object, *, position_side: object = None) -> object:
    leg = _position_leg(value, position_side=position_side)
    if leg is not None and leg.get("mark_price") is not None:
        return leg.get("mark_price")
    if isinstance(value, Mapping) and value.get("position_mode") == "HEDGE":
        for name in ("long", "short"):
            candidate = value.get(name)
            if (
                isinstance(candidate, Mapping)
                and candidate.get("mark_price") is not None
            ):
                return candidate.get("mark_price")
    return None


def _position_gross_notional(value: object) -> Decimal:
    if not isinstance(value, Mapping):
        return Decimal(0)
    if value.get("position_mode") != "HEDGE":
        return Decimal(str(value.get("notional", "0")))
    return sum(
        (
            Decimal(str(leg.get("notional", "0")))
            for name in ("long", "short")
            if isinstance((leg := value.get(name)), Mapping)
        ),
        Decimal(0),
    )


def _portfolio_risk_position(
    portfolio: Mapping[str, object],
    *,
    track_id: str,
    position_side: object,
) -> Mapping[str, object] | None:
    positions = portfolio.get("positions")
    if not isinstance(positions, list):
        return None
    item = next(
        (
            candidate
            for candidate in positions
            if isinstance(candidate, Mapping)
            and candidate.get("track_id") == track_id
            and candidate.get("position_side") == position_side
        ),
        None,
    )
    return cast(Mapping[str, object], item) if isinstance(item, Mapping) else None


def _hedge_leg_leverage(
    portfolio: Mapping[str, object],
    *,
    track_id: str,
    position_side: object,
) -> Decimal | None:
    if position_side not in {"LONG", "SHORT"}:
        return None
    position = _portfolio_risk_position(
        portfolio,
        track_id=track_id,
        position_side=position_side,
    )
    if position is not None and position.get("leverage") is not None:
        return Decimal(str(position["leverage"]))
    hedge_state = portfolio.get("hedge_state")
    legs = (
        hedge_state.get("position_legs") if isinstance(hedge_state, Mapping) else None
    )
    if not isinstance(legs, list):
        return None
    leg = next(
        (
            candidate
            for candidate in legs
            if isinstance(candidate, Mapping)
            and candidate.get("track_id") == track_id
            and candidate.get("position_side") == position_side
        ),
        None,
    )
    if not isinstance(leg, Mapping) or leg.get("leverage") is None:
        return None
    return Decimal(str(leg["leverage"]))


def requires_barrier_account_audit(binding: Mapping[str, object]) -> bool:
    return binding.get("account_data_mode") == AccountDataMode.HISTORICAL_EXACT.value


def public_hedge_input_audit(
    audit: Mapping[str, object],
) -> dict[str, object]:
    differences = audit.get("differences")
    if not isinstance(differences, list):
        raise TypeError("internal HEDGE input audit differences are invalid")
    snapshot = audit.get("snapshot")
    if snapshot is not None and not isinstance(snapshot, Mapping):
        raise TypeError("internal HEDGE input audit snapshot is invalid")
    return {
        "schema_version": "replay.hedge-input-audit-summary.v1",
        "status": str(audit.get("status")),
        "proof_hash": audit.get("proof_hash"),
        "difference_count": len(differences),
        "difference_hashes": [
            canonical_sha256(difference) for difference in differences
        ],
        "snapshot_hash": (None if snapshot is None else canonical_sha256(snapshot)),
    }


def planned_entry_reference(
    *,
    payload: Mapping[str, object],
    selected_track: Mapping[str, object],
) -> object:
    if payload.get("order_type") == "LIMIT":
        return payload.get("limit_price")
    position = selected_track.get("position")
    mark = _position_mark(position, position_side=payload.get("position_side"))
    if mark is not None:
        return mark
    return selected_track.get("public_price")


def active_instrument_rule(
    portfolio: Mapping[str, object],
    *,
    track_id: str,
) -> Mapping[str, object]:
    rules = portfolio.get("instrument_rules")
    if not isinstance(rules, list):
        raise TrainingRunError(
            "TRADE_PLAN_RULE_UNAVAILABLE",
            "trade-plan sizing requires an active instrument rule",
            status_code=409,
        )
    active = next(
        (
            item
            for item in rules
            if isinstance(item, Mapping)
            and item.get("track_id") == track_id
            and isinstance(item.get("rule"), Mapping)
        ),
        None,
    )
    if not isinstance(active, Mapping) or not isinstance(active.get("rule"), Mapping):
        raise TrainingRunError(
            "TRADE_PLAN_RULE_UNAVAILABLE",
            "trade-plan sizing requires an active instrument rule",
            status_code=409,
        )
    return cast(Mapping[str, object], active["rule"])


def build_trade_plan_snapshot(
    *,
    draft: Mapping[str, object],
    payload: Mapping[str, object],
    selected_track: Mapping[str, object],
    portfolio: object,
    entry_price: object,
) -> dict[str, object]:
    expected = {
        "sizing_mode",
        "risk_amount",
        "risk_percent",
        "invalidation_price",
        "target_price",
        "reason",
    }
    if set(draft) != expected:
        raise TrainingRunError(
            "TRADE_PLAN_INVALID",
            "trade-plan fields do not match the contract",
            status_code=422,
            details={
                "missing": sorted(expected - set(draft)),
                "unknown": sorted(set(draft) - expected),
            },
        )
    if payload.get("reduce_only") is not False or payload.get("order_type") not in {
        "MARKET",
        "LIMIT",
    }:
        raise TrainingRunError(
            "TRADE_PLAN_INVALID",
            "trade plans require a non-reduce-only market or limit order",
            status_code=422,
        )
    side = payload.get("side")
    if side not in {"BUY", "SELL"}:
        raise TrainingRunError(
            "TRADE_PLAN_INVALID",
            "trade-plan side is invalid",
            status_code=422,
        )
    if not isinstance(portfolio, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "run portfolio projection is invalid",
            status_code=503,
        )

    def decimal_value(value: object, field_name: str) -> Decimal:
        try:
            normalized = normalize_decimal_string(value, field_name=field_name)
            parsed = Decimal(normalized)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise TrainingRunError(
                "TRADE_PLAN_INVALID",
                f"{field_name} is invalid",
                status_code=422,
            ) from exc
        if parsed <= 0:
            raise TrainingRunError(
                "TRADE_PLAN_INVALID",
                f"{field_name} must be positive",
                status_code=422,
            )
        return parsed

    def decimal_text(value: Decimal, field_name: str) -> str:
        return normalize_decimal_string(format(value, "f"), field_name=field_name)

    entry = decimal_value(entry_price, "trade-plan entry price")
    invalidation = decimal_value(
        draft["invalidation_price"],
        "trade-plan invalidation price",
    )
    target = decimal_value(draft["target_price"], "trade-plan target price")
    if side == "BUY":
        price_sides_valid = invalidation < entry < target
    else:
        price_sides_valid = target < entry < invalidation
    if not price_sides_valid:
        raise TrainingRunError(
            "TRADE_PLAN_PRICE_SIDE_INVALID",
            "invalidation and target prices must bracket entry in the order direction",
            status_code=422,
            details={"side": side, "entry_price": decimal_text(entry, "entry")},
        )
    reason = draft["reason"]
    if not isinstance(reason, str):
        raise TrainingRunError(
            "TRADE_PLAN_INVALID",
            "trade-plan reason must be a string",
            status_code=422,
        )
    normalized_reason = reason.strip()
    if not normalized_reason or len(normalized_reason) > 500:
        raise TrainingRunError(
            "TRADE_PLAN_INVALID",
            "trade-plan reason must contain 1-500 characters",
            status_code=422,
        )
    equity = decimal_value(portfolio.get("equity"), "account equity")
    sizing_mode = draft["sizing_mode"]
    risk_percent: str | None
    if sizing_mode == "RISK_AMOUNT":
        if draft.get("risk_percent") is not None:
            raise TrainingRunError(
                "TRADE_PLAN_INVALID",
                "fixed-risk sizing must not include risk_percent",
                status_code=422,
            )
        risk_budget = decimal_value(draft.get("risk_amount"), "risk amount")
        risk_percent = None
    elif sizing_mode == "ACCOUNT_RISK_PERCENT":
        if draft.get("risk_amount") is not None:
            raise TrainingRunError(
                "TRADE_PLAN_INVALID",
                "percentage-risk sizing must not include risk_amount",
                status_code=422,
            )
        percent = decimal_value(draft.get("risk_percent"), "risk percent")
        if percent > 100:
            raise TrainingRunError(
                "TRADE_PLAN_INVALID",
                "risk percent must not exceed 100",
                status_code=422,
            )
        risk_percent = decimal_text(percent, "risk percent")
        risk_budget = equity * percent / Decimal(100)
    else:
        raise TrainingRunError(
            "TRADE_PLAN_INVALID",
            "trade-plan sizing mode is unsupported",
            status_code=422,
        )
    if risk_budget > equity:
        raise TrainingRunError(
            "TRADE_PLAN_RISK_EXCEEDS_EQUITY",
            "planned maximum loss exceeds current account equity",
            status_code=422,
            details={
                "risk_amount": decimal_text(risk_budget, "risk amount"),
                "account_equity": decimal_text(equity, "account equity"),
            },
        )
    track_id = str(selected_track["track_id"])
    rule = active_instrument_rule(portfolio, track_id=track_id)
    contract_size = decimal_value(rule.get("contract_size"), "contract size")
    quantity_step = decimal_value(rule.get("quantity_step"), "quantity step")
    minimum_quantity = decimal_value(rule.get("min_quantity"), "minimum quantity")
    maximum_quantity = decimal_value(rule.get("max_quantity"), "maximum quantity")
    risk_per_unit = abs(entry - invalidation) * contract_size
    raw_quantity = risk_budget / risk_per_unit
    quantity = (raw_quantity / quantity_step).to_integral_value(
        rounding=ROUND_FLOOR
    ) * quantity_step
    quantity = min(quantity, maximum_quantity)
    if quantity < minimum_quantity or quantity <= 0:
        raise TrainingRunError(
            "TRADE_PLAN_SIZE_BELOW_MINIMUM",
            "risk budget is too small for the active minimum quantity",
            status_code=422,
            details={
                "minimum_quantity": decimal_text(minimum_quantity, "minimum quantity"),
                "quantity_step": decimal_text(quantity_step, "quantity step"),
            },
        )
    position = _position_leg(
        selected_track.get("position"),
        position_side=payload.get("position_side"),
    )
    if position is not None:
        try:
            position_quantity = Decimal(str(position.get("quantity", "0")))
        except InvalidOperation as exc:
            raise TrainingRunError(
                "TRAINING_RUN_STORAGE_DEGRADED",
                "selected position quantity is invalid",
                status_code=503,
            ) from exc
        if position_quantity != 0 and (position_quantity > 0) != (side == "BUY"):
            raise TrainingRunError(
                "TRADE_PLAN_REVERSE_REQUIRES_EXPLICIT_ACTION",
                "a trade plan cannot implicitly reduce or reverse the current position",
                status_code=409,
            )
    reward_risk_ratio = abs(target - entry) * contract_size / risk_per_unit
    return {
        "schema_version": "replay.trade-plan.snapshot.v1",
        "track_id": track_id,
        "client_order_id": str(payload["client_order_id"]),
        "side": side,
        "order_type": str(payload["order_type"]),
        "sizing_mode": sizing_mode,
        "risk_amount": decimal_text(risk_budget, "risk amount"),
        "risk_percent": risk_percent,
        "account_equity": decimal_text(equity, "account equity"),
        "entry_price": decimal_text(entry, "entry price"),
        "invalidation_price": decimal_text(invalidation, "invalidation price"),
        "target_price": decimal_text(target, "target price"),
        "risk_per_unit": decimal_text(risk_per_unit, "risk per unit"),
        "reward_risk_ratio": decimal_text(reward_risk_ratio, "reward risk ratio"),
        "quantity": decimal_text(quantity, "planned quantity"),
        "reason": normalized_reason,
    }


def assert_exact_account_order_filters(
    *,
    payload: Mapping[str, object],
    selected_track: Mapping[str, object],
    portfolio: object,
    replace_position: bool = False,
) -> None:
    if not isinstance(portfolio, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "run portfolio projection is invalid",
            status_code=503,
        )
    history = portfolio.get("account_history")
    if not isinstance(history, Mapping) or history.get("mode") != "HISTORICAL_EXACT":
        return
    if history.get("status") != "ACTIVE":
        raise TrainingRunError(
            "ACCOUNT_HISTORY_ARCHIVE_DEGRADED",
            "exact account inputs are not active",
            status_code=409,
            details={"fallback_applied": False},
        )
    raw_rules = portfolio.get("instrument_rules")
    if not isinstance(raw_rules, list):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "exact instrument-rule projection is invalid",
            status_code=503,
        )
    selected_id = str(selected_track["track_id"])
    active = next(
        (
            item
            for item in raw_rules
            if isinstance(item, Mapping) and item.get("track_id") == selected_id
        ),
        None,
    )
    if not isinstance(active, Mapping) or not isinstance(active.get("rule"), Mapping):
        raise TrainingRunError(
            "ACCOUNT_HISTORY_RULE_MISSING",
            "selected exact account track has no active historical rule",
            status_code=409,
            details={"fallback_applied": False},
        )
    rule = active["rule"]
    assert isinstance(rule, Mapping)
    try:
        quantity = Decimal(str(payload["quantity"]))
        step = Decimal(str(rule["quantity_step"]))
        minimum = Decimal(str(rule["min_quantity"]))
        maximum = Decimal(str(rule["max_quantity"]))
        if quantity < minimum or quantity > maximum or quantity % step != 0:
            raise TrainingRunError(
                "ACCOUNT_HISTORY_QUANTITY_FILTER",
                "order quantity violates the active historical exchange rule",
                status_code=422,
                details={
                    "rule_revision": active.get("revision"),
                    "min_quantity": str(minimum),
                    "max_quantity": str(maximum),
                    "quantity_step": str(step),
                },
            )
        for field_name in ("limit_price", "stop_price"):
            raw = payload.get(field_name)
            if raw is None:
                continue
            price = Decimal(str(raw))
            tick = Decimal(str(rule["price_tick"]))
            if price <= 0 or price % tick != 0:
                raise TrainingRunError(
                    "ACCOUNT_HISTORY_PRICE_FILTER",
                    f"{field_name} violates the active historical price tick",
                    status_code=422,
                    details={
                        "rule_revision": active.get("revision"),
                        "price_tick": str(tick),
                    },
                )
        position = selected_track.get("position")
        if not isinstance(position, Mapping):
            raise TypeError("selected exact position is invalid")
        reference = (
            payload.get("limit_price")
            or payload.get("stop_price")
            or _position_mark(
                position,
                position_side=payload.get("position_side"),
            )
        )
        price = Decimal(str(reference))
        contract_size = Decimal(str(rule["contract_size"]))
        notional = quantity * price * contract_size
        if payload.get("reduce_only") is not True:
            minimum_notional = Decimal(str(rule["min_notional"]))
            maximum_notional = Decimal(str(rule["max_notional"]))
            existing_notional = (
                Decimal(0) if replace_position else _position_gross_notional(position)
            )
            if (
                notional < minimum_notional
                or notional > maximum_notional
                or existing_notional + notional > maximum_notional
            ):
                raise TrainingRunError(
                    "ACCOUNT_HISTORY_NOTIONAL_FILTER",
                    "order notional violates the active historical exchange rule",
                    status_code=422,
                    details={
                        "rule_revision": active.get("revision"),
                        "min_notional": str(minimum_notional),
                        "max_notional": str(maximum_notional),
                        "order_notional": str(notional),
                    },
                )
    except TrainingRunError:
        raise
    except (InvalidOperation, KeyError, TypeError, ZeroDivisionError) as exc:
        raise TrainingRunError(
            "ACCOUNT_HISTORY_RULE_INVALID",
            "active historical order filters are invalid",
            status_code=409,
            details={"fallback_applied": False},
        ) from exc


def assert_exact_account_capacity_context(
    *,
    payload: Mapping[str, object],
    selected_track: Mapping[str, object],
    portfolio: object,
) -> None:
    """Validate quantity-independent historical price rules."""

    if not isinstance(portfolio, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "run portfolio projection is invalid",
            status_code=503,
        )
    history = portfolio.get("account_history")
    if not isinstance(history, Mapping) or history.get("mode") != "HISTORICAL_EXACT":
        return
    if history.get("status") != "ACTIVE":
        raise TrainingRunError(
            "ACCOUNT_HISTORY_ARCHIVE_DEGRADED",
            "exact account inputs are not active",
            status_code=409,
            details={"fallback_applied": False},
        )
    rule = active_instrument_rule(
        portfolio,
        track_id=str(selected_track["track_id"]),
    )
    try:
        tick = Decimal(str(rule["price_tick"]))
        for field_name in ("limit_price", "stop_price"):
            raw = payload.get(field_name)
            if raw is None:
                continue
            price = Decimal(str(raw))
            if price <= 0 or price % tick != 0:
                raise TrainingRunError(
                    "ACCOUNT_HISTORY_PRICE_FILTER",
                    f"{field_name} violates the active historical price tick",
                    status_code=422,
                    details={"price_tick": str(tick)},
                )
    except TrainingRunError:
        raise
    except (InvalidOperation, KeyError, TypeError) as exc:
        raise TrainingRunError(
            "ACCOUNT_HISTORY_RULE_INVALID",
            "active historical capacity filters are invalid",
            status_code=409,
            details={"fallback_applied": False},
        ) from exc


def shared_order_capacity_quantity(
    *,
    adapter_max_quantity: object,
    reference_price: object,
    payload: Mapping[str, object],
    selected_track: Mapping[str, object],
    portfolio: object,
    binding: Mapping[str, object],
) -> str:
    """Clamp adapter capacity to shared-account and historical-rule limits."""

    if not isinstance(portfolio, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "run portfolio projection is invalid",
            status_code=503,
        )
    config = binding.get("adapter_config")
    if not isinstance(config, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training adapter config is invalid",
            status_code=503,
        )
    try:
        maximum = Decimal(str(adapter_max_quantity))
        price = Decimal(str(reference_price))
        if payload.get("reduce_only") is True:
            return decimal_to_string(maximum, field_name="max_quantity")
        raw_leverage = payload.get("leverage")
        leverage = Decimal(str(raw_leverage or config["max_leverage"]))
        track_id = str(selected_track["track_id"])
        if binding.get("position_mode") == "HEDGE":
            active_leg_leverage = _hedge_leg_leverage(
                portfolio,
                track_id=track_id,
                position_side=payload.get("position_side"),
            )
            if raw_leverage is None and active_leg_leverage is not None:
                leverage = active_leg_leverage
            active_position = _portfolio_risk_position(
                portfolio,
                track_id=track_id,
                position_side=payload.get("position_side"),
            )
            if (
                raw_leverage is not None
                and active_position is not None
                and active_leg_leverage is not None
                and leverage != active_leg_leverage
            ):
                raise TrainingRunError(
                    "RISK_LIMIT_EXCEEDED",
                    "opening order leverage differs from the active hedge leg",
                    status_code=409,
                )
        configured_max = Decimal(str(config["max_leverage"]))
        if leverage < 1 or leverage > configured_max:
            raise TrainingRunError(
                "RISK_LIMIT_EXCEEDED",
                "order leverage is outside the session limit",
                status_code=409,
            )
        contract_size = Decimal(1)
        quantity_step: Decimal | None = None
        minimum_quantity = Decimal(0)
        minimum_notional = Decimal(0)
        rules = portfolio.get("instrument_rules")
        active = (
            next(
                (
                    item
                    for item in rules
                    if isinstance(rules, list)
                    and isinstance(item, Mapping)
                    and item.get("track_id") == selected_track.get("track_id")
                    and isinstance(item.get("rule"), Mapping)
                ),
                None,
            )
            if isinstance(rules, list)
            else None
        )
        if isinstance(active, Mapping):
            rule = cast(Mapping[str, object], active["rule"])
            contract_size = Decimal(str(rule.get("contract_size", "1")))
            rule_max_leverage = Decimal(str(rule.get("max_leverage", leverage)))
            if (
                leverage > rule_max_leverage
                and raw_leverage is None
                and binding.get("position_mode") != "HEDGE"
            ):
                leverage = rule_max_leverage
            elif leverage > rule_max_leverage:
                raise TrainingRunError(
                    "RISK_LIMIT_EXCEEDED",
                    "order leverage exceeds the active instrument rule",
                    status_code=409,
                )
            quantity_step = Decimal(str(rule["quantity_step"]))
            minimum_quantity = Decimal(str(rule["min_quantity"]))
            minimum_notional = Decimal(str(rule["min_notional"]))
            maximum = min(maximum, Decimal(str(rule["max_quantity"])))
            position = selected_track.get("position")
            if not isinstance(position, Mapping):
                raise TypeError("selected position projection is invalid")
            remaining_notional = max(
                Decimal(0),
                Decimal(str(rule["max_notional"])) - _position_gross_notional(position),
            )
            maximum = min(maximum, remaining_notional / (price * contract_size))
        if portfolio.get("margin_mode") == "ISOLATED":
            allocations = portfolio.get("isolated_allocations")
            account = selected_track.get("account")
            if not isinstance(allocations, Mapping) or not isinstance(account, Mapping):
                raise TypeError("isolated account projection is invalid")
            position_side = payload.get("position_side")
            allocation_key = isolated_margin_key(
                track_id,
                None if position_side is None else str(position_side),
            )
            allocated = Decimal(str(allocations.get(allocation_key, "0")))
            if binding.get("position_mode") == "HEDGE":
                positions = portfolio.get("positions")
                orders = portfolio.get("orders")
                if not isinstance(positions, list) or not isinstance(orders, list):
                    raise TypeError("HEDGE isolated risk projection is invalid")
                risk_position = next(
                    (
                        item
                        for item in positions
                        if isinstance(item, Mapping)
                        and item.get("track_id") == track_id
                        and item.get("position_side") == position_side
                    ),
                    None,
                )
                in_use = Decimal(
                    str(
                        0
                        if not isinstance(risk_position, Mapping)
                        else risk_position.get("initial_margin", "0")
                    )
                ) + sum(
                    (
                        Decimal(str(order.get("reserved_margin", "0")))
                        for order in orders
                        if isinstance(order, Mapping)
                        and order.get("track_id") == track_id
                        and order.get("position_side") == position_side
                        and order.get("status") in {"OPEN", "PARTIALLY_FILLED"}
                    ),
                    Decimal(0),
                )
            else:
                in_use = Decimal(str(account.get("margin_used", "0"))) + Decimal(
                    str(account.get("reserved_margin", "0"))
                )
            available = allocated - in_use
            if allocated <= 0:
                available = Decimal(0)
        else:
            available = Decimal(str(portfolio["available_equity"]))
        shared_maximum = max(Decimal(0), available) * leverage / (price * contract_size)
        maximum = min(maximum, shared_maximum)
        if quantity_step is not None:
            maximum = (maximum / quantity_step).to_integral_value(
                rounding=ROUND_FLOOR
            ) * quantity_step
        maximum = max(Decimal(0), maximum)
        if (
            maximum < minimum_quantity
            or maximum * price * contract_size < minimum_notional
        ):
            maximum = Decimal(0)
        return decimal_to_string(maximum, field_name="max_quantity")
    except TrainingRunError:
        raise
    except (InvalidOperation, KeyError, TypeError, ZeroDivisionError) as exc:
        raise TrainingRunError(
            "REPLAY_CONTROL_INVALID",
            "order capacity cannot be valued against the shared settlement account",
            status_code=422,
        ) from exc


def assert_shared_settlement_reservation(
    *,
    payload: Mapping[str, object],
    selected_track: Mapping[str, object],
    portfolio: object,
    binding: Mapping[str, object],
    release_selected_margin: bool = False,
    release_order_reservation: Decimal = Decimal(0),
) -> None:
    if payload.get("reduce_only") is True:
        return
    if not isinstance(portfolio, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "run portfolio projection is invalid",
            status_code=503,
        )
    config = binding.get("adapter_config")
    if not isinstance(config, Mapping):
        raise TrainingRunError(
            "TRAINING_RUN_STORAGE_DEGRADED",
            "training adapter config is invalid",
            status_code=503,
        )
    price_value = payload.get("limit_price") or payload.get("stop_price")
    if price_value is None:
        position = selected_track.get("position")
        price_value = _position_mark(
            position,
            position_side=payload.get("position_side"),
        )
        if price_value is None:
            price_value = selected_track.get("public_price")
    try:
        quantity = Decimal(str(payload["quantity"]))
        price = Decimal(str(price_value))
        max_leverage = Decimal(str(config["max_leverage"]))
        leverage = max_leverage
        raw_leverage = payload.get("leverage")
        if raw_leverage is not None:
            leverage = Decimal(str(raw_leverage))
            if leverage < 1 or leverage > max_leverage:
                raise TrainingRunError(
                    "RISK_LIMIT_EXCEEDED",
                    "order leverage must be between 1 and session max_leverage",
                    status_code=409,
                )
        track_id = str(selected_track["track_id"])
        if binding.get("position_mode") == "HEDGE":
            active_leg_leverage = _hedge_leg_leverage(
                portfolio,
                track_id=track_id,
                position_side=payload.get("position_side"),
            )
            if raw_leverage is None and active_leg_leverage is not None:
                leverage = active_leg_leverage
            active_position = _portfolio_risk_position(
                portfolio,
                track_id=track_id,
                position_side=payload.get("position_side"),
            )
            if (
                raw_leverage is not None
                and active_position is not None
                and active_leg_leverage is not None
                and leverage != active_leg_leverage
            ):
                raise TrainingRunError(
                    "RISK_LIMIT_EXCEEDED",
                    "opening order leverage differs from the active hedge leg",
                    status_code=409,
                )
        contract_size = Decimal(1)
        quote_step = Decimal("0.00000001")
        rules = portfolio.get("instrument_rules")
        active = next(
            (
                item
                for item in rules
                if isinstance(rules, list)
                and isinstance(item, Mapping)
                and item.get("track_id") == selected_track.get("track_id")
                and isinstance(item.get("rule"), Mapping)
            ),
            None,
        )
        if isinstance(active, Mapping):
            active_rule = cast(Mapping[str, object], active["rule"])
            contract_size = Decimal(str(active_rule.get("contract_size", "1")))
            quote_step = Decimal(str(active_rule.get("quote_step", quote_step)))
            rule_max_leverage = Decimal(str(active_rule.get("max_leverage", leverage)))
            if (
                leverage > rule_max_leverage
                and raw_leverage is None
                and binding.get("position_mode") != "HEDGE"
            ):
                leverage = rule_max_leverage
            elif leverage > rule_max_leverage:
                raise TrainingRunError(
                    "RISK_LIMIT_EXCEEDED",
                    "order leverage exceeds the active instrument rule",
                    status_code=409,
                )
        history = portfolio.get("account_history")
        if isinstance(history, Mapping) and history.get("mode") == "HISTORICAL_EXACT":
            rules = portfolio.get("instrument_rules")
            if not isinstance(rules, list):
                raise TypeError("exact instrument rules are missing")
            active = next(
                (
                    item
                    for item in rules
                    if isinstance(item, Mapping)
                    and item.get("track_id") == selected_track.get("track_id")
                ),
                None,
            )
            if not isinstance(active, Mapping) or not isinstance(
                active.get("rule"), Mapping
            ):
                raise TypeError("exact active instrument rule is missing")
            exact_rule = active["rule"]
            assert isinstance(exact_rule, Mapping)
            contract_size = Decimal(str(exact_rule["contract_size"]))
            quote_step = Decimal(str(exact_rule["quote_step"]))
            exact_rule_max = Decimal(str(exact_rule["max_leverage"]))
            if (
                leverage > exact_rule_max
                and raw_leverage is None
                and binding.get("position_mode") != "HEDGE"
            ):
                leverage = exact_rule_max
            elif leverage > exact_rule_max:
                raise TrainingRunError(
                    "RISK_LIMIT_EXCEEDED",
                    "order leverage exceeds the active historical rule",
                    status_code=409,
                )
        if portfolio.get("margin_mode") == "ISOLATED":
            allocations = portfolio.get("isolated_allocations")
            track_account = selected_track.get("account")
            if not isinstance(allocations, Mapping) or not isinstance(
                track_account,
                Mapping,
            ):
                raise TrainingRunError(
                    "TRAINING_RUN_STORAGE_DEGRADED",
                    "isolated account projection is invalid",
                    status_code=503,
                )
            position_side = payload.get("position_side")
            allocation_key = isolated_margin_key(
                track_id,
                None if position_side is None else str(position_side),
            )
            allocated = Decimal(str(allocations.get(allocation_key, "0")))
            if binding.get("position_mode") == "HEDGE":
                positions = portfolio.get("positions")
                orders = portfolio.get("orders")
                if not isinstance(positions, list) or not isinstance(orders, list):
                    raise TypeError("HEDGE isolated risk projection is invalid")
                risk_position = next(
                    (
                        item
                        for item in positions
                        if isinstance(item, Mapping)
                        and item.get("track_id") == track_id
                        and item.get("position_side") == position_side
                    ),
                    None,
                )
                position_margin = Decimal(
                    str(
                        0
                        if not isinstance(risk_position, Mapping)
                        else risk_position.get("initial_margin", "0")
                    )
                )
                order_margin = sum(
                    (
                        Decimal(str(order.get("reserved_margin", "0")))
                        for order in orders
                        if isinstance(order, Mapping)
                        and order.get("track_id") == track_id
                        and order.get("position_side") == position_side
                        and order.get("status") in {"OPEN", "PARTIALLY_FILLED"}
                    ),
                    Decimal(0),
                )
                in_use = position_margin + order_margin
            else:
                position_margin = Decimal(str(track_account.get("margin_used", "0")))
                in_use = position_margin + Decimal(
                    str(track_account.get("reserved_margin", "0"))
                )
            available = allocated - in_use
            if release_selected_margin:
                available += position_margin
            available += release_order_reservation
            if allocated <= 0:
                raise TrainingRunError(
                    "ISOLATED_MARGIN_REQUIRED",
                    "allocate isolated margin before placing an opening order",
                    status_code=409,
                    details={"track_id": track_id},
                )
        else:
            available = Decimal(str(portfolio["available_equity"]))
            if release_selected_margin:
                track_account = selected_track.get("account")
                if not isinstance(track_account, Mapping):
                    raise TypeError("selected track account is invalid")
                available += Decimal(str(track_account.get("margin_used", "0")))
            available += release_order_reservation
        reservation = round_to_step(
            quantity * price * contract_size / leverage,
            quote_step,
            upward=True,
        )
    except (InvalidOperation, KeyError, TypeError, ZeroDivisionError) as exc:
        raise TrainingRunError(
            "REPLAY_CONTROL_INVALID",
            "order cannot be valued against the shared settlement account",
            status_code=422,
        ) from exc
    if quantity <= 0 or price <= 0 or leverage <= 0:
        raise TrainingRunError(
            "REPLAY_CONTROL_INVALID",
            "order reservation inputs must be positive",
            status_code=422,
        )
    if reservation > available:
        raise TrainingRunError(
            "RUN_ACCOUNT_MARGIN_EXCEEDED",
            "order exceeds the TrainingRun shared available equity",
            status_code=409,
            details={
                "required_reservation": str(reservation),
                "available_equity": str(available),
            },
        )


def order_payload_with_optional_leverage(
    payload: Mapping[str, object],
    expected: set[str],
) -> Mapping[str, object]:
    """Exact payload contract with optional per-order leverage ≤ max."""

    data = dict(payload)
    leverage = data.pop("leverage", None)
    position_side = data.pop("position_side", None)
    validated = dict(service_validation_ops.exact_payload(data, expected))
    if position_side is not None:
        if position_side not in {"LONG", "SHORT"}:
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "position_side must be LONG or SHORT",
                status_code=422,
            )
        validated["position_side"] = position_side
    if leverage is not None:
        if not isinstance(leverage, str):
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "leverage must be a canonical Decimal string",
                status_code=422,
            )
        try:
            normalized = normalize_decimal_string(leverage, field_name="leverage")
        except (TypeError, ValueError) as exc:
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "leverage is invalid",
                status_code=422,
            ) from exc
        if Decimal(normalized) < 1:
            raise TrainingRunError(
                "REPLAY_CONTROL_INVALID",
                "leverage must be at least 1",
                status_code=422,
            )
        validated["leverage"] = normalized
    return validated
