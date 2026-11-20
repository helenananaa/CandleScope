"""Only the cells finer precedence reaches are refined (history/source_precedence.trim_rejected)."""
from __future__ import annotations

import math
import random

import pytest

from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.cover_plan import FixedHistorySource, HistoryReadSpan
from app.data_engine.history.source_precedence import drive, edge_cells, trim_rejected

MINUTE = 60_000


def span_of(width, cells, start=0):
    source = FixedHistorySource(SeriesKey("BTCUSDT", "1h", market_type="futures"), width, 0,
                                ((0, 1 << 50),), frozenset({"open"}), "test")
    return HistoryReadSpan(source, start, start + cells * width)


def predicate(rows, deleted_from):
    """The planners' rule: a finer row of width w in [start - w + 1, end), or a deletion before end."""
    def rejects(part):
        if deleted_from is not None and deleted_from < part.end_ms:
            return True
        return any(part.start_ms - width + 1 <= opened < part.end_ms for opened, width in rows)
    return rejects


@pytest.mark.parametrize("seed", range(200))
def test_the_middle_runs_from_the_first_reached_cell_to_the_last(seed):
    rng = random.Random(seed)
    width = rng.choice([4 * 60, 60, 15]) * MINUTE
    cells = rng.randrange(1, 70)
    span = span_of(width, cells, start=rng.randrange(0, 50) * width)
    rows = [(span.start_ms + rng.randrange(-width, cells * width), rng.choice([MINUTE, 5 * MINUTE]))
            for _ in range(rng.choice([1, 1, 2, 5, 40]))]
    deleted_from = span.start_ms + rng.randrange(0, cells * width) if rng.random() < 0.15 else None
    rejects = predicate(rows, deleted_from)
    if not rejects(span):
        return
    probes = []
    head, middle, tail = drive(trim_rejected(span), lambda part: probes.append(part) or rejects(part))
    reached = [at for at in range(cells) if rejects(span_of(width, 1, span.start_ms + at * width))]
    assert middle.start_ms == span.start_ms + reached[0] * width
    assert middle.end_ms == span.start_ms + (reached[-1] + 1) * width
    assert (head is None) == (reached[0] == 0) and (tail is None) == (reached[-1] == cells - 1)
    for part in (head, tail):
        if part is not None:
            assert not rejects(part) and part.source is span.source
    pieces = [part for part in (head, middle, tail) if part is not None]
    assert pieces[0].start_ms == span.start_ms and pieces[-1].end_ms == span.end_ms
    assert all(left.end_ms == right.start_ms for left, right in zip(pieces, pieces[1:]))
    assert len(probes) <= 2 * math.ceil(math.log2(max(cells, 2))) + 2
    if len(reached) == cells and cells > 1:
        # Every cell reached: the span's two edge cells, prefetched by every caller.
        assert probes == list(edge_cells(span))


def test_a_single_cell_is_refined_without_probes():
    span = span_of(60 * MINUTE, 1)
    assert drive(trim_rejected(span), lambda part: pytest.fail("probed")) == (None, span, None)
    assert edge_cells(span) == ()
