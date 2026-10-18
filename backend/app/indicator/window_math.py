"""Window-local arithmetic shared by full, incremental and replay indicators.

Keep this algorithm in sync with replayWindowMath.ts. Compensated, anchored
sums depend only on the selected window, not on discarded historical prices.
"""

from collections.abc import Iterable, Sequence


def compensated_sum(values: Iterable[float]) -> float:
    total = correction = 0.0
    for value in values:
        next_total = total + value
        correction += (
            (total - next_total) + value
            if abs(total) >= abs(value)
            else (value - next_total) + total
        )
        total = next_total
    return total + correction


def window_mean(values: Sequence[float]) -> float:
    anchor = values[0]
    return anchor + compensated_sum(value - anchor for value in values) / len(values)


def window_moments(values: Sequence[float]) -> tuple[float, float]:
    mean = window_mean(values)
    return mean, compensated_sum((value - mean) * (value - mean) for value in values)
