"""The closed-bar grid a forward run advances on (ADR-BACKTEST-015 B-333).

A forward run consumes closed bars of its signal interval, as FIXED and FOLLOW runs
of the same series do, so its result over the same bars is the FIXED result.
Any fixed-length interval of a minute or more qualifies: minutes, hours, days and
Monday-aligned weeks. Calendar months and zoned calendars have no fixed length.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.data_engine.interval_policy import IntervalAlignment, IntervalSpec, parse_interval_spec

from .errors import BacktestError

MINUTE_MS = 60_000


@dataclass(frozen=True)
class BarGrid:
    interval: str
    step_ms: int
    spec: IntervalSpec

    def aligned(self, time_ms: object) -> bool:
        """Whether ``time_ms`` is a bar open on this grid."""
        return type(time_ms) is int and self.spec.floor_ms(time_ms) == time_ms

    def closes_bar(self, time_ms: object) -> bool:
        """Whether ``time_ms`` is the inclusive close of a bar on this grid."""
        return type(time_ms) is int and self.aligned(time_ms + 1)

    def closed_through(self, now_ms: int) -> int:
        """The inclusive close of the newest bar that has closed at ``now_ms``."""
        return self.spec.floor_ms(now_ms) - 1

    def count(self, from_ms: int, through_ms: int) -> int:
        """Bars from the open ``from_ms`` through the close ``through_ms``."""
        return (through_ms + 1 - from_ms) // self.step_ms


@lru_cache(maxsize=64)
def bar_grid(interval: str) -> BarGrid:
    """The grid of a canonical fixed-length interval; refuses calendar intervals and aliases."""
    spec = parse_interval_spec(interval) if type(interval) is str else None
    if (spec is None or spec.canonical != interval or spec.timezone
            or spec.alignment in {IntervalAlignment.CALENDAR_MONTH, IntervalAlignment.ZONED_CALENDAR}
            or spec.nominal_ms < MINUTE_MS or spec.nominal_ms % MINUTE_MS):
        raise BacktestError("FIDELITY_UNSUPPORTED",
            "Forward runs need a fixed-length signal interval of whole minutes, such as 1m, 5m, 1h or 1d")
    return BarGrid(interval, spec.nominal_ms, spec)


def supports(interval: object) -> bool:
    try:
        bar_grid(interval)  # type: ignore[arg-type]
    except BacktestError:
        return False
    return True
