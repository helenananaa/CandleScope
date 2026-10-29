"""Content-validated canonical blocks shared across fixed target intervals.

Coarse blocks and fine boundaries always come from the selected base series,
never substituted exchange-native candles. Original additive contributions
retain their order and normalization; summing rounded block volumes changes
OHLCV. Source reads remain necessary: reuse saves reduction work, not IO.
"""
from __future__ import annotations

import math
import threading
from collections import Counter, OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from .models import BarData, SeriesKey


class SourceSnapshot(NamedTuple):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool
    quote_volume: float | None
    trades: int | None
    taker_buy_base: float | None
    taker_buy_quote: float | None
    source: str
    prevalidated: tuple | None
    trusted_final: bool

    @property
    def _prevalidated_aggregation_fields(self) -> tuple | None:
        return self.prevalidated

    # Reuse canonical normalization on immutable input, without allocating and
    # reclassifying a mutable BarData for each source row on a cold miss.
    normalized_aggregation_fields = BarData.normalized_aggregation_fields
    normalized_aggregation_values = BarData.normalized_aggregation_values


def _signature(bar: BarData) -> SourceSnapshot:
    return SourceSnapshot(bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume,
                          bar.is_closed, bar.quote_volume, bar.trades, bar.taker_buy_base,
                          bar.taker_buy_quote, bar.source, bar._prevalidated_aggregation_fields,
                          bar.trusted_final)


@dataclass(frozen=True, slots=True)
class AggregateBlock:
    signature: tuple[SourceSnapshot, ...]
    values: tuple[tuple, ...]
    output: tuple
    cover: tuple[int, ...]


def _output(values: tuple[tuple, ...], highs: list[float], lows: list[float]) -> tuple:
    def additive(field: int, *, integer: bool = False) -> float | int | None:
        items = [row[field] for row in values]
        if any(item is None for item in items):
            return None
        return sum(int(item) for item in items) if integer else round(sum(float(item) for item in items), 8)

    return (values[0][0], values[0][1], max(highs), min(lows), values[-1][4],
            round(sum(float(row[5]) for row in values), 8), True,
            additive(7), additive(8, integer=True), additive(9), additive(10))


