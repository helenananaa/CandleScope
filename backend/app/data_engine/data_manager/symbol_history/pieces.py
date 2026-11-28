"""Cutting missing source slots into pieces, and what a piece reports back (§3, §7.2).

A piece is one writer's unit of work: one source interval, one half-open
range, one declared write range. Pieces are cut at fixed, epoch-aligned
blocks so that recomputing after partial progress yields the same bounds
(nothing fragments), and a block never holds more than ``MAX_PIECE_BARS``
source bars: a long fetch let the 1,024-revision receipt window roll past
the acquisition on the RC network (§7.2).
"""
from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from .demands import DemandOwner
from .slots import Segment

MAX_PIECE_BARS = 4_000

_SECOND = 1_000
_MINUTE = 60 * _SECOND
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR
# Whole UTC days first, so 1m pieces line up with daily archive objects.
_BLOCK_CANDIDATES_MS = (7 * _DAY, 2 * _DAY, _DAY, 12 * _HOUR, 6 * _HOUR, 4 * _HOUR, 2 * _HOUR, _HOUR,
                        30 * _MINUTE, 15 * _MINUTE, 5 * _MINUTE, _MINUTE, _SECOND)


def piece_block_ms(width_ms: int, max_bars: int = MAX_PIECE_BARS) -> int:
    """The largest calendar-aligned block with at most ``max_bars`` source bars.

    1m sources get two UTC days (2,880 bars), 1s sources one hour (3,600).
    """
    for block in _BLOCK_CANDIDATES_MS:
        if block % width_ms == 0 and block // width_ms <= max_bars:
            return block
    return width_ms * max(1, max_bars)


_ids = itertools.count(1)


@dataclass(frozen=True, slots=True)
class Piece:
    """A source range ``[start_ms, end_ms)`` one execution fetches and writes."""

    piece_id: str
    source_interval: str
    width_ms: int
    start_ms: int
    end_ms: int
    urgency: int
    owners: frozenset[DemandOwner] = field(compare=False)

    @property
    def bars(self) -> int:
        return (self.end_ms - self.start_ms) // self.width_ms


def cut_pieces(source_interval: str, width_ms: int, segments: Iterable[Segment], *,
               max_bars: int = MAX_PIECE_BARS) -> list[Piece]:
    """Pieces for missing segments, most urgent first and newest first within one urgency."""
    block = piece_block_ms(width_ms, max_bars)
    pieces = []
    for segment in segments:
        end = segment.end_ms
        while end > segment.start_ms:
            start = max(segment.start_ms, (end - 1) // block * block)
            pieces.append(Piece(f"p{next(_ids)}", source_interval, width_ms, start, end,
                                segment.urgency, segment.owners))
            end = start
    pieces.sort(key=lambda piece: (piece.urgency, -piece.end_ms))
    return pieces


@dataclass(frozen=True, slots=True)
class PieceResult:
    """What an executed piece proved.

    ``written`` holds the source ranges now present (trusted, closed rows),
    also for a failed or cancelled piece that committed some pages first.
    A failed piece's remaining range is handed back to the existing backfill
    path, which then behaves as it does without the planner.
    """

    status: Literal["committed", "failed", "cancelled"]
    written: tuple[tuple[int, int], ...] = ()
    error: str | None = None
