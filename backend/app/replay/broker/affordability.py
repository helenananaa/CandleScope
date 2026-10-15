"""Opening-order cash budgets, including execution costs before margin."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


@dataclass(frozen=True)
class OpeningBudget:
    margin: Decimal
    fee: Decimal
    slippage: Decimal
    quote_step: Decimal

    def required(self, quantity: Decimal) -> Decimal:
        def rounded(value: Decimal) -> Decimal:
            return (value / self.quote_step).to_integral_value(rounding=ROUND_CEILING) * self.quote_step
        return rounded(quantity * self.margin) + rounded(quantity * self.fee) + quantity * self.slippage

    def capacity(self, available: Decimal, quantity_step: Decimal) -> Decimal:
        cost = self.margin + self.fee + self.slippage
        maximum = (max(Decimal(0), available) / cost / quantity_step).to_integral_value(rounding=ROUND_FLOOR) * quantity_step
        if self.required(maximum) > available:
            # Separately rounded margin and fee can consume two extra cash
            # steps; this bounded correction leaves only that tiny safety dust.
            maximum = (max(Decimal(0), available - 2 * self.quote_step) / cost / quantity_step).to_integral_value(rounding=ROUND_FLOOR) * quantity_step
        return maximum


def opening_budget(*, reference: Decimal, leverage: Decimal, side: str,
                   limit: bool, slippage_bps: Decimal, fee_bps: Decimal,
                   price_tick: Decimal, quote_step: Decimal,
                   contract_size: Decimal = Decimal(1)) -> OpeningBudget:
    if min(reference, leverage, price_tick, quote_step, contract_size) <= 0:
        raise ValueError("opening budget requires positive price, leverage and steps")
    if min(slippage_bps, fee_bps) < 0 or slippage_bps >= 10_000:
        raise ValueError("opening budget execution costs are invalid")
    if side not in {"BUY", "SELL"}:
        raise ValueError("opening budget side is invalid")
    fill = reference
    if not limit:
        direction = Decimal(1) if side == "BUY" else Decimal(-1)
        fill = reference * (1 + direction * slippage_bps / 10_000)
        fill = (fill / price_tick).to_integral_value(
            rounding=ROUND_CEILING if side == "BUY" else ROUND_FLOOR) * price_tick
    return OpeningBudget(
        margin=max(reference, fill) * contract_size / leverage,
        fee=fill * contract_size * fee_bps / 10_000,
        slippage=abs(fill - reference) * contract_size,
        quote_step=quote_step,
    )
