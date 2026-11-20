"""Pure finer-source precedence shared by historical read and backfill plans.

The mutation mapping is a bounded, pinned D126 snapshot supplied by the caller.
These helpers perform no reads, qualify no records and retain no shared state.
"""

MAX_PRESENCE_WINDOWS = 4096


def finer_requirements(span, precedences, mutations):
    for fine, width in precedences:
        if width >= span.source.width_ms:
            continue
        lo, hi = max(0, span.start_ms - width + 1), span.end_ms
        change = mutations[fine]
        # Only the minimum open is a reliable bound for legacy malformed
        # candles/deletions whose close can precede their open.
        if change is None or change["start_ms"] >= hi:
            continue
        yield fine, lo, hi, change["delete_revision"] > 0


def collect_presence_windows(spans, precedences, mutations):
    requested = {}
    count = 0
    for span in spans:
        for fine, lo, hi, deleted in finer_requirements(span, precedences, mutations):
            if deleted or count >= MAX_PRESENCE_WINDOWS:
                continue
            bounds = requested.setdefault(fine, set())
            previous = len(bounds)
            bounds.add((lo, hi))
            count += len(bounds) - previous
    return {source: tuple(sorted(bounds)) for source, bounds in requested.items()}


def trim_rejected(span):
    """The part of a rejected span that finer precedence actually reaches.

    A coarse span is rejected when a finer row (or a deletion footprint) may
    reach it. Only its cells from the first one reached to the last need finer
    grids; the cells before and after stay on the span's grid. Every planner
    and reader of mixed history uses this one rule, so a plan stores exactly
    the cells a later read composes from.

    A generator shared by synchronous and asynchronous callers (``drive``): it
    yields sub-spans of ``span`` and is sent whether each is rejected by the
    predicate that rejected ``span``. It returns ``(head, middle, tail)``:
    ``middle`` (first to last rejected cell) must be refined, ``head`` and
    ``tail`` (None when empty) are accepted by the predicate. Rejection is
    monotone in a sub-span's range (finer rows in [start - width + 1, end), or
    a deletion starting before end), so the first and last rejected cells are
    binary searched over prefixes and suffixes: two probes (its edge cells)
    when every cell is reached.
    """
    width, cells = span.source.width_ms, span.rows
    if cells <= 1:
        return None, span, None

    def part(lo, hi):
        return type(span)(span.source, span.start_ms + lo * width, span.start_ms + hi * width)

    if (yield part(0, 1)):
        first = 0
    else:
        accepted, rejected = 1, cells  # prefix lengths
        while rejected - accepted > 1:
            middle = (accepted + rejected) // 2
            if (yield part(0, middle)):
                rejected = middle
            else:
                accepted = middle
        first = rejected - 1
    if first == cells - 1 or (yield part(cells - 1, cells)):
        last = cells - 1
    else:
        rejected, accepted = first, cells - 1  # suffix starts
        while accepted - rejected > 1:
            middle = (accepted + rejected) // 2
            if (yield part(middle, cells)):
                rejected = middle
            else:
                accepted = middle
        last = rejected
    return (part(0, first) if first else None, part(first, last + 1),
            part(last + 1, cells) if last + 1 < cells else None)


def drive(steps, rejects):
    """Run ``trim_rejected`` with a synchronous predicate."""
    try:
        probe = next(steps)
        while True:
            probe = steps.send(bool(rejects(probe)))
    except StopIteration as done:
        return done.value


async def drive_async(steps, rejects):
    """Run ``trim_rejected`` with an awaitable predicate."""
    try:
        probe = next(steps)
        while True:
            probe = steps.send(bool(await rejects(probe)))
    except StopIteration as done:
        return done.value


def edge_cells(span):
    """A span's first and last cells: the probes ``trim_rejected`` makes first."""
    if span.rows <= 1:
        return ()
    width = span.source.width_ms
    return (type(span)(span.source, span.start_ms, span.start_ms + width),
            type(span)(span.source, span.end_ms - width, span.end_ms))