class AggregateBlockCache:
    """LRU with hard component/entry bounds including intermediate blocks.

    Identity includes every source-series semantic. Every hit compares all row
    fields (including decoder normalization and finality); no storage revision
    ledger, mutable source references or target-interval-specific identity is
    assumed. Short locks allow unrelated reductions to proceed concurrently.
    Racing identical builders adopt the first equivalent published block.
    """

    def __init__(self, *, max_components: int = 32_768, max_entries: int = 8_192) -> None:
        self.max_components = max(0, max_components)
        self.max_entries = max(0, max_entries)
        self._blocks: OrderedDict[tuple, AggregateBlock] = OrderedDict()
        self._sizes: dict[SeriesKey, Counter[int]] = {}
        self._lock = threading.Lock()
        self._components = 0
        self._stats = dict(hits=0, builds=0, corrections=0, evictions=0,
                           reused_components=0, mixed_buckets=0, coarse_blocks=0,
                           fine_rows=0, fallback_buckets=0)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {**self._stats, "entries": len(self._blocks), "components": self._components,
                    "max_components": self.max_components, "max_entries": self.max_entries}

    def _get(self, cache_key: tuple, signatures: tuple[SourceSnapshot, ...]) -> AggregateBlock | None:
        with self._lock:
            cached = self._blocks.get(cache_key)
            if cached is not None and cached.signature == signatures:
                self._blocks.move_to_end(cache_key)
                self._stats["hits"] += 1
                self._stats["reused_components"] += len(signatures)
                return cached
        return None

    def _remember(self, key: SeriesKey, block: AggregateBlock) -> AggregateBlock:
        cache_key = (key, block.signature[0].time, len(block.signature))
        size = len(block.values)
        with self._lock:
            cached = self._blocks.get(cache_key)
            if cached is not None and cached.signature == block.signature:
                self._blocks.move_to_end(cache_key)
                return cached
            self._stats["builds"] += 1
            if cached is not None:
                self._components -= len(self._blocks.pop(cache_key).values)
                self._sizes[key][size] -= 1
                self._stats["corrections"] += 1
            if size <= self.max_components and self.max_entries:
                self._blocks[cache_key] = block
                self._components += size
                self._sizes.setdefault(key, Counter())[size] += 1
                while self._components > self.max_components or len(self._blocks) > self.max_entries:
                    victim_key, victim = self._blocks.popitem(last=False)
                    victim_series, _, victim_size = victim_key
                    self._components -= len(victim.values)
                    sizes = self._sizes[victim_series]
                    sizes[victim_size] -= 1
                    if sizes[victim_size] <= 0:
                        del sizes[victim_size]
                    if not sizes:
                        del self._sizes[victim_series]
                    self._stats["evictions"] += 1
        return block

    @staticmethod
    def _complete(rows: tuple[SourceSnapshot, ...], bucket: int, width: int, source_width: int) -> bool:
        return len(rows) == width // source_width and all(
            row.time == bucket + index * source_width and row.is_closed and row.trusted_final
            and all(math.isfinite(value) for value in (row.open, row.high, row.low, row.close))
            for index, row in enumerate(rows)
        )

    def aggregate(
        self, bars: list[BarData], key: SeriesKey, width: int, source_width: int,
        fallback: Callable[..., list[BarData]],
    ) -> list[BarData]:
        # Prime-minute stress cases keep the bounded streaming reducer without
        # expanding a large tree. Calendar/non-tiling routes never enter here.
        if not bars or source_width <= 0 or width % source_width or not 2 <= width // source_width <= 64:
            return fallback(bars)
        if any(b.time < a.time for a, b in zip(bars, bars[1:])):
            bars = sorted(bars, key=lambda bar: bar.time)
        # Freeze before normalization, so a source correction cannot label old
        # normalized values with a newer fingerprint. No mutable source refs
        # survive this call, including on the canonical cold path.
        snapshots = [_signature(bar) for bar in bars]
        with self._lock:
            sizes = sorted((size for size, count in self._sizes.get(key, {}).items()
                            if count > 0), reverse=True)
        counts = dict(mixed_buckets=0, coarse_blocks=0, fine_rows=0, fallback_buckets=0)

        def remember_cold(inputs: list, values: tuple[tuple, ...], bar: BarData) -> None:
            signatures = tuple(inputs)
            if not self._complete(signatures, bar.time, width, source_width):
                counts["fallback_buckets"] += 1
                return
            output = (bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume,
                      bar.is_closed, bar.quote_volume, bar.trades, bar.taker_buy_base, bar.taker_buy_quote)
            self._remember(key, AggregateBlock(signatures, values, output, (1,) * len(values)))
            counts["fine_rows"] += len(values)

        result: list[BarData] = []
        misses: list[SourceSnapshot] = []
        index = 0
        # Cold sources stay on the canonical single-pass reducer and capture
        # the values it already produced. Do not eagerly build unused children.
        while sizes and index < len(snapshots):
            start = index
            bucket = snapshots[start].time // width * width
            while index < len(snapshots) and snapshots[index].time // width * width == bucket:
                index += 1
            group = tuple(snapshots[start:index])
            block = self._get((key, bucket, len(group)), group)
            if block is not None and len(group) == width // source_width and block.output[0] == bucket:
                result.append(BarData(*block.output))
                counts["coarse_blocks"] += 1
                continue
            if (not any(size < len(group) for size in sizes)
                    or not self._complete(group, bucket, width, source_width)):
                misses.extend(group)
                continue
            position = 0
            parts: list[AggregateBlock] = []
            cover: list[int] = []
            while position < len(group):
                part = None
                for size in sizes:
                    if size >= len(group) or size > len(group) - position:
                        continue
                    part = self._get((key, group[position].time, size), group[position:position + size])
                    if part is not None:
                        break
                if part is not None:
                    parts.append(part)
                    cover.append(len(part.values))
                    position += len(part.values)
                else:
                    # Normalize boundary rows only if a reusable coarse part
                    # exists. A wholly cold bucket goes through the bulk path.
                    cover.append(1)
                    position += 1
            if not parts:
                misses.extend(group)
                continue
            values: list[tuple] = []
            highs: list[float] = []
            lows: list[float] = []
            position = 0
            part_index = 0
            for size in cover:
                if size > 1:
                    part = parts[part_index]
                    part_index += 1
                    values.extend(part.values)
                    highs.append(part.output[2])
                    lows.append(part.output[3])
                else:
                    row = group[position].normalized_aggregation_values()
                    values.append(row)
                    highs.append(row[2])
                    lows.append(row[3])
                position += size
            normalized = tuple(values)
            block = self._remember(key, AggregateBlock(group, normalized, _output(normalized, highs, lows), tuple(cover)))
            result.append(BarData(*block.output))
            counts["mixed_buckets"] += int(len(set(cover)) > 1)
            counts["coarse_blocks"] += len(parts)
            counts["fine_rows"] += sum(size == 1 for size in cover)
        result.extend(fallback(misses if sizes else snapshots, remember_cold))
        if sizes:
            result.sort(key=lambda bar: bar.time)
        with self._lock:
            for name, count in counts.items():
                self._stats[name] += count
        return result
