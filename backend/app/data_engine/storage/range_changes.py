"""Bounded D126 proof that a declared dependency range stayed unchanged."""
from .revisions import (
    IDENTITY_COLUMNS,
    StaleAcquisition,
    block_change_receipts,
    current_revision,
    series_change,
    series_range_spans,
    span_overlaps_half_open,
)


def check_range_since(conn, keys, start, stop, revision):
    head = current_revision(conn)
    changed = [key for key in keys if (row := series_change(conn, key)) is not None
               and row['revision'] > revision and row['start_ms'] < stop and row['end_ms'] >= start]
    if not changed:
        return
    receipts = block_change_receipts(conn, revision, head)
    if receipts:
        changed_set = set(changed)
        if any(tuple(row[name] for name in IDENTITY_COLUMNS) in changed_set
               and row['start_ms'] < stop and row['end_ms'] >= start for row in receipts):
            raise StaleAcquisition('canonical dependency range changed during acquisition', details={'reason':'canonical_range_changed'})
        return
    for key in changed:
        spans = series_range_spans(conn, key, revision, head)
        if spans is None:
            raise StaleAcquisition('dependency range receipt suffix is unavailable', details={'reason':'range_receipt_suffix_unavailable'})
        if any(span_overlaps_half_open(span, start, stop) for span in spans):
            raise StaleAcquisition('canonical dependency range changed during acquisition', details={'reason':'canonical_range_changed'})


def check_store_range(store, keys, start, stop, revision):
    with store._reading() as conn, conn:
        conn.execute('BEGIN')
        check_range_since(conn, keys, start, stop, revision)
