"""Typed numeric indicator requests, independent from transport and alerts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.data_engine.data_manager.models import BarData, SeriesKey
from app.indicator.warmup import indicator_warmup_bars

# Enough confirmed rows for the slowest builtin the parameter schemas allow
# (EMA 500 needs 7,409) to converge; see ADR-INDICATOR-001.
MAX_NUMERIC_SOURCE_SLOTS = 8_192


@dataclass(frozen=True, slots=True)
class BuiltinOutput:
    name: str
    params: tuple[tuple[str, int | float | str], ...]
    output_id: str


@dataclass(frozen=True, slots=True)
class IndicatorQuery:
    source: SeriesKey
    outputs: tuple[BuiltinOutput, ...]
    through_ms: int | None = None
    # None derives the slots each output needs to converge to the same value
    # a chart shows for that bar, whatever window the chart requested.
    source_slots: int | None = None
    seed_policy: str = 'confirmed_rolling_slots_v1'
    minimum_revision: int = 0
    expected_bar: BarData | None = None

    def __post_init__(self):
        if not 1 <= len(self.outputs) <= 3 or len(set(self.outputs)) != len(self.outputs):
            raise ValueError('One to three distinct builtin outputs required')
        if self.source_slots is None:
            object.__setattr__(self, 'source_slots', convergent_source_slots(self.outputs))
        if (type(self.source_slots) is not int
                or not 1 <= self.source_slots <= MAX_NUMERIC_SOURCE_SLOTS):
            raise ValueError(
                f'Numeric input is limited to {MAX_NUMERIC_SOURCE_SLOTS} source slots')
        if self.seed_policy != 'confirmed_rolling_slots_v1':
            raise ValueError('Unsupported numeric seed policy')
        if self.through_ms is not None and (type(self.through_ms) is not int or self.through_ms < 0):
            raise ValueError('Invalid numeric input frontier')
        if type(self.minimum_revision) is not int or self.minimum_revision < 0:
            raise ValueError('Invalid source revision')


def convergent_source_slots(outputs: tuple[BuiltinOutput, ...]) -> int:
    """Confirmed rows whose newest value no longer depends on the seed."""
    return min(MAX_NUMERIC_SOURCE_SLOTS, max(
        indicator_warmup_bars(output.name, dict(output.params)) + 1 for output in outputs))


@dataclass(frozen=True, slots=True)
class NumericIndicatorSnapshot:
    source: SeriesKey
    status: Literal['ready', 'warming', 'stale', 'unavailable']
    values: tuple[tuple[BuiltinOutput, float | None], ...] = ()
    closed_through: int | None = None
    source_slots: int = 0
    closed_rows: int = 0
    storage_revision: int | None = None
    input_fingerprint: str | None = None
    seed_policy: str = 'confirmed_rolling_slots_v1'
    reason: str | None = None
    cache_hits: int = 0
    latest_closed: BarData | None = None
    stream_version: tuple[tuple[str, str | int], ...] = ()


class IndicatorInputUnavailable(RuntimeError):
    """Input is incomplete, superseded or no longer bound to its owner."""
