"""Pure, conservative portfolio screening and time-ordered interval valuation.

An envelope is sufficient evidence to skip a range, never evidence to liquidate.
No account objects, financial writes or future account snapshots are constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Mapping, Sequence

from .account import InstrumentRule


def combine_equity_summaries(summaries):
    """Compose ordered ranges, including drawdown crossing their boundary."""
    result = None
    with localcontext() as context:
        context.prec = 60
        for summary in summaries:
            if result is None:
                result = dict(summary)
                continue
            peak, low = Decimal(result["peak"]), Decimal(summary["trough"])
            result["max_drawdown"] = str(
                max(
                    Decimal(result["max_drawdown"]),
                    Decimal(summary["max_drawdown"]),
                    peak - low,
                )
            )
            result["peak"] = str(max(peak, Decimal(summary["peak"])))
            if low < Decimal(result["trough"]):
                result["trough"], result["trough_time_ms"] = (
                    summary["trough"],
                    summary["trough_time_ms"],
                )
            result["last"] = summary["last"]
            result["events"] += summary["events"]
            result["integer_path"] = result["integer_path"] and summary["integer_path"]
    return result


@dataclass(frozen=True, slots=True)
class IntervalLeg:
    track_id: str
    side: str
    quantity: Decimal
    entry: Decimal
    rule: InstrumentRule
    isolated_cash: Decimal = Decimal(0)

    @property
    def weight(self) -> Decimal:
        return (
            self.quantity
            * Decimal(self.rule.contract_size)
            * (1 if self.side == "LONG" else -1)
        )


def safe_envelope(
    *,
    cash: Decimal,
    legs: Sequence[IntervalLeg],
    bounds: Mapping[str, tuple[Decimal, Decimal]],
    margin_mode: str,
    reserved_margin: Decimal = Decimal(0),
) -> bool:
    """Check all legs against conservative, independently attainable bounds."""
    if margin_mode not in {"CROSS", "ISOLATED"} or not cash.is_finite():
        return False
    with localcontext() as ctx:
        ctx.prec = 60
        minimum_equity, maximum_requirement = cash, reserved_margin
        for leg in legs:
            low, high = bounds[leg.track_id]
            if not low.is_finite() or not high.is_finite() or not 0 < low <= high:
                return False
            quantity = leg.quantity * Decimal(leg.rule.contract_size)
            if quantity <= 0 or leg.side not in {"LONG", "SHORT"}:
                return False
            # A tier transition is an exact-event boundary, not an assumption
            # that the old maintenance formula remains valid across the range.
            if (
                leg.rule.active_maintenance_tier(low * quantity, extend_last_tier=True)[
                    0
                ]
                != leg.rule.active_maintenance_tier(
                    high * quantity, extend_last_tier=True
                )[0]
            ):
                return False
            worst = low if leg.side == "LONG" else high
            pnl = (worst - leg.entry) * quantity * (1 if leg.side == "LONG" else -1)
            quote = Decimal(leg.rule.quote_step)
            if (
                max(abs(cash), abs(pnl), high * quantity).adjusted()
                - quote.as_tuple().exponent
                > ctx.prec - 4
            ):
                return False
            requirement = (
                leg.rule.maintenance_margin(high * quantity, extend_last_tier=True)
                + quote * 2
            )
            if margin_mode == "ISOLATED" and leg.isolated_cash + pnl <= requirement:
                return False
            minimum_equity += pnl
            maximum_requirement += requirement
        return margin_mode == "ISOLATED" or minimum_equity > maximum_requirement


def ordered_equity_summary(
    *,
    cash: Decimal,
    legs: Sequence[IntervalLeg],
    initial_prices: Mapping[str, Decimal],
    events: Sequence[tuple[int, int, str, int, Decimal]],
    sample_times: set[int] | None = None,
    _partition_after: tuple[int, int] | None = None,
) -> dict[str, object]:
    """Exact extrema/drawdown over (time, phase, track, sequence, price).

    Use integers only when every affine intermediate fits the reference 60-digit
    Decimal context. The unusual-precision branch retains that formula verbatim.
    Events include the existing global phase order, including unequal market grids.
    """
    ordered = sorted(events, key=lambda event: event[:4])
    operands = [cash, *initial_prices.values()]
    operands.extend(
        value
        for leg in legs
        for value in (leg.entry, leg.quantity, Decimal(leg.rule.contract_size))
    )
    operands.extend(event[4] for event in ordered)
    if not all(value.is_finite() for value in operands):
        raise ValueError("non-finite portfolio input")
    smallest = min(value.as_tuple().exponent for value in operands)
    largest = max(value.adjusted() for value in operands)
    exact_integer = 4 * (largest - smallest + 1) + len(str(len(legs) + 1)) < 60
    with localcontext() as ctx:
        ctx.prec = 60
        prices = dict(initial_prices)

        def scalar():
            return cash + sum(
                (
                    (prices[leg.track_id] - leg.entry)
                    * leg.quantity
                    * Decimal(leg.rule.contract_size)
                    * (1 if leg.side == "LONG" else -1)
                    for leg in legs
                ),
                Decimal(0),
            )

        if exact_integer:
            # All products are exact under the checked reference context.
            weights = {
                track: sum(
                    (leg.weight for leg in legs if leg.track_id == track), Decimal(0)
                )
                for track in prices
            }
            intercept = cash - sum((leg.entry * leg.weight for leg in legs), Decimal(0))
            exponent = min(
                [intercept.as_tuple().exponent]
                + [
                    weights[track].as_tuple().exponent + price.as_tuple().exponent
                    for track, price in prices.items()
                ]
                + [
                    weights[e[2]].as_tuple().exponent + e[4].as_tuple().exponent
                    for e in ordered
                ]
            )

            def integer(value):
                return int(value.scaleb(-exponent))

            current = integer(intercept) + sum(
                integer(weights[track] * price) for track, price in prices.items()
            )
            price_exponent = min(
                [p.as_tuple().exponent for p in prices.values()]
                + [event[4].as_tuple().exponent for event in ordered]
            )
            integer_weights = {
                track: int(weight.scaleb(price_exponent - exponent))
                for track, weight in weights.items()
            }
            integer_prices = {
                track: int(price.scaleb(-price_exponent))
                for track, price in prices.items()
            }

            def convert(value):
                return str(Decimal(value).scaleb(exponent))
        else:
            current = scalar()
            convert = str
        first = current
        peak = trough = current
        drawdown = current - current
        trough_time = None
        points = [] if sample_times is not None else None
        observations = [] if _partition_after is not None else None
        for offset, (timestamp, _phase, track, _sequence, price) in enumerate(ordered):
            prices[track] = price
            if exact_integer:
                next_price = int(price.scaleb(-price_exponent))
                current += integer_weights[track] * (next_price - integer_prices[track])
                integer_prices[track] = next_price
            else:
                current = scalar()
            # The coordinator settles a whole same-time cohort before exposing
            # its portfolio. Intermediate per-track prices are not observations.
            if offset + 1 < len(ordered) and ordered[offset + 1][0] == timestamp:
                continue
            if observations is not None:
                observations.append((timestamp, current, offset + 1))
            peak = max(peak, current)
            if current < trough:
                trough, trough_time = current, timestamp
            drawdown = max(drawdown, peak - current)
            if points is not None and timestamp in sample_times:
                points.append((timestamp, convert(current)))
        result = {
            "schema": "portfolio-interval-summary.v1",
            "first": convert(first),
            "last": convert(current),
            "peak": convert(peak),
            "trough": convert(trough),
            "max_drawdown": convert(drawdown),
            "trough_time_ms": trough_time,
            "events": len(ordered),
            "integer_path": exact_integer,
        }
        if observations is not None:
            after, fallback = _partition_after
            pivot = (trough_time if trough_time is not None
                     and after < trough_time < ordered[-1][0] else fallback)
            partitions = []
            initial, previous_count = first, 0
            for selected in (
                [o for o in observations if o[0] <= pivot],
                [o for o in observations if o[0] > pivot],
            ):
                local_peak = local_trough = initial
                local_drawdown = initial - initial
                local_trough_time = None
                for timestamp, value, _ in selected:
                    local_peak = max(local_peak, value)
                    if value < local_trough:
                        local_trough, local_trough_time = value, timestamp
                    local_drawdown = max(local_drawdown, local_peak - value)
                final = selected[-1][1] if selected else initial
                end_count = selected[-1][2] if selected else previous_count
                partitions.append(dict(
                    schema=result["schema"], first=convert(initial), last=convert(final),
                    peak=convert(local_peak), trough=convert(local_trough),
                    max_drawdown=convert(local_drawdown), trough_time_ms=local_trough_time,
                    events=end_count - previous_count, integer_path=exact_integer,
                ))
                initial, previous_count = final, end_count
            result["ordered_events"] = ordered
            result["partitions"] = partitions
            result["partition_time_ms"] = pivot
        if points is not None:
            result["points"] = points
        return result
