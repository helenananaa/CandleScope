"""Typed numeric indicator requests, independent from transport and alerts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.data_engine.data_manager.models import BarData, SeriesKey


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
    source_slots: int = 250
    seed_policy: str = 'confirmed_rolling_slots_v1'
    minimum_revision: int = 0
    expected_bar: BarData | None = None

    def __post_init__(self):
        if not 1 <= len(self.outputs) <= 3 or len(set(self.outputs)) != len(self.outputs):
            raise ValueError('One to three distinct builtin outputs required')
        if type(self.source_slots) is not int or not 1 <= self.source_slots <= 250:
            raise ValueError('Numeric input is limited to250 source slots')
        if self.seed_policy != 'confirmed_rolling_slots_v1':
            raise ValueError('Unsupported numeric seed policy')
        if self.through_ms is not None and (type(self.through_ms) is not int or self.through_ms < 0):
            raise ValueError('Invalid numeric input frontier')
        if type(self.minimum_revision) is not int or self.minimum_revision < 0:
            raise ValueError('Invalid source revision')


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
