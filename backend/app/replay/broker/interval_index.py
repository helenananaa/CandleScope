"""Immutable price-range screening; candidates still use the broker trigger rule."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from ..dataset import ReplayBar


class PriceRangeIndex:
    """A binary summary tree over immutable inclusive price ranges."""

    def __init__(self, ranges: Sequence[tuple[Decimal, Decimal]]):
        self.length = len(ranges)
        size = 1
        while size < self.length:
            size *= 2
        self.size = size
        self.low = [Decimal("Infinity")] * (2 * size)
        self.high = [Decimal("-Infinity")] * (2 * size)
        for i, (low, high) in enumerate(ranges):
            if low.is_nan() or high.is_nan() or low > high:
                raise ValueError("invalid price range")
            self.low[size + i] = low
            self.high[size + i] = high
        for i in range(size - 1, 0, -1):
            self.low[i] = min(self.low[2 * i], self.low[2 * i + 1])
            self.high[i] = max(self.high[2 * i], self.high[2 * i + 1])

    def _validate_span(self, start: int, end: int) -> None:
        if not 0 <= start <= end <= self.length:
            raise ValueError("price range span is outside the index")

    def range_bounds(self, *, start: int, end: int) -> tuple[Decimal, Decimal] | None:
        self._validate_span(start, end)
        if start == end:
            return None
        left, right = start + self.size, end + self.size
        low, high = Decimal("Infinity"), Decimal("-Infinity")
        while left < right:
            if left & 1:
                low, high = min(low, self.low[left]), max(high, self.high[left])
                left += 1
            if right & 1:
                right -= 1
                low, high = min(low, self.low[right]), max(high, self.high[right])
            left //= 2
            right //= 2
        return low, high

    def first_outside(
        self, low: Decimal, high: Decimal, *, start: int, end: int
    ) -> int:
        """First leaf not contained in [low, high]; descend only suspect nodes."""
        self._validate_span(start, end)
        if not low.is_finite() or not high.is_finite() or low > high:
            raise ValueError("invalid certified price envelope")

        def find(node: int, left: int, right: int) -> int:
            if right <= start or left >= end:
                return end
            if self.low[node] >= low and self.high[node] <= high:
                return end
            if right - left == 1:
                return left
            middle = (left + right) // 2
            hit = find(node * 2, left, middle)
            return hit if hit != end else find(node * 2 + 1, middle, right)

        return find(1, 0, self.size)

    def first_touch(self, price: Decimal, *, below: bool, start: int, end: int) -> int:
        """Find the first possible touch in [start,end), or return end."""
        self._validate_span(start, end)

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


class BarInteractionIndex(PriceRangeIndex):
    def __init__(self, bars: Sequence[ReplayBar]):
        self.bars = tuple(bars)
        super().__init__(
            tuple((Decimal(bar.low), Decimal(bar.high)) for bar in self.bars)
        )
