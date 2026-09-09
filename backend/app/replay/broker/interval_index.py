"""Immutable price-range screening; candidates still use the broker trigger rule."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from ..dataset import ReplayBar


class BarInteractionIndex:
    def __init__(self, bars: Sequence[ReplayBar]):
        self.bars = tuple(bars)
        size = 1
        while size < len(bars):
            size *= 2
        self.size = size
        self.low = [Decimal("Infinity")] * (2 * size)
        self.high = [Decimal("-Infinity")] * (2 * size)
        for i, bar in enumerate(bars):
            self.low[size + i] = Decimal(bar.low)
            self.high[size + i] = Decimal(bar.high)
        for i in range(size - 1, 0, -1):
            self.low[i] = min(self.low[2 * i], self.low[2 * i + 1])
            self.high[i] = max(self.high[2 * i], self.high[2 * i + 1])

    def first_touch(self, price: Decimal, *, below: bool, start: int, end: int) -> int:
        """Find the first possible touch in [start,end), or return end."""

        def find(node: int, left: int, right: int) -> int:
            if right <= start or left >= end:
                return end
            if (self.low[node] > price) if below else (self.high[node] < price):
                return end
            if right - left == 1:
                return left
            middle = (left + right) // 2
            hit = find(node * 2, left, middle)
            return hit if hit != end else find(node * 2 + 1, middle, right)

        return find(1, 0, self.size)
