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
