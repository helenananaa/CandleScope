"""Account math operations on a caller-owned transaction."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal, getcontext
from functools import lru_cache

from app.replay.broker.models import decimal_to_string
from app.replay.canonical import canonical_sha256
from app.replay.internal_commands import (
    REVEALED_REFERENCE_CLOSE_FIDELITY,
)

from ..account import (
    InstrumentRule,
    round_to_step,
)

TOUCH_OR_TAPE_LIQUIDATION_FIDELITY = REVEALED_REFERENCE_CLOSE_FIDELITY


VERSIONED_MAINTENANCE_TIER_FIDELITY = "VERSIONED_MAINTENANCE_TIER_APPLIED"


EXTRAPOLATED_MAINTENANCE_TIER_FIDELITY = (
    "LAST_MAINTENANCE_TIER_RATE_DEDUCTION_EXTRAPOLATED"
)


@lru_cache(maxsize=128)
def _stored_instrument_rule(rule_json: str) -> InstrumentRule:
    # Rules and their tier objects are frozen. Cache by the complete stored
    # value, so any revision or edit is parsed and validated independently.
    return InstrumentRule.from_mapping(json.loads(rule_json))


def _direct_liquidation_tick(
    *,
    mark_price: Decimal,
    scope_equity: Decimal,
    other_maintenance: Decimal,
    contract_quantity: Decimal,
    position_side: str,
    rule: InstrumentRule,
    current_grid: Decimal,
    bankruptcy_price: Decimal,
    breached: Callable[[Decimal], bool],
) -> Decimal | None:
    """Certify a candidate and its adjacent tick; otherwise keep the old search.

    Rounded maintenance is a staircase. In particular, a tiny LONG position
    does not necessarily have a monotone breach predicate on the price grid.
    Never replace the reference search unless monotonicity is established.
    """
    tick = Decimal(rule.price_tick)
    quote = Decimal(rule.quote_step)
    quantity_tick = contract_quantity * tick
    if (
        position_side == "LONG"
        and quantity_tick < quote
        and any(Decimal(t.maintenance_rate) > 0 for t in rule.maintenance_tiers)
    ):
        return None
    # Require exact arithmetic on the entire reference search grid. Otherwise
    # finite Decimal precision can itself introduce steps in candidate equity.
    bound = max(current_grid, bankruptcy_price, mark_price, tick)
    price_exponent = min(tick.as_tuple().exponent, mark_price.as_tuple().exponent)
    product_exponent = price_exponent + contract_quantity.as_tuple().exponent
    lowest_exponent = min(
        product_exponent,
        scope_equity.as_tuple().exponent,
        other_maintenance.as_tuple().exponent,
        quote.as_tuple().exponent,
    )
    largest_adjusted = (
        max(
            bound.adjusted() + contract_quantity.adjusted() + 2,
            scope_equity.adjusted(),
            other_maintenance.adjusted(),
        )
        + 2
    )
    if largest_adjusted - lowest_exponent + 1 > getcontext().prec:
        return None
    tiers = rule.maintenance_tiers
    rates = tuple(Decimal(t.maintenance_rate) for t in tiers)
    deductions = tuple(Decimal(t.maintenance_deduction) for t in tiers)
    for tier, rate, deduction in zip(tiers, rates, deductions):
        cap = Decimal(tier.notional_cap)
        smallest = (
            min(product_exponent, cap.as_tuple().exponent) + rate.as_tuple().exponent
        )
        smallest = min(smallest, deduction.as_tuple().exponent)
        largest = max(largest_adjusted, cap.adjusted()) + rate.adjusted() + 2
        if max(largest, deduction.adjusted()) - smallest + 1 > min(
            60, getcontext().prec
        ):
            return None
    # Continuous piecewise raw maintenance gives a nondecreasing rounded
    # function; discontinuous versioned rules keep the reference behavior.
    for i in range(1, len(tiers)):
        cap = Decimal(tiers[i - 1].notional_cap)
        if cap * rates[i - 1] - deductions[i - 1] != cap * rates[i] - deductions[i]:
            return None
    if position_side == "LONG" and (
        round_to_step(quantity_tick * max(rates), quote, upward=True) > quantity_tick
    ):
        return None
    direction = Decimal(1) if position_side == "LONG" else Decimal(-1)
    # Roots are proposals only. All acceptance decisions below use the exact
    # original predicate, including its arithmetic and upward money rounding.
    capital = (
        scope_equity - direction * contract_quantity * mark_price - other_maintenance
    )
    proposals = []
    lower_cap = Decimal(0)
    for i, (rate, deduction) in enumerate(zip(rates, deductions)):
        raw = (-capital - deduction) / (contract_quantity * (direction - rate))
        notional = raw * contract_quantity
        if notional >= lower_cap and (
            i == len(tiers) - 1 or notional <= Decimal(tiers[i].notional_cap)
        ):
            proposals.append(raw)
        lower_cap = Decimal(tiers[i].notional_cap)
    if any(deductions) or not any(rates):
        proposals.append(-capital / (direction * contract_quantity))
    for raw in proposals:
        if not raw.is_finite() or raw < 0:
            continue
        center = round_to_step(raw, tick, upward=position_side == "SHORT")
        # Rounding can shift the actual boundary by more than a tick. Such a
        # case deliberately falls back rather than scanning an unbounded band.
        for candidate in (center, center - tick, center + tick):
            if candidate < 0:
                continue
            if position_side == "LONG":
                if candidate >= current_grid:
                    continue
                if breached(candidate) and not breached(candidate + tick):
                    return candidate
            else:
                if candidate <= current_grid or candidate > bankruptcy_price:
                    continue
                if breached(candidate) and not breached(candidate - tick):
                    return candidate
        # Small positions can move by many price ticks when maintenance is
        # rounded by one money unit. Certify a bracket, then run the same
        # integer search inside it; never treat the continuous root as final.
        radius = (
            round_to_step(
                quote / (contract_quantity * (Decimal(1) - max(rates))),
                tick,
                upward=True,
            )
            + tick
        )
        if position_side == "LONG":
            lower = max(Decimal(0), center - radius)
            upper = min(current_grid, center + radius)
            if lower >= upper or not breached(lower) or breached(upper):
                continue
            hit, safe = int(lower / tick), int(upper / tick)
            while safe - hit > 1:
                middle = (hit + safe) // 2
                if breached(Decimal(middle) * tick):
                    hit = middle
                else:
                    safe = middle
            return Decimal(hit) * tick
        lower = max(current_grid, center - radius)
        upper = min(bankruptcy_price, center + radius)
        if lower >= upper or breached(lower) or not breached(upper):
            continue
        safe, hit = int(lower / tick), int(upper / tick)
        while hit - safe > 1:
            middle = (hit + safe) // 2
            if breached(Decimal(middle) * tick):
                hit = middle
            else:
                safe = middle
        return Decimal(hit) * tick
    return None


def _project_liquidation_price_pair(
    *,
    mark_price: Decimal,
    scope_equity: Decimal,
    scope_maintenance_margin: Decimal,
    absolute_quantity: Decimal,
    position_side: str,
    rule: InstrumentRule,
) -> tuple[Decimal, Decimal]:
    """Project deterministic adverse-tick liquidation and bankruptcy prices."""

    if absolute_quantity <= 0:
        raise ValueError("liquidation price projection requires positive quantity")
    direction = Decimal(1) if position_side == "LONG" else Decimal(-1)
    contract_quantity = absolute_quantity * Decimal(rule.contract_size)
    denominator = direction * contract_quantity
    bankruptcy_raw = mark_price - scope_equity / denominator
    tick = Decimal(rule.price_tick)
    upward = position_side == "SHORT"
    bankruptcy_price = max(
        Decimal(0),
        round_to_step(
            max(Decimal(0), bankruptcy_raw),
            tick,
            upward=upward,
        ),
    )
    current_leg_maintenance = rule.maintenance_margin(
        contract_quantity * mark_price,
        extend_last_tier=True,
    )
    other_maintenance = scope_maintenance_margin - current_leg_maintenance
    if other_maintenance < 0:
        raise ValueError("scope maintenance is below selected leg maintenance")

    def breached(candidate_price: Decimal) -> bool:
        candidate_equity = scope_equity + (
            direction * (candidate_price - mark_price) * contract_quantity
        )
        candidate_maintenance = other_maintenance + rule.maintenance_margin(
            contract_quantity * candidate_price,
            extend_last_tier=True,
        )
        return candidate_equity <= candidate_maintenance

    current_grid = round_to_step(mark_price, tick, upward=upward)
    if breached(current_grid):
        liquidation_price = current_grid
        return liquidation_price, bankruptcy_price
    if position_side == "LONG" and not breached(Decimal(0)):
        return Decimal(0), bankruptcy_price
    direct = _direct_liquidation_tick(
        mark_price=mark_price,
        scope_equity=scope_equity,
        other_maintenance=other_maintenance,
        contract_quantity=contract_quantity,
        position_side=position_side,
        rule=rule,
        current_grid=current_grid,
        bankruptcy_price=bankruptcy_price,
        breached=breached,
    )
    if direct is not None:
        return direct, bankruptcy_price
    if position_side == "LONG":
        breached_units = 0
        safe_units = int(current_grid / tick)
        while safe_units - breached_units > 1:
            candidate_units = (breached_units + safe_units) // 2
            if breached(Decimal(candidate_units) * tick):
                breached_units = candidate_units
            else:
                safe_units = candidate_units
        liquidation_price = Decimal(breached_units) * tick
    else:
        safe_units = int(current_grid / tick)
        breached_units = max(safe_units, int(bankruptcy_price / tick))
        if not breached(Decimal(breached_units) * tick):
            raise ValueError("short bankruptcy tick does not breach maintenance")
        while breached_units - safe_units > 1:
            candidate_units = (safe_units + breached_units) // 2
            if breached(Decimal(candidate_units) * tick):
                breached_units = candidate_units
            else:
                safe_units = candidate_units
        liquidation_price = Decimal(breached_units) * tick
    return liquidation_price, bankruptcy_price


def _maintenance_margin_proof(
    *,
    rule: InstrumentRule,
    rule_revision: int,
    rule_hash: str,
    rule_fidelity: str,
    position_notional: Decimal,
    risk_tier: int,
    liquidation_price: Decimal | None,
    absolute_quantity: Decimal,
) -> dict[str, object]:
    """Describe when retained-position risk leaves the pinned tier envelope."""

    last_tier_cap = Decimal(rule.maintenance_tiers[-1].notional_cap)
    position_extrapolated = position_notional > last_tier_cap
    liquidation_notional = (
        None
        if liquidation_price is None
        else absolute_quantity * Decimal(rule.contract_size) * liquidation_price
    )
    liquidation_extrapolated = (
        liquidation_notional is not None and liquidation_notional > last_tier_cap
    )
    if position_extrapolated and liquidation_extrapolated:
        explanation = "POSITION_AND_LIQUIDATION_NOTIONAL_ABOVE_LAST_VERSIONED_TIER_CAP"
    elif position_extrapolated:
        explanation = "POSITION_NOTIONAL_ABOVE_LAST_VERSIONED_TIER_CAP"
    elif liquidation_extrapolated:
        explanation = "LIQUIDATION_NOTIONAL_ABOVE_LAST_VERSIONED_TIER_CAP"
    else:
        explanation = None
    payload = {
        "schema_version": "replay.maintenance-margin-proof.v1",
        "rule_revision": rule_revision,
        "rule_hash": rule_hash,
        "rule_fidelity": rule_fidelity,
        "risk_tier": risk_tier,
        "last_tier_notional_cap": decimal_to_string(
            last_tier_cap,
            field_name="last maintenance tier cap",
        ),
        "position_notional": decimal_to_string(
            position_notional,
            field_name="maintenance proof position notional",
        ),
        "position_tier_extrapolated": position_extrapolated,
        "liquidation_price_notional": (
            None
            if liquidation_notional is None
            else decimal_to_string(
                liquidation_notional,
                field_name="maintenance proof liquidation notional",
            )
        ),
        "liquidation_tier_extrapolated": liquidation_extrapolated,
        "fidelity": (
            EXTRAPOLATED_MAINTENANCE_TIER_FIDELITY
            if position_extrapolated or liquidation_extrapolated
            else VERSIONED_MAINTENANCE_TIER_FIDELITY
        ),
        "explanation": explanation,
    }
    return {**payload, "proof_hash": canonical_sha256(payload)}
