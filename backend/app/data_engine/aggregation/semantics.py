"""Pure field, coverage and finality rules shared by history and live adapters.

All ranges are half-open milliseconds. No clock, source lookup, scheduling or
I/O is allowed here. Inputs have already passed their source's admission policy.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from math import fsum


class ClosePolicy(str, Enum):
    EXPLICIT = "every_component_closed"
    # Compatibility policy for historical query previews. It is NOT proof
    # of authoritative closure for realtime publication or durable rebuilds.
    SUCCESSOR = "successor_confirms_previous"


@dataclass(frozen=True, slots=True)
class CoverageStatus:
    complete: bool = False
    enhanced_complete: bool = False
    closed: bool = False


def evaluate_coverage(
    *,
    has_components: bool,
    starts_at_boundary: bool,
    contiguous: bool,
    reaches_end: bool,
    within_bounds: bool,
    all_closed: bool,
    last_closed: bool,
    close_policy: ClosePolicy,
) -> CoverageStatus:
    """Evaluate explicit evidence, including calendar-adjusted prefix evidence.

    A forming contiguous prefix may expose enhanced totals. A closed prefix
    that does not reach the target end may not. An interior hole, overlap or
    boundary-crossing source never proves complete coverage or finality.
    """
    close_policy = ClosePolicy(close_policy)
    prefix = has_components and starts_at_boundary and contiguous and within_bounds
    complete = bool(prefix and reaches_end)
    closed_evidence = all_closed if close_policy is ClosePolicy.EXPLICIT else last_closed
    return CoverageStatus(
        complete=complete,
        enhanced_complete=bool(prefix and (reaches_end or not last_closed)),
        closed=bool(complete and closed_evidence),
    )


@dataclass(frozen=True, slots=True)
class Coverage:
    """Coalesced occupied ranges, not a copy of every component timestamp.

    Storage is O(number of holes), normally one range. B130 owns admission and
    retained-memory bounds; this value owns no cache. Exclusions are supplied
    explicitly at evaluation, so a hole is never silently treated as a session.
    """
    ranges: tuple[tuple[int, int], ...]
    all_closed: bool
    last_closed: bool
    count: int

    @classmethod
    def from_ranges(cls, components: Iterable[tuple[int, int, bool]]) -> Coverage:
        ranges: list[tuple[int, int]] = []
        all_closed = True
        last_closed = False
        count = 0
        for start, end, closed in components:
            if start >= end or (ranges and start < ranges[-1][1]):
                raise ValueError("components must be ordered, positive and non-overlapping")
            if ranges and start == ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], end)
            else:
                ranges.append((start, end))
            all_closed = all_closed and closed
            last_closed = closed
            count += 1
        return cls(tuple(ranges), bool(count and all_closed), last_closed, count)

    def evaluate(
        self, start_ms: int, end_ms: int, *,
        close_policy: ClosePolicy = ClosePolicy.EXPLICIT,
        exclusions: tuple[tuple[int, int], ...] = (),
    ) -> CoverageStatus:
        expected = expected_ranges(start_ms, end_ms, exclusions)
        if not self.ranges or not expected:
            return CoverageStatus()
        # Occupancy must be an exact prefix of the expected trading ranges;
        # only its last range may stop early. This also rejects closed-market
        # input and a coarse component spanning an explicit session break.
        prefix = len(self.ranges) <= len(expected) and all(
            actual[0] == wanted[0]
            and actual[1] <= wanted[1]
            and (index == len(self.ranges) - 1 or actual[1] == wanted[1])
            for index, (actual, wanted) in enumerate(zip(self.ranges, expected))
        )
        return evaluate_coverage(
            has_components=bool(self.count), starts_at_boundary=prefix,
            contiguous=prefix, within_bounds=prefix,
            reaches_end=self.ranges == expected,
            all_closed=self.all_closed, last_closed=self.last_closed,
            close_policy=close_policy,
        )


def expected_ranges(
    start_ms: int, end_ms: int, exclusions: tuple[tuple[int, int], ...] = (),
) -> tuple[tuple[int, int], ...]:
    if start_ms >= end_ms:
        raise ValueError("target must have positive width")
    result = []
    cursor = start_ms
    for start, end in exclusions:
        if start < cursor or start >= end or end > end_ms:
            raise ValueError("exclusions must be ordered, disjoint and inside target")
        if cursor < start:
            result.append((cursor, start))
        cursor = end
    if cursor < end_ms:
        result.append((cursor, end_ms))
    return tuple(result)


def combine_coverage(parts: Sequence[Coverage]) -> Coverage:
    ranges = Coverage.from_ranges(
        (start, end, True) for part in parts for start, end in part.ranges
    ).ranges
    nonempty = [part for part in parts if part.count]
    return Coverage(
        ranges, bool(nonempty and all(part.all_closed for part in nonempty)),
        nonempty[-1].last_closed if nonempty else False,
        sum(part.count for part in nonempty),
    )


def sum_additive(
    values: Iterable[float | int | None], *, integer: bool = False,
) -> float | int | None:
    """Unknown is contagious; round only when projecting the final result.

    fsum avoids page-size-dependent rounding of running totals. Composition
    uses unrounded sufficient statistics, with equivalence tolerance specified
    in K130's contract (IEEE floats are not asserted to be associative).
    """
    present = tuple(values)
    if None in present:
        return None
    return sum(int(value) for value in present) if integer else fsum(present)


@dataclass(frozen=True, slots=True)
class FieldSummary:
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None
    trades: int | None
    taker_buy_base: float | None
    taker_buy_quote: float | None

    def project(self, *, enhanced_complete: bool = True) -> dict:
        fields = {
            name: round(getattr(self, name), 8)
            for name in ("open", "high", "low", "close", "volume")
        }
        for name in ("quote_volume", "trades", "taker_buy_base", "taker_buy_quote"):
            value = getattr(self, name)
            fields[name] = (
                (value if name == "trades" else round(value, 8))
                if enhanced_complete and value is not None else None
            )
        return fields

    @property
    def vwap(self) -> float | None:
        # Valid only when the caller's volume semantics say quote/base is a
        # price. Never average per-component or per-block VWAP values.
        if self.quote_volume is None or self.volume <= 0:
            return None
        return self.quote_volume / self.volume


def summarize_fields(rows: Sequence[tuple]) -> FieldSummary:
    """Reduce normalized (O,H,L,C,V,quote,trades,taker_base,taker_quote) rows."""
    if not rows:
        raise ValueError("an empty range has no OHLCV value")
    return FieldSummary(
        open=rows[0][0], high=max(row[1] for row in rows),
        low=min(row[2] for row in rows), close=rows[-1][3],
        volume=sum_additive(row[4] for row in rows),
        quote_volume=sum_additive(row[5] for row in rows),
        trades=sum_additive((row[6] for row in rows), integer=True),
        taker_buy_base=sum_additive(row[7] for row in rows),
        taker_buy_quote=sum_additive(row[8] for row in rows),
    )


def combine_fields(parts: Sequence[FieldSummary]) -> FieldSummary:
    return summarize_fields([
        (part.open, part.high, part.low, part.close, part.volume,
         part.quote_volume, part.trades, part.taker_buy_base, part.taker_buy_quote)
        for part in parts
    ])
