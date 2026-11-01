"""K130 accepted-component and composable-summary contract.

The canonical readonly BarData/SeriesKey remain owned by D126. A revision is
an opaque acquisition-view token supplied by that owner, not a second ledger
and not a transport sequence. Source admission/replacement precedes this API.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.data_engine.data_manager.models import BarData, SeriesKey

from .semantics import (
    ClosePolicy, Coverage, CoverageStatus, FieldSummary,
    combine_coverage, combine_fields, summarize_fields,
)

ALGORITHM_VERSION = "k130-fsum-v1"


@dataclass(frozen=True, slots=True)
class InputRevision:
    """Read-view revision in an explicit domain; numbers across domains do not order."""
    series: SeriesKey
    domain: str
    version: int

    def __post_init__(self) -> None:
        if not self.domain or self.version < 0:
            raise ValueError("revision requires a domain and nonnegative version")


@dataclass(frozen=True, slots=True)
class AcceptedComponent:
    series: SeriesKey
    bar: BarData
    end_ms: int
    revision: InputRevision | None = None

    def __post_init__(self) -> None:
        if self.end_ms <= self.bar.time_ms:
            raise ValueError("component must have positive half-open width")
        if self.revision is not None and self.revision.series != self.series:
            raise ValueError("revision must identify the accepted source series")
        if not all(isfinite(getattr(self.bar, field)) for field in (
            "open", "high", "low", "close", "volume",
        )) or self.bar.volume < 0:
            raise ValueError("accepted OHLCV must be finite with nonnegative volume")


@dataclass(frozen=True, slots=True)
class AggregateSummary:
    target: SeriesKey
    values: FieldSummary
    coverage: Coverage
    revisions: tuple[InputRevision, ...]
    revisions_known: bool
    all_authoritative: bool
    algorithm_version: str = ALGORITHM_VERSION

    @property
    def vwap(self) -> float | None:
        """Derive price only from compatible quote/base sufficient statistics."""
        if (self.target.volume_semantics != "base_asset"
                or self.values.quote_volume is None or self.values.volume <= 0):
            return None
        return self.values.quote_volume / self.values.volume

    def evaluate(
        self, start_ms: int, end_ms: int, *,
        exclusions: tuple[tuple[int, int], ...] = (),
        close_policy: ClosePolicy = ClosePolicy.EXPLICIT,
    ) -> CoverageStatus:
        return self.coverage.evaluate(
            start_ms, end_ms, exclusions=exclusions, close_policy=close_policy,
        )

    def is_authoritative(
        self, start_ms: int, end_ms: int, *,
        exclusions: tuple[tuple[int, int], ...] = (),
    ) -> bool:
        # A successor policy can serve a historical preview; it cannot invent
        # the per-source explicit closure required for publication authority.
        return self.all_authoritative and self.evaluate(
            start_ms, end_ms, exclusions=exclusions,
        ).closed


def _merge_revisions(parts: Iterable[Iterable[InputRevision]]) -> tuple[InputRevision, ...]:
    by_domain: dict[tuple[SeriesKey, str], InputRevision] = {}
    for revisions in parts:
        for revision in revisions:
            key = (revision.series, revision.domain)
            previous = by_domain.get(key)
            if previous is not None and previous.version != revision.version:
                raise ValueError("cannot combine different acquisition views of one source")
            by_domain[key] = revision
    if len(by_domain) <= 1:
        return tuple(by_domain.values())
    return tuple(sorted(by_domain.values(), key=lambda item: (item.series.topic, item.domain)))


def summarize(components: Iterable[AcceptedComponent], *, target: SeriesKey) -> AggregateSummary:
    """Reference batch adapter; caller has already selected one version per leaf.

    Duplicate/overlapping components are ambiguous and rejected, never summed
    twice. A realtime replacement must rebuild from its accepted index (or use
    R129's future correction index), not append a new cumulative snapshot here.
    """
    ordered = sorted(components, key=lambda item: item.bar.time_ms)
    if not ordered:
        raise ValueError("empty input cannot manufacture a zero-volume candle")
    if any(replace(item.series, interval=target.interval) != target for item in ordered):
        raise ValueError("incompatible provider, market, instrument or bar semantics")
    values = []
    for item in ordered:
        row = item.bar.normalized_aggregation_values()
        values.append((*row[1:6], *row[7:]))
    return AggregateSummary(
        target=target, values=summarize_fields(values),
        coverage=Coverage.from_ranges(
            (item.bar.time_ms, item.end_ms, item.bar.is_closed) for item in ordered
        ),
        revisions=_merge_revisions(
            (item.revision,) if item.revision is not None else () for item in ordered
        ),
        revisions_known=all(item.revision is not None for item in ordered),
        all_authoritative=all(item.bar.trusted_final for item in ordered),
    )


def combine(parts: Sequence[AggregateSummary]) -> AggregateSummary:
    """Compose ordered, non-overlapping blocks without rounding partial totals."""
    if not parts:
        raise ValueError("empty input cannot manufacture a summary")
    target = parts[0].target
    if any(part.target != target or part.algorithm_version != ALGORITHM_VERSION for part in parts):
        raise ValueError("summary target semantics and algorithm versions must match")
    return AggregateSummary(
        target=target, values=combine_fields([part.values for part in parts]),
        coverage=combine_coverage([part.coverage for part in parts]),
        revisions=_merge_revisions(part.revisions for part in parts),
        revisions_known=all(part.revisions_known for part in parts),
        all_authoritative=all(part.all_authoritative for part in parts),
    )
