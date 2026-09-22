"""Bounded, presentation-only depth selection and per-view hysteresis."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from itertools import islice
from math import log
from typing import Any, Mapping

MULTIPLIERS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)


def step_scores(
    data: Mapping[str, Any], tick: Decimal, target_rows: int, range_bps: int = 0,
    max_multiplier: int = 1000,
) -> dict[Decimal, float]:
    """Score at most 512 near-price levels per side; never invent missing liquidity.

    Auto's default inspection horizon is 10 bps, independent of output count.
    Each side's target is capped by available raw levels so a thin side cannot
    force the dense side to raw. Undershooting that target costs more than
    overshooting. Prefer finer steps on equal scores.
    """
    sides: list[tuple[list[Decimal], Any]] = []
    for name, rounding in (("bids", ROUND_FLOOR), ("asks", ROUND_CEILING)):
        prices = []
        for row in islice(data.get(name, ()), 512):
            price = row.decimal_pair()[0] if hasattr(row, "decimal_pair") else Decimal(str(row[0]))
            prices.append(price)
        if prices:
            distance = prices[0] * Decimal(range_bps or 10) / 10000
            prices = [price for price in prices if abs(price - prices[0]) <= distance]
            sides.append((prices, rounding))
    scores: dict[Decimal, float] = {}
    for multiplier in MULTIPLIERS:
        if multiplier > max_multiplier:
            break
        step = tick * multiplier
        score = 0.0
        for prices, rounding in sides:
            buckets = {(price / step).to_integral_value(rounding=rounding) for price in prices}
            target = min(max(2, target_rows), len(prices))
            count = len(buckets)
            error = log(count / target)
            score += abs(error) * (3 if error < 0 else 1)
            # Mild sparsity penalty, subordinate to preserving readable detail.
            span = int(max(buckets) - min(buckets)) + 1
            if len(prices) > target_rows:
                score += 0.15 * (1 - count / span)
        scores[step] = score
    return scores


@dataclass
class AutoGroupingState:
    step: Decimal | None = None
    pending: Decimal | None = None
    pending_since: float = 0.0
    changed_at: float = 0.0

    def choose(self, scores: dict[Decimal, float], now: float, frozen: bool = False) -> Decimal:
        best = min(scores, key=lambda step: (scores[step], step))
        if self.step not in scores:
            self.step, self.changed_at = best, now
            self.pending = None
        elif frozen or best == self.step or scores[self.step] - scores[best] < 0.25:
            self.pending = None
        elif self.pending != best:
            self.pending, self.pending_since = best, now
        elif now - self.pending_since >= 2 and now - self.changed_at >= 5:
            self.step, self.changed_at = best, now
            self.pending = None
        assert self.step is not None
        return self.step
